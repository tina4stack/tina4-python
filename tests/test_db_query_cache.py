"""Request-scoped DB query cache (default-on) — protects the DB from rapid
identical reads. See tina4_python/database/connection.py.

Layers:
  • request-scoped (DEFAULT ON, off-switch TINA4_QUERY_CACHE=false) — dedupes
    identical SELECTs, cleared per request + on writes, short safety TTL.
  • persistent (opt-in TINA4_DB_CACHE=true) — cross-request TTL cache, NOT
    cleared per request.
"""
import pytest

from tina4_python.database.connection import Database


def _make_db(tmp_path):
    db = Database("sqlite://" + str(tmp_path / "qc.db"))
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n TEXT)")
    db.execute("INSERT INTO t (n) VALUES ('a'), ('b')")
    return db


class TestRequestScopedDefault:
    def test_on_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        stats = db.cache_stats()
        assert stats["enabled"] is True
        assert stats["mode"] == "request"

    def test_identical_fetches_dedupe(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")   # miss -> populates
        db.fetch("SELECT * FROM t")   # hit
        stats = db.cache_stats()
        assert stats["hits"] >= 1
        assert stats["size"] == 1

    def test_write_invalidates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        db.execute("INSERT INTO t (n) VALUES ('c')")
        assert db.cache_stats()["size"] == 0

    def test_insert_helper_invalidates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        db.insert("t", {"n": "d"})
        assert db.cache_stats()["size"] == 0


class TestRequestBoundary:
    def test_reset_clears_request_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        # Simulate the dispatcher firing at the start of the next request.
        Database.reset_request_caches()
        assert db.cache_stats()["size"] == 0

    def test_reset_preserves_counters(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        db.fetch("SELECT * FROM t")  # one hit
        hits_before = db.cache_stats()["hits"]
        db.cache_new_request()
        assert db.cache_stats()["hits"] == hits_before  # cumulative counters survive
        assert db.cache_stats()["size"] == 0


class TestOffSwitch:
    def test_query_cache_false_disables(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_QUERY_CACHE", "false")
        db = _make_db(tmp_path)
        stats = db.cache_stats()
        assert stats["enabled"] is False
        assert stats["mode"] == "off"
        db.fetch("SELECT * FROM t")
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 0  # nothing cached
        assert db.cache_stats()["hits"] == 0


class TestPersistentMode:
    def test_db_cache_true_is_persistent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        stats = db.cache_stats()
        assert stats["enabled"] is True
        assert stats["mode"] == "persistent"
        assert stats["ttl"] == 30

    def test_persistent_survives_request_reset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.delenv("TINA4_QUERY_CACHE", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        Database.reset_request_caches()  # no-op in persistent mode
        assert db.cache_stats()["size"] == 1
