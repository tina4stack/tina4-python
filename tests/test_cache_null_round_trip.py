"""CACHE CONTRACT - a cached null round-trips as null.

Pins ``a-cached-null-round-trips-as-null`` from
``plan/v3/fixtures/cache_contract.json`` (ADR-0024).

    A cached value of null/None/nil comes back as that value, not as the storage
    envelope that wrapped it, and not as a miss.

MEASURED in Node: the file backend handed back the storage ENVELOPE
(``{key, value, expiresAt}``) instead of the value when the cached value was
null, because it read ``data.value ?? data``. The caller received an object
where it had stored nothing, so ``if (cached)`` was TRUE for a cached null and
the cache turned an absence into a presence. Caching "this lookup found nothing"
is the single most common reason to cache a null, so the wrong answer is served
exactly where the feature is used.

A note on what "not as a miss" can mean here. In Python and Ruby, None/nil IS
the miss sentinel of the backend contract, so a caller cannot separate the two
from the return value alone. The observable that DOES separate them is the
backend's own hit/miss accounting, which is public through stats(), so that is
what these tests assert. The stronger form - a distinguishable sentinel or a
`default=` parameter, which is what Django and Rails expose - is a contract
change beyond this invariant and is recorded as owed rather than smuggled in.

Every backend here is REAL. Nothing is simulated.
"""
import os
import socket
import uuid
from urllib.parse import urlparse

import pytest

from tina4_python.cache import _create_backend

REDIS_URL = os.environ.get("TINA4_TEST_REDIS_URL", "redis://localhost:6379")
VALKEY_URL = os.environ.get("TINA4_TEST_VALKEY_URL", "valkey://localhost:6380")
MEMCACHED_URL = os.environ.get("TINA4_TEST_MEMCACHED_URL", "memcached://localhost:11211")
MONGO_URL = os.environ.get("TINA4_TEST_MONGO_URI", "mongodb://localhost:27017")


def _reachable(url: str, default_port: int) -> bool:
    parsed = urlparse(url if "://" in url else "//" + url)
    try:
        sock = socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or default_port), timeout=2)
        sock.close()
        return True
    except OSError:
        return False


def _every_backend(tmp_path):
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


def test_a_cached_null_comes_back_as_null(tmp_path):
    """The rule, on every provider."""
    for backend in _every_backend(tmp_path):
        key = f"null-{uuid.uuid4().hex}"
        backend.set(key, None, 300)

        got = backend.get(key)

        assert got is None, (
            f"{backend.name()} returned {got!r} for a cached null - the caller "
            "gets something where it stored nothing"
        )


def test_a_cached_null_is_not_the_storage_envelope(tmp_path):
    """The measured Node defect, stated so it cannot pass by accident.

    Returning the envelope makes a cached null TRUTHY, so every
    `if cached:` guard in every application inverts.
    """
    for backend in _every_backend(tmp_path):
        key = f"null-{uuid.uuid4().hex}"
        backend.set(key, None, 300)

        got = backend.get(key)

        assert not isinstance(got, dict), (
            f"{backend.name()} returned the storage ENVELOPE {got!r} instead of "
            "the cached null"
        )
        assert not got, (
            f"{backend.name()} made a cached null TRUTHY, so `if cached:` is "
            "true for a value that is absent"
        )


def test_a_cached_null_is_a_hit_not_a_miss(tmp_path):
    """The cache must know it HAS the entry, even though the value is null.

    This is what separates "we looked and there is nothing" from "we never
    looked", and it is the reason to cache a null in the first place.
    """
    for backend in _every_backend(tmp_path):
        backend.clear()
        key = f"null-{uuid.uuid4().hex}"
        backend.set(key, None, 300)
        before = backend.stats()

        backend.get(key)

        after = backend.stats()
        assert after["hits"] == before["hits"] + 1, (
            f"{backend.name()} did not count a cached null as a HIT"
        )
        assert after["misses"] == before["misses"], (
            f"{backend.name()} counted a cached null as a MISS - the cache "
            "cannot tell 'we looked and found nothing' from 'we never looked'"
        )


def test_a_missing_key_is_still_a_miss(tmp_path):
    """NEGATIVE: fixing the null path must not turn every miss into a hit.

    The obvious wrong fix - always report a hit and return None - satisfies the
    tests above and destroys the cache's accounting.
    """
    for backend in _every_backend(tmp_path):
        backend.clear()
        before = backend.stats()

        assert backend.get(f"never-written-{uuid.uuid4().hex}") is None

        after = backend.stats()
        assert after["misses"] == before["misses"] + 1, (
            f"{backend.name()} did not count an absent key as a MISS"
        )
        assert after["hits"] == before["hits"], (
            f"{backend.name()} counted an absent key as a HIT"
        )


def test_other_falsy_values_round_trip_intact(tmp_path):
    """NEGATIVE: false, 0, "" and [] are VALUES, not absences.

    A null fix built on falsiness (`value || envelope`, `if not value`) breaks
    every one of these, and each is a perfectly ordinary thing to cache.
    """
    for backend in _every_backend(tmp_path):
        for label, value in (("false", False), ("zero", 0), ("empty-string", ""),
                             ("empty-list", []), ("empty-dict", {})):
            key = f"falsy-{label}-{uuid.uuid4().hex}"
            backend.set(key, value, 300)

            got = backend.get(key)

            assert got == value and type(got) is type(value), (
                f"{backend.name()} mangled a cached {label}: stored {value!r}, "
                f"got {got!r}"
            )
