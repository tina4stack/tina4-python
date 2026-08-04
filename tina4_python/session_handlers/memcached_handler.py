# Tina4 Memcached Session Handler — zero-dependency text protocol over TCP.
"""
Memcached session handler.

Memcached was already one of the seven CACHE backends in all four frameworks but
was NOT a session backend in any of them, even though it is the classic PHP
session store. This closes that gap.

Speaks the memcached TEXT protocol directly over a socket, so there is no client
dependency — the same zero-dependency choice the Redis/Valkey handlers make.

BACKEND-FAILURE POLICY. A genuine key miss returns ``{}`` silently (no session
yet is normal). A TRANSPORT failure — server unreachable, connection dropped
mid-reply, a protocol error — RAISES, so the Session layer can log-loud and
degrade. Collapsing the two is how a dead cache silently logs every user out.

Memcached has no persistence and no replication: a restart drops every session.
That is a deliberate trade (it is a cache), and it is why file/database remain
the defaults.

Environment variables:
    TINA4_SESSION_MEMCACHED_HOST   — hostname (default: localhost)
    TINA4_SESSION_MEMCACHED_PORT   — port (default: 11211)
    TINA4_SESSION_MEMCACHED_PREFIX — key prefix (default: tina4:session:)
    TINA4_SESSION_TTL              — session TTL in seconds (default: 3600)
"""
import hashlib
import json
import os
import socket
import time

from tina4_python.session import SessionHandler

# Memcached rejects a key over 250 bytes or containing a space/control char.
# A session id is normally short hex, but the prefix is caller-supplied, so any
# key that could exceed the limit is hashed rather than truncated — truncating
# would let two different sessions collide on one key.
_MAX_KEY_BYTES = 250

# memcached's exptime field changes meaning at 30 days: at or below this it is
# RELATIVE seconds, above it the server reads an ABSOLUTE UNIX TIMESTAMP. See
# MemcachedSessionHandler._exptime for why we convert instead of clamping.
_MAX_RELATIVE_EXPTIME = 2592000


class MemcachedSessionHandler(SessionHandler):
    """Memcached-backed session handler with native TTL expiry."""

    def __init__(self, **config):
        self._host = config.get("host", os.environ.get("TINA4_SESSION_MEMCACHED_HOST", "localhost"))
        self._port = int(config.get("port", os.environ.get("TINA4_SESSION_MEMCACHED_PORT", "11211")))
        self._prefix = config.get("prefix", os.environ.get("TINA4_SESSION_MEMCACHED_PREFIX", "tina4:session:"))
        self._ttl = int(config.get("ttl", os.environ.get("TINA4_SESSION_TTL", "3600")))
        self._timeout = float(config.get("timeout", 5))

    def _key(self, session_id: str) -> str:
        key = f"{self._prefix}{session_id}"
        if len(key.encode()) > _MAX_KEY_BYTES or any(c.isspace() or ord(c) < 33 for c in key):
            return f"{self._prefix}{hashlib.sha256(session_id.encode()).hexdigest()}"
        return key

    def _command(self, payload: bytes, terminators: tuple[bytes, ...]) -> bytes:
        """Run one memcached command and return the raw reply.

        RAISES on any transport failure. The cache backend swallows these and
        returns b"" — correct for a cache (a miss and an outage are both "not
        cached"), wrong for a session, where an outage must be distinguishable
        from "no session yet".
        """
        sock = None
        try:
            sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
            sock.settimeout(self._timeout)
            sock.sendall(payload)
            buf = b""
            while not any(buf.endswith(t) or t in buf for t in terminators):
                chunk = sock.recv(4096)
                if not chunk:
                    raise RuntimeError("connection closed before a complete reply")
                buf += chunk
            return buf
        except Exception as exc:
            raise RuntimeError(
                f"Memcached session backend at {self._host}:{self._port} failed: {exc}"
            ) from exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    # ── SessionHandler Interface ─────────────────────────────────

    def read(self, session_id: str) -> dict:
        """Return the stored session, or {} for a genuine miss."""
        resp = self._command(f"get {self._key(session_id)}\r\n".encode(), (b"END\r\n",))
        if not resp.startswith(b"VALUE"):
            return {}                      # genuine miss — not an error
        try:
            header, rest = resp.split(b"\r\n", 1)
            nbytes = int(header.split()[3])
            return json.loads(rest[:nbytes].decode())
        except (ValueError, IndexError, json.JSONDecodeError):
            # A corrupt/unparseable value is treated as no session rather than
            # crashing the request; the next write replaces it.
            return {}

    @staticmethod
    def _exptime(ttl: int) -> int:
        """Convert a ttl in SECONDS to memcached's dual-meaning exptime field.

        memcached documents exptime as RELATIVE seconds up to 2592000 (30 days),
        and as an ABSOLUTE UNIX TIMESTAMP for anything larger. Sending a raw ttl
        of 2592001 therefore does not mean "30 days and one second" - it means
        1970-01-31, which is already past, so the item expires the instant it is
        stored. memcached still replies STORED, so the write looks fine and the
        very next read is a miss: a silent logout on every request.

        Measured against real memcached 1.6.45: ttl=2592000 survives, ttl=2592001
        vanishes instantly.

        We CONVERT rather than CLAMP. Clamping a 60-day session down to 30 days
        would silently shorten a lifetime the operator explicitly asked to be
        longer, which is the same class of lie in the other direction.
        """
        if ttl > _MAX_RELATIVE_EXPTIME:
            return int(time.time()) + ttl
        return ttl

    def write(self, session_id: str, data: dict, ttl: int = 0):
        """Store the session with a TTL (0 falls back to TINA4_SESSION_TTL)."""
        effective_ttl = self._exptime(ttl if ttl > 0 else self._ttl)
        payload = json.dumps(data, default=str).encode()
        cmd = f"set {self._key(session_id)} 0 {effective_ttl} {len(payload)}\r\n".encode()
        resp = self._command(cmd + payload + b"\r\n", (b"STORED\r\n", b"ERROR\r\n",
                                                       b"SERVER_ERROR", b"CLIENT_ERROR"))
        if not resp.startswith(b"STORED"):
            raise RuntimeError(f"Memcached did not store the session: {resp[:80]!r}")

    def destroy(self, session_id: str):
        """Delete the session. A key that was already gone is not an error."""
        self._command(
            f"delete {self._key(session_id)}\r\n".encode(),
            (b"DELETED\r\n", b"NOT_FOUND\r\n", b"ERROR\r\n"),
        )

    def gc(self, max_lifetime: int):
        """No-op — memcached expires keys itself via the TTL set on write."""
        pass

    def close(self):
        """No-op — each command uses its own short-lived connection."""
        pass
