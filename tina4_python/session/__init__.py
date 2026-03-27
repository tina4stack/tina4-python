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


class SessionHandler:
    """Base class for session storage backends."""

    def read(self, session_id: str) -> dict:
        raise NotImplementedError

    def write(self, session_id: str, data: dict, ttl: int):
        raise NotImplementedError

    def destroy(self, session_id: str):
        raise NotImplementedError

    def gc(self, max_lifetime: int):
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

    def write(self, session_id: str, data: dict, ttl: int):
        f = self._file(session_id)
        expires = time.time() + ttl if ttl > 0 else 0
        f.write_text(
            json.dumps({"_data": data, "_expires": expires}, default=str),
            encoding="utf-8",
        )

    def destroy(self, session_id: str):
        self._file(session_id).unlink(missing_ok=True)

    def gc(self, max_lifetime: int):
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

    def write(self, session_id: str, data: dict, ttl: int):
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

    def gc(self, max_lifetime: int):
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
        self._ttl = ttl or int(os.environ.get("TINA4_SESSION_TTL", "1800"))  # 30 min
        self._session_id: str | None = None
        self._data: dict = {}
        self._dirty: bool = False

    @staticmethod
    def _resolve_handler() -> SessionHandler:
        """Auto-select session handler from TINA4_SESSION_BACKEND env var."""
        backend = os.environ.get("TINA4_SESSION_BACKEND", "file").lower().strip()
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
        elif backend in ("database", "db"):
            return DatabaseSessionHandler()
        else:
            return FileSessionHandler()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def start(self, session_id: str = None) -> str:
        """Start or resume a session. Returns the session ID."""
        self._session_id = session_id or secrets.token_urlsafe(32)
        self._data = self._handler.read(self._session_id)
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

    def all(self) -> dict:
        """Get all session data."""
        return dict(self._data)

    def clear(self):
        """Clear all session data."""
        self._data.clear()
        self._dirty = True

    def save(self):
        """Persist session data to the backend."""
        if self._session_id and self._dirty:
            self._handler.write(self._session_id, self._data, self._ttl)
            self._dirty = False

    def destroy(self):
        """Destroy the session entirely."""
        if self._session_id:
            self._handler.destroy(self._session_id)
            self._data.clear()
            self._session_id = None
            self._dirty = False

    def regenerate(self) -> str:
        """Regenerate session ID (prevents fixation attacks)."""
        old_id = self._session_id
        if old_id:
            self._handler.destroy(old_id)
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

    def cookie_header(self, cookie_name: str = "tina4_session") -> str:
        """Return a Set-Cookie header value for this session."""
        samesite = os.environ.get("TINA4_SESSION_SAMESITE", "Lax")
        return f"{cookie_name}={self._session_id}; Path=/; HttpOnly; SameSite={samesite}; Max-Age={self._ttl}"

    def gc(self):
        """Run garbage collection on the backend."""
        self._handler.gc(self._ttl)


__all__ = [
    "Session", "SessionHandler",
    "FileSessionHandler", "DatabaseSessionHandler",
]
