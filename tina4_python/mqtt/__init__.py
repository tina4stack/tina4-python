"""Zero-dependency MQTT 3.1.1 client -- the protocol every broker and every IoT
device already speaks.

Built on ``socket`` and ``struct`` only: no third-party package, so an app that
talks to Mosquitto / EMQX / HiveMQ / AWS IoT adds nothing to its dependency tree.

Shaped like tina4_python.queue.Queue on purpose -- publish / subscribe / consume::

    from tina4_python.mqtt import Mqtt

    mqtt = Mqtt()                                   # TINA4_MQTT_URL
    mqtt.publish("fleet/meter-42/telemetry", '{"kwh":12.5}', qos=1)

    for message in mqtt.consume("fleet/+/telemetry", qos=1):
        if message.duplicate:                       # QoS 1 is at-least-once
            continue
        store(message.topic, message.payload)

Environment: ``TINA4_MQTT_URL`` (default mqtt://127.0.0.1:1883),
``TINA4_MQTT_CLIENT_ID``, ``TINA4_MQTT_KEEPALIVE`` (seconds, default 60),
``TINA4_MQTT_CA_FILE``, ``TINA4_MQTT_TLS_VERIFY``.

No background thread is started by default. When a connection is otherwise idle
the broker drops it past 1.5x keepalive, so opt in to the cooperative keepalive
with ``start_keepalive`` -- it registers a ``background()`` task exactly like the
queue consumers do, rather than spawning a thread of its own.
"""

from __future__ import annotations

import os
import secrets
import select
import socket
import struct
import threading
import time
from typing import Any, Iterator
from urllib.parse import unquote

from tina4_python.dotenv import is_truthy
from tina4_python.mqtt.message import MqttMessage

__all__ = ["Mqtt", "MqttMessage", "MqttError", "MqttTimeoutError"]


class MqttError(Exception):
    """Any MQTT protocol / connection failure."""


class MqttTimeoutError(MqttError):
    """The broker did not answer inside the timeout."""


def _truthy(value: str | None) -> bool:
    # One env truthiness table for the whole framework - see dotenv.is_truthy.
    # A second copy here is a second thing to keep in step, and env booleans
    # answering differently per subsystem is the ADR-0024 break in miniature.
    return is_truthy(value) if value is not None else False


# Control packet types. The low nibble of SUBSCRIBE is 0x2 because MQTT 3.1.1
# mandates QoS 1 on that packet.
_CONNECT = 0x10
_CONNACK = 0x20
_PUBLISH = 0x30
_PUBACK = 0x40
_SUBSCRIBE = 0x82
_SUBACK = 0x90
_PINGREQ = 0xC0
_PINGRESP = 0xD0
_DISCONNECT = 0xE0

_PROTOCOL_LEVEL = 0x04  # 4 == MQTT 3.1.1
_DEFAULT_PORT = 1883
_DEFAULT_TLS_PORT = 8883
_DEFAULT_URL = "mqtt://127.0.0.1:1883"
_DEFAULT_KEEPALIVE = 60
_SUBSCRIPTION_REFUSED = 0x80
_MAX_REMAINING_LENGTH = 268_435_455  # 4 varint bytes
_READ_CHUNK = 16_384

# QoS 2 is refused, never silently downgraded. A caller who asked for
# exactly-once and quietly got at-least-once would double-process every
# duplicate forever without ever seeing an error.
_QOS2_REFUSED_MESSAGE = (
    "MQTT QoS 2 (exactly-once delivery) is not supported by Tina4 -- this "
    "client speaks QoS 0 and QoS 1 only, and refuses QoS 2 rather than "
    "silently downgrading it to QoS 1. Use QoS 1 with an idempotent consumer "
    "keyed on (device_id, device_timestamp): duplicates are then harmless, "
    "which is what exactly-once was for."
)

_CONNACK_RETURN_CODES = {
    1: "unacceptable protocol version",
    2: "client identifier rejected",
    3: "server unavailable",
    4: "bad user name or password",
    5: "not authorised",
}


class Mqtt:
    """Zero-dependency MQTT 3.1.1 client. See the module docstring."""

    __slots__ = (
        "host", "port", "client_id", "keepalive", "clean_session", "username",
        "_tls", "_password", "_ca_file", "_tls_verify",
        "_will_topic", "_will_payload", "_will_qos", "_will_retain",
        "_timeout", "_read_timeout",
        "_packet_id", "_inbox", "_write_lock", "_last_write_at",
        "_socket", "_keepalive_task", "_read_buffer", "_read_cursor",
    )

    def __init__(self, url: str | None = None, client_id: str | None = None,
                 username: str | None = None, password: str | None = None,
                 ca_file: str | None = None, tls_verify: bool | None = None,
                 keepalive: int | None = None, clean_session: bool = True,
                 will_topic: str | None = None, will_payload: Any = None,
                 will_qos: int = 0, will_retain: bool = False,
                 timeout: float = 5, read_timeout: float | None = None,
                 connect: bool = True) -> None:
        parsed = self.parse_url(url or os.environ.get("TINA4_MQTT_URL") or _DEFAULT_URL)
        self.host = parsed["host"]
        self.port = parsed["port"]
        self._tls = parsed["tls"]
        # Explicit arguments win over the url's userinfo: the more specific source.
        self.username = username if username is not None else parsed["username"]
        self._password = password if password is not None else parsed["password"]
        if self._password and not self.username:
            raise ValueError(
                "MQTT password without a username is not allowed by MQTT 3.1.1 -- "
                "supply both (mqtt://user:pass@host, or username=/password=) or neither"
            )
        self._ca_file = ca_file or (os.environ.get("TINA4_MQTT_CA_FILE") or None)
        self._tls_verify = (
            _truthy(os.environ.get("TINA4_MQTT_TLS_VERIFY", "true"))
            if tls_verify is None else tls_verify
        )
        self.client_id = client_id or os.environ.get("TINA4_MQTT_CLIENT_ID") or ""
        if not self.client_id:
            self.client_id = "tina4-" + secrets.token_hex(8)
        self.keepalive = int(keepalive or os.environ.get("TINA4_MQTT_KEEPALIVE") or _DEFAULT_KEEPALIVE)
        self.clean_session = clean_session
        self._will_topic = will_topic
        self._will_payload = will_payload
        self._will_qos = will_qos
        self._will_retain = will_retain
        self._timeout = timeout
        self._read_timeout = read_timeout

        if will_topic:
            self._refuse_unsupported_qos(will_qos)

        self._packet_id = 0
        self._inbox: list[MqttMessage] = []
        self._write_lock = threading.Lock()
        self._last_write_at = 0.0
        self._socket: Any = None
        self._keepalive_task = None
        self._read_buffer = bytearray()
        self._read_cursor = 0

        if connect:
            self.connect()

    # -- url parsing --------------------------------------------------------

    @classmethod
    def parse_url(cls, url: str) -> dict[str, Any]:
        """Split an MQTT url into {host, port, tls, username, password}.

        ``mqtt://host:port`` and ``tcp://host:port`` are plain TCP (default port
        1883); ``mqtts://host:port`` is TLS (default 8883). A bare ``host`` or
        ``host:port`` works too, and an IPv6 literal is bracketed
        (``mqtt://[::1]:1883``). Credentials ride in the userinfo and are
        percent-decoded, so a password containing @ : or / survives.
        """
        raw = (url or "").strip()
        if not raw:
            raise ValueError(f"MQTT url is empty -- set TINA4_MQTT_URL (e.g. {_DEFAULT_URL})")

        scheme = None
        if "://" in raw:
            scheme = raw.split("://", 1)[0].lower()
            if scheme not in ("mqtt", "tcp", "mqtts"):
                raise ValueError(
                    f"unsupported MQTT url scheme {scheme!r} in {raw!r} -- this client "
                    "speaks mqtt://, tcp:// or mqtts:// (TLS). WebSocket transports are "
                    "not implemented."
                )
            rest = raw.split("://", 1)[1]
        else:
            rest = raw

        tls = scheme == "mqtts"

        # Split on the LAST "@" so a password containing an un-encoded "@" still
        # leaves the host intact.
        username = password = None
        if "@" in rest:
            userinfo, _, rest = rest.rpartition("@")
            raw_username, sep, raw_password = userinfo.partition(":")
            username = cls._percent_decode(raw_username)
            if sep:
                password = cls._percent_decode(raw_password)

        # host is a [bracketed ipv6] or a run without : or /
        host = rest
        port_str = None
        path_stripped = rest.split("/", 1)[0]
        if path_stripped.startswith("["):
            close = path_stripped.find("]")
            if close == -1:
                raise ValueError(f"malformed MQTT url {raw!r} -- unclosed IPv6 bracket")
            host = path_stripped[1:close]
            after = path_stripped[close + 1:]
            if after.startswith(":"):
                port_str = after[1:]
        else:
            host, sep, maybe_port = path_stripped.partition(":")
            if sep:
                port_str = maybe_port

        if not host:
            raise ValueError(f"malformed MQTT url {raw!r} -- expected mqtt://host:port")
        if port_str is not None and not port_str.isdigit():
            raise ValueError(f"malformed MQTT url {raw!r} -- port must be numeric")

        return {
            "host": host,
            "port": int(port_str) if port_str else (_DEFAULT_TLS_PORT if tls else _DEFAULT_PORT),
            "tls": tls,
            "username": username or None,
            "password": password,
        }

    @staticmethod
    def _percent_decode(value: str) -> str:
        # unquote, NOT unquote_plus: the latter also turns "+" into a space,
        # which silently corrupts a password.
        return unquote(value or "")

    @staticmethod
    def encode_remaining_length(value: int) -> bytes:
        """Remaining Length varint: 7 bits per byte, high bit means "another
        byte follows". A single-byte assumption works for every packet under 128
        bytes and then fails, so this is exercised directly at 0/127/128/16383."""
        length = int(value)
        if length < 0 or length > _MAX_REMAINING_LENGTH:
            raise ValueError(f"remaining length {length} is outside 0..{_MAX_REMAINING_LENGTH}")
        out = bytearray()
        while True:
            byte = length & 0x7F
            length >>= 7
            out.append(byte | 0x80 if length > 0 else byte)
            if length <= 0:
                break
        return bytes(out)

    # -- connection ---------------------------------------------------------

    def connect(self) -> bool:
        """Open the socket and complete the CONNECT / CONNACK handshake. Also the
        reconnect path: an existing socket is closed first, and a durable session
        (clean_session=False) resumes with the same client_id."""
        self._close_socket()
        try:
            raw = socket.create_connection((self.host, self.port), timeout=self._timeout)
            raw.settimeout(None)
            # Telemetry frames are tiny; Nagle would add latency for no gain.
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._socket = self._wrap_in_tls(raw) if self._tls else raw
        except OSError as e:
            self._close_socket()
            raise MqttError(f"could not connect to MQTT broker at {self.host}:{self.port}: {e}")

        self._inbox.clear()
        self._read_buffer = bytearray()
        self._read_cursor = 0

        body = bytearray()
        body += self._mqtt_string("MQTT")
        body += struct.pack("BB", _PROTOCOL_LEVEL, self._connect_flags())
        body += struct.pack(">H", self.keepalive)
        # Payload order is FIXED: client id, will topic, will message, username,
        # password. Emitting them in any other order shifts every field after it.
        body += self._mqtt_string(self.client_id)
        if self._will_topic:
            body += self._mqtt_string(self._will_topic)
            will_bytes = self._payload_bytes(self._will_payload)
            body += struct.pack(">H", len(will_bytes)) + will_bytes
        if self.username:
            body += self._mqtt_string(self.username)
        if self._password:
            body += self._mqtt_string(self._password)
        self._write_packet(_CONNECT, body)

        header, payload = self._read_packet(self._deadline_in(self._timeout))
        if header != _CONNACK or len(payload) < 2:
            raise MqttError(f"expected CONNACK, got {header:#04x}")
        return_code = payload[1]
        if return_code != 0:
            reason = _CONNACK_RETURN_CODES.get(return_code, "unknown return code")
            raise MqttError(
                f"broker refused the connection: {reason} (CONNACK return code {return_code})"
            )
        return True

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def tls(self) -> bool:
        """True when this connection runs over TLS (mqtts://)."""
        return self._tls

    @property
    def cipher(self) -> str | None:
        """The negotiated cipher suite name, or None on a plain connection. A
        real name here is proof the TLS handshake actually completed."""
        if not self._tls or not self.connected:
            return None
        info = self._socket.cipher()
        return info[0] if info else None

    @property
    def tls_version(self) -> str | None:
        """The negotiated TLS protocol version ("TLSv1.3"), or None when plain."""
        if not self._tls or not self.connected:
            return None
        return self._socket.version()

    def __repr__(self) -> str:
        # Never dump _password: a client can end up in a log line, an exception
        # report or the debug overlay.
        user = f" username={self.username!r}" if self.username else ""
        scheme = "mqtts" if self._tls else "mqtt"
        return (f"<Mqtt {scheme}://{self.host}:{self.port} client_id={self.client_id!r}"
                f"{user} connected={self.connected}>")

    # -- publish / subscribe / receive -------------------------------------

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> int | None:
        """Publish an application message. Returns the packet identifier for
        QoS 1 (the broker's PUBACK must carry it back) and None for QoS 0.

        retain=True tells the broker to keep this as the topic's last known value
        and hand it to every FUTURE subscriber -- how a dashboard shows current
        state the moment it connects. Publishing an EMPTY payload with retain=True
        clears a retained value."""
        self._refuse_unsupported_qos(qos)
        payload_bytes = self._payload_bytes(payload)
        topic_field = self._mqtt_string(topic)
        # The packet identifier exists ONLY when QoS > 0.
        packet_id = self._next_packet_id() if qos > 0 else None

        body = bytearray()
        body += topic_field
        if packet_id is not None:
            body += struct.pack(">H", packet_id)
        body += payload_bytes
        self._write_packet(_PUBLISH | (qos << 1) | (0x01 if retain else 0x00), body)

        if qos == 1:
            self._wait_for_acknowledgement(_PUBACK, packet_id, "PUBACK")
        return packet_id

    def subscribe(self, topic_filter: str, qos: int = 1) -> int:
        """Subscribe to a topic filter ("fleet/+/telemetry", "fleet/#"). Returns
        the QoS the broker GRANTED, which can be lower than requested.

        A SUBACK carrying 0x80 is a REFUSAL, not a success -- treating any SUBACK
        as success means sitting on a dead subscription receiving nothing, so it
        raises here."""
        self._refuse_unsupported_qos(qos)
        packet_id = self._next_packet_id()
        filter_field = self._mqtt_string(topic_filter)

        body = bytearray()
        body += struct.pack(">H", packet_id)
        body += filter_field
        body.append(qos)
        self._write_packet(_SUBSCRIBE, body)

        payload = self._wait_for_acknowledgement(_SUBACK, packet_id, "SUBACK")
        if len(payload) < 3:
            raise MqttError(f"malformed SUBACK: no return code for {topic_filter!r}")
        granted = payload[2]
        if granted == _SUBSCRIPTION_REFUSED:
            raise MqttError(
                f"broker refused the subscription to {topic_filter!r} (SUBACK return "
                "code 0x80) -- check the topic filter and the broker ACLs"
            )
        return granted

    def receive(self, timeout: float | None = None, ack: bool = True) -> MqttMessage:
        """Read the next application message. Returns an MqttMessage.

        ack=True (the default) acknowledges a QoS 1 delivery immediately, which
        is right for a synchronous read. Pass ack=False when the message must be
        stored before the broker is allowed to forget it -- an unacknowledged
        QoS 1 message is redelivered with DUP set. consume() does exactly that."""
        message = self._inbox.pop(0) if self._inbox else self._read_publish(
            self._deadline_in(timeout if timeout is not None else self._read_timeout)
        )
        if ack:
            message.acknowledge()
        return message

    def consume(self, topic_filter: str | None = None, qos: int = 1,
                iterations: int = 0, timeout: float | None = None) -> Iterator[MqttMessage]:
        """Long-running consumer, mirroring Queue.consume().

            for message in mqtt.consume("fleet/+/telemetry", qos=1):
                store(message)

        The message is acknowledged AFTER the loop body returns control to the
        generator (the next iteration), so a body that raises leaves the message
        unacknowledged and the broker redelivers it with DUP set -- at-least-once,
        the point of QoS 1. iterations > 0 stops after that many messages."""
        if topic_filter:
            self.subscribe(topic_filter, qos=qos)
        consumed = 0
        while True:
            message = self.receive(timeout=timeout, ack=False)
            yield message
            message.acknowledge()
            consumed += 1
            if iterations > 0 and consumed >= iterations:
                break

    def acknowledge(self, packet_id: int) -> bool:
        """PUBACK a QoS 1 delivery. Called by MqttMessage.acknowledge()."""
        self._write_packet(_PUBACK, struct.pack(">H", packet_id))
        return True

    # -- keepalive ----------------------------------------------------------

    def ping(self, timeout: float | None = None) -> bool:
        """PINGREQ and wait for the PINGRESP. Use this when nothing else is
        reading the socket; under a consume loop use start_keepalive instead."""
        self.send_keepalive()
        deadline = self._deadline_in(timeout if timeout is not None else self._timeout)
        while True:
            header, payload = self._read_packet(deadline)
            if header == _PINGRESP:
                return True
            if self._stash_publish(header, payload):
                continue
            raise MqttError(f"expected PINGRESP, got {header:#04x}")

    def send_keepalive(self) -> bool:
        """Write a PINGREQ without waiting for the answer. The PINGRESP is
        absorbed by whatever is reading the socket (receive skips it)."""
        self._write_packet(_PINGREQ, b"")
        return True

    def start_keepalive(self, interval: float | None = None):
        """Opt in to the cooperative keepalive. Registers a background() task --
        the same mechanism the queue consumers use -- that sends a PINGREQ only
        when the connection has gone quiet, so an actively publishing client
        costs no extra packets."""
        if self._keepalive_task is not None:
            return self._keepalive_task
        if self.keepalive <= 0:
            raise MqttError("keepalive is disabled (keepalive=0) -- nothing to schedule")
        from tina4_python.core.server import background  # lazy: idle clients never load it
        seconds = interval if interval is not None else max(self.keepalive / 2.0, 1.0)

        def _tick():
            if self.connected and self._idle_for(seconds):
                self.send_keepalive()

        self._keepalive_task = background(_tick, interval=seconds)
        return self._keepalive_task

    def stop_keepalive(self) -> bool:
        if self._keepalive_task is None:
            return False
        self._keepalive_task.stop()
        self._keepalive_task = None
        return True

    def disconnect(self) -> bool:
        """Say goodbye properly: DISCONNECT then close. The broker discards the
        Last Will on a graceful disconnect."""
        self.stop_keepalive()
        try:
            if self.connected:
                self._write_packet(_DISCONNECT, b"")
        except (MqttError, OSError):
            pass  # already gone -- closing is still the right outcome
        finally:
            self._close_socket()
        return True

    def kill(self) -> bool:
        """Drop the socket WITHOUT a DISCONNECT -- what a crashed or unplugged
        device looks like to the broker, and therefore what fires the Last Will."""
        self.stop_keepalive()
        self._close_socket()
        return True

    # -- internals ----------------------------------------------------------

    def _connect_flags(self) -> int:
        flags = 0x02 if self.clean_session else 0x00
        if self._will_topic:
            # Will flag 0x04, will QoS at bits 3-4, will retain 0x20.
            flags |= 0x04 | (self._will_qos << 3)
            if self._will_retain:
                flags |= 0x20
        if self.username:
            flags |= 0x80
        if self._password:
            flags |= 0x40
        return flags

    def _wrap_in_tls(self, raw_socket):
        """Wrap the TCP socket in TLS. ``ssl`` is stdlib, so mqtts:// costs no
        dependency -- and it is imported HERE, not at module top, so a plain
        mqtt:// app never loads it."""
        import ssl
        # PROTOCOL_TLS_CLIENT gives each context its OWN cert store. Never mutate
        # a shared/global store (the shared-default-store footgun): with a global
        # store a CA loaded for one client would be trusted by every later client
        # in the process -- so we build and verify against this context alone.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if self._tls_verify:
            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = True
            context.load_default_certs()  # system CAs, for a publicly-signed broker
            if self._ca_file:
                if not os.path.isfile(self._ca_file):
                    raw_socket.close()
                    raise MqttError(
                        f"MQTT CA file not found: {self._ca_file} -- TINA4_MQTT_CA_FILE "
                        "(or ca_file=) must point at the broker's CA certificate in PEM form"
                    )
                context.load_verify_locations(self._ca_file)
        else:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            from tina4_python.debug import Log
            Log.warning(
                f"MQTT TLS certificate verification is DISABLED for mqtts://{self.host}:{self.port} "
                "-- the connection is encrypted but the broker's identity is NOT verified, so a "
                "man in the middle can read and rewrite this traffic. Set TINA4_MQTT_CA_FILE "
                "(or ca_file=) to the broker's CA and drop TINA4_MQTT_TLS_VERIFY=false."
            )
        try:
            # server_hostname is ALWAYS passed (unlike Ruby, where SNI is skipped
            # for an IP literal): Python couples check_hostname with
            # server_hostname and matches it against the certificate -- including
            # IP-address SANs -- so an IP here is verified against the cert's IP
            # SAN. OpenSSL simply omits an IP from the SNI extension on the wire.
            ssl_socket = context.wrap_socket(raw_socket, server_hostname=self.host)
            return ssl_socket
        except ssl.SSLError as e:
            raw_socket.close()
            raise MqttError(f"MQTT TLS handshake with {self.host}:{self.port} failed: {e}")

    def _refuse_unsupported_qos(self, qos: int) -> None:
        if qos == 2:
            raise ValueError(_QOS2_REFUSED_MESSAGE)
        if qos not in (0, 1):
            raise ValueError(f"qos must be 0 or 1 (got {qos!r})")

    @staticmethod
    def _mqtt_string(value: str) -> bytes:
        """Every MQTT string is a 2-byte big-endian length followed by UTF-8 bytes."""
        data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if len(data) > 0xFFFF:
            raise ValueError("MQTT string is longer than 65535 bytes")
        return struct.pack(">H", len(data)) + data

    @staticmethod
    def _payload_bytes(payload: Any) -> bytes:
        if payload is None:
            return b""
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
        return str(payload).encode("utf-8")

    def _next_packet_id(self) -> int:
        # Packet identifiers are 1..65535; 0 is invalid.
        with self._write_lock:
            self._packet_id = (self._packet_id % 0xFFFF) + 1
            return self._packet_id

    def _write_packet(self, header: int, body: bytes) -> bool:
        if not self.connected:
            raise MqttError("not connected to an MQTT broker")
        fixed = bytearray((header,))
        fixed += self.encode_remaining_length(len(body))
        try:
            with self._write_lock:
                self._socket.sendall(bytes(fixed) + bytes(body))
                self._last_write_at = time.monotonic()
        except OSError as e:
            raise MqttError(f"MQTT write failed: {e}")
        return True

    def _read_packet(self, deadline: float | None):
        """Returns (control_byte, body). The fixed header is read in exactly
        1 + N bytes (N <= 4 for the varint) so the next packet's header is never
        consumed by a speculative over-read."""
        header = self._read_exact(1, deadline)[0]
        multiplier = 1
        length = 0
        while True:
            byte = self._read_exact(1, deadline)[0]
            length += (byte & 0x7F) * multiplier
            if (byte & 0x80) == 0:
                break
            multiplier <<= 7
            if multiplier > 0x200000:
                raise MqttError("malformed Remaining Length (more than 4 varint bytes)")
        return header, (b"" if length == 0 else self._read_exact(length, deadline))

    def _read_exact(self, count: int, deadline: float | None) -> bytes:
        """TCP is a stream: a single recv returns SHORT. Reads go through ONE
        buffer, filled a whole _READ_CHUNK at a time -- fewer syscalls, and it
        keeps the TLS layer's decrypted buffer drained so a later select never
        blocks on an empty socket while plaintext is already waiting."""
        if not self.connected:
            raise MqttError("not connected to an MQTT broker")
        while self._buffered_bytes() < count:
            self._fill_read_buffer(deadline)
        return self._take_buffered(count)

    def _buffered_bytes(self) -> int:
        return len(self._read_buffer) - self._read_cursor

    def _take_buffered(self, count: int) -> bytes:
        chunk = bytes(self._read_buffer[self._read_cursor:self._read_cursor + count])
        self._read_cursor += count
        if self._read_cursor >= len(self._read_buffer):
            self._read_buffer = bytearray()
            self._read_cursor = 0
        return chunk

    def _fill_read_buffer(self, deadline: float | None) -> None:
        self._wait_readable(deadline)
        try:
            data = self._socket.recv(_READ_CHUNK)
        except OSError as e:
            raise MqttError(f"MQTT read failed: {e}")
        if not data:
            raise MqttError("broker closed the connection")
        self._read_buffer += data

    def _wait_readable(self, deadline: float | None) -> None:
        # Bytes already decrypted inside the TLS layer are readable NOW; the
        # underlying socket may have nothing, so selecting on it first would hang.
        pending = getattr(self._socket, "pending", None)
        if callable(pending) and pending() > 0:
            return
        remaining = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MqttTimeoutError("timed out waiting for the MQTT broker")
        readable, _, _ = select.select([self._socket], [], [], remaining)
        if not readable:
            raise MqttTimeoutError("timed out waiting for the MQTT broker")

    def _read_publish(self, deadline: float | None) -> MqttMessage:
        while True:
            header, payload = self._read_packet(deadline)
            if header == _PINGRESP:
                continue
            message = self._parse_publish(header, payload)
            if message is not None:
                return message
            raise MqttError(f"expected PUBLISH, got {header:#04x}")

    def _stash_publish(self, header: int, payload: bytes) -> bool:
        """A PUBLISH that arrives while we wait for a PUBACK/SUBACK/PINGRESP
        (normal when the same connection both publishes and subscribes) is parked
        in the inbox so receive still delivers it, in order, instead of it being
        mistaken for the acknowledgement."""
        message = self._parse_publish(header, payload)
        if message is None:
            return False
        self._inbox.append(message)
        return True

    def _parse_publish(self, header: int, payload: bytes) -> MqttMessage | None:
        if (header & 0xF0) != _PUBLISH:
            return None
        qos = (header & 0x06) >> 1
        topic_length = struct.unpack(">H", payload[0:2])[0]
        offset = 2 + topic_length
        topic = payload[2:2 + topic_length].decode("utf-8", errors="replace")
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", payload[offset:offset + 2])[0]
            offset += 2
        return MqttMessage(
            topic=topic,
            payload=bytes(payload[offset:]),
            qos=qos,
            retained=(header & 0x01) == 0x01,
            duplicate=(header & 0x08) == 0x08,
            packet_id=packet_id,
            client=self,
        )

    def _wait_for_acknowledgement(self, expected_header: int, packet_id: int | None, name: str) -> bytes:
        """Wait for a specific acknowledgement, tolerating interleaved PUBLISH
        and PINGRESP packets. A mismatched packet identifier is silent data loss
        if ignored, so it raises."""
        deadline = self._deadline_in(self._timeout)
        while True:
            header, payload = self._read_packet(deadline)
            if header == _PINGRESP:
                continue
            if self._stash_publish(header, payload):
                continue
            if header != expected_header:
                raise MqttError(f"expected {name}, got {header:#04x}")
            received_id = struct.unpack(">H", payload[0:2])[0]
            if received_id != packet_id:
                raise MqttError(
                    f"{name} packet identifier mismatch: broker acknowledged "
                    f"{received_id} but we sent {packet_id}"
                )
            return payload

    def _idle_for(self, seconds: float) -> bool:
        return (time.monotonic() - self._last_write_at) >= seconds

    @staticmethod
    def _deadline_in(seconds: float | None) -> float | None:
        return time.monotonic() + seconds if seconds is not None else None

    def _close_socket(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None
