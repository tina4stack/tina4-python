"""Unified cache backend set — memory / file / database / redis / valkey /
memcached / mongodb. See tina4_python/cache/__init__.py (_create_backend).

Network backends skip when the service isn't reachable, so CI without those
services stays green; locally (with the services up) they run for real.
"""
import os
import socket

import pytest

from tina4_python.cache import _create_backend, _RedisBackend


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

    def test_unavailable_backend_falls_back_to_file(self, tmp_path):
        # A configured backend whose service is unreachable degrades to the
        # file backend (a real working cache), not a silent no-op.
        os.environ["TINA4_CACHE_DIR"] = str(tmp_path)
        try:
            b = _create_backend(backend="redis", url="redis://localhost:6399")  # dead port
            assert b.name() == "file"
            b.set("k", {"v": 1}, 60)
            assert b.get("k") == {"v": 1}
        finally:
            os.environ.pop("TINA4_CACHE_DIR", None)


class TestCredentials:
    """Credentials come from the URL (user:pass@) or TINA4_CACHE_USERNAME /
    TINA4_CACHE_PASSWORD — parity with TINA4_DATABASE_USERNAME / _PASSWORD.
    Parsing is verified without a live server (it happens in __init__)."""

    def test_url_credentials_parsed(self):
        b = _RedisBackend(url="redis://alice:s3cret@127.0.0.1:6399")
        assert b._username == "alice"
        assert b._password == "s3cret"
        assert b._host == "127.0.0.1" and b._port == 6399

    def test_password_only_url(self):
        b = _RedisBackend(url="redis://:justpass@127.0.0.1:6399")
        assert b._username is None
        assert b._password == "justpass"

    def test_env_credentials(self, monkeypatch):
        monkeypatch.setenv("TINA4_CACHE_USERNAME", "bob")
        monkeypatch.setenv("TINA4_CACHE_PASSWORD", "pw")
        b = _RedisBackend(url="redis://127.0.0.1:6399")
        assert b._username == "bob" and b._password == "pw"

    def test_no_credentials(self, monkeypatch):
        monkeypatch.delenv("TINA4_CACHE_USERNAME", raising=False)
        monkeypatch.delenv("TINA4_CACHE_PASSWORD", raising=False)
        b = _RedisBackend(url="redis://127.0.0.1:6399")
        assert b._username is None and b._password is None


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


# Password-protected Redis from the docker harness (redis-auth, port 6381).
@pytest.mark.skipif(not _reachable("localhost", 6381), reason="auth redis not running")
def test_redis_auth_roundtrip():
    # Real authenticated round-trip — must connect (not fall back to file).
    b = _create_backend(backend="redis", url="redis://:s3cret@localhost:6381")
    assert b.name() == "redis"
    _roundtrip(b, "redis")


@pytest.mark.skipif(not _reachable("localhost", 6381), reason="auth redis not running")
def test_redis_wrong_password_falls_back_to_file(tmp_path):
    os.environ["TINA4_CACHE_DIR"] = str(tmp_path)
    try:
        b = _create_backend(backend="redis", url="redis://:wrongpass@localhost:6381")
        assert b.name() == "file"  # bad auth → graceful fallback, not a no-op
        b.set("k", {"v": 1}, 60)
        assert b.get("k") == {"v": 1}
    finally:
        os.environ.pop("TINA4_CACHE_DIR", None)
