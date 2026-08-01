"""DB query cache — protects the DB from rapid identical reads.
See tina4_python/database/connection.py.

Layers — BOTH opt-in:
  • request-scoped (DEFAULT OFF, opt-in via TINA4_AUTO_CACHING=true) — dedupes
    identical SELECTs, cleared per request + on writes, short safety TTL. Ships
    OFF because handing back pre-write state in a read-after-write (e.g.
    SELECT MAX(id) right before an INSERT in the same request) is a correctness
    footgun as a default; read-heavy endpoints opt in deliberately.
  • persistent (opt-in TINA4_DB_CACHE=true) — cross-request TTL cache, NOT
    cleared per request.
"""
import socket

import pytest

from tina4_python.database.connection import Database


def _reachable(host: str, port: int) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _make_db(tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "qc.db"))
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n TEXT)")
    db.execute("INSERT INTO t (n) VALUES ('a'), ('b')")
    return db


class TestRequestScopedDefault:
    def test_off_by_default(self, tmp_path, monkeypatch):
        # With neither cache env var set, the request-scoped cache is now OFF.
        # It defaults OFF because a read-after-write within one request could
        # otherwise hand back stale, pre-write state (a correctness footgun).
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        stats = db.cache_stats()
        assert stats["enabled"] is False
        assert stats["mode"] == "off"

    def test_identical_fetches_dedupe(self, tmp_path, monkeypatch):
        # Opt in to the request-scoped cache to test the feature behaviour.
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")   # miss -> populates
        db.fetch("SELECT * FROM t")   # hit
        stats = db.cache_stats()
        assert stats["hits"] >= 1
        assert stats["size"] == 1

    def test_write_invalidates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        db.execute("INSERT INTO t (n) VALUES ('c')")
        assert db.cache_stats()["size"] == 0

    def test_insert_helper_invalidates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        db.insert("t", {"n": "d"})
        assert db.cache_stats()["size"] == 0


class TestRequestBoundary:
    def test_reset_clears_request_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        # Simulate the dispatcher firing at the start of the next request.
        Database.reset_request_caches()
        assert db.cache_stats()["size"] == 0

    def test_reset_preserves_counters(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
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
        monkeypatch.setenv("TINA4_AUTO_CACHING", "false")
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
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        stats = db.cache_stats()
        assert stats["enabled"] is True
        assert stats["mode"] == "persistent"
        assert stats["ttl"] == 30

    def test_persistent_survives_request_reset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1
        Database.reset_request_caches()  # no-op in persistent mode
        assert db.cache_stats()["size"] == 1


class TestNoCacheBypass:
    """Per-query ``no_cache=True`` bypasses the DB query cache entirely —
    no lookup, no store — and runs straight against the DB. Works in both
    cache modes. The canonical API mirrored by PHP/Ruby/Node.

    Proof that the DB is really re-hit: we mutate the table via the raw
    adapter (``db.adapter.execute``), which does NOT go through
    ``Database.execute`` and therefore does NOT invalidate the cache. A
    normal read then keeps returning the stale cached value while a
    ``no_cache=True`` read sees the new value.
    """

    def test_no_cache_skips_cached_value_request_mode(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        # Normal read caches the current rows.
        first = db.fetch_all("SELECT n FROM t ORDER BY id")
        assert [r["n"] for r in first] == ["a", "b"]
        # Mutate behind the cache's back (raw adapter — no invalidation).
        db.adapter.execute("UPDATE t SET n = 'Z' WHERE n = 'a'")
        # Normal read still returns the STALE cached value (proves cache active).
        cached = db.fetch_all("SELECT n FROM t ORDER BY id")
        assert [r["n"] for r in cached] == ["a", "b"]
        # no_cache=True bypasses the cache and hits the DB → sees the new value.
        fresh = db.fetch_all("SELECT n FROM t ORDER BY id", no_cache=True)
        assert [r["n"] for r in fresh] == ["Z", "b"]

    def test_no_cache_read_does_not_populate_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        # A no_cache read must NOT store anything.
        db.fetch("SELECT * FROM t", no_cache=True)
        assert db.cache_stats()["size"] == 0
        # And it doesn't count as a normal miss/hit either.
        assert db.cache_stats()["hits"] == 0
        # A subsequent normal read is a fresh miss that DOES populate.
        db.fetch("SELECT * FROM t")
        assert db.cache_stats()["size"] == 1

    def test_fetch_one_no_cache_bypasses(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        row = db.fetch_one("SELECT n FROM t WHERE id = 1")  # caches 'a'
        assert row["n"] == "a"
        db.adapter.execute("UPDATE t SET n = 'Z' WHERE id = 1")
        assert db.fetch_one("SELECT n FROM t WHERE id = 1")["n"] == "a"  # stale cached
        assert db.fetch_one("SELECT n FROM t WHERE id = 1", no_cache=True)["n"] == "Z"

    def test_no_cache_bypasses_persistent_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "memory")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        # Use fetch_all consistently so populate + reads share one cache key
        # (the key encodes limit/offset, and fetch_all defaults limit=0 vs
        # fetch's limit=100).
        first = db.fetch_all("SELECT n FROM t ORDER BY id")  # populate persistent cache
        assert [r["n"] for r in first] == ["a", "b"]
        assert db.cache_stats()["size"] == 1
        db.adapter.execute("UPDATE t SET n = 'Z' WHERE id = 1")
        # Persistent cache still serves the stale rows on a normal read.
        cached = db.fetch_all("SELECT n FROM t ORDER BY id")
        assert [r["n"] for r in cached] == ["a", "b"]
        # no_cache=True bypasses persistent cache too.
        fresh = db.fetch_all("SELECT n FROM t ORDER BY id", no_cache=True)
        assert [r["n"] for r in fresh] == ["Z", "b"]
        # And the no_cache read added nothing new to the persistent store.
        assert db.cache_stats()["size"] == 1

    def test_normal_cached_path_still_works(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
        monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t")   # miss -> populates
        db.fetch("SELECT * FROM t")   # hit
        stats = db.cache_stats()
        assert stats["hits"] >= 1
        assert stats["size"] == 1


class TestPersistentBackend:
    """Persistent mode (TINA4_DB_CACHE=true) routes through the unified
    CacheBackend (TINA4_DB_CACHE_BACKEND); the cached DatabaseResult is
    serialized and reconstructed so shared backends work across instances."""

    def test_memory_backend_reconstructs_result(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "memory")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        db.fetch("SELECT * FROM t ORDER BY id")
        r = db.fetch("SELECT * FROM t ORDER BY id")  # hit → reconstructed
        from tina4_python.database.adapter import DatabaseResult
        assert isinstance(r, DatabaseResult)
        assert r.count == 2 and [row["n"] for row in r] == ["a", "b"]
        assert db.cache_stats()["mode"] == "persistent"
        assert db.cache_stats()["hits"] >= 1

    @pytest.mark.skipif(not _reachable("localhost", 6379), reason="redis not running")
    def test_redis_backend_shared_across_instances(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "redis")
        monkeypatch.setenv("TINA4_DB_CACHE_URL", "redis://localhost:6379")
        path = "sqlite:///" + str(tmp_path / "shared.db")
        db1 = Database(path)
        db1.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n TEXT)")
        db1.execute("INSERT INTO t (n) VALUES ('x'), ('y')")
        db1._cache_invalidate()
        db1.fetch("SELECT * FROM t ORDER BY id")     # populate shared redis
        db2 = Database(path)                          # separate instance, same redis
        r = db2.fetch("SELECT * FROM t ORDER BY id")  # cross-instance hit (no query)
        assert db2.cache_stats()["hits"] >= 1 and db2.cache_stats()["misses"] == 0
        assert [row["n"] for row in r] == ["x", "y"]
        assert db2.cache_stats()["backend"] == "redis"


class TestPersistentFetchOneShape:
    """fetch_one() returns a plain dict, not a DatabaseResult.

    The persistent serializer read ``result.records`` unconditionally, so the
    moment TINA4_DB_CACHE was turned on EVERY fetch_one() raised
    ``AttributeError: 'dict' object has no attribute 'records'``. The opt-in
    persistent cache was therefore unusable with fetch_one. PHP, Ruby and Node
    all already carried a shape marker; Python was the 1-of-4 outlier.
    """

    def test_db_cache_persistent_fetch_one_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "memory")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)

        first = db.fetch_one("SELECT * FROM t WHERE id = 1")   # miss, stores
        second = db.fetch_one("SELECT * FROM t WHERE id = 1")  # hit, reconstructs

        assert isinstance(first, dict) and first["n"] == "a"
        assert isinstance(second, dict), "a cached fetch_one must come back as a dict"
        assert second["n"] == "a"
        assert db.cache_stats()["hits"] >= 1

    def test_db_cache_persistent_fetch_and_fetch_one_do_not_collide(self, tmp_path, monkeypatch):
        """The two shapes share one backend, so each must keep its own type."""
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "memory")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)
        from tina4_python.database.adapter import DatabaseResult

        db.fetch("SELECT * FROM t ORDER BY id")
        db.fetch_one("SELECT * FROM t WHERE id = 1")

        assert isinstance(db.fetch("SELECT * FROM t ORDER BY id"), DatabaseResult)
        assert isinstance(db.fetch_one("SELECT * FROM t WHERE id = 1"), dict)

    def test_db_cache_persistent_fetch_one_missing_row_round_trips(self, tmp_path, monkeypatch):
        """A cached 'no such row' must stay None, not become an empty result."""
        monkeypatch.setenv("TINA4_DB_CACHE", "true")
        monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "memory")
        monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
        db = _make_db(tmp_path)

        assert db.fetch_one("SELECT * FROM t WHERE id = 999") is None
        assert db.fetch_one("SELECT * FROM t WHERE id = 999") is None
