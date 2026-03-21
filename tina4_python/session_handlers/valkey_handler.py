# Tina4 Valkey Session Handler — Valkey (Redis-compatible) via `redis` package or raw RESP.
"""
Valkey session handler. Valkey is Redis-compatible and uses the RESP protocol.
Uses `redis` package if available, falls back to raw RESP protocol over TCP
sockets (zero dependencies).

Environment variables:
    TINA4_SESSION_VALKEY_HOST     — hostname (default: localhost)
    TINA4_SESSION_VALKEY_PORT     — port (default: 6379)
    TINA4_SESSION_VALKEY_PASSWORD — password (default: none)
    TINA4_SESSION_VALKEY_DB       — database number (default: 0)
    TINA4_SESSION_TTL             — session TTL in seconds (default: 1800)
"""
import json
import os
import socket

from tina4_python.session import SessionHandler


class ValkeySessionHandler(SessionHandler):
    """Valkey-backed session handler with TTL support.

    Valkey is wire-compatible with Redis. Uses `redis` package when available,
    raw RESP protocol as fallback.
    """

    def __init__(self, **config):
        self._host = config.get("host", os.environ.get("TINA4_SESSION_VALKEY_HOST", "localhost"))
        self._port = int(config.get("port", os.environ.get("TINA4_SESSION_VALKEY_PORT", "6379")))
        self._password = config.get("password") or os.environ.get("TINA4_SESSION_VALKEY_PASSWORD") or None
        self._db = int(config.get("db", os.environ.get("TINA4_SESSION_VALKEY_DB", "0")))
        self._ttl = int(config.get("ttl", os.environ.get("TINA4_SESSION_TTL", "1800")))
        self._prefix = config.get("prefix", "tina4:session:")

        self._redis_client = None
        self._use_redis_pkg = False

        # Raw socket state
        self._socket: socket.socket | None = None

        # Try redis package (works with Valkey since it's RESP-compatible)
        try:
            import redis as redis_pkg
            self._redis_client = redis_pkg.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
            )
            self._use_redis_pkg = True
        except ImportError:
            pass

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    # ── SessionHandler Interface ─────────────────────────────────

    def read(self, session_id: str) -> dict:
        """Read session data by session ID."""
        if self._use_redis_pkg:
            data = self._redis_client.get(self._key(session_id))
            if data is None:
                return {}
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}
        else:
            self._ensure_connected()
            data = self._send_command("GET", self._key(session_id))
            if data is None:
                return {}
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}

    def write(self, session_id: str, data: dict, ttl: int = 0):
        """Write session data with TTL."""
        effective_ttl = ttl if ttl > 0 else self._ttl
        payload = json.dumps(data, default=str)
        key = self._key(session_id)

        if self._use_redis_pkg:
            if effective_ttl > 0:
                self._redis_client.setex(key, effective_ttl, payload)
            else:
                self._redis_client.set(key, payload)
        else:
            self._ensure_connected()
            if effective_ttl > 0:
                self._send_command("SETEX", key, str(effective_ttl), payload)
            else:
                self._send_command("SET", key, payload)

    def destroy(self, session_id: str):
        """Delete a session."""
        if self._use_redis_pkg:
            self._redis_client.delete(self._key(session_id))
        else:
            self._ensure_connected()
            self._send_command("DEL", self._key(session_id))

    def gc(self, max_lifetime: int):
        """Garbage collection. Valkey/Redis handles TTL automatically."""
        pass

    def close(self):
        """Close the connection."""
        if self._use_redis_pkg:
            if self._redis_client:
                self._redis_client.close()
        else:
            self._close_raw()

    # ── Raw RESP Protocol Implementation ─────────────────────────

    def _ensure_connected(self):
        if self._socket is None:
            self._connect_raw()

    def _connect_raw(self):
        self._socket = socket.create_connection((self._host, self._port), timeout=10)
        self._socket.settimeout(30)

        if self._password:
            result = self._send_command("AUTH", self._password)
            if result != "OK":
                raise RuntimeError("Valkey authentication failed")

        if self._db > 0:
            result = self._send_command("SELECT", str(self._db))
            if result != "OK":
                raise RuntimeError(f"Valkey SELECT database {self._db} failed")

    def _close_raw(self):
        if self._socket:
            try:
                self._send_command("QUIT")
            except (OSError, ConnectionError):
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _send_command(self, *args: str):
        """Send a RESP command and read the reply."""
        cmd = f"*{len(args)}\r\n"
        for arg in args:
            cmd += f"${len(arg)}\r\n{arg}\r\n"
        self._socket.sendall(cmd.encode("utf-8"))
        return self._read_reply()

    def _read_reply(self):
        """Read a RESP reply from the socket."""
        line = self._read_line()
        reply_type = line[0]
        data = line[1:]

        if reply_type == "+":
            return data
        elif reply_type == "-":
            raise RuntimeError(f"Valkey error: {data}")
        elif reply_type == ":":
            return int(data)
        elif reply_type == "$":
            length = int(data)
            if length == -1:
                return None
            value = self._recv_exact(length + 2)
            return value[:length].decode("utf-8")
        elif reply_type == "*":
            count = int(data)
            if count == -1:
                return None
            result = []
            for _ in range(count):
                result.append(self._read_reply())
            return result
        else:
            raise RuntimeError(f"Unknown RESP reply type: {reply_type}")

    def _read_line(self) -> str:
        """Read a line terminated by \\r\\n."""
        line = b""
        while True:
            char = self._socket.recv(1)
            if not char:
                raise RuntimeError("Connection closed while reading from Valkey")
            if char == b"\r":
                self._socket.recv(1)  # consume \n
                break
            line += char
        return line.decode("utf-8")

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise RuntimeError("Connection closed while reading Valkey data")
            data += chunk
        return data
