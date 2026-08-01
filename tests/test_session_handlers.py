# Tests for Tina4 Session Handlers — Redis, MongoDB, Valkey.
"""
Tests cover:
- Handler interface/contract verification (construction only, no dependency)
- Real write/read/destroy/expiry/gc round-trips against the LIVE Redis, Valkey
  and MongoDB, verified out-of-band with an INDEPENDENT client
- Loud skips naming host and port when a service is absent

3.13.95 -- the no-mock sweep. This file used to carry three MagicMock classes
(TestRedisHandlerMocked, TestMongoDBHandlerMocked, TestValkeyHandlerMocked) plus
two MagicMock-backed Session tests. They asserted the SHAPE of a call
(`setex.assert_called_once_with(...)`) and never proved a single byte reached a
server -- the same defect that let the Node MongoDB queue redeliver every
completed job for two releases. Every one of them is gone; the assertions they
were reaching for are now made against the real store.

The out-of-band verification clients below (`redis.Redis`, `pymongo.MongoClient`)
are NOT doubles: they are second, independent connections to the same real
server, used to observe what the handler actually stored. That is the
`test_write_path_contract.py::ContractConnection` pattern -- a write visible only
on the writing handle is exactly the bug a second connection catches.
"""
import json
import os
import socket as _socket
import time
import uuid
from urllib.parse import urlparse
import pytest


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


# TestRedisHandlerMocked lived here. It drove read/write/destroy/close against a
# MagicMock and asserted setex/delete CALL SHAPES. Deleted in the no-mock sweep;
# every assertion it made now runs against the live Redis in
# TestRedisIntegration below, where the key name, the TTL and the deletion are
# read back off the server with an independent client.


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


# TestMongoDBHandlerMocked lived here. find_one returned a hand-written dict, so
# document round-trip, upsert semantics and the $lt gc query were never executed
# by Mongo, and test_read_expired_session_returns_empty FABRICATED last_accessed
# instead of letting a real document age. Deleted; see TestMongoDBIntegration.


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


# TestValkeyHandlerMocked lived here. It never opened a socket to Valkey, so it
# would have kept passing with the handler pointed at the wrong port entirely.
# Deleted; see TestValkeyIntegration, which talks to the real daemon on 6380.


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
    """Session over a REAL backend, proven by a CROSS-INSTANCE read-back.

    Both tests here used a MagicMock client and asserted
    ``session.get("user_id") == 42`` immediately after ``session.set`` -- which
    reads the in-process dict, not the store. They passed for a handler that
    discarded every write. The only assertion that proves a value left the
    process is a SECOND Session, built on a SECOND handler instance, resuming
    the same id and finding the value; that is what these do now.
    """

    def test_session_with_redis_handler(self):
        from tina4_python.session import Session
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        if not _reachable(_REDIS_HOST, _REDIS_PORT):
            pytest.skip(f"redis not reachable at {_REDIS_HOST}:{_REDIS_PORT}")

        writer = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=600)
        sid = f"sess-{uuid.uuid4().hex}"
        session = Session(handler=writer, ttl=600)
        assert session.start(sid) == sid
        session.set("user_id", 42)
        session.save()
        try:
            # A SEPARATE handler == a separate connection to the real server.
            reader = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=600)
            resumed = Session(handler=reader, ttl=600)
            assert resumed.start(sid) == sid
            assert resumed.get("user_id") == 42, (
                "the value never reached Redis -- Session.save() did not persist"
            )
            reader.close()
        finally:
            writer.destroy(sid)
            writer.close()

    def test_session_with_valkey_handler(self):
        from tina4_python.session import Session
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        if not _reachable(_VALKEY_HOST, _VALKEY_PORT):
            pytest.skip(f"valkey not reachable at {_VALKEY_HOST}:{_VALKEY_PORT}")

        writer = ValkeySessionHandler(host=_VALKEY_HOST, port=_VALKEY_PORT, ttl=600)
        sid = f"sess-{uuid.uuid4().hex}"
        session = Session(handler=writer, ttl=600)
        assert session.start(sid) == sid
        session.set("lang", "en")
        session.save()
        try:
            reader = ValkeySessionHandler(host=_VALKEY_HOST, port=_VALKEY_PORT, ttl=600)
            resumed = Session(handler=reader, ttl=600)
            assert resumed.start(sid) == sid
            assert resumed.get("lang") == "en", (
                "the value never reached Valkey -- Session.save() did not persist"
            )
            reader.close()
        finally:
            writer.destroy(sid)
            writer.close()


# ── Integration Tests (require actual services) ─────────────────


def _observer(host: int, port: int):
    """A SECOND, independent connection to the real Redis/Valkey.

    Not a double -- it is the witness. Everything the deleted MagicMock classes
    asserted about key names and TTLs is asserted here against what the server
    actually holds, on a connection the handler under test does not own.
    """
    import redis as redis_pkg

    return redis_pkg.Redis(host=host, port=port, db=0, decode_responses=True)


class _RedisLikeContract:
    """Shared real-server contract for the Redis and Valkey handlers.

    Valkey is a separate daemon on a separate port speaking its own build of the
    protocol; running the identical contract against both is the point.
    """

    HOST: str = ""
    PORT: int = 0
    NAME: str = ""

    def _handler(self, **kw):
        raise NotImplementedError

    def _sid(self):
        return f"itest-{uuid.uuid4().hex}"

    def test_read_write_destroy_cycle(self):
        handler = self._handler(ttl=60)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"user_id": 99})
            assert handler.read(sid)["user_id"] == 99
            handler.destroy(sid)
            assert handler.read(sid) == {}
            assert obs.exists(f"tina4:session:{sid}") == 0, "the key survived destroy()"
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_read_of_a_never_written_id_is_empty(self):
        # A genuinely unknown key on a HEALTHY server: empty, not an error.
        handler = self._handler(ttl=60)
        try:
            assert handler.read(self._sid()) == {}
        finally:
            handler.close()

    def test_write_stores_json_under_the_prefixed_key(self):
        # Replaces setex.assert_called_once_with(...): read the real bytes back
        # off the server on an independent connection.
        handler = self._handler(ttl=600)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"user_id": 42, "role": "admin"}, ttl=600)
            raw = obs.get(f"tina4:session:{sid}")
            assert raw is not None, f"nothing stored at tina4:session:{sid}"
            assert json.loads(raw) == {"user_id": 42, "role": "admin"}
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_explicit_ttl_is_applied_by_the_server(self):
        handler = self._handler(ttl=60)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"user_id": 42}, ttl=600)
            ttl = obs.ttl(f"tina4:session:{sid}")
            assert 590 <= ttl <= 600, f"server reports TTL {ttl}, expected ~600"
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_default_ttl_is_applied_by_the_server(self):
        handler = self._handler(ttl=1800)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"user_id": 42})  # no ttl arg -> handler default
            ttl = obs.ttl(f"tina4:session:{sid}")
            assert 1790 <= ttl <= 1800, f"server reports TTL {ttl}, expected ~1800"
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_a_custom_prefix_changes_the_real_key(self):
        prefix = f"probe:{uuid.uuid4().hex[:8]}:"
        handler = self._handler(ttl=60, prefix=prefix)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"a": 1})
            assert obs.exists(f"{prefix}{sid}") == 1
            assert obs.exists(f"tina4:session:{sid}") == 0
        finally:
            obs.delete(f"{prefix}{sid}")
            obs.close()
            handler.close()

    @pytest.mark.slow
    def test_the_ttl_actually_expires_the_session(self):
        # The MagicMock version could only ever assert the NUMBER 600 was passed.
        # This waits for the real server to drop the real key.
        handler = self._handler(ttl=60)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"user_id": 1}, ttl=1)
            assert handler.read(sid) == {"user_id": 1}
            time.sleep(1.5)
            assert obs.exists(f"tina4:session:{sid}") == 0, "server kept an expired key"
            assert handler.read(sid) == {}
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_corrupt_stored_bytes_read_as_an_empty_session(self):
        # Genuinely corrupt data in the real store, planted by an independent
        # client -- not a mocked return value.
        handler = self._handler(ttl=60)
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            obs.set(f"tina4:session:{sid}", "not-json")
            assert handler.read(sid) == {}
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()

    def test_close_releases_the_connection_and_is_repeatable(self):
        handler = self._handler(ttl=60)
        sid = self._sid()
        try:
            handler.write(sid, {"x": 1})
            handler.close()
            handler.close()  # idempotent against a real client
            # redis-py reconnects on demand: the handler is still usable, which
            # proves close() released rather than corrupted the pool.
            assert handler.read(sid) == {"x": 1}
        finally:
            handler.destroy(sid)
            handler.close()

    def test_the_zero_dependency_raw_protocol_path_talks_to_the_same_server(self):
        """The RESP fallback used when the `redis` package is absent.

        Selecting it is real configuration (the same switch __init__ makes when
        the import fails), not a double: the socket, the RESP framing and the
        server are all real. Nothing in the suite had ever run this path.
        """
        handler = self._handler(ttl=60)
        handler._use_redis_pkg = False
        handler._redis_client = None
        sid = self._sid()
        obs = _observer(self.HOST, self.PORT)
        try:
            handler.write(sid, {"raw": True}, ttl=300)
            assert obs.ttl(f"tina4:session:{sid}") > 0
            assert handler.read(sid) == {"raw": True}
            handler.destroy(sid)
            assert obs.exists(f"tina4:session:{sid}") == 0
        finally:
            obs.delete(f"tina4:session:{sid}")
            obs.close()
            handler.close()


@pytest.mark.skipif(
    not _reachable(_REDIS_HOST, _REDIS_PORT),
    reason=f"redis not reachable at {_REDIS_HOST}:{_REDIS_PORT}",
)
class TestRedisIntegration(_RedisLikeContract):
    """Real Redis. No doubles anywhere in this class."""

    HOST, PORT, NAME = _REDIS_HOST, _REDIS_PORT, "redis"

    def _handler(self, **kw):
        from tina4_python.session_handlers.redis_handler import RedisSessionHandler

        return RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, **kw)


@pytest.mark.skipif(
    not _reachable(_VALKEY_HOST, _VALKEY_PORT),
    reason=f"valkey not reachable at {_VALKEY_HOST}:{_VALKEY_PORT}",
)
class TestValkeyIntegration(_RedisLikeContract):
    """Real Valkey on its own port and its own daemon. No doubles."""

    HOST, PORT, NAME = _VALKEY_HOST, _VALKEY_PORT, "valkey"

    def _handler(self, **kw):
        from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler

        return ValkeySessionHandler(host=_VALKEY_HOST, port=_VALKEY_PORT, **kw)


@pytest.mark.skipif(
    not _reachable(_MONGO_HOST, _MONGO_PORT),
    reason=f"mongo not reachable at {_MONGO_HOST}:{_MONGO_PORT}",
)
class TestMongoDBIntegration:
    """Real MongoDB. Documents are observed with an independent pymongo client."""

    URL = f"mongodb://{_MONGO_HOST}:{_MONGO_PORT}"

    def _handler(self, **kw):
        from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

        return MongoDBSessionHandler(url=self.URL, **kw)

    def _observer(self, collection="sessions"):
        import pymongo

        client = pymongo.MongoClient(self.URL, serverSelectionTimeoutMS=3000)
        return client, client["tina4"][collection]

    def _sid(self):
        return f"itest-{uuid.uuid4().hex}"

    def test_read_write_destroy_cycle(self):
        handler = self._handler(ttl=60)
        sid = self._sid()
        client, coll = self._observer()
        try:
            handler.write(sid, {"user_id": 99})
            assert handler.read(sid)["user_id"] == 99
            handler.destroy(sid)
            assert handler.read(sid) == {}
            assert coll.find_one({"_id": sid}) is None, "the document survived destroy()"
        finally:
            coll.delete_one({"_id": sid})
            client.close()
            handler.close()

    def test_a_second_handler_instance_reads_the_same_document(self):
        # Durability, not local state: the reader is a separate client.
        writer = self._handler(ttl=60)
        reader = self._handler(ttl=60)
        sid = self._sid()
        try:
            writer.write(sid, {"user_id": 7, "role": "admin"})
            assert reader.read(sid) == {"user_id": 7, "role": "admin"}
        finally:
            writer.destroy(sid)
            writer.close()
            reader.close()

    def test_read_of_a_never_written_id_is_empty(self):
        handler = self._handler(ttl=60)
        try:
            assert handler.read(self._sid()) == {}
        finally:
            handler.close()

    def test_write_upserts_rather_than_duplicating(self):
        handler = self._handler(ttl=60)
        sid = self._sid()
        client, coll = self._observer()
        try:
            handler.write(sid, {"n": 1})
            handler.write(sid, {"n": 2})
            assert coll.count_documents({"_id": sid}) == 1
            assert coll.find_one({"_id": sid})["data"] == {"n": 2}
        finally:
            coll.delete_one({"_id": sid})
            client.close()
            handler.close()

    @pytest.mark.slow
    def test_a_genuinely_aged_document_reads_empty_and_is_removed(self):
        # The mocked version fabricated last_accessed. This lets a REAL document
        # age past a REAL ttl and then checks Mongo no longer holds it.
        handler = self._handler(ttl=1)
        sid = self._sid()
        client, coll = self._observer()
        try:
            handler.write(sid, {"user_id": 42})
            assert coll.find_one({"_id": sid}) is not None
            time.sleep(1.5)
            assert handler.read(sid) == {}
            assert coll.find_one({"_id": sid}) is None, (
                "an expired read must destroy the document, not just hide it"
            )
        finally:
            coll.delete_one({"_id": sid})
            client.close()
            handler.close()

    @pytest.mark.slow
    def test_gc_removes_only_the_genuinely_expired_documents(self):
        # Own collection so gc() cannot disturb anything else in the database.
        coll_name = f"sessions_gc_{uuid.uuid4().hex[:8]}"
        handler = self._handler(ttl=3600, collection=coll_name)
        client, coll = self._observer(coll_name)
        old_a, old_b, fresh = self._sid(), self._sid(), self._sid()
        try:
            handler.write(old_a, {"a": 1})
            handler.write(old_b, {"b": 2})
            time.sleep(2)
            handler.write(fresh, {"c": 3})
            handler.gc(1)  # anything last touched more than 1s ago
            assert coll.find_one({"_id": old_a}) is None
            assert coll.find_one({"_id": old_b}) is None
            assert coll.find_one({"_id": fresh}) is not None, "gc ate a live session"
            assert coll.count_documents({}) == 1
        finally:
            coll.drop()
            client.close()
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
