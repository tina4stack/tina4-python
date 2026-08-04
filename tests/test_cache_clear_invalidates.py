"""CACHE CONTRACT - clear() really invalidates, on EVERY provider.

Pins ``clear-really-invalidates-on-every-provider`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    clear() removes every entry this cache can serve, on EVERY provider. It is
    never a no-op, and never limited to the keys the local process happens to
    have written.

WHY THIS FILE EXISTS AND THE EXISTING CACHE TESTS DID NOT CATCH IT
    ``_RedisBackend`` has TWO transports: the ``redis`` package when it is
    importable, and a raw RESP socket otherwise. The raw path is what a
    ZERO-DEPENDENCY install runs, which is every developer's first install and
    what ADR-0024 rule 4 says counts double. ``uv sync --extra test`` installs
    the ``redis`` package, so every existing redis test took the DRIVER path and
    the default transport had no coverage at all. Its ``clear()`` was a literal
    ``pass``.

    So these tests pin the transport explicitly and run BOTH, against a real
    Redis / Valkey / Memcached over a real socket. Nothing here is mocked:
    selecting a transport is configuration, not a stand-in - every assertion
    below is answered by the live service.

SERVICE ADDRESSES
    Default to the lab's localhost ports; override per service so a developer
    (or a second agent) can point at their own isolated containers:
        TINA4_TEST_CACHE_REDIS_URL      (default redis://localhost:6379)
        TINA4_TEST_CACHE_VALKEY_URL     (default valkey://localhost:6380)
        TINA4_TEST_CACHE_MEMCACHED_URL  (default memcached://localhost:11211)
"""
import os
import socket
import time
import uuid
from urllib.parse import urlparse

import pytest

from tina4_python.cache import _MemcachedBackend, _RedisBackend, _ValkeyBackend

REDIS_URL = os.environ.get("TINA4_TEST_CACHE_REDIS_URL", "redis://localhost:6379")
VALKEY_URL = os.environ.get("TINA4_TEST_CACHE_VALKEY_URL", "valkey://localhost:6380")
MEMCACHED_URL = os.environ.get("TINA4_TEST_CACHE_MEMCACHED_URL", "memcached://localhost:11211")


def _reachable(url: str, default_port: int) -> bool:
    parsed = urlparse(url if "://" in url else "//" + url)
    try:
        sock = socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or default_port), timeout=2
        )
        sock.close()
        return True
    except OSError:
        return False


redis_up = pytest.mark.skipif(
    not _reachable(REDIS_URL, 6379), reason="redis service not reachable"
)
valkey_up = pytest.mark.skipif(
    not _reachable(VALKEY_URL, 6379), reason="valkey service not reachable"
)
memcached_up = pytest.mark.skipif(
    not _reachable(MEMCACHED_URL, 11211), reason="memcached service not reachable"
)


def _raw(backend):
    """Pin a redis/valkey backend to the ZERO-DEPENDENCY RESP transport.

    Not a mock: the backend still opens a real TCP socket to the real server and
    speaks real RESP. This only selects WHICH of the two shipped transports runs,
    so the default-install path is covered even where the driver is installed.
    """
    backend._client = None
    backend._use_raw = True
    assert backend.is_available(), "raw RESP transport could not reach the server"
    return backend


def _driver(backend):
    """Pin a redis/valkey backend to the ``redis`` package transport."""
    if backend._client is None:
        pytest.skip("redis client library not installed")
    backend._use_raw = False
    return backend


# ── redis / valkey ────────────────────────────────────────────────


@redis_up
@pytest.mark.parametrize("transport", ["resp", "driver"])
def test_clear_on_the_raw_resp_transport_is_not_a_no_op(transport):
    """clear() must actually remove entries on BOTH transports.

    The measured defect: on the raw RESP path clear() was ``pass``, so a write
    never invalidated the persistent DB query cache and every instance kept
    serving pre-write rows until the TTL ran out.
    """
    backend = _RedisBackend(REDIS_URL)
    backend = _raw(backend) if transport == "resp" else _driver(backend)

    key = f"contract-{uuid.uuid4().hex}"
    backend.set(key, {"row": "before"}, 300)
    assert backend.get(key) == {"row": "before"}, "precondition: the value is cached"

    backend.clear()

    assert backend.get(key) is None, (
        f"clear() left the entry readable on the {transport} transport - "
        "it is a no-op, so a write never invalidates the cache"
    )


@redis_up
@pytest.mark.parametrize("transport", ["resp", "driver"])
def test_clear_removes_entries_written_by_another_instance(transport):
    """clear() is not limited to what THIS process wrote.

    Two Tina4 instances share one Redis. Instance A writes, instance B clears
    after a write; A's entry must be gone. A clear scoped to the local process's
    own write log would leave B serving stale rows forever.
    """
    writer = _RedisBackend(REDIS_URL)
    clearer = _RedisBackend(REDIS_URL)
    writer = _raw(writer) if transport == "resp" else _driver(writer)
    clearer = _raw(clearer) if transport == "resp" else _driver(clearer)

    key = f"contract-{uuid.uuid4().hex}"
    writer.set(key, {"row": "from-instance-a"}, 300)
    assert clearer.get(key) == {"row": "from-instance-a"}, "precondition: shared visibility"

    clearer.clear()

    assert writer.get(key) is None, (
        "clear() on instance B left instance A's entry readable - "
        "cross-instance invalidation does not hold"
    )


@redis_up
@pytest.mark.parametrize("transport", ["resp", "driver"])
def test_clear_leaves_another_tenants_keys_untouched(transport):
    """NEGATIVE: clear() must not be a FLUSHALL.

    Removing every entry THIS cache can serve is the rule. Removing every key on
    a shared Redis is a different, far worse thing: it destroys other
    applications' data. Both halves are the contract.
    """
    backend = _RedisBackend(REDIS_URL)
    backend = _raw(backend) if transport == "resp" else _driver(backend)

    outsider_key = f"someone-elses-app:{uuid.uuid4().hex}"
    # Write OUTSIDE the tina4 prefix, through the same real connection.
    if backend._client is not None:
        backend._client.set(outsider_key, "not-ours")
    else:
        backend._resp_command("SET", outsider_key, "not-ours")

    backend.set(f"contract-{uuid.uuid4().hex}", {"row": 1}, 300)
    backend.clear()

    if backend._client is not None:
        survived = backend._client.get(outsider_key)
    else:
        survived = backend._resp_command("GET", outsider_key)
    assert survived == "not-ours", (
        "clear() destroyed a key outside the tina4 prefix - it is flushing the "
        "whole server, not this cache"
    )
    # Clean up after ourselves; never leave another tenant's namespace dirty.
    if backend._client is not None:
        backend._client.delete(outsider_key)
    else:
        backend._resp_command("DEL", outsider_key)


@redis_up
def test_clear_removes_many_entries_not_just_the_first_page():
    """clear() must remove EVERY entry: every SCAN page, and a full reply.

    THE COUNT IS LOAD-BEARING AND WAS MEASURED, not guessed. At 250 keys a
    ``SCAN ... COUNT 500`` returns everything on the FIRST page with cursor 0,
    so a cursor loop that stops after one page still clears everything and the
    test goes green while gating nothing. That is exactly what happened: the
    first version of this test used 250 and stayed GREEN under a mutation that
    broke the loop. 2000 keys spans several pages on a real Redis, so the same
    mutation now fails here.

    It also covers the other half: the reply for a page of keys exceeds one
    64KB recv, which the old single-read RESP parser truncated silently.

    The bulk write is pipelined over ONE real connection using the backend's own
    encoder and the same SETEX it would send anyway. That is the real wire path,
    just not reconnecting 2000 times - which took over 20 seconds and taught the
    test nothing.
    """
    total = 2000
    backend = _raw(_RedisBackend(REDIS_URL))
    marker = uuid.uuid4().hex
    keys = [f"contract-{marker}-{i}" for i in range(total)]

    sock, reader = backend._resp_session()
    try:
        payload = b"".join(
            backend._resp_encode("SETEX", backend._prefix + key, "300", f'{{"i":{i}}}')
            for i, key in enumerate(keys)
        )
        sock.sendall(payload)
        for _ in keys:
            backend._resp_read(reader)
    finally:
        reader.close()
        sock.close()

    # Confirm the write really landed before asserting the clear did anything.
    assert backend.get(keys[0]) == {"i": 0}
    assert backend.get(keys[-1]) == {"i": total - 1}

    backend.clear()

    survivors = [key for key in keys if backend.get(key) is not None]
    assert survivors == [], (
        f"{len(survivors)} of {total} entries survived clear() - the scan "
        "stopped after one page, or the reply was truncated"
    )


@valkey_up
def test_clear_invalidates_on_valkey_too(_unused=None):
    """The same rule on Valkey - a second provider on the same wire protocol."""
    backend = _raw(_ValkeyBackend(VALKEY_URL))
    key = f"contract-{uuid.uuid4().hex}"
    backend.set(key, {"row": "before"}, 300)
    assert backend.get(key) == {"row": "before"}
    backend.clear()
    assert backend.get(key) is None, "clear() is a no-op on valkey's RESP transport"


# ── memcached ─────────────────────────────────────────────────────


@memcached_up
def test_memcached_clear_invalidates_for_a_second_instance():
    """memcached clear() must invalidate globally, not per-process.

    The measured defect: clear() deleted only the keys the LOCAL process had
    written, so a second instance kept serving stale rows. memcached has no KEYS
    scan, so the answer is the documented namespace-generation idiom - bump a
    shared counter and every previously-written key becomes unreachable to
    EVERY instance at once.
    """
    writer = _MemcachedBackend(MEMCACHED_URL)
    clearer = _MemcachedBackend(MEMCACHED_URL)

    key = f"contract-{uuid.uuid4().hex}"
    writer.set(key, {"row": "from-instance-a"}, 300)
    assert clearer.get(key) == {"row": "from-instance-a"}, "precondition: shared visibility"

    clearer.clear()

    assert writer.get(key) is None, (
        "clear() on instance B left instance A's entry readable - memcached has "
        "no cross-instance invalidation, so a second instance serves stale rows"
    )


@memcached_up
def test_memcached_clear_leaves_another_tenants_keys_untouched():
    """NEGATIVE: memcached clear() must never be a global flush_all.

    flush_all wipes every key on the instance, including every other
    application's. That is the failure mode the namespace generation avoids.
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    outsider_key = f"someone-elses-app-{uuid.uuid4().hex}"
    payload = b"not-ours"
    backend._command(
        f"set {outsider_key} 0 300 {len(payload)}\r\n".encode() + payload + b"\r\n", b"\r\n"
    )

    backend.set(f"contract-{uuid.uuid4().hex}", {"row": 1}, 300)
    backend.clear()

    resp = backend._command(f"get {outsider_key}\r\n".encode(), b"END\r\n")
    assert b"not-ours" in resp, (
        "clear() destroyed a key outside the tina4 namespace - it is flushing "
        "the whole memcached instance, not this cache"
    )
    backend._command(f"delete {outsider_key}\r\n".encode(), b"\r\n")


@memcached_up
def test_memcached_entries_written_before_a_clear_stay_invalid():
    """A cleared entry must not come back when the generation is re-read.

    Guards the namespace fix against an in-process generation cache that goes
    stale: after clear(), a brand-new backend instance (fresh process) must also
    miss.
    """
    writer = _MemcachedBackend(MEMCACHED_URL)
    key = f"contract-{uuid.uuid4().hex}"
    writer.set(key, {"row": "before"}, 300)
    writer.clear()

    fresh = _MemcachedBackend(MEMCACHED_URL)
    assert fresh.get(key) is None, (
        "a process that started AFTER the clear can still read the cleared "
        "entry - the invalidation did not reach the shared server"
    )
    # And a value written after the clear is readable again (the namespace is
    # usable, not permanently poisoned).
    writer.set(key, {"row": "after"}, 300)
    assert _MemcachedBackend(MEMCACHED_URL).get(key) == {"row": "after"}


@memcached_up
def test_memcached_clear_does_not_strand_live_entries_from_other_keys():
    """NEGATIVE: only THIS cache's entries go; the backend stays usable.

    A generation bump must not break subsequent writes/reads (the classic
    off-by-one where the reader and writer disagree about the generation).
    """
    backend = _MemcachedBackend(MEMCACHED_URL)
    backend.clear()
    keys = [f"contract-{uuid.uuid4().hex}" for _ in range(5)]
    for index, key in enumerate(keys):
        backend.set(key, {"i": index}, 300)
    for index, key in enumerate(keys):
        assert backend.get(key) == {"i": index}, "write/read disagree after a clear"
    assert backend.stats()["size"] == len(keys)
