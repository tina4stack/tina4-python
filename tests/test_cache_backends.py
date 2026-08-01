"""Unified cache backend set — memory / file / database / redis / valkey /
memcached / mongodb. See tina4_python/cache/__init__.py (_create_backend).

Network backends skip when the service isn't reachable, so CI without those
services stays green; locally (with the services up) they run for real.

These tests exercise REAL backends — every assertion checks an actual cached
value, a real miss, real hit/miss/size accounting, or a real TTL expiry. No
mocks: the redis/valkey/memcached/mongodb tests connect to the live service
(or skip), the memory/file/database tests use the real in-process / on-disk /
SQLite backend.
"""
import os
import socket
import time

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
    """Real set -> get -> value, miss, hit/miss/size accounting, delete.

    Asserts the ACTUAL cached value comes back (not just that get() is
    callable), that a missing key is a real miss, that the backend's
    hit/miss/size counters move in response to real operations, and that
    delete removes the entry for real.
    """
    b.clear()

    # Backend identity (cheap rename / wiring guard).
    assert b.name() == expect_name

    # A fresh, cleared backend reports zero entries.
    assert b.stats()["size"] == 0

    # set -> get returns the exact stored value (structured payload round-trips
    # through JSON serialisation intact).
    b.set("k1", {"v": 1, "name": "Alice"}, 60)
    assert b.get("k1") == {"v": 1, "name": "Alice"}

    # A second distinct value coexists.
    b.set("k2", [1, 2, 3], 60)
    assert b.get("k2") == [1, 2, 3]
    assert b.stats()["size"] == 2

    # A missing key is a real miss (None, not an error / not the wrong value).
    assert b.get("missing") is None

    # Stats backend label + counters reflect the real operations above:
    # 3 successful gets (k1, k2, k1-via-... ) and 1 miss so far.
    st = b.stats()
    assert st["backend"] == expect_name
    assert st["hits"] >= 2          # k1 and k2 were each fetched at least once
    assert st["misses"] >= 1        # the "missing" lookup

    # Overwrite updates the value in place (no stale read).
    b.set("k1", {"v": 99}, 60)
    assert b.get("k1") == {"v": 99}

    # delete removes the entry for real: it reports it existed, then the key
    # becomes a genuine miss.
    assert b.delete("k1") is True
    assert b.get("k1") is None
    # Deleting an already-absent key reports False (it did not exist).
    assert b.delete("k1") is False


def _ttl_expiry(b):
    """Real TTL behaviour: an entry with a 1s TTL is present immediately and
    GONE after the TTL elapses (a real read-through expiry, not a sweep we
    have to trigger manually)."""
    b.clear()
    b.set("ttlkey", {"temp": True}, 1)
    assert b.get("ttlkey") == {"temp": True}   # alive before expiry
    time.sleep(1.4)
    assert b.get("ttlkey") is None             # expired -> real miss
    b.clear()


class TestLocalBackends:
    """Always-available backends — no external service needed."""

    def test_memory(self):
        b = _create_backend(backend="memory")
        _roundtrip(b, "memory")
        _ttl_expiry(b)

    def test_file(self, tmp_path):
        os.environ["TINA4_CACHE_DIR"] = str(tmp_path)
        try:
            b = _create_backend(backend="file")
            _roundtrip(b, "file")
            _ttl_expiry(b)
        finally:
            os.environ.pop("TINA4_CACHE_DIR", None)

    def test_database_sqlite(self, tmp_path):
        b = _create_backend(backend="database", url="sqlite:///" + str(tmp_path / "cache.db"))
        _roundtrip(b, "database")
        _ttl_expiry(b)

    def test_cache_backend_unknown_name_raises(self):
        """An unrecognised TINA4_CACHE_BACKEND raises, naming the valid set.

        It used to fall through to memory, so a typo (redsi) produced a running
        app with a per-process cache while the operator believed it was Redis.
        Same contract the session layer already settled on.
        """
        with pytest.raises(ValueError) as excinfo:
            _create_backend(backend="redsi")
        message = str(excinfo.value)
        assert "redsi" in message
        assert "memory, file, redis, valkey, memcached, mongodb, database" in message

    def test_cache_backend_known_names_do_not_raise(self):
        """Negative control: every documented name (and alias) still builds."""
        for name in ("memory", "", "file", "MEMORY", " file "):
            assert _create_backend(backend=name).name() in ("memory", "file")

    def test_unavailable_backend_falls_back_to_file(self, tmp_path):
        # A configured backend whose service is unreachable degrades to the
        # file backend (a real working cache), not a silent no-op.
        os.environ["TINA4_CACHE_DIR"] = str(tmp_path)
        try:
            b = _create_backend(backend="redis", url="redis://localhost:6399")  # dead port
            assert b.name() == "file"
            b.set("k", {"v": 1}, 60)
            assert b.get("k") == {"v": 1}
            # And it is a real file-backed cache: the value is persisted to disk.
            assert any(tmp_path.glob("*.json"))
        finally:
            os.environ.pop("TINA4_CACHE_DIR", None)


class TestCredentials:
    """Credentials come from the URL (user:pass@) or TINA4_CACHE_USERNAME /
    TINA4_CACHE_PASSWORD — parity with TINA4_DATABASE_USERNAME / _PASSWORD.

    These cover the credential-PARSING code paths (which run in __init__ with
    no live server needed) for the input shapes the live-auth round-trip below
    does not exercise — URL user:pass, password-only URL, env-var credentials,
    and the no-credentials default. Real authenticated behaviour against a live
    server is covered by ``test_redis_auth_roundtrip`` /
    ``test_redis_wrong_password_falls_back_to_file``.
    """

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
    # Must really connect (not silently fall back to file).
    assert b.name() == "redis"
    _roundtrip(b, "redis")
    _ttl_expiry(b)


@pytest.mark.skipif(not _reachable("localhost", 6380), reason="valkey not running")
def test_valkey_backend():
    b = _create_backend(backend="valkey", url="valkey://localhost:6380")
    assert b.name() == "valkey"
    _roundtrip(b, "valkey")
    _ttl_expiry(b)


@pytest.mark.skipif(not _reachable("localhost", 11211), reason="memcached not running")
def test_memcached_backend():
    b = _create_backend(backend="memcached", url="memcached://localhost:11211")
    assert b.name() == "memcached"
    _roundtrip(b, "memcached")
    _ttl_expiry(b)


@pytest.mark.skipif(not _reachable("localhost", 11211), reason="memcached not running")
def test_negative_memcached_size_ignores_another_tenants_keys():
    """Regression: `size` reported the WHOLE SERVER's item count.

    Memcached was the only backend of the seven that leaked: it read the global
    `curr_items` from `stats`, so `cache_stats()["size"]` counted every key
    written by every other application sharing that server. Every other backend
    is scoped - memory counts its own dict, redis/valkey scan their own prefix,
    file counts its own directory, mongo its own collection, database its own
    table.

    It also made this file's own `_roundtrip` intermittently fail in a full-suite
    run with `assert 7 == 0`, because something else in the suite had keys in the
    same memcached. That is the symptom; the leaked public API is the bug.

    NO MOCK: a second REAL client writes to the same REAL server, which is
    exactly the shared-tenant situation being asserted about.
    """
    b = _create_backend(backend="memcached", url="memcached://localhost:11211")
    b.clear()
    assert b.stats()["size"] == 0

    # A DIFFERENT tenant writes to the same server, outside this backend.
    sock = socket.create_connection(("localhost", 11211), timeout=3)
    try:
        for i in range(6):
            sock.sendall(b"set other:tenant:%d 0 60 5\r\nhello\r\n" % i)
            sock.recv(100)
    finally:
        sock.close()

    assert b.stats()["size"] == 0, "size must count OUR entries, not the server's"

    b.set("mine", {"a": 1}, 60)
    assert b.stats()["size"] == 1, "our own entry must be counted"

    # An expired entry stops counting without a round-trip: the TTL we set is
    # the TTL we account for.
    b.set("brief", {"a": 1}, 1)
    assert b.stats()["size"] == 2
    time.sleep(2)
    assert b.stats()["size"] == 1, "an expired entry must drop out of the count"

    b.clear()
    assert b.stats()["size"] == 0


@pytest.mark.skipif(not _reachable("localhost", 11211), reason="memcached not running")
def test_negative_memcached_clear_does_not_wipe_another_tenants_keys():
    """Regression: `clear()` sent `flush_all` and wiped the WHOLE server.

    cache_clear() is public API. On memcached it destroyed every key on the
    instance, including every other application sharing it - no other backend
    does that; each clears only what it owns. A shared memcached is the normal
    deployment, so this was data loss for anyone else on the box.

    NO MOCK: a second REAL client writes to the same REAL server, and the
    assertion is that its keys SURVIVE our clear().
    """
    b = _create_backend(backend="memcached", url="memcached://localhost:11211")
    b.clear()
    b.set("ours", {"a": 1}, 60)

    # A DIFFERENT tenant's key, written outside this backend.
    sock = socket.create_connection(("localhost", 11211), timeout=3)
    try:
        sock.sendall(b"set other:survivor 0 60 5\r\nhello\r\n")
        sock.recv(100)
    finally:
        sock.close()

    b.clear()

    # Ours is gone...
    assert b.get("ours") is None
    assert b.stats()["size"] == 0

    # ...and theirs is untouched.
    sock = socket.create_connection(("localhost", 11211), timeout=3)
    try:
        sock.sendall(b"get other:survivor\r\n")
        resp = b""
        while b"END\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
    finally:
        sock.close()
    assert b"hello" in resp, "clear() destroyed another tenant's key"

    # tidy up after ourselves
    sock = socket.create_connection(("localhost", 11211), timeout=3)
    try:
        sock.sendall(b"delete other:survivor\r\n")
        sock.recv(100)
    finally:
        sock.close()


@pytest.mark.skipif(not _reachable("localhost", 27017), reason="mongodb not running")
def test_mongodb_backend():
    pytest.importorskip("pymongo")
    b = _create_backend(backend="mongodb", url="mongodb://localhost:27017/tina4_cache")
    assert b.name() == "mongodb"
    _roundtrip(b, "mongodb")
    _ttl_expiry(b)


@pytest.mark.skipif(not _reachable("localhost", 6379), reason="redis not running")
def test_redis_cross_instance_visibility():
    """A value written by one backend instance is visible to a second instance
    pointed at the same server — proof the data lives in Redis, not in-process."""
    writer = _create_backend(backend="redis", url="redis://localhost:6379")
    writer.clear()
    writer.set("shared", {"from": "writer"}, 60)

    reader = _create_backend(backend="redis", url="redis://localhost:6379")
    assert reader.get("shared") == {"from": "writer"}
    writer.clear()


# Password-protected Redis from the docker harness (redis-auth, port 6381).
@pytest.mark.skipif(not _reachable("localhost", 6381), reason="auth redis not running")
def test_redis_auth_roundtrip():
    # Real authenticated round-trip — must connect (not fall back to file).
    b = _create_backend(backend="redis", url="redis://:s3cret@localhost:6381")
    assert b.name() == "redis"
    _roundtrip(b, "redis")
    _ttl_expiry(b)


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
