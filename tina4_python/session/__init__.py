# Tina4 Session — Pluggable session backends, zero core dependencies.
"""
File-based sessions by default. Pluggable backends for Redis, MongoDB, Database.

    from tina4_python.session import Session, FileSessionHandler

    session = Session(handler=FileSessionHandler("/tmp/sessions"))
    session.start("session-id-123")
    session.set("user_id", 42)
    session.get("user_id")  # 42
    session.save()
"""
import os
import json
import time
import hashlib
import secrets
from pathlib import Path


def session_cookie_name() -> str:
    """Resolve the session cookie name — the single source of truth shared by
    the WRITE side (``Session.cookie_header``) and the READ side
    (``core/server._init_session``), so a cookie written under a renamed name is
    read back on the next request.

        TINA4_SESSION_NAME   Cookie name (default: ``tina4_session``)

    Keeping this in one place means the default can never drift between the two
    sides: an operator who sets ``TINA4_SESSION_NAME`` renames the cookie on both
    the emit and the parse paths at once.
    """
    return os.environ.get("TINA4_SESSION_NAME", "tina4_session")


class SessionHandler:
    """Base class for session storage backends."""

    def read(self, session_id: str) -> dict:
        raise NotImplementedError

    def write(self, session_id: str, data: dict, ttl: int = 0):
        raise NotImplementedError

    def destroy(self, session_id: str):
        raise NotImplementedError

    def gc(self, max_lifetime: int = 0):
        """Garbage-collect expired sessions."""
        pass


class FileSessionHandler(SessionHandler):
    """File-based session storage (default, zero-dep)."""

    def __init__(self, path: str = None):
        self._path = Path(
            path or os.environ.get("TINA4_SESSION_PATH", "data/sessions")
        )
        self._path.mkdir(parents=True, exist_ok=True)

    def _file(self, session_id: str) -> Path:
        safe = hashlib.sha256(session_id.encode()).hexdigest()
        return self._path / f"{safe}.json"

    def read(self, session_id: str) -> dict:
        f = self._file(session_id)
        if not f.exists():
            return {}
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("_expires", 0) and time.time() > data["_expires"]:
                f.unlink(missing_ok=True)
                return {}
            return data.get("_data", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def write(self, session_id: str, data: dict, ttl: int = 0):
        f = self._file(session_id)
        expires = time.time() + ttl if ttl > 0 else 0
        f.write_text(
            json.dumps({"_data": data, "_expires": expires}, default=str),
            encoding="utf-8",
        )

    def destroy(self, session_id: str):
        self._file(session_id).unlink(missing_ok=True)

    def gc(self, max_lifetime: int = 0):
        now = time.time()
        for f in self._path.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("_expires", 0) and now > data["_expires"]:
                    f.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                f.unlink(missing_ok=True)


class DatabaseSessionHandler(SessionHandler):
    """Database-backed session storage. Uses whatever DB is connected."""

    def __init__(self, db):
        self._db = db
        self._ensure_table()

    def _ensure_table(self):
        if not self._db.table_exists("tina4_session"):
            self._db.execute("""
                CREATE TABLE tina4_session (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            self._db.commit()

    def read(self, session_id: str) -> dict:
        row = self._db.fetch_one(
            "SELECT data, expires_at FROM tina4_session WHERE session_id = ?",
            [session_id],
        )
        if not row:
            return {}
        if row["expires_at"] and time.time() > row["expires_at"]:
            self.destroy(session_id)
            return {}
        try:
            return json.loads(row["data"])
        except json.JSONDecodeError:
            return {}

    def write(self, session_id: str, data: dict, ttl: int = 0):
        expires = time.time() + ttl if ttl > 0 else 0
        payload = json.dumps(data, default=str)
        existing = self._db.fetch_one(
            "SELECT session_id FROM tina4_session WHERE session_id = ?",
            [session_id],
        )
        if existing:
            self._db.execute(
                "UPDATE tina4_session SET data = ?, expires_at = ? WHERE session_id = ?",
                [payload, expires, session_id],
            )
        else:
            self._db.execute(
                "INSERT INTO tina4_session (session_id, data, expires_at) VALUES (?, ?, ?)",
                [session_id, payload, expires],
            )
        self._db.commit()

    def destroy(self, session_id: str):
        self._db.execute(
            "DELETE FROM tina4_session WHERE session_id = ?",
            [session_id],
        )
        self._db.commit()

    def gc(self, max_lifetime: int = 0):
        self._db.execute(
            "DELETE FROM tina4_session WHERE expires_at > 0 AND expires_at < ?",
            [time.time()],
        )
        self._db.commit()


class Session:
    """Session manager — works with any SessionHandler backend.

    Usage:
        session = Session()  # FileSessionHandler by default
        session.start()      # Generate or resume session
        session.set("key", "value")
        session.get("key")   # "value"
        session.save()
    """

    def __init__(self, handler: SessionHandler = None, ttl: int = None):
        self._handler = handler or self._resolve_handler()
        self._ttl = ttl or int(os.environ.get("TINA4_SESSION_TTL", "3600"))  # 60 min
        self._session_id: str | None = None
        self._data: dict = {}
        self._dirty: bool = False
        # Backend-failure policy (parity across all 4 frameworks): a backend
        # that becomes unreachable mid-request must NEVER take the whole app
        # down with it, and must NEVER fail silently. The default is
        # "log-loud + degrade" — a read failure logs an error and yields an
        # empty session, a write failure logs and is best-effort. Set
        # TINA4_SESSION_STRICT=true to re-raise instead (matches the `strict`
        # escape hatch used by events/seeding) when you'd rather a failed
        # persist surface loudly than be tolerated.
        self._strict: bool = str(
            os.environ.get("TINA4_SESSION_STRICT", "false")
        ).strip().lower() in ("true", "1", "yes", "on")

    #: Every accepted TINA4_SESSION_BACKEND value, aliases included. Byte-identical
    #: membership in all four frameworks; this tuple is the one place it is written
    #: in Python, so the dispatch below and the error message can never disagree.
    VALID_BACKENDS = (
        "file", "filesystem",
        "redis",
        "valkey",
        "mongodb", "mongo",
        "memcached", "memcache",
        "database", "db",
    )

    #: The canonical name of each backend, for the error message. Listing every
    #: alias would make the message longer without making it clearer.
    CANONICAL_BACKENDS = ("file", "redis", "valkey", "mongodb", "memcached", "database")

    @staticmethod
    def _resolve_handler() -> SessionHandler:
        """
        Auto-select session handler from TINA4_SESSION_BACKEND env var.

        An UNRECOGNISED name raises ValueError. It used to fall through to the
        file handler silently, which is the worst possible answer: a typo in
        TINA4_SESSION_BACKEND ("redsi", "Redis" before normalisation was uniform)
        wrote sessions to local disk while the operator believed they were in
        Redis. Nothing logged, nothing failed, and the symptom appeared later as
        users being logged out whenever a request landed on another instance.

        A BLANK value still means file. An env var set to "" is a SET variable,
        so it never reaches os.environ.get's default; treating blank as an error
        would break every deployment that clears the var to take the default.
        """
        backend = os.environ.get("TINA4_SESSION_BACKEND", "file").lower().strip()
        if not backend:
            return FileSessionHandler()
        if backend not in Session.VALID_BACKENDS:
            raise ValueError(
                f'Unknown session backend "{backend}". '
                f'Valid backends: {", ".join(Session.CANONICAL_BACKENDS)}. '
                "Leave TINA4_SESSION_BACKEND unset for the file default."
            )
        if backend in ("file", "filesystem"):
            return FileSessionHandler()
        elif backend in ("redis",):
            from tina4_python.session_handlers import RedisSessionHandler
            return RedisSessionHandler()
        elif backend in ("valkey",):
            from tina4_python.session_handlers import ValkeySessionHandler
            return ValkeySessionHandler()
        elif backend in ("mongodb", "mongo"):
            from tina4_python.session_handlers import MongoDBSessionHandler
            return MongoDBSessionHandler()
        elif backend in ("memcached", "memcache"):
            from tina4_python.session_handlers import MemcachedSessionHandler
            return MemcachedSessionHandler()
        elif backend in ("database", "db"):
            # Resolve the same connection the ORM uses (global bound db, then
            # TINA4_DATABASE_URL). DatabaseSessionHandler "uses whatever DB is
            # connected" — so reuse the single ORM resolver rather than guess.
            from tina4_python.orm.model import ORM
            return DatabaseSessionHandler(ORM._get_db())
        # No else. The membership check above already rejected everything that is
        # not in VALID_BACKENDS, so a silent file fallback here would only be able
        # to hide a name that IS valid but has no branch - which is a bug in this
        # method, not a user's typo, and must not be swallowed.
        raise ValueError(
            f'Session backend "{backend}" is listed in VALID_BACKENDS but has no '
            "handler branch. This is a framework bug, not a configuration error."
        )

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def get_session_id(self) -> str | None:
        """Return the current session ID string."""
        return self._session_id

    # ── Backend-failure policy: log-loud + degrade ─────────────────────
    #
    # The handlers themselves stay honest — they raise when the backend
    # (Redis/Valkey/Mongo/DB) is unreachable. The Session layer is the single
    # place that decides the resilience policy so every backend behaves the
    # same: a transient outage logs and degrades rather than 500-ing every
    # request (cascade outage) or vanishing silently. A genuinely empty result
    # (no such session yet) is NOT an error — the handler returns {} without
    # raising, so it never hits these logs.

    def _log_backend_error(self, op: str, exc: Exception) -> None:
        from tina4_python.debug import Log
        Log.error(
            f"Session backend {op} failed "
            f"({type(self._handler).__name__}): {exc}"
        )

    def _safe_read(self, session_id: str) -> dict:
        try:
            return self._handler.read(session_id)
        except Exception as exc:
            self._log_backend_error("read", exc)
            if self._strict:
                raise
            return {}

    def _safe_write(self, session_id: str, data: dict, ttl: int) -> bool:
        try:
            self._handler.write(session_id, data, ttl)
            return True
        except Exception as exc:
            self._log_backend_error("write", exc)
            if self._strict:
                raise
            return False

    def _safe_destroy(self, session_id: str) -> bool:
        try:
            self._handler.destroy(session_id)
            return True
        except Exception as exc:
            self._log_backend_error("destroy", exc)
            if self._strict:
                raise
            return False

    def start(self, session_id: str = None) -> str:
        """Start or resume a session. Returns the session ID."""
        self._session_id = session_id or secrets.token_urlsafe(32)
        self._data = self._safe_read(self._session_id)
        self._dirty = False
        return self._session_id

    def get(self, key: str, default=None):
        """Get a session value."""
        return self._data.get(key, default)

    def set(self, key: str, value):
        """Set a session value."""
        self._data[key] = value
        self._dirty = True

    def delete(self, key: str):
        """Remove a session key."""
        self._data.pop(key, None)
        self._dirty = True

    # Alias for backward compatibility
    unset = delete

    def has(self, key: str) -> bool:
        return key in self._data

    # ── Dict-style access ──────────────────────────────────────────────
    #
    # Flask, Django, and FastAPI all let users treat the session like a
    # dict (``session["key"] = value``, ``"key" in session``). We mirror
    # that. The four dunders below delegate to the same store as the
    # explicit set/get/delete/has API.

    def __getitem__(self, key: str):
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value
        self._dirty = True

    def __delitem__(self, key: str) -> None:
        if key not in self._data:
            raise KeyError(key)
        del self._data[key]
        self._dirty = True

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def all(self) -> dict:
        """Get all session data."""
        return dict(self._data)

    def clear(self):
        """Clear all session data."""
        self._data.clear()
        self._dirty = True

    def save(self):
        """Persist session data to the backend.

        Returns True on a successful persist, False if the backend was
        unreachable (logged). The dirty flag is only cleared on success so a
        later save() retries once the backend recovers.
        """
        if self._session_id and self._dirty:
            if self._safe_write(self._session_id, self._data, self._ttl):
                self._dirty = False
                return True
            return False
        return True

    def destroy(self):
        """Destroy the session entirely."""
        if self._session_id:
            self._safe_destroy(self._session_id)
            self._data.clear()
            self._session_id = None
            self._dirty = False

    def regenerate(self) -> str:
        """Regenerate session ID (prevents fixation attacks).

        Call this right after a successful login or any privilege change to
        defeat session fixation — the pre-auth ID is discarded and the data
        carried onto a fresh, unguessable ID.
        """
        old_id = self._session_id
        if old_id:
            self._safe_destroy(old_id)
        self._session_id = secrets.token_urlsafe(32)
        self._dirty = True
        self.save()
        return self._session_id

    def flash(self, key: str, value=None):
        """Set a flash message (auto-deleted after next read).

        Call with value to set, without to get (and auto-remove).
        """
        flash_key = f"_flash_{key}"
        if value is not None:
            self.set(flash_key, value)
        else:
            val = self.get(flash_key)
            self.unset(flash_key)
            return val

    def get_flash(self, key: str, default=None):
        """Get flash data by key (alias for flash(key) without value)."""
        result = self.flash(key)
        return result if result is not None else default

    def cookie_header(self, cookie_name: str = None, request=None) -> str:
        """Return a Set-Cookie header value for this session.

        Cookie attributes are env-driven so deployments can flip security
        flags without redeploying app code:

            TINA4_SESSION_NAME      Cookie name (default: tina4_session)
            TINA4_SESSION_HTTPONLY  HttpOnly flag (default: true)
            TINA4_SESSION_SECURE    Secure flag (default: false). Forces
                                    Secure on regardless of request scheme.
            TINA4_SESSION_SAMESITE  SameSite attribute (default: Lax)

        The Secure attribute is set when ANY of the following holds:

          1. TINA4_SESSION_SECURE is truthy (explicit opt-in), OR
          2. SameSite is ``None`` — browsers reject SameSite=None without
             Secure, OR
          3. the request is really on https — detected proxy-aware via
             ``request.is_secure_scheme()`` (honours x-forwarded-proto, first
             hop of a comma chain), so a session behind a TLS-terminating
             proxy still ships Secure (#95).

        Plain HTTP with no proxy signal and no TLS stays non-Secure: a Secure
        cookie over plain http is undeliverable and would silently break the
        session. Pass ``request`` so the scheme can be detected; omit it and
        only the env/SameSite signals apply.
        """
        if cookie_name is None:
            cookie_name = session_cookie_name()
        samesite = os.environ.get("TINA4_SESSION_SAMESITE", "Lax")
        # Default true for HttpOnly (matches v2 behaviour) — only drop the
        # flag when the operator explicitly opts out.
        httponly = str(os.environ.get("TINA4_SESSION_HTTPONLY", "true")).strip().lower() in ("true", "1", "yes", "on")
        secure = str(os.environ.get("TINA4_SESSION_SECURE", "false")).strip().lower() in ("true", "1", "yes", "on")
        secure = (
            secure
            or samesite.strip().lower() == "none"
            or (request is not None and request.is_secure_scheme())
        )

        parts = [f"{cookie_name}={self._session_id}", "Path=/"]
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        parts.append(f"SameSite={samesite}")
        parts.append(f"Max-Age={self._ttl}")
        return "; ".join(parts)

    def gc(self):
        """Run garbage collection on the backend (best-effort)."""
        try:
            self._handler.gc(self._ttl)
        except Exception as exc:
            self._log_backend_error("gc", exc)
            if self._strict:
                raise


__all__ = [
    "Session", "SessionHandler",
    "FileSessionHandler", "DatabaseSessionHandler",
    "session_cookie_name",
]
