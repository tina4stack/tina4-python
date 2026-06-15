"""Unified cache backend set — memory / file / database / redis / valkey /
memcached / mongodb. See tina4_python/cache/__init__.py (_create_backend).

Network backends skip when the service isn't reachable, so CI without those
services stays green; locally (with the services up) they run for real.
"""
import os
import socket

import pytest

from tina4_python.cache import _create_backend


def _reachable(host: str, port: int) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _roundtrip(b, expect_name: str):
    b.clear()
    b.set("k1", {"v": 1, "name": "Alice"}, 60)
    assert b.get("k1") == {"v": 1, "name": "Alice"}
    assert b.get("missing") is None
    st = b.stats()
    assert st["backend"] == expect_name
    for field in ("hits", "misses", "size"):
        assert field in st
    assert b.delete("k1") is True
    assert b.get("k1") is None


class TestLocalBackends:
    """Always-available backends — no external service needed."""

    def test_memory(self):
        _roundtrip(_create_backend(backend="memory"), "memory")

    def test_file(self, tmp_path):
        os.environ["TINA4_CACHE_DIR"] = str(tmp_path)
        try:
            _roundtrip(_create_backend(backend="file"), "file")
        finally:
            os.environ.pop("TINA4_CACHE_DIR", None)

    def test_database_sqlite(self, tmp_path):
        b = _create_backend(backend="database", url="sqlite:///" + str(tmp_path / "cache.db"))
        _roundtrip(b, "database")

    def test_unknown_falls_back_to_memory(self):
        assert _create_backend(backend="bogus").name() == "memory"


@pytest.mark.skipif(not _reachable("localhost", 6379), reason="redis not running")
def test_redis_backend():
    b = _create_backend(backend="redis", url="redis://localhost:6379")
    _roundtrip(b, "redis")


@pytest.mark.skipif(not _reachable("localhost", 6380), reason="valkey not running")
def test_valkey_backend():
    b = _create_backend(backend="valkey", url="valkey://localhost:6380")
    _roundtrip(b, "valkey")


@pytest.mark.skipif(not _reachable("localhost", 11211), reason="memcached not running")
def test_memcached_backend():
    b = _create_backend(backend="memcached", url="memcached://localhost:11211")
    _roundtrip(b, "memcached")


@pytest.mark.skipif(not _reachable("localhost", 27017), reason="mongodb not running")
def test_mongodb_backend():
    pytest.importorskip("pymongo")
    b = _create_backend(backend="mongodb", url="mongodb://localhost:27017/tina4_cache")
    _roundtrip(b, "mongodb")
