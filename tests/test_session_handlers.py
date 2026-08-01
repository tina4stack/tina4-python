# Tests for Tina4 Session Handlers — Redis, MongoDB, Valkey.
"""
Tests cover:
- Handler interface/contract verification
- In-memory operation without external services (mocked)
- Skip markers for tests requiring actual Redis/MongoDB/Valkey
"""
import json
import os
import socket as _socket
import time
from urllib.parse import urlparse
import pytest
from unittest.mock import MagicMock, patch


# ── Live-service targets ─────────────────────────────────────────
# The integration tests below run a real write->read->destroy round-trip against
# the provisioned Redis/MongoDB/Valkey. They are gated on the service being
# REACHABLE (not on an opt-in env var), so they RUN BY DEFAULT whenever the
# local/CI infra is up — the same pattern the other real-service suites use
# (test_queue_backends, test_database_drivers). An env var still overrides the
# target (CI sets TINA4_TEST_*_URL); it just defaults to the local docker infra.
# Under TINA4_REQUIRE_SERVICES (CI) a "not reachable" skip becomes a hard failure
# (see conftest.py), so a provisioned session backend can never silently no-op.


def _service_target(env_var: str, default_url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(os.environ.get(env_var) or default_url)
    return (parsed.hostname or "localhost", parsed.port or default_port)


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with _socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_REDIS_HOST, _REDIS_PORT = _service_target("TINA4_TEST_REDIS_URL", "redis://localhost:6379", 6379)
_MONGO_HOST, _MONGO_PORT = _service_target("TINA4_TEST_MONGO_URL", "mongodb://localhost:27017", 27017)
_VALKEY_HOST, _VALKEY_PORT = _service_target("TINA4_TEST_VALKEY_URL", "redis://localhost:6380", 6380)


# ── Interface Contract Tests ─────────────────────────────────────


class TestSessionHandlerContract:
    """Verify that all handlers extend SessionHandler and implement required methods."""

    def test_redis_handler_extends_session_handler(self):
        from tina4_python.session import SessionHandler
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        assert issubclass(RedisSessionHandler, SessionHandler)
        handler = RedisSessionHandler()
        assert callable(getattr(handler, "read", None))
        assert callable(getattr(handler, "write", None))
        assert callable(getattr(handler, "destroy", None))
        assert callable(getattr(handler, "gc", None))

    def test_mongodb_handler_extends_session_handler(self):
        from tina4_python.session import SessionHandler
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        assert issubclass(MongoDBSessionHandler, SessionHandler)
        handler = MongoDBSessionHandler()
        assert callable(getattr(handler, "read", None))
        assert callable(getattr(handler, "write", None))
        assert callable(getattr(handler, "destroy", None))
        assert callable(getattr(handler, "gc", None))

    def test_valkey_handler_extends_session_handler(self):
        from tina4_python.session import SessionHandler
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        assert issubclass(ValkeySessionHandler, SessionHandler)
        handler = ValkeySessionHandler()
        assert callable(getattr(handler, "read", None))
        assert callable(getattr(handler, "write", None))
        assert callable(getattr(handler, "destroy", None))
        assert callable(getattr(handler, "gc", None))

    def test_database_handler_extends_session_handler(self):
        from tina4_python.session import SessionHandler, DatabaseSessionHandler
        from tina4_python.database import Database

        db = Database("sqlite::memory:")
        assert issubclass(DatabaseSessionHandler, SessionHandler)
        handler = DatabaseSessionHandler(db)
        assert callable(getattr(handler, "read", None))
        assert callable(getattr(handler, "write", None))
        assert callable(getattr(handler, "destroy", None))
        assert callable(getattr(handler, "gc", None))


# ── Redis Handler Tests ──────────────────────────────────────────


class TestRedisHandlerConfig:
    """Test Redis handler configuration without connecting."""

    def test_default_config(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler()
        assert handler._host == "localhost"
        assert handler._port == 6379
        assert handler._db == 0
        assert handler._ttl == 3600  # default documented in redis_handler.py
        assert handler._prefix == "tina4:session:"

    def test_custom_config(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler(
            host="redis.example.com",
            port=6380,
            db=2,
            ttl=3600,
            prefix="myapp:sess:",
            password="secret",
        )
        assert handler._host == "redis.example.com"
        assert handler._port == 6380
        assert handler._db == 2
        assert handler._ttl == 3600
        assert handler._prefix == "myapp:sess:"
        assert handler._password == "secret"

    def test_env_config(self, monkeypatch):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        monkeypatch.setenv("TINA4_SESSION_REDIS_HOST", "redis-env")
        monkeypatch.setenv("TINA4_SESSION_REDIS_PORT", "6390")
        monkeypatch.setenv("TINA4_SESSION_REDIS_PASSWORD", "envpass")
        monkeypatch.setenv("TINA4_SESSION_REDIS_DB", "3")
        monkeypatch.setenv("TINA4_SESSION_TTL", "7200")

        handler = RedisSessionHandler()
        assert handler._host == "redis-env"
        assert handler._port == 6390
        assert handler._password == "envpass"
        assert handler._db == 3
        assert handler._ttl == 7200

    def test_gc_is_noop(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler()
        handler.gc(1800)  # Should not raise


class TestRedisHandlerMocked:
    """Test Redis handler with mocked redis client."""

    def _make_handler_with_mock(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler()
        mock_client = MagicMock()
        handler._redis_client = mock_client
        handler._use_redis_pkg = True
        return handler, mock_client

    def test_read_returns_empty_when_no_data(self):
        handler, mock_client = self._make_handler_with_mock()
        mock_client.get.return_value = None
        assert handler.read("session-1") == {}

    def test_read_returns_parsed_json(self):
        handler, mock_client = self._make_handler_with_mock()
        mock_client.get.return_value = json.dumps({"user_id": 42, "role": "admin"})
        result = handler.read("session-1")
        assert result == {"user_id": 42, "role": "admin"}

    def test_read_returns_empty_on_invalid_json(self):
        handler, mock_client = self._make_handler_with_mock()
        mock_client.get.return_value = "not-json"
        assert handler.read("session-1") == {}

    def test_write_with_ttl(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.write("session-1", {"user_id": 42}, ttl=600)
        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[0] == "tina4:session:session-1"
        assert args[1] == 600

    def test_write_uses_default_ttl(self):
        handler, mock_client = self._make_handler_with_mock()
        handler._ttl = 1800
        handler.write("session-1", {"user_id": 42})
        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[1] == 1800

    def test_destroy(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.destroy("session-1")
        mock_client.delete.assert_called_once_with("tina4:session:session-1")

    def test_close(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.close()
        mock_client.close.assert_called_once()


# ── MongoDB Handler Tests ────────────────────────────────────────


class TestMongoDBHandlerConfig:
    """Test MongoDB handler configuration without connecting."""

    def test_default_config(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler()
        assert handler._host == "localhost"
        assert handler._port == 27017
        assert handler._database == "tina4"
        assert handler._collection_name == "sessions"
        assert handler._ttl == 3600  # default documented in mongodb_handler.py

    def test_custom_config(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler(
            url="mongodb://mongo.example.com:27018",
            database="myapp",
            collection="user_sessions",
            ttl=3600,
        )
        assert handler._host == "mongo.example.com"
        assert handler._port == 27018
        assert handler._database == "myapp"
        assert handler._collection_name == "user_sessions"
        assert handler._ttl == 3600

    def test_env_config(self, monkeypatch):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        monkeypatch.setenv("TINA4_SESSION_MONGO_URL", "mongodb://mongo-env:27019")
        monkeypatch.setenv("TINA4_SESSION_MONGO_DB", "envdb")
        monkeypatch.setenv("TINA4_SESSION_MONGO_COLLECTION", "env_sessions")
        monkeypatch.setenv("TINA4_SESSION_TTL", "7200")

        handler = MongoDBSessionHandler()
        assert handler._host == "mongo-env"
        assert handler._port == 27019
        assert handler._database == "envdb"
        assert handler._collection_name == "env_sessions"
        assert handler._ttl == 7200

    def test_url_parsing(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler(url="mongodb://user:pass@db.host.com:27020/mydb")
        assert handler._host == "db.host.com"
        assert handler._port == 27020


@pytest.mark.skipif(
    not _reachable(_MONGO_HOST, _MONGO_PORT),
    reason=f"MongoDB is not reachable at {_MONGO_HOST}:{_MONGO_PORT}",
)
class TestMongoDBHandlerReal:
    """MongoDB handler against a REAL MongoDB server.

    This class replaces a MagicMock-based one. The mocks asserted the SHAPE of
    the pymongo calls (``update_one`` was called, the filter had ``$lt`` on
    ``last_accessed``), which is not the same thing as the handler working - and
    two of those assertions were pinning the destroy-on-unstamped defect in
    place, so the mock suite went green while the bug shipped.

    Every assertion below is made OUT OF BAND with an independent pymongo
    handle, never through the code under test.
    """

    @pytest.fixture
    def handler(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        pytest.importorskip("pymongo", reason="pymongo is not installed")
        instance = MongoDBSessionHandler(
            url=f"mongodb://{_MONGO_HOST}:{_MONGO_PORT}",
            database="tina4_test",
            collection="session_handlers",
            ttl=3600,
        )
        instance._collection.delete_many({})
        yield instance
        try:
            instance._collection.delete_many({})
        finally:
            instance.close()

    def _probe(self):
        """An INDEPENDENT client for out-of-band assertions."""
        import pymongo

        return pymongo.MongoClient(
            f"mongodb://{_MONGO_HOST}:{_MONGO_PORT}", serverSelectionTimeoutMS=3000
        )["tina4_test"]["session_handlers"]

    def test_read_returns_empty_when_no_doc(self, handler):
        assert handler.read("no-such-session") == {}

    def test_read_returns_session_data(self, handler):
        handler.write("session-1", {"user_id": 42}, 3600)
        assert handler.read("session-1") == {"user_id": 42}

    def test_read_expired_session_returns_empty_and_destroys(self, handler):
        """A GENUINELY expired document still reads empty and is still destroyed."""
        self._probe().insert_one({
            "_id": "session-1",
            "data": {"user_id": 42},
            "expires_at": time.time() - 120,
        })

        assert handler.read("session-1") == {}
        assert self._probe().find_one({"_id": "session-1"}) is None

    def test_read_unstamped_document_survives(self, handler):
        """A document carrying NO expiry must be returned and KEPT.

        The old relative shape (``time.time() - doc.get("last_accessed", 0) >
        self._ttl``) fed a missing stamp into a subtraction that is always true
        and then called destroy(), so an unstamped document was silently
        destroyed on first read.
        """
        self._probe().insert_one({"_id": "naked", "data": {"user_id": 42}})

        assert handler.read("naked") == {"user_id": 42}
        assert self._probe().find_one({"_id": "naked"}) is not None

    def test_write_upserts(self, handler):
        handler.write("session-1", {"user_id": 42}, 3600)
        handler.write("session-1", {"user_id": 43}, 3600)

        assert self._probe().count_documents({"_id": "session-1"}) == 1
        assert handler.read("session-1") == {"user_id": 43}

    def test_write_honours_the_per_call_ttl(self, handler):
        handler.write("shortlived", {"user_id": 42}, 1)

        stored = self._probe().find_one({"_id": "shortlived"})
        assert stored["expires_at"] - time.time() < 5, "a ttl of 1s must not become the 3600s default"

    def test_destroy(self, handler):
        handler.write("session-1", {"user_id": 42}, 3600)
        handler.destroy("session-1")

        assert self._probe().find_one({"_id": "session-1"}) is None

    def test_gc_deletes_expired_but_keeps_unstamped(self, handler):
        probe = self._probe()
        probe.insert_one({"_id": "stale", "data": {"a": 1}, "expires_at": time.time() - 120})
        probe.insert_one({"_id": "naked", "data": {"a": 1}})
        probe.insert_one({"_id": "zeroed", "data": {"a": 1}, "expires_at": 0})

        handler.gc(1800)

        assert probe.find_one({"_id": "stale"}) is None, "a genuinely expired doc must be swept"
        assert probe.find_one({"_id": "naked"}) is not None, "an unstamped doc must never be swept"
        assert probe.find_one({"_id": "zeroed"}) is not None, "a zero-stamped doc must never be swept"



# ── Valkey Handler Tests ─────────────────────────────────────────


class TestValkeyHandlerConfig:
    """Test Valkey handler configuration without connecting."""

    def test_default_config(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler()
        assert handler._host == "localhost"
        assert handler._port == 6379
        assert handler._db == 0
        assert handler._ttl == 3600  # default documented in valkey_handler.py
        assert handler._prefix == "tina4:session:"

    def test_custom_config(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler(
            host="valkey.example.com",
            port=6380,
            db=1,
            ttl=3600,
            prefix="valkey:sess:",
            password="valkeypass",
        )
        assert handler._host == "valkey.example.com"
        assert handler._port == 6380
        assert handler._db == 1
        assert handler._ttl == 3600
        assert handler._prefix == "valkey:sess:"
        assert handler._password == "valkeypass"

    def test_env_config(self, monkeypatch):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        monkeypatch.setenv("TINA4_SESSION_VALKEY_HOST", "valkey-env")
        monkeypatch.setenv("TINA4_SESSION_VALKEY_PORT", "6400")
        monkeypatch.setenv("TINA4_SESSION_VALKEY_PASSWORD", "envpass")
        monkeypatch.setenv("TINA4_SESSION_VALKEY_DB", "5")
        monkeypatch.setenv("TINA4_SESSION_TTL", "900")

        handler = ValkeySessionHandler()
        assert handler._host == "valkey-env"
        assert handler._port == 6400
        assert handler._password == "envpass"
        assert handler._db == 5
        assert handler._ttl == 900

    def test_gc_is_noop(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler()
        handler.gc(1800)  # Should not raise


class TestValkeyHandlerMocked:
    """Test Valkey handler with mocked redis client."""

    def _make_handler_with_mock(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler()
        mock_client = MagicMock()
        handler._redis_client = mock_client
        handler._use_redis_pkg = True
        return handler, mock_client

    def test_read_returns_empty_when_no_data(self):
        handler, mock_client = self._make_handler_with_mock()
        mock_client.get.return_value = None
        assert handler.read("session-1") == {}

    def test_read_returns_parsed_json(self):
        handler, mock_client = self._make_handler_with_mock()
        mock_client.get.return_value = json.dumps({"theme": "dark"})
        result = handler.read("session-1")
        assert result == {"theme": "dark"}

    def test_write_with_ttl(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.write("session-1", {"theme": "dark"}, ttl=300)
        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[0] == "tina4:session:session-1"
        assert args[1] == 300

    def test_destroy(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.destroy("session-1")
        mock_client.delete.assert_called_once_with("tina4:session:session-1")

    def test_close(self):
        handler, mock_client = self._make_handler_with_mock()
        handler.close()
        mock_client.close.assert_called_once()


# ── Database Session Handler Tests ────────────────────────────────


class TestDatabaseSessionHandler:
    """Test DatabaseSessionHandler with a real SQLite in-memory database."""

    def _make_handler(self):
        from tina4_python.session import DatabaseSessionHandler
        from tina4_python.database import Database

        db = Database("sqlite::memory:")
        handler = DatabaseSessionHandler(db)
        return handler

    def test_write_and_read(self):
        handler = self._make_handler()
        handler.write("sess-1", {"user_id": 42, "role": "admin"}, ttl=1800)
        result = handler.read("sess-1")
        assert result == {"user_id": 42, "role": "admin"}

    def test_read_nonexistent(self):
        handler = self._make_handler()
        result = handler.read("nonexistent-session")
        assert result == {}

    def test_destroy(self):
        handler = self._make_handler()
        handler.write("sess-2", {"user_id": 99}, ttl=1800)
        assert handler.read("sess-2") == {"user_id": 99}
        handler.destroy("sess-2")
        assert handler.read("sess-2") == {}

    def test_expiry(self):
        handler = self._make_handler()
        handler.write("sess-3", {"user_id": 7}, ttl=1)
        time.sleep(1.5)
        result = handler.read("sess-3")
        assert result == {}

    def test_gc(self):
        handler = self._make_handler()
        # Write two sessions with very short TTL (already expired)
        handler.write("expired-1", {"a": 1}, ttl=1)
        handler.write("expired-2", {"b": 2}, ttl=1)
        # Write one session that is still valid
        handler.write("valid-1", {"c": 3}, ttl=3600)
        time.sleep(1.5)
        handler.gc(1800)
        # Expired sessions should be cleaned up
        assert handler.read("expired-1") == {}
        assert handler.read("expired-2") == {}
        # Valid session should still exist
        assert handler.read("valid-1") == {"c": 3}


class TestResolveHandlerDatabase:
    """Test that Session._resolve_handler returns DatabaseSessionHandler for database backend."""

    def test_resolve_handler_database(self, monkeypatch):
        from tina4_python.session import Session, DatabaseSessionHandler
        from tina4_python.database import Database
        from tina4_python.orm import model as orm_model

        monkeypatch.setenv("TINA4_SESSION_BACKEND", "database")
        # Bind a REAL in-memory SQLite database — the database backend resolves
        # whatever connection the ORM is bound to, exactly as it does in a live
        # app. No patching: _resolve_handler() runs for real and the returned
        # handler is wired to this real db.
        prev_db = orm_model._database
        db = Database("sqlite::memory:")
        orm_model.bind_database(db)
        try:
            handler = Session._resolve_handler()
            assert isinstance(handler, DatabaseSessionHandler)
            # Exercise the real handler end-to-end against the real SQLite db.
            handler.write("resolve-1", {"user_id": 5}, ttl=3600)
            assert handler.read("resolve-1") == {"user_id": 5}
            handler.destroy("resolve-1")
            assert handler.read("resolve-1") == {}
        finally:
            orm_model._database = prev_db


# ── Session Integration Tests ────────────────────────────────────


class TestSessionWithHandlers:
    """Test that handlers work with the Session class."""

    def _make_redis_handler_mocked(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler()
        mock_client = MagicMock()
        handler._redis_client = mock_client
        handler._use_redis_pkg = True
        return handler, mock_client

    def test_session_with_redis_handler(self):
        from tina4_python.session import Session

        handler, mock_client = self._make_redis_handler_mocked()
        mock_client.get.return_value = None

        session = Session(handler=handler, ttl=600)
        sid = session.start("test-session")
        assert sid == "test-session"
        session.set("user_id", 42)
        assert session.get("user_id") == 42

    def test_session_with_valkey_handler(self):
        from tina4_python.session import Session
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler()
        mock_client = MagicMock()
        handler._redis_client = mock_client
        handler._use_redis_pkg = True
        mock_client.get.return_value = None

        session = Session(handler=handler, ttl=600)
        sid = session.start("valkey-session")
        assert sid == "valkey-session"
        session.set("lang", "en")
        assert session.get("lang") == "en"


# ── Integration Tests (require actual services) ─────────────────


@pytest.mark.skipif(
    not _reachable(_REDIS_HOST, _REDIS_PORT),
    reason="redis not reachable"
)
class TestRedisIntegration:
    """Integration tests that drive a real Redis server (no mocks)."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=60)
        handler.write("int-test", {"user_id": 99})
        data = handler.read("int-test")
        assert data["user_id"] == 99
        handler.destroy("int-test")
        assert handler.read("int-test") == {}
        handler.close()


@pytest.mark.skipif(
    not _reachable(_MONGO_HOST, _MONGO_PORT),
    reason="mongo not reachable"
)
class TestMongoDBIntegration:
    """Integration tests that drive a real MongoDB server (no mocks)."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler(url=f"mongodb://{_MONGO_HOST}:{_MONGO_PORT}", ttl=60)
        handler.write("int-test", {"user_id": 99})
        data = handler.read("int-test")
        assert data["user_id"] == 99
        handler.destroy("int-test")
        assert handler.read("int-test") == {}
        handler.close()


@pytest.mark.skipif(
    not _reachable(_VALKEY_HOST, _VALKEY_PORT),
    reason="valkey not reachable"
)
class TestValkeyIntegration:
    """Integration tests that drive a real Valkey server (no mocks)."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler(host=_VALKEY_HOST, port=_VALKEY_PORT, ttl=60)
        handler.write("int-test", {"user_id": 99})
        data = handler.read("int-test")
        assert data["user_id"] == 99
        handler.destroy("int-test")
        assert handler.read("int-test") == {}
        handler.close()


# ── Import Tests ─────────────────────────────────────────────────


class TestImports:
    """Test that handlers can be imported from the package."""

    def test_import_from_package(self):
        from tina4_python.session_handlers import (
            RedisSessionHandler,
            MongoDBSessionHandler,
            ValkeySessionHandler,
        )

        assert RedisSessionHandler is not None
        assert MongoDBSessionHandler is not None
        assert ValkeySessionHandler is not None

    def test_instantiate_without_connection(self):
        from tina4_python.session_handlers import (
            RedisSessionHandler,
            MongoDBSessionHandler,
            ValkeySessionHandler,
        )

        redis_h = RedisSessionHandler()
        mongo_h = MongoDBSessionHandler()
        valkey_h = ValkeySessionHandler()
        assert redis_h is not None
        assert mongo_h is not None
        assert valkey_h is not None
