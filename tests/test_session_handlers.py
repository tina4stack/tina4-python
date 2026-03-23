# Tests for Tina4 Session Handlers — Redis, MongoDB, Valkey.
"""
Tests cover:
- Handler interface/contract verification
- In-memory operation without external services (mocked)
- Skip markers for tests requiring actual Redis/MongoDB/Valkey
"""
import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch


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
        assert handler._ttl == 1800
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
        assert handler._ttl == 1800

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


class TestMongoDBHandlerMocked:
    """Test MongoDB handler with mocked pymongo client."""

    def _make_handler_with_mock(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler()
        mock_collection = MagicMock()
        handler._collection = mock_collection
        handler._use_pymongo = True
        return handler, mock_collection

    def test_read_returns_empty_when_no_doc(self):
        handler, mock_collection = self._make_handler_with_mock()
        mock_collection.find_one.return_value = None
        assert handler.read("session-1") == {}

    def test_read_returns_session_data(self):
        handler, mock_collection = self._make_handler_with_mock()
        mock_collection.find_one.return_value = {
            "_id": "session-1",
            "data": {"user_id": 42},
            "last_accessed": time.time(),
        }
        result = handler.read("session-1")
        assert result == {"user_id": 42}

    def test_read_expired_session_returns_empty(self):
        handler, mock_collection = self._make_handler_with_mock()
        handler._ttl = 60
        mock_collection.find_one.return_value = {
            "_id": "session-1",
            "data": {"user_id": 42},
            "last_accessed": time.time() - 120,  # expired
        }
        result = handler.read("session-1")
        assert result == {}
        mock_collection.delete_one.assert_called_once()

    def test_write_upserts(self):
        handler, mock_collection = self._make_handler_with_mock()
        handler.write("session-1", {"user_id": 42})
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"_id": "session-1"}
        assert call_args[1]["upsert"] is True

    def test_destroy(self):
        handler, mock_collection = self._make_handler_with_mock()
        handler.destroy("session-1")
        mock_collection.delete_one.assert_called_once_with({"_id": "session-1"})

    def test_gc_deletes_expired(self):
        handler, mock_collection = self._make_handler_with_mock()
        handler.gc(1800)
        mock_collection.delete_many.assert_called_once()
        call_args = mock_collection.delete_many.call_args[0][0]
        assert "$lt" in call_args["last_accessed"]


# ── Valkey Handler Tests ─────────────────────────────────────────


class TestValkeyHandlerConfig:
    """Test Valkey handler configuration without connecting."""

    def test_default_config(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler()
        assert handler._host == "localhost"
        assert handler._port == 6379
        assert handler._db == 0
        assert handler._ttl == 1800
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

        monkeypatch.setenv("TINA4_SESSION_BACKEND", "database")
        # DatabaseSessionHandler requires a db arg; patch it to accept no-arg construction
        db = Database("sqlite::memory:")
        with patch(
            "tina4_python.session.DatabaseSessionHandler",
            return_value=DatabaseSessionHandler(db),
        ) as mock_cls:
            handler = Session._resolve_handler()
            mock_cls.assert_called_once()
            assert isinstance(handler, DatabaseSessionHandler)


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
    not os.environ.get("TINA4_TEST_REDIS_URL"),
    reason="TINA4_TEST_REDIS_URL not set"
)
class TestRedisIntegration:
    """Integration tests that require an actual Redis server."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        handler = RedisSessionHandler(ttl=60)
        handler.write("int-test", {"user_id": 99})
        data = handler.read("int-test")
        assert data["user_id"] == 99
        handler.destroy("int-test")
        assert handler.read("int-test") == {}
        handler.close()


@pytest.mark.skipif(
    not os.environ.get("TINA4_TEST_MONGO_URL"),
    reason="TINA4_TEST_MONGO_URL not set"
)
class TestMongoDBIntegration:
    """Integration tests that require an actual MongoDB server."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        handler = MongoDBSessionHandler(ttl=60)
        handler.write("int-test", {"user_id": 99})
        data = handler.read("int-test")
        assert data["user_id"] == 99
        handler.destroy("int-test")
        assert handler.read("int-test") == {}
        handler.close()


@pytest.mark.skipif(
    not os.environ.get("TINA4_TEST_VALKEY_URL"),
    reason="TINA4_TEST_VALKEY_URL not set"
)
class TestValkeyIntegration:
    """Integration tests that require an actual Valkey server."""

    def test_read_write_destroy_cycle(self):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        handler = ValkeySessionHandler(ttl=60)
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
