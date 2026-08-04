"""CACHE CONTRACT - sweep() returns a real count, everywhere.

Pins ``sweep-returns-a-real-count-everywhere`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    sweep() evicts expired entries and returns how many it evicted, on every
    provider.

MEASURED: sweep() behaved three different ways across the family - real counts
in Python/PHP, a NoMethodError crash on 6 of 7 providers in Ruby, and a
permanent 0 in Node. A monitoring dashboard reading that number is reading three
different things, and one of them is a crash.

AND a defect found while proving it, in Python, the reference implementation:
the DATABASE backend had no sweep() at all. redis, valkey, memcached and mongodb
expire entries SERVER-SIDE, so 0 is the honest answer for them - nothing was
evicted because there was nothing left to evict. A SQL table does not expire
anything by itself: rows were only deleted when someone happened to read that
exact key again, so expired rows accumulated forever and the one API whose job
is to reclaim them reported 0 and did nothing.

Every backend here is REAL - a real in-process store, a real directory on disk,
a real SQLite database, and the real network services. Nothing is simulated.
"""
import os
import socket
import time
from urllib.parse import urlparse

import pytest

from tina4_python.cache import _create_backend

REDIS_URL = os.environ.get("TINA4_TEST_CACHE_REDIS_URL", "redis://localhost:6379")
VALKEY_URL = os.environ.get("TINA4_TEST_CACHE_VALKEY_URL", "valkey://localhost:6380")
MEMCACHED_URL = os.environ.get("TINA4_TEST_CACHE_MEMCACHED_URL", "memcached://localhost:11211")
MONGO_URL = os.environ.get("TINA4_TEST_CACHE_MONGO_URL", "mongodb://localhost:27017")


def _reachable(url: str, default_port: int) -> bool:
    parsed = urlparse(url if "://" in url else "//" + url)
    try:
        sock = socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or default_port), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


def _all_backends(tmp_path):
    """Every provider the framework offers, each a REAL one."""
    backends = [
        _create_backend(backend="memory"),
        _create_backend(backend="file", cache_dir=str(tmp_path / "filecache")),
        _create_backend(backend="database", url=f"sqlite:///{tmp_path / 'cache.db'}"),
    ]
    if _reachable(REDIS_URL, 6379):
        backends.append(_create_backend(backend="redis", url=REDIS_URL))
    if _reachable(VALKEY_URL, 6379):
        backends.append(_create_backend(backend="valkey", url=VALKEY_URL))
    if _reachable(MEMCACHED_URL, 11211):
        backends.append(_create_backend(backend="memcached", url=MEMCACHED_URL))
    if _reachable(MONGO_URL, 27017):
        pytest.importorskip("pymongo")
        backends.append(_create_backend(
            backend="mongodb", url=f"{MONGO_URL}/tina4_cache_contract"))
    return backends


def test_sweep_is_available_on_every_provider(tmp_path):
    """Every provider ANSWERS sweep() with an integer.

    This is the Ruby NoMethodError in contract form: a method that exists on one
    provider and blows up on six is not a swappable API, and a caller that has
    to guard `respond_to?(:sweep)` cannot tell "not supported" from "evicted
    nothing".
    """
    for backend in _all_backends(tmp_path):
        result = backend.sweep()
        assert isinstance(result, int), (
            f"{backend.name()}.sweep() returned {result!r}, not an integer count"
        )
        assert result >= 0, f"{backend.name()}.sweep() returned a negative count"


def test_sweep_returns_the_number_of_entries_it_evicted(tmp_path):
    """The count is REAL on every provider that holds entries locally.

    memory, file and database all keep expired entries until something removes
    them, so the count must be exact.
    """
    for backend in (
        _create_backend(backend="memory"),
        _create_backend(backend="file", cache_dir=str(tmp_path / "fc")),
        _create_backend(backend="database", url=f"sqlite:///{tmp_path / 'c.db'}"),
    ):
        backend.clear()
        for index in range(3):
            backend.set(f"doomed-{index}", {"i": index}, 1)
        backend.set("survivor", {"i": "keep"}, 300)
        time.sleep(1.2)

        evicted = backend.sweep()

        assert evicted == 3, (
            f"{backend.name()}.sweep() reported {evicted} evictions, expected 3 - "
            "the number a monitoring dashboard reads is not the number of "
            "entries actually reclaimed"
        )
        assert backend.get("survivor") == {"i": "keep"}, (
            f"{backend.name()}.sweep() removed a LIVE entry"
        )


def test_sweep_evicts_expired_entries_from_the_database_backend(tmp_path):
    """The SQL cache table must actually shrink.

    A database cache does not self-expire. Before this, expired rows were only
    deleted when someone re-read that exact key, so the table grew without bound
    and sweep() - the API whose whole job is reclaiming that space - returned 0.
    """
    backend = _create_backend(backend="database", url=f"sqlite:///{tmp_path / 'sweep.db'}")
    backend.clear()
    for index in range(4):
        backend.set(f"expired-{index}", {"i": index}, 1)
    backend.set("live", {"i": "live"}, 300)
    time.sleep(1.2)
    assert backend.stats()["size"] == 5, "precondition: expired rows are still on disk"

    evicted = backend.sweep()

    assert evicted == 4, f"sweep() reported {evicted}, expected 4 expired rows"
    assert backend.stats()["size"] == 1, (
        "the expired rows are still in the tina4_cache table - sweep() counted "
        "them but did not delete them"
    )


def test_sweep_returns_zero_when_nothing_has_expired(tmp_path):
    """NEGATIVE: a sweep with nothing to do reports 0, it does not guess.

    Catches a sweep that returns the total entry count, or the number it
    inspected, rather than the number it evicted.
    """
    for backend in (
        _create_backend(backend="memory"),
        _create_backend(backend="file", cache_dir=str(tmp_path / "fc2")),
        _create_backend(backend="database", url=f"sqlite:///{tmp_path / 'c2.db'}"),
    ):
        backend.clear()
        for index in range(3):
            backend.set(f"live-{index}", {"i": index}, 300)

        assert backend.sweep() == 0, (
            f"{backend.name()}.sweep() reported evictions with nothing expired"
        )
        assert backend.stats()["size"] == 3, (
            f"{backend.name()}.sweep() deleted live entries"
        )


def test_sweep_leaves_entries_without_a_ttl_alone(tmp_path):
    """NEGATIVE: ttl <= 0 means "never expires" and sweep must respect it.

    An entry stored with no TTL has expires_at 0. A sweep comparing `now >
    expires_at` without excluding 0 would evict every permanent entry on its
    first run - silently, and reported as a successful reclaim.
    """
    for backend in (
        _create_backend(backend="memory"),
        _create_backend(backend="file", cache_dir=str(tmp_path / "fc3")),
        _create_backend(backend="database", url=f"sqlite:///{tmp_path / 'c3.db'}"),
    ):
        backend.clear()
        backend.set("permanent", {"i": "forever"}, 0)
        time.sleep(0.2)

        assert backend.sweep() == 0, (
            f"{backend.name()}.sweep() evicted an entry stored with no TTL"
        )
        assert backend.get("permanent") == {"i": "forever"}, (
            f"{backend.name()} lost a permanent entry to sweep()"
        )
