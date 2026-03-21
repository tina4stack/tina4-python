# Tina4 Kafka Queue Backend — Kafka protocol via confluent-kafka or raw TCP.
"""
Kafka queue backend. Uses `confluent-kafka` if available, falls back to raw
Kafka wire protocol over TCP sockets (zero dependencies).

Environment variables:
    TINA4_KAFKA_BROKERS  — comma-separated broker list (default: localhost:9092)
    TINA4_KAFKA_GROUP_ID — consumer group ID (default: tina4_consumer_group)
"""
import json
import os
import secrets
import socket
import struct
import zlib


class KafkaBackend:
    """Kafka queue backend implementing the Tina4 queue contract.

    Methods: enqueue, dequeue, acknowledge, reject, size, clear, dead_letter, close.
    """

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
        self._last_message = None

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
            if topic not in self._subscribed_topics:
                self._consumer.subscribe([topic])
                self._subscribed_topics.add(topic)
            msg = self._consumer.poll(timeout=1.0)
            if msg is None or msg.error():
                return None
            self._last_message = msg
            try:
                return json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        else:
            self._ensure_topic_metadata(topic)
            offset = self._offsets.get(topic, 0)
            result = self._send_fetch(topic, offset)
            if result is None:
                return None
            self._offsets[topic] = result["next_offset"]
            return result["message"]

    def acknowledge(self, topic: str, message_id: str):
        """Acknowledge a message. In Kafka, this commits the consumer offset."""
        if self._use_confluent:
            if self._consumer and self._last_message:
                self._consumer.commit(message=self._last_message)
                self._last_message = None
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
        conf = {"bootstrap.servers": self._brokers, "client.id": self._client_id}
        self._producer = self._confluent.Producer(conf)

        consumer_conf = {
            "bootstrap.servers": self._brokers,
            "group.id": self._group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
        self._consumer = self._confluent.Consumer(consumer_conf)

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

    def _send_produce(self, topic: str, key: str, value: str):
        header = self._request_header(0, 0)

        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")

        # MessageSet format v0
        message = (
            struct.pack("!B", 0)  # magic byte
            + struct.pack("!B", 0)  # attributes
            + self._kafka_bytes(key_bytes)
            + self._kafka_bytes(value_bytes)
        )
        crc = zlib.crc32(message) & 0xFFFFFFFF
        full_message = struct.pack("!I", crc) + message

        # MessageSet: offset(8) + message size(4) + message
        message_set = struct.pack("!Q", 0) + struct.pack("!I", len(full_message)) + full_message

        body = (
            struct.pack("!H", 1)  # required acks = 1
            + struct.pack("!I", 5000)  # timeout ms
            + struct.pack("!I", 1)  # 1 topic
            + self._kafka_string(topic)
            + struct.pack("!I", 1)  # 1 partition
            + struct.pack("!I", 0)  # partition 0
            + struct.pack("!I", len(message_set))
            + message_set
        )

        self._send_request(header + body)
        self._read_response()

    def _send_fetch(self, topic: str, offset: int) -> dict | None:
        header = self._request_header(1, 0)

        body = (
            struct.pack("!i", -1)  # replica id
            + struct.pack("!I", 5000)  # max wait ms
            + struct.pack("!I", 1)  # min bytes
            + struct.pack("!I", 1)  # 1 topic
            + self._kafka_string(topic)
            + struct.pack("!I", 1)  # 1 partition
            + struct.pack("!I", 0)  # partition 0
            + struct.pack("!Q", offset)  # fetch offset
            + struct.pack("!I", 1048576)  # max bytes (1MB)
        )

        self._send_request(header + body)
        response = self._read_response()

        # Parse FetchResponse
        pos = 4  # number of topics
        if pos + 2 > len(response):
            return None
        topic_name_len = struct.unpack("!H", response[pos:pos + 2])[0]
        pos += 2 + topic_name_len
        pos += 4  # partition count
        pos += 4  # partition id

        if pos + 2 > len(response):
            return None
        error_code = struct.unpack("!H", response[pos:pos + 2])[0]
        pos += 2
        pos += 8  # high watermark

        if pos + 4 > len(response):
            return None
        message_set_size = struct.unpack("!I", response[pos:pos + 4])[0]
        pos += 4

        if message_set_size == 0 or error_code != 0:
            return None

        # Parse first message from MessageSet
        if pos + 12 > len(response):
            return None
        msg_offset = struct.unpack("!Q", response[pos:pos + 8])[0]
        pos += 8
        pos += 4  # msg_size

        # Skip CRC(4) + magic(1) + attributes(1)
        pos += 6

        # Key
        if pos + 4 > len(response):
            return None
        key_len = struct.unpack("!I", response[pos:pos + 4])[0]
        pos += 4
        if key_len > 0 and key_len != 0xFFFFFFFF:
            pos += key_len

        # Value
        if pos + 4 > len(response):
            return None
        value_len = struct.unpack("!I", response[pos:pos + 4])[0]
        pos += 4
        if value_len <= 0 or value_len == 0xFFFFFFFF:
            return None

        if pos + value_len > len(response):
            return None
        value = response[pos:pos + value_len]

        try:
            message = json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        return {"message": message, "next_offset": msg_offset + 1}
