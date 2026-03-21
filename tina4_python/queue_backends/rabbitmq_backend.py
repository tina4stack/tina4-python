# Tina4 RabbitMQ Queue Backend — AMQP 0-9-1 via pika or raw TCP sockets.
"""
RabbitMQ queue backend. Uses `pika` if available, falls back to raw AMQP
over TCP sockets (zero dependencies).

Environment variables:
    TINA4_RABBITMQ_HOST     — hostname (default: localhost)
    TINA4_RABBITMQ_PORT     — port (default: 5672)
    TINA4_RABBITMQ_USERNAME — username (default: guest)
    TINA4_RABBITMQ_PASSWORD — password (default: guest)
    TINA4_RABBITMQ_VHOST    — virtual host (default: /)
"""
import json
import os
import secrets
import socket
import struct


class RabbitMQBackend:
    """RabbitMQ queue backend implementing the Tina4 queue contract.

    Methods: enqueue, dequeue, acknowledge, reject, size, clear, dead_letter, close.
    """

    def __init__(self, **config):
        self._host = config.get("host", os.environ.get("TINA4_RABBITMQ_HOST", "localhost"))
        self._port = int(config.get("port", os.environ.get("TINA4_RABBITMQ_PORT", "5672")))
        self._username = config.get("username", os.environ.get("TINA4_RABBITMQ_USERNAME", "guest"))
        self._password = config.get("password", os.environ.get("TINA4_RABBITMQ_PASSWORD", "guest"))
        self._vhost = config.get("vhost", os.environ.get("TINA4_RABBITMQ_VHOST", "/"))

        self._pika = None
        self._connection = None
        self._channel = None
        self._use_pika = False

        # Raw socket state
        self._socket: socket.socket | None = None
        self._channel_id = 1
        self._declared_queues: set[str] = set()
        self._last_delivery_tag: int | None = None

        # Try pika first
        try:
            import pika
            self._pika = pika
            self._use_pika = True
        except ImportError:
            pass

    # ── Public Interface ─────────────────────────────────────────

    def connect(self):
        """Connect to RabbitMQ."""
        if self._use_pika:
            self._connect_pika()
        else:
            self._connect_raw()

    def enqueue(self, topic: str, message: dict) -> str:
        """Push a message onto a queue. Returns the message ID."""
        self._ensure_connected()
        msg_id = message.get("id", secrets.token_hex(8))
        message["id"] = msg_id
        body = json.dumps(message, default=str)

        if self._use_pika:
            self._ensure_queue_pika(topic)
            self._channel.basic_publish(
                exchange="",
                routing_key=topic,
                body=body,
                properties=self._pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                ),
            )
        else:
            self._declare_queue_raw(topic)
            self._basic_publish_raw(topic, body)

        return msg_id

    def dequeue(self, topic: str) -> dict | None:
        """Pop a message from a queue. Returns message dict or None."""
        self._ensure_connected()

        if self._use_pika:
            self._ensure_queue_pika(topic)
            method, _props, body = self._channel.basic_get(queue=topic, auto_ack=False)
            if method is None:
                return None
            self._last_delivery_tag = method.delivery_tag
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
        else:
            self._declare_queue_raw(topic)
            result = self._basic_get_raw(topic)
            if result is None:
                return None
            self._last_delivery_tag = result["delivery_tag"]
            return result["message"]

    def acknowledge(self, topic: str, message_id: str):
        """Acknowledge a message as processed."""
        if self._last_delivery_tag is None:
            return
        self._ensure_connected()

        if self._use_pika:
            self._channel.basic_ack(delivery_tag=self._last_delivery_tag)
        else:
            self._basic_ack_raw(self._last_delivery_tag)
        self._last_delivery_tag = None

    def reject(self, topic: str, message_id: str, requeue: bool = True):
        """Reject a message. Optionally requeue it."""
        if self._last_delivery_tag is None:
            return
        self._ensure_connected()

        if self._use_pika:
            self._channel.basic_nack(
                delivery_tag=self._last_delivery_tag, requeue=requeue
            )
        else:
            self._basic_nack_raw(self._last_delivery_tag, requeue)
        self._last_delivery_tag = None

    def size(self, topic: str) -> int:
        """Get the number of messages in a queue."""
        self._ensure_connected()

        if self._use_pika:
            result = self._channel.queue_declare(queue=topic, durable=True, passive=True)
            return result.method.message_count
        else:
            return self._queue_size_raw(topic)

    def clear(self, topic: str):
        """Purge all messages from a queue."""
        self._ensure_connected()

        if self._use_pika:
            # Declare the queue first (idempotent) to ensure it exists
            self._channel.queue_declare(queue=topic, durable=True)
            self._channel.queue_purge(queue=topic)
        else:
            self._queue_purge_raw(topic)

    def dead_letter(self, topic: str, message: dict):
        """Send a message to the dead letter queue."""
        self.enqueue(f"{topic}.dead_letter", message)

    def close(self):
        """Close the connection."""
        if self._use_pika:
            if self._connection and self._connection.is_open:
                self._connection.close()
            self._connection = None
            self._channel = None
        else:
            self._close_raw()

    # ── Pika Implementation ──────────────────────────────────────

    def _connect_pika(self):
        credentials = self._pika.PlainCredentials(self._username, self._password)
        params = self._pika.ConnectionParameters(
            host=self._host,
            port=self._port,
            virtual_host=self._vhost,
            credentials=credentials,
        )
        self._connection = self._pika.BlockingConnection(params)
        self._channel = self._connection.channel()

    def _ensure_queue_pika(self, topic: str):
        if topic not in self._declared_queues:
            self._channel.queue_declare(queue=topic, durable=True)
            self._declared_queues.add(topic)

    # ── Raw AMQP 0-9-1 Implementation ───────────────────────────

    def _connect_raw(self):
        self._socket = socket.create_connection(
            (self._host, self._port), timeout=10
        )
        self._socket.settimeout(30)

        # AMQP protocol header
        self._socket.sendall(b"AMQP\x00\x00\x09\x01")

        # Connection.Start
        self._read_frame()

        # Connection.StartOk
        self._send_connection_start_ok()

        # Connection.Tune
        self._read_frame()

        # Connection.TuneOk
        self._send_connection_tune_ok()

        # Connection.Open
        self._send_connection_open()

        # Connection.OpenOk
        self._read_frame()

        # Channel.Open
        self._send_channel_open()

        # Channel.OpenOk
        self._read_frame()

    def _close_raw(self):
        if self._socket is None:
            return
        try:
            self._send_channel_close()
            self._read_frame()
            self._send_connection_close()
            self._read_frame()
        except (OSError, ConnectionError):
            pass
        finally:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
            self._declared_queues.clear()

    def _ensure_connected(self):
        if self._use_pika:
            if self._connection is None or not self._connection.is_open:
                self.connect()
        else:
            if self._socket is None:
                self.connect()

    def _read_frame(self) -> dict:
        """Read a single AMQP frame."""
        header = self._recv_exact(7)
        frame_type, channel, size = struct.unpack("!BHI", header)

        payload = self._recv_exact(size) if size > 0 else b""
        frame_end = self._recv_exact(1)
        if frame_end != b"\xce":
            raise RuntimeError("Invalid AMQP frame end marker")

        return {"type": frame_type, "channel": channel, "payload": payload}

    def _write_frame(self, frame_type: int, channel: int, payload: bytes):
        """Write a raw AMQP frame."""
        header = struct.pack("!BHI", frame_type, channel, len(payload))
        self._socket.sendall(header + payload + b"\xce")

    def _write_method(self, channel: int, class_id: int, method_id: int, args: bytes = b""):
        """Write a method frame (type=1)."""
        payload = struct.pack("!HH", class_id, method_id) + args
        self._write_frame(1, channel, payload)

    def _short_str(self, s: str) -> bytes:
        encoded = s.encode("utf-8")
        return struct.pack("!B", len(encoded)) + encoded

    def _long_str(self, s: str | bytes) -> bytes:
        if isinstance(s, str):
            s = s.encode("utf-8")
        return struct.pack("!I", len(s)) + s

    def _empty_table(self) -> bytes:
        return struct.pack("!I", 0)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise RuntimeError("Connection closed while reading AMQP data")
            data += chunk
        return data

    def _send_connection_start_ok(self):
        mechanism = "PLAIN"
        response = f"\x00{self._username}\x00{self._password}"
        locale = "en_US"
        args = (
            self._empty_table()
            + self._short_str(mechanism)
            + self._long_str(response)
            + self._short_str(locale)
        )
        self._write_method(0, 10, 11, args)

    def _send_connection_tune_ok(self):
        args = struct.pack("!HIH", 0, 131072, 60)
        self._write_method(0, 10, 31, args)

    def _send_connection_open(self):
        args = self._short_str(self._vhost) + self._short_str("") + struct.pack("!B", 0)
        self._write_method(0, 10, 40, args)

    def _send_channel_open(self):
        self._write_method(self._channel_id, 20, 10, self._short_str(""))

    def _send_channel_close(self):
        args = struct.pack("!H", 200) + self._short_str("Normal shutdown") + struct.pack("!HH", 0, 0)
        self._write_method(self._channel_id, 20, 40, args)

    def _send_connection_close(self):
        args = struct.pack("!H", 200) + self._short_str("Normal shutdown") + struct.pack("!HH", 0, 0)
        self._write_method(0, 10, 50, args)

    def _declare_queue_raw(self, queue: str) -> int:
        if queue in self._declared_queues:
            return 0
        args = (
            struct.pack("!H", 0)
            + self._short_str(queue)
            + struct.pack("!B", 0b00000010)  # durable=true
            + self._empty_table()
        )
        self._write_method(self._channel_id, 50, 10, args)
        frame = self._read_frame()
        self._declared_queues.add(queue)

        # Parse message count from DeclareOk
        payload = frame["payload"]
        offset = 4  # skip class_id(2) + method_id(2)
        queue_name_len = payload[offset]
        offset += 1 + queue_name_len
        if offset + 8 <= len(payload):
            message_count = struct.unpack("!I", payload[offset:offset + 4])[0]
            return message_count
        return 0

    def _queue_size_raw(self, queue: str) -> int:
        # Force re-declare to get current count
        self._declared_queues.discard(queue)
        return self._declare_queue_raw(queue)

    def _queue_purge_raw(self, queue: str):
        self._declare_queue_raw(queue)
        # Queue.Purge = class 50, method 30
        args = struct.pack("!H", 0) + self._short_str(queue) + struct.pack("!B", 0)
        self._write_method(self._channel_id, 50, 30, args)
        self._read_frame()  # Queue.PurgeOk

    def _basic_publish_raw(self, queue: str, body: str):
        body_bytes = body.encode("utf-8")

        # Basic.Publish = class 60, method 40
        args = (
            struct.pack("!H", 0)
            + self._short_str("")        # exchange (default)
            + self._short_str(queue)     # routing key
            + struct.pack("!B", 0)       # mandatory=false, immediate=false
        )
        self._write_method(self._channel_id, 60, 40, args)

        # Content header frame (type=2)
        content_type = self._short_str("application/json")
        content_header = (
            struct.pack("!HH", 60, 0)
            + struct.pack("!Q", len(body_bytes))
            + struct.pack("!H", 0b1000000000000000)  # content-type set
            + content_type
        )
        self._write_frame(2, self._channel_id, content_header)

        # Content body frame (type=3)
        self._write_frame(3, self._channel_id, body_bytes)

    def _basic_get_raw(self, queue: str) -> dict | None:
        # Basic.Get = class 60, method 70
        args = struct.pack("!H", 0) + self._short_str(queue) + struct.pack("!B", 0)
        self._write_method(self._channel_id, 60, 70, args)

        frame = self._read_frame()
        payload = frame["payload"]
        method_id = struct.unpack("!H", payload[2:4])[0]

        # Basic.GetEmpty = method 72
        if method_id == 72:
            return None

        # Basic.GetOk = method 71 — parse delivery tag
        delivery_tag = struct.unpack("!Q", payload[4:12])[0]

        # Read content header
        header_frame = self._read_frame()
        body_size = struct.unpack("!Q", header_frame["payload"][4:12])[0]

        # Read content body
        body = b""
        remaining = body_size
        while remaining > 0:
            body_frame = self._read_frame()
            body += body_frame["payload"]
            remaining -= len(body_frame["payload"])

        try:
            message = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = {}

        return {"delivery_tag": delivery_tag, "message": message}

    def _basic_ack_raw(self, delivery_tag: int):
        # Basic.Ack = class 60, method 80
        args = struct.pack("!Q", delivery_tag) + struct.pack("!B", 0)
        self._write_method(self._channel_id, 60, 80, args)

    def _basic_nack_raw(self, delivery_tag: int, requeue: bool = True):
        # Basic.Nack = class 60, method 120
        flags = 0b00000010 if requeue else 0
        args = struct.pack("!Q", delivery_tag) + struct.pack("!B", flags)
        self._write_method(self._channel_id, 60, 120, args)
