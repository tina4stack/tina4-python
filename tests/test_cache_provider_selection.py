"""CACHE CONTRACT - an explicit provider is honoured, and an unreachable one
degrades visibly.

Pins TWO invariants from ``plan/v3/fixtures/cache_contract.json`` (ADR-0024),
because they are the two halves of one question: which provider did I actually
get, and was I told?

    an-explicit-provider-is-honoured
        A provider requested explicitly is the provider used. It may not be
        overridden by ambient state such as another middleware instance already
        existing.

    an-unreachable-backend-degrades-visibly
        A backend whose driver is missing or whose service is unreachable logs a
        warning and falls back to a REAL persistent cache (the file backend),
        never to a silent no-op.

MEASURED for the first: in Node an explicitly-requested response-cache provider
was silently IGNORED once any responseCache middleware existed, because the
module-level backend was memoised and returned before the config was read. The
developer names a backend, the framework quietly uses a different one, and the
only symptom is cache behaviour that does not match the configuration.

The second is the guard that keeps every other rule honest: a cache that
silently stops caching looks identical to a cache that is working, right up
until the load arrives.

UNREACHABILITY IS REAL HERE. The tests point a backend at a genuinely closed
port on localhost - a real connect() that really fails - never a simulated
outage.
"""
import os
import socket

import pytest

from tina4_python.cache import ResponseCache, _create_backend


def _closed_port() -> int:
    """A port nothing is listening on. Bind it, read it, release it.

    The bind proves the port was free at that instant; the release means a
    connect() to it really fails at the OS level. That is a genuine
    unreachable service, not a stand-in for one.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ── an explicit provider is honoured ──────────────────────────────


def test_an_explicitly_named_provider_is_used(tmp_path, monkeypatch):
    """A named backend wins over the env AND over anything already built.

    Named "explicitly named ... is used" rather than "explicit provider is
    honoured" ON PURPOSE: the contract auditor matches a case name as a
    SUBSTRING of the suite file, so a name that is a PREFIX of another case
    would still be "found" after it was deleted. Do not shorten it back.
    """
    monkeypatch.setenv("TINA4_CACHE_BACKEND", "memory")
    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "explicit"))

    # Build one first, so a memoised module-level backend would already exist.
    ambient = ResponseCache()
    explicit = ResponseCache(backend="file")

    assert explicit._backend.name() == "file", (
        f"asked for the 'file' provider and got '{explicit._backend.name()}' - "
        "the explicit request was overridden by ambient state"
    )
    assert ambient._backend.name() == "memory", (
        "building an explicit instance changed the ambient one"
    )


def test_an_explicit_provider_is_honoured_after_another_instance_exists(tmp_path, monkeypatch):
    """The measured Node defect, stated directly.

    Order matters: this is exactly the sequence that broke - some middleware is
    constructed, THEN a second one names a provider and is silently ignored.
    """
    monkeypatch.setenv("TINA4_CACHE_BACKEND", "memory")
    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "second"))

    first = ResponseCache()
    assert first._backend.name() == "memory", "precondition: the ambient provider is memory"

    second = ResponseCache(backend="file")

    assert second._backend.name() == "file", (
        "the second middleware asked for 'file' and was handed the first "
        "instance's memoised backend instead"
    )


def test_two_explicit_providers_do_not_share_a_backend(tmp_path, monkeypatch):
    """NEGATIVE: honouring the request must mean a DIFFERENT store, not a label.

    A fix that records the requested name but still hands back the memoised
    object would pass a name assertion and change nothing observable.
    """
    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "shared-dir"))
    memory_cache = ResponseCache(backend="memory")
    file_cache = ResponseCache(backend="file")

    memory_cache._backend.set("only-in-memory", {"v": 1}, 300)

    assert file_cache._backend.get("only-in-memory") is None, (
        "the two explicitly-named providers are the same object - the provider "
        "name was honoured but the store was not"
    )


def test_an_unrecognised_provider_raises(monkeypatch):
    """NEGATIVE: a typo must fail loudly, not fall through to memory.

    Falling through turned TINA4_CACHE_BACKEND=redsi into a running app with a
    per-process cache while the operator believed it was in Redis.
    """
    with pytest.raises(ValueError) as caught:
        _create_backend(backend="redsi")
    assert "redsi" in str(caught.value), "the error does not name the bad value"
    assert "redis" in str(caught.value), "the error does not list the valid backends"


# ── an unreachable backend degrades visibly ───────────────────────


def test_an_unreachable_backend_falls_back_to_the_file_backend(tmp_path, monkeypatch):
    """A REAL closed port, on every network provider.

    The fallback must be the FILE backend - a real persistent cache - and never
    memory (which silently loses cross-process sharing) and never a no-op.
    """
    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "fallback"))
    port = _closed_port()

    for backend, url in (
        ("redis", f"redis://127.0.0.1:{port}"),
        ("valkey", f"valkey://127.0.0.1:{port}"),
        ("memcached", f"memcached://127.0.0.1:{port}"),
        ("mongodb", f"mongodb://127.0.0.1:{port}/tina4_cache_contract"),
    ):
        resolved = _create_backend(backend=backend, url=url)
        assert resolved.name() == "file", (
            f"an unreachable '{backend}' resolved to '{resolved.name()}', not "
            "'file' - the fallback is not a real persistent cache"
        )


def test_the_fallback_backend_actually_caches(tmp_path, monkeypatch):
    """NEGATIVE: degrading must not mean a silent no-op.

    A no-op backend passes a name check and every write, and looks identical to
    a working cache until the load arrives. So the fallback is exercised: store,
    read it back, and confirm it reached the real filesystem.
    """
    cache_dir = tmp_path / "reallyworks"
    monkeypatch.setenv("TINA4_CACHE_DIR", str(cache_dir))
    resolved = _create_backend(backend="redis", url=f"redis://127.0.0.1:{_closed_port()}")

    resolved.set("degraded", {"v": "still cached"}, 300)

    assert resolved.get("degraded") == {"v": "still cached"}, (
        "the fallback backend accepted a write and lost it - the cache "
        "silently stopped caching"
    )
    assert list(cache_dir.glob("*.json")), (
        "nothing reached the filesystem, so the 'file' fallback is a no-op "
        "wearing the file backend's name"
    )


def test_an_unreachable_backend_logs_a_warning(tmp_path, monkeypatch, capsys):
    """The degradation must be VISIBLE, naming the provider that went away.

    Captured through stdout rather than pytest's caplog on purpose: Tina4's
    ``Log`` writes through its own formatter, not the stdlib ``logging`` tree,
    so caplog sees nothing and a warning-exists assertion built on it would pass
    whether or not anything was ever logged.
    """
    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "warned"))
    capsys.readouterr()  # drop anything emitted before this point

    _create_backend(backend="redis", url=f"redis://127.0.0.1:{_closed_port()}")

    logged = (capsys.readouterr().out or "").lower()
    assert "redis" in logged and "file" in logged and "unavailable" in logged, (
        "the fallback was silent, or the warning does not say WHICH backend "
        f"went away and what replaced it. Captured: {logged!r}"
    )


def test_a_reachable_backend_is_not_replaced(tmp_path, monkeypatch):
    """NEGATIVE: the fallback must not fire when the service is fine.

    A probe that fails open would send every deployment to the file backend and
    report a working cache - the same invisible degradation, from the other
    direction.
    """
    redis_url = os.environ.get("TINA4_TEST_CACHE_REDIS_URL", "redis://localhost:6379")
    from urllib.parse import urlparse
    parsed = urlparse(redis_url if "://" in redis_url else "//" + redis_url)
    try:
        probe = socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 6379), timeout=2)
        probe.close()
    except OSError:
        pytest.skip("redis service not reachable")

    monkeypatch.setenv("TINA4_CACHE_DIR", str(tmp_path / "notreplaced"))
    resolved = _create_backend(backend="redis", url=redis_url)

    assert resolved.name() == "redis", (
        "a REACHABLE redis was replaced by the file backend - the availability "
        "probe fails open, so every deployment silently loses its shared cache"
    )
