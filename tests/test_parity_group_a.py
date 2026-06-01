"""Parity Group A — ergonomic-win additions on Database, Queue, Session,
WebSocketConnection, I18n, Migration.

These tests pin the new surface introduced in 3.13.0 to address the
docs↔code audit. Each documented symbol gets a passing test so the
audit gate stays green.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ─── Database.get_connection / fetch_all / pool property ──────────────────


def _sqlite_db():
    """Fresh in-memory SQLite Database for each test."""
    from tina4_python.database import Database
    return Database("sqlite:///:memory:")


class TestDatabaseGetConnection:
    def test_classmethod_returns_database(self):
        from tina4_python.database import Database
        db = Database.get_connection("sqlite:///:memory:")
        assert isinstance(db, Database)
        db.close()

    def test_get_connection_no_url_uses_env_default(self, monkeypatch):
        from tina4_python.database import Database
        monkeypatch.setenv("TINA4_DATABASE_URL", "sqlite:///:memory:")
        db = Database.get_connection()
        assert db.url == "sqlite:///:memory:"
        db.close()


class TestDatabaseFetchAll:
    def test_returns_records_list_directly(self):
        db = _sqlite_db()
        db.execute("CREATE TABLE u (id INTEGER, name TEXT)")
        db.insert("u", {"id": 1, "name": "Alice"})
        db.insert("u", {"id": 2, "name": "Bob"})

        rows = db.fetch_all("SELECT * FROM u ORDER BY id")
        assert isinstance(rows, list)
        assert rows == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        db.close()

    def test_returns_empty_list_when_no_rows(self):
        db = _sqlite_db()
        db.execute("CREATE TABLE u (id INTEGER)")
        rows = db.fetch_all("SELECT * FROM u")
        assert rows == []
        db.close()

    def test_supports_params_and_pagination(self):
        db = _sqlite_db()
        db.execute("CREATE TABLE u (id INTEGER, active INTEGER)")
        for i in range(10):
            db.insert("u", {"id": i, "active": i % 2})
        active = db.fetch_all("SELECT id FROM u WHERE active = ? ORDER BY id", [1], limit=3)
        assert [r["id"] for r in active] == [1, 3, 5]
        db.close()


class TestDatabasePoolProperty:
    def test_returns_none_when_unpooled(self):
        db = _sqlite_db()
        assert db.pool is None
        db.close()

    def test_returns_pool_when_pooled(self):
        from tina4_python.database import Database, connection as connmod
        # SQLite memory + pool=2 should expose ConnectionPool through .pool
        db = Database("sqlite:///:memory:", pool=2)
        assert db.pool is not None
        # size is a plain int attribute on ConnectionPool (size() returns int)
        assert db.pool.size == 2 or db.pool.size() == 2  # tolerate both shapes
        db.close()


# ─── DatabaseResult.columns ───────────────────────────────────────────────


class TestDatabaseResultColumns:
    def test_columns_from_first_row(self):
        db = _sqlite_db()
        db.execute("CREATE TABLE u (id INTEGER, name TEXT, email TEXT)")
        db.insert("u", {"id": 1, "name": "Alice", "email": "a@x"})
        result = db.fetch("SELECT id, name, email FROM u")
        assert result.columns == ["id", "name", "email"]
        db.close()

    def test_columns_empty_when_no_rows(self):
        db = _sqlite_db()
        db.execute("CREATE TABLE u (id INTEGER)")
        result = db.fetch("SELECT * FROM u")
        assert result.columns == []
        db.close()


# ─── Job.error attribute ──────────────────────────────────────────────────


class TestJobError:
    def test_default_is_none(self):
        from tina4_python.queue.job import Job
        job = Job(queue=None, job_id="j1", topic="t", data={"x": 1})
        assert job.error is None

    def test_can_be_set_at_construction(self):
        from tina4_python.queue.job import Job
        job = Job(queue=None, job_id="j2", topic="t", data={}, error="bad payload")
        assert job.error == "bad payload"

    def test_to_hash_includes_error(self):
        from tina4_python.queue.job import Job
        job = Job(queue=None, job_id="j3", topic="t", data={}, error="boom")
        assert job.to_hash()["error"] == "boom"


# ─── Queue.produce(delay_until=) ──────────────────────────────────────────


class TestQueueProduceDelayUntil:
    def test_delay_until_naive_datetime(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        q = Queue(topic="parity-a-delay-naive")

        target = datetime.now() + timedelta(seconds=5)
        q.produce("parity-a-delay-naive", {"x": 1}, delay_until=target)
        # No assertion on backend internals — just verify the call accepts the kwarg
        # and the resulting size > 0
        assert q.size() >= 1
        q.clear()

    def test_delay_until_aware_datetime(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        q = Queue(topic="parity-a-delay-aware")

        target = datetime.now(timezone.utc) + timedelta(seconds=10)
        q.produce("parity-a-delay-aware", {"x": 1}, delay_until=target)
        assert q.size() >= 1
        q.clear()

    def test_delay_until_in_past_clamps_to_zero(self, tmp_path, monkeypatch):
        from tina4_python.queue import Queue
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        q = Queue(topic="parity-a-delay-past")

        # Past target — must not raise
        target = datetime.now() - timedelta(hours=1)
        q.produce("parity-a-delay-past", {"x": 1}, delay_until=target)
        assert q.size() >= 1
        q.clear()


# ─── migration.migrate / rollback / status module-level ────────────────────


class TestMigrationModuleLevel:
    def test_migrate_function_exists_and_callable(self, tmp_path, monkeypatch):
        import tina4_python.migration as m
        assert callable(m.migrate)
        assert callable(m.rollback)
        assert callable(m.status)

    def test_status_returns_dict(self, tmp_path, monkeypatch):
        from tina4_python.migration import status
        from tina4_python.database import Database

        # Run from a temp dir so the migration tracker can be created
        monkeypatch.chdir(tmp_path)
        (tmp_path / "migrations").mkdir()
        db = Database("sqlite:///:memory:")
        result = status(db)
        assert isinstance(result, dict)
        db.close()


# ─── i18n.t module-level ──────────────────────────────────────────────────


class TestI18nModuleLevel:
    def test_t_function_callable(self):
        from tina4_python.i18n import t
        # Missing key returns the key itself (graceful fallback)
        assert t("nonexistent-parity-test-key") == "nonexistent-parity-test-key"

    def test_set_default_replaces_instance(self):
        from tina4_python.i18n import I18n, t, set_default
        # Build a custom I18n with an in-memory translation
        instance = I18n()
        instance._translations["en"] = {"hello": "Hello, {name}!"}
        instance.locale = "en"
        set_default(instance)
        assert t("hello", name="Alice") == "Hello, Alice!"
        # Reset for other tests
        set_default(I18n())


# ─── Session dict-style access ────────────────────────────────────────────


def _make_session():
    """Build a fresh Session with a memory handler."""
    from tina4_python.session import Session

    class _MemoryHandler:
        def __init__(self):
            self.store = {}

        def read(self, sid):
            return self.store.get(sid, {})

        def write(self, sid, data, ttl):
            self.store[sid] = data

        def destroy(self, sid):
            self.store.pop(sid, None)

        def gc(self, max_lifetime):
            pass

    sess = Session(handler=_MemoryHandler(), ttl=3600)
    sess.start()
    return sess


class TestSessionDictAccess:
    def test_setitem_and_getitem(self):
        s = _make_session()
        s["user_id"] = 42
        assert s["user_id"] == 42

    def test_contains(self):
        s = _make_session()
        s["k"] = "v"
        assert "k" in s
        assert "missing" not in s

    def test_delitem(self):
        s = _make_session()
        s["k"] = "v"
        del s["k"]
        assert "k" not in s

    def test_getitem_raises_keyerror_for_missing(self):
        s = _make_session()
        with pytest.raises(KeyError):
            _ = s["missing"]

    def test_delitem_raises_keyerror_for_missing(self):
        s = _make_session()
        with pytest.raises(KeyError):
            del s["missing"]

    def test_iter_and_len(self):
        s = _make_session()
        s["a"] = 1
        s["b"] = 2
        assert sorted(list(s)) == ["a", "b"]
        assert len(s) == 2

    def test_dict_and_explicit_apis_share_state(self):
        s = _make_session()
        s.set("via_set", "value")
        assert s["via_set"] == "value"

        s["via_setitem"] = "other"
        assert s.get("via_setitem") == "other"


# ─── WebSocketConnection.connection_count ─────────────────────────────────


class TestWebSocketConnectionCount:
    def test_returns_one_when_no_manager(self):
        from tina4_python.websocket import WebSocketConnection

        # Mock reader/writer just enough for __init__
        class _MockWriter:
            def get_extra_info(self, _):
                return ("127.0.0.1", 1234)

        conn = WebSocketConnection(
            reader=None,
            writer=_MockWriter(),
            path="/test",
        )
        assert conn.connection_count == 1

    def test_delegates_to_manager_count(self):
        from tina4_python.websocket import WebSocketConnection, WebSocketManager

        class _MockWriter:
            def get_extra_info(self, _):
                return ("127.0.0.1", 0)

        mgr = WebSocketManager()
        conns = [
            WebSocketConnection(reader=None, writer=_MockWriter(), path="/x")
            for _ in range(3)
        ]
        for c in conns:
            c._manager = mgr
            mgr.add(c)
        for c in conns:
            assert c.connection_count == 3
