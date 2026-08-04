"""CACHE CONTRACT - cache_clear() clears the PERSISTENT layer.

Pins ``cache-clear-clears-the-persistent-layer`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    The database-level cache_clear() clears the PERSISTENT shared backend, not
    only the in-process layer.

MEASURED: ``Database.cache_clear()`` cleared ``self._query_cache`` (the
in-process dict) and the counters, and never touched ``self._cache_backend``.
So with TINA4_DB_CACHE=true it was a no-op on every provider. Code that clears
the cache after a bulk import appeared to work in development, where the cache
IS in-process, and did nothing in production, where it is shared. Python was the
only framework with this bug: PHP, Ruby and Node all already cleared the
backend, so Python is fixed rather than mirrored.

Every assertion runs against a REAL shared Redis. Nothing is simulated.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

from tina4_python.database import Database

REDIS_URL = os.environ.get("TINA4_TEST_REDIS_URL", "redis://localhost:6379")
_parsed = urlparse(REDIS_URL if "://" in REDIS_URL else "//" + REDIS_URL)


def _reachable(host: str, port: int) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


redis_up = pytest.mark.skipif(
    not _reachable(_parsed.hostname or "localhost", _parsed.port or 6379),
    reason="redis service not reachable",
)

SQL = "SELECT owner FROM widget WHERE id = ?"


def _seed(path):
    db = Database(f"sqlite:///{path}")
    db.execute("CREATE TABLE IF NOT EXISTS widget (id INTEGER PRIMARY KEY, owner TEXT)")
    db.execute("DELETE FROM widget")
    db.insert("widget", {"id": 1, "owner": "original"})
    return db


@pytest.fixture
def persistent_redis(monkeypatch):
    monkeypatch.setenv("TINA4_DB_CACHE", "true")
    monkeypatch.setenv("TINA4_DB_CACHE_TTL", "300")
    monkeypatch.setenv("TINA4_DB_CACHE_BACKEND", "redis")
    monkeypatch.setenv("TINA4_DB_CACHE_URL", REDIS_URL)


@redis_up
def test_cache_clear_clears_the_persistent_backend(tmp_path, persistent_redis):
    """The rule, asserted against the REAL shared backend.

    The entry must be GONE from Redis after cache_clear(), not merely gone from
    the in-process dict that production never uses.
    """
    db = _seed(tmp_path / "app.db")
    assert db._cache_backend is not None, "precondition: a persistent backend is configured"
    db.cache_clear()

    db.fetch(SQL, [1])
    # Count entries in the REAL backend rather than reconstructing the key, so
    # this cannot go quietly green if the key format changes.
    assert db._cache_backend.stats()["size"] > 0, "precondition: the read was cached in redis"

    db.cache_clear()

    assert db._cache_backend.stats()["size"] == 0, (
        "cache_clear() left the entry in the SHARED backend - it cleared only "
        "the in-process dict, so clearing the cache after a bulk import works "
        "in development and does nothing in production"
    )


@redis_up
def test_cache_clear_is_visible_to_another_instance(tmp_path, persistent_redis):
    """A clear on one instance must be seen by every instance.

    The end-to-end shape of the same rule: the point of a shared backend is that
    an operator can clear the cache from ONE process after a bulk import.
    """
    db_one = _seed(tmp_path / "shared.db")
    db_two = Database(f"sqlite:///{tmp_path / 'shared.db'}")
    db_one.cache_clear()

    db_one.fetch(SQL, [1])
    assert db_two._cache_backend.stats()["size"] > 0, "precondition: shared visibility"

    db_one.cache_clear()

    assert db_two._cache_backend.stats()["size"] == 0, (
        "instance two still sees the entry instance one cleared - the clear "
        "never reached the shared backend"
    )


@redis_up
def test_cache_clear_leaves_the_backend_usable(tmp_path, persistent_redis):
    """NEGATIVE: clearing must not poison the cache.

    A clear that also broke subsequent caching would pass the assertion above
    and still be wrong, so this pins that a read AFTER a clear caches again.
    """
    db = _seed(tmp_path / "reusable.db")
    db.cache_clear()
    db.fetch(SQL, [1])
    assert db._cache_backend.stats()["size"] > 0, (
        "nothing was cached after cache_clear() - the clear left the backend "
        "unusable"
    )
    stats = db.cache_stats()
    assert stats["mode"] == "persistent"
    assert stats["backend"] == "redis"


def test_cache_clear_without_a_persistent_backend_is_safe(tmp_path, monkeypatch):
    """NEGATIVE: the request-scoped and off modes must not break.

    With no shared backend configured there is nothing to clear remotely, and
    cache_clear() must still clear the in-process layer and reset the counters
    rather than raising on a None backend.
    """
    monkeypatch.setenv("TINA4_DB_CACHE", "false")
    monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
    monkeypatch.delenv("TINA4_DB_CACHE_URL", raising=False)

    db = _seed(tmp_path / "local.db")
    assert db._cache_backend is None, "precondition: no shared backend in request-scoped mode"
    db.fetch(SQL, [1])
    db.cache_clear()

    stats = db.cache_stats()
    assert stats["mode"] == "request"
    assert stats["size"] == 0
    assert stats["hits"] == 0 and stats["misses"] == 0
