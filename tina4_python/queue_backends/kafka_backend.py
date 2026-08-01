# Tina4 Kafka Queue Backend — Kafka protocol via confluent-kafka or raw TCP.
"""
Kafka queue backend. Uses `confluent-kafka` if available, falls back to raw
Kafka wire protocol over TCP sockets (zero dependencies).

Environment variables:
    TINA4_KAFKA_BROKERS  — comma-separated broker list (default: localhost:9092)
    TINA4_KAFKA_GROUP_ID — consumer group ID (default: tina4_consumer_group)

    TLS/SASL (each read as TINA4_KAFKA_<NAME> first, then bare KAFKA_<NAME>):
    TINA4_KAFKA_SECURITY_PROTOCOL — e.g. SSL / SASL_SSL (default: PLAINTEXT)
    TINA4_KAFKA_SSL_CA_LOCATION   — CA cert path for TLS brokers/proxies
    TINA4_KAFKA_SASL_MECHANISM / TINA4_KAFKA_SASL_USERNAME / TINA4_KAFKA_SASL_PASSWORD — optional SASL
"""
import json
import os
import secrets
import socket
import struct
import time
import zlib


class KafkaConnector:
    """Kafka queue backend implementing the Tina4 queue contract.

    Methods: enqueue, dequeue, acknowledge, reject, size, clear, dead_letter, close.
    """

    # Lowest Produce/Fetch versions Kafka 4.x still accepts.
    #
    # Kafka 4.0 removed message formats v0/v1, and with them Produce v0-v2 and
    # Fetch v0-v3. A request at a removed version is NOT answered with an error
    # code -- the broker logs UnsupportedVersionException and closes the socket, so
    # the client only sees EOF. These are the first versions carrying RecordBatch
    # v2, which _encode_record_batch/_decode_first_record speak.
    #
    # This path only runs when confluent-kafka is ABSENT (see __init__), which is
    # why the bug hid for so long: CI installs confluent-kafka, so the raw path was
    # never exercised and its tests passed without touching this code.
    PRODUCE_VERSION = 3
    FETCH_VERSION = 4

    def __init__(self, **config):
        self._brokers = config.get(
            "brokers", os.environ.get("TINA4_KAFKA_BROKERS", "localhost:9092")
        )
        self._group_id = config.get(
            "group_id", os.environ.get("TINA4_KAFKA_GROUP_ID", "tina4_consumer_group")
        )
        self._client_id = config.get("client_id", "tina4-python")

        self._confluent = None
        self._producer = None
        self._consumer = None
        self._use_confluent = False

        # Raw socket state
        self._socket: socket.socket | None = None
        self._correlation_id = 0
        self._offsets: dict[str, int] = {}
        self._known_topics: set[str] = set()
        self._subscribed_topics: set[str] = set()
        # Kafka commits an OFFSET, not a record, so a commit is only safe once
        # the caller names the message it finished. Keyed by message id: a
        # single "last message" slot committed past whichever record happened
        # to be polled most recently, burying anything failed before it.
        self._in_flight: dict[str, object] = {}

        # Try confluent-kafka first
        try:
            import confluent_kafka
            self._confluent = confluent_kafka
            self._use_confluent = True
        except ImportError:
            pass

    # ── Public Interface ─────────────────────────────────────────

    def connect(self):
        """Connect to Kafka."""
        if self._use_confluent:
            self._connect_confluent()
        else:
            self._connect_raw()

    def enqueue(self, topic: str, message: dict) -> str:
        """Push a message onto a Kafka topic. Returns the message ID."""
        self._ensure_connected()
        msg_id = message.get("id", secrets.token_hex(8))
        message["id"] = msg_id
        body = json.dumps(message, default=str)

        if self._use_confluent:
            self._producer.produce(topic=topic, key=msg_id, value=body)
            self._producer.flush(timeout=5)
        else:
            self._ensure_topic_metadata(topic)
            self._send_produce(topic, msg_id, body)

        return msg_id

    def dequeue(self, topic: str) -> dict | None:
        """Consume a message from a Kafka topic. Returns message dict or None."""
        self._ensure_connected()

        if self._use_confluent:
            first = topic not in self._subscribed_topics
            if first:
                self._consumer.subscribe([topic])
                self._subscribed_topics.add(topic)
            # The FIRST poll after subscribing must drive the consumer-group
            # join + partition assignment, which takes several seconds on a cold
            # broker. Until partitions are assigned, poll() returns None even
            # when the topic already has messages -- so a single short poll made
            # dequeue() return None right after enqueue(). Poll in a bounded loop
            # on first subscribe (deadline TINA4_KAFKA_ASSIGN_TIMEOUT, default
            # 15s); steady state stays a single ~1s poll.
            deadline = time.monotonic() + (
                float(os.environ.get("TINA4_KAFKA_ASSIGN_TIMEOUT", "15")) if first else 1.0
            )
            msg = None
            while True:
                candidate = self._consumer.poll(timeout=0.5)
                if candidate is not None and not candidate.error():
                    msg = candidate
                    break
                if time.monotonic() >= deadline:
                    break
            if msg is None:
                return None
            try:
                message = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
            if isinstance(message, dict) and message.get("id") is not None:
                self._in_flight[str(message["id"])] = msg
            return message
        else:
            self._ensure_topic_metadata(topic)
            offset = self._offsets.get(topic, 0)
            result = self._send_fetch(topic, offset)
            if result is None:
                return None
            self._offsets[topic] = result["next_offset"]
            return result["message"]

    def acknowledge(self, topic: str, message_id: str):
        """Acknowledge THIS message by committing the offset just past it."""
        if self._use_confluent:
            msg = self._in_flight.pop(str(message_id), None)
            if self._consumer and msg is not None:
                self._consumer.commit(message=msg)
        # For raw protocol, offset advancement in dequeue serves as acknowledgment

    def reject(self, topic: str, message_id: str, requeue: bool = True):
        """Reject a message. If requeue is True, re-publish it to the topic."""
        if requeue:
            # Re-publish the message
            self.enqueue(topic, {"id": message_id, "_requeued": True})

    def size(self, topic: str) -> int:
        """Get approximate topic size. Kafka does not natively support this."""
        # Kafka has no simple queue size concept; return 0 as documented in PHP
        return 0

    def clear(self, topic: str):
        """Clear is not natively supported by Kafka.

        Topics must be deleted and recreated, or retention set to 0 temporarily.
        This is a no-op for safety.
        """
        pass

    def dead_letter(self, topic: str, message: dict):
        """Send a message to the dead letter topic."""
        self.enqueue(f"{topic}.dead_letter", message)

    def close(self):
        """Close the connection."""
        if self._use_confluent:
            if self._producer:
                self._producer.flush(timeout=5)
                self._producer = None
            if self._consumer:
                self._consumer.close()
                self._consumer = None
        else:
            self._close_raw()

    # ── Confluent-Kafka Implementation ───────────────────────────

    def _connect_confluent(self):
        security = self._security_config()
        conf = {"bootstrap.servers": self._brokers, "client.id": self._client_id, **security}
        self._producer = self._confluent.Producer(conf)

        consumer_conf = {
            "bootstrap.servers": self._brokers,
            "client.id": self._client_id,
            "group.id": self._group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            **security,
        }
        self._consumer = self._confluent.Consumer(consumer_conf)

    @staticmethod
    def _security_config() -> dict:
        """Build SSL/SASL client config from env (for a TLS broker/proxy).

        Each setting is read from the Tina4-namespaced env var first
        (``TINA4_KAFKA_SECURITY_PROTOCOL`` …) and falls back to the bare
        librdkafka-convention name (``KAFKA_SECURITY_PROTOCOL`` …) that many
        Kafka deployments already set. Honours security.protocol (e.g. SSL,
        SASL_SSL), ssl.ca.location, and optional SASL (mechanism / username /
        password). Unset keys leave librdkafka defaults (PLAINTEXT).
        """
        # rdkafka key -> env suffix (read as TINA4_KAFKA_<suffix>, then KAFKA_<suffix>)
        mapping = {
            "security.protocol": "SECURITY_PROTOCOL",
            "ssl.ca.location": "SSL_CA_LOCATION",
            "sasl.mechanism": "SASL_MECHANISM",
            "sasl.username": "SASL_USERNAME",
            "sasl.password": "SASL_PASSWORD",
        }
        config = {}
        for rdk, suffix in mapping.items():
            value = os.environ.get(f"TINA4_KAFKA_{suffix}") or os.environ.get(f"KAFKA_{suffix}")
            if value:
                config[rdk] = value
        return config

    # ── Raw Kafka Wire Protocol Implementation ───────────────────

    def _connect_raw(self):
        broker_list = [b.strip() for b in self._brokers.split(",")]
        connected = False

        for broker in broker_list:
            parts = broker.split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 9092
            try:
                self._socket = socket.create_connection((host, port), timeout=10)
                self._socket.settimeout(30)
                connected = True
                break
            except (OSError, ConnectionError):
                continue

        if not connected:
            raise RuntimeError(
                f"Kafka connection failed: could not connect to any broker in [{self._brokers}]"
            )

    def _close_raw(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
            self._known_topics.clear()

    def _ensure_connected(self):
        if self._use_confluent:
            if self._producer is None:
                self.connect()
        else:
            if self._socket is None:
                self.connect()

    def _ensure_topic_metadata(self, topic: str):
        if topic in self._known_topics:
            return
        self._send_metadata_request(topic)
        self._known_topics.add(topic)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise RuntimeError("Connection closed while reading Kafka data")
            data += chunk
        return data

    def _request_header(self, api_key: int, api_version: int) -> bytes:
        self._correlation_id += 1
        return (
            struct.pack("!HHI", api_key, api_version, self._correlation_id)
            + self._kafka_string(self._client_id)
        )

    def _send_request(self, data: bytes):
        frame = struct.pack("!I", len(data)) + data
        self._socket.sendall(frame)

    def _read_response(self) -> bytes:
        header = self._recv_exact(4)
        length = struct.unpack("!I", header)[0]
        payload = self._recv_exact(length)
        # Skip correlation ID (first 4 bytes)
        return payload[4:]

    def _kafka_string(self, s: str) -> bytes:
        encoded = s.encode("utf-8")
        return struct.pack("!H", len(encoded)) + encoded

    def _kafka_bytes(self, s: str | bytes) -> bytes:
        if isinstance(s, str):
            s = s.encode("utf-8")
        return struct.pack("!I", len(s)) + s

    def _send_metadata_request(self, topic: str):
        header = self._request_header(3, 0)
        body = struct.pack("!I", 1) + self._kafka_string(topic)
        self._send_request(header + body)
        self._read_response()

    # ── Record format v2 primitives ──────────────────────────────────

    _CRC32C_TABLE = None

    @classmethod
    def _crc32c(cls, data: bytes) -> int:
        """CRC32C (Castagnoli) -- what record format v2 requires.

        zlib.crc32 is CRC-32/ISO-HDLC, a DIFFERENT polynomial: using it produces a
        batch the encoder happily builds and the broker silently rejects. The
        stdlib has no CRC32C, and Tina4 is zero-dependency, so the table is built
        once here (verified against the spec vector: crc32c(b"123456789") ==
        0xE3069283).
        """
        if cls._CRC32C_TABLE is None:
            poly = 0x82F63B78  # reversed Castagnoli polynomial
            table = []
            for i in range(256):
                crc = i
                for _ in range(8):
                    crc = (crc >> 1) ^ (poly if crc & 1 else 0)
                table.append(crc)
            cls._CRC32C_TABLE = table

        table = cls._CRC32C_TABLE
        crc = 0xFFFFFFFF
        for b in data:
            crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
        return crc ^ 0xFFFFFFFF

    @staticmethod
    def _varint(value: int) -> bytes:
        """Zigzag LEB128 -- how record format v2 encodes lengths and deltas."""
        u = (value << 1) ^ (value >> 63)  # zigzag; >> is arithmetic in Python
        out = bytearray()
        while True:
            byte = u & 0x7F
            u >>= 7
            if u:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                return bytes(out)

    @staticmethod
    def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
        """Read one zigzag LEB128 varint. Returns (value, new_pos)."""
        result = 0
        shift = 0
        while pos < len(buf):
            b = buf[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return (result >> 1) ^ -(result & 1), pos

    def _encode_record_batch(self, key: bytes, value: bytes) -> bytes:
        """Encode one record as a RecordBatch v2.

        Kafka 4.x REMOVED message formats v0/v1 and with them Produce v0-v2 and
        Fetch v0-v3. A removed version is not answered with an error code: the
        broker logs
          UnsupportedVersionException: Received request for api with key 0
          (Produce) and unsupported version 0
        and CLOSES THE SOCKET, so the client only sees EOF. (kafka-broker-api-
        versions.sh still advertises "Produce(0): 0 to 13" -- the advertised range
        and the handler disagree; trust the broker log.)
        """
        timestamp = int(time.time() * 1000)

        record_body = (
            struct.pack("!B", 0)               # attributes (unused, must be 0)
            + self._varint(0)                  # timestampDelta
            + self._varint(0)                  # offsetDelta
            + self._varint(len(key)) + key
            + self._varint(len(value)) + value
            + self._varint(0)                  # header count
        )
        record = self._varint(len(record_body)) + record_body

        after_crc = (
            struct.pack("!H", 0)               # attributes (no compression)
            + struct.pack("!i", 0)             # lastOffsetDelta (1 record => 0)
            + struct.pack("!q", timestamp)     # baseTimestamp
            + struct.pack("!q", timestamp)     # maxTimestamp
            + struct.pack("!q", -1)            # producerId (not idempotent)
            + struct.pack("!h", -1)            # producerEpoch
            + struct.pack("!i", -1)            # baseSequence
            + struct.pack("!i", 1)             # record count
            + record
        )

        after_length = (
            struct.pack("!i", -1)              # partitionLeaderEpoch
            + struct.pack("!B", 2)             # magic = 2 (record format v2)
            + struct.pack("!I", self._crc32c(after_crc))
            + after_crc
        )

        return struct.pack("!q", 0) + struct.pack("!i", len(after_length)) + after_length

    def _send_produce(self, topic: str, key: str, value: str):
        """Send a ProduceRequest v3 -- the lowest version Kafka 4.x still accepts.

        Topic auto-creation is ASYNCHRONOUS, so a brand-new topic answers
        UNKNOWN_TOPIC_OR_PARTITION (3) or LEADER_NOT_AVAILABLE (5) on the first
        produce. Both are retriable. This matters: the previous implementation
        never read the error code, so it reported SUCCESS on that race and
        silently dropped the message.
        """
        retriable = (3, 5)
        for attempt in range(1, 11):
            error_code = self._produce_once(topic, key, value)
            if error_code == 0:
                return
            if error_code not in retriable or attempt == 10:
                raise RuntimeError(
                    f"Kafka rejected the produce for topic {topic}: "
                    f"error code {error_code}"
                    + (f" after {attempt} attempts" if attempt > 1 else "")
                )
            self._known_topics.discard(topic)
            self._ensure_topic_metadata(topic)
            time.sleep(0.2)

    def _produce_once(self, topic: str, key: str, value: str) -> int:
        """One ProduceRequest v3 round trip. Returns the partition error code."""
        header = self._request_header(0, self.PRODUCE_VERSION)
        batch = self._encode_record_batch(key.encode("utf-8"), value.encode("utf-8"))

        body = (
            struct.pack("!h", -1)              # transactional_id = null (v3+)
            + struct.pack("!H", 1)             # acks = 1
            + struct.pack("!I", 5000)          # timeout ms
            + struct.pack("!I", 1)             # 1 topic
            + self._kafka_string(topic)
            + struct.pack("!I", 1)             # 1 partition
            + struct.pack("!I", 0)             # partition 0
            + struct.pack("!I", len(batch))    # records as BYTES
            + batch
        )

        self._send_request(header + body)
        response = self._read_response()

        pos = 4                                                   # topic array count
        name_len = struct.unpack("!H", response[pos:pos + 2])[0]
        pos += 2 + name_len
        pos += 4                                                  # partition array count
        pos += 4                                                  # partition index
        return struct.unpack("!H", response[pos:pos + 2])[0]

    def _decode_first_record(self, records: bytes) -> tuple[bytes, int] | None:
        """Pull the FIRST record out of a RecordBatch v2 blob.

        Returns (value_bytes, absolute_offset), or None when the blob holds no
        usable record: an empty batch, or a control batch (transaction markers,
        which carry no user payload).
        """
        if len(records) < 61:          # a v2 batch header alone is 61 bytes
            return None

        base_offset = struct.unpack("!q", records[0:8])[0]
        magic = records[16]
        if magic != 2:
            raise RuntimeError(
                f"Unexpected Kafka record format v{magic}; this client speaks v2 only"
            )

        attributes = struct.unpack("!H", records[21:23])[0]
        if attributes & 0x20:
            return None                # control batch: no user records
        if attributes & 0x07:
            raise RuntimeError(
                "Kafka returned a COMPRESSED record batch; this client does not "
                "decompress. Set compression.type=producer or none on the topic."
            )

        count = struct.unpack("!i", records[57:61])[0]
        if count == 0:
            return None

        pos = 61                       # first record starts after the header
        _, pos = self._read_varint(records, pos)     # record length
        pos += 1                                     # record attributes
        _, pos = self._read_varint(records, pos)     # timestampDelta
        offset_delta, pos = self._read_varint(records, pos)

        key_len, pos = self._read_varint(records, pos)
        if key_len > 0:
            pos += key_len

        value_len, pos = self._read_varint(records, pos)
        if value_len <= 0:
            return None                # null or empty value

        return records[pos:pos + value_len], base_offset + offset_delta

    def _send_fetch(self, topic: str, offset: int) -> dict | None:
        """Send a FetchRequest v4 (Kafka 4.x dropped v0-v3) and decode the first
        record out of the returned RecordBatch v2."""
        header = self._request_header(1, self.FETCH_VERSION)

        body = (
            struct.pack("!i", -1)              # replica id (ordinary consumer)
            + struct.pack("!I", 5000)          # max wait ms
            + struct.pack("!I", 1)             # min bytes
            + struct.pack("!I", 52428800)      # max bytes (50MB) -- v3+
            + struct.pack("!B", 0)             # isolation: read_uncommitted -- v4+
            + struct.pack("!I", 1)             # 1 topic
            + self._kafka_string(topic)
            + struct.pack("!I", 1)             # 1 partition
            + struct.pack("!I", 0)             # partition 0
            + struct.pack("!Q", offset)        # fetch offset
            + struct.pack("!I", 1048576)       # partition max bytes
        )

        self._send_request(header + body)
        response = self._read_response()

        pos = 4                                                   # throttle_time_ms
        pos += 4                                                  # topic array count
        if pos + 2 > len(response):
            return None
        name_len = struct.unpack("!H", response[pos:pos + 2])[0]
        pos += 2 + name_len
        pos += 4                                                  # partition array count
        pos += 4                                                  # partition index

        if pos + 2 > len(response):
            return None
        error_code = struct.unpack("!H", response[pos:pos + 2])[0]
        pos += 2
        pos += 8                                                  # high watermark
        pos += 8                                                  # last stable offset -- v4+

        # aborted_transactions: nullable array, -1 (0xFFFFFFFF) means null.
        if pos + 4 > len(response):
            return None
        aborted = struct.unpack("!I", response[pos:pos + 4])[0]
        pos += 4
        if aborted != 0xFFFFFFFF:
            pos += aborted * 16                                   # producer_id + first_offset

        if pos + 4 > len(response):
            return None
        records_size = struct.unpack("!I", response[pos:pos + 4])[0]
        pos += 4

        # UNKNOWN_TOPIC_OR_PARTITION (3) and LEADER_NOT_AVAILABLE (5) mean "nothing
        # to read here yet", not a failure: a consumer that starts before its
        # producer, or right after auto-creation (which is asynchronous), sees them
        # routinely. dequeue() is documented to return None when there is no
        # message, and the confluent path returns None for exactly this case -- so
        # raising here made the SAME public method behave differently depending on
        # which client library happened to be installed. Any OTHER code is a real
        # protocol/authorisation failure and still raises loudly.
        if error_code in (3, 5):
            return None
        if error_code != 0:
            raise RuntimeError(
                f"Kafka rejected the fetch for topic {topic}: error code {error_code}"
            )
        if records_size in (0, 0xFFFFFFFF) or pos + records_size > len(response):
            return None

        decoded = self._decode_first_record(response[pos:pos + records_size])
        if decoded is None:
            return None
        value, msg_offset = decoded

        try:
            message = json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        return {"message": message, "next_offset": msg_offset + 1}

# Backwards-compatible alias — external code and tests may use the old name.
KafkaBackend = KafkaConnector
