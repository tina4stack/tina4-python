"""SESSION CONTRACT: the session key prefix is configurable by env var, on every RESP backend.

ADR-0024: swapping one session backend for another changes ONE env var and
nothing else. Namespacing the keys those backends write is part of that
configuration surface, and it was present in ONE framework out of four.

WHY THIS FILE EXISTS. Measured 2026-08-05 across all four frameworks:

    TINA4_SESSION_MEMCACHED_PREFIX   python YES  php YES  ruby YES  node YES
    TINA4_SESSION_VALKEY_PREFIX      python no   php no   ruby YES  node YES
    TINA4_SESSION_REDIS_PREFIX       python no   php no   ruby no   node YES

Three tiers for one idea. Two apps sharing a Redis could namespace their
sessions on Node and silently collide on Python - and an operator reading the
Node docs would set a variable the other three ignore, with no error and no
signal. That is the ADR-0024 failure mode exactly: identical configuration,
different observable outcome.

NO MOCKS. Both backends here are the real service (real Redis, real Valkey), and
every claim about the key's NAME is checked with an INDEPENDENT client on a
second connection - never by asking the handler what it thinks it wrote. A
handler that lies consistently would pass a self-report; it cannot pass this.

THE THREE CASES, and why each is load-bearing:
  1. positive  - the env var really names the key ON THE SERVER.
  2. precedence - an explicit option still beats the env var. Without this,
                  "always read the env var" passes case 1 and quietly breaks
                  every caller that passes prefix= explicitly.
  3. negative  - with nothing set the default is still "tina4:session:".
                 Without this, "always prepend the env var, empty or not"
                 passes cases 1 and 2 and renames every existing key in every
                 deployment that never asked for a prefix.
"""
import os
import socket as _socket
import uuid
from urllib.parse import urlparse

import pytest

from tina4_python.session_handlers.redis_handler import RedisSessionHandler
from tina4_python.session_handlers.valkey_handler import ValkeySessionHandler


def _target(env_var: str, default_url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(os.environ.get(env_var) or default_url)
    return (parsed.hostname or "localhost", parsed.port or default_port)


REDIS_HOST, REDIS_PORT = _target("TINA4_TEST_REDIS_URL", "redis://localhost:6379", 6379)
VALKEY_HOST, VALKEY_PORT = _target("TINA4_TEST_VALKEY_URL", "redis://localhost:6380", 6380)

# Each backend, with the env var ITS handler reads and the db number the suite
# is configured for. The db is resolved, not assumed: a witness that skips it
# reads database 0 while the handler wrote elsewhere.
BACKENDS = (
    ("redis", RedisSessionHandler, REDIS_HOST, REDIS_PORT,
     "TINA4_SESSION_REDIS_PREFIX", "TINA4_SESSION_REDIS_DB"),
    ("valkey", ValkeySessionHandler, VALKEY_HOST, VALKEY_PORT,
     "TINA4_SESSION_VALKEY_PREFIX", "TINA4_SESSION_VALKEY_DB"),
)


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with _socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _witness(host: str, port: int, db: int):
    """A SECOND, independent connection - the only thing that may confirm a key name."""
    import redis as redis_pkg

    return redis_pkg.Redis(host=host, port=port, db=db, decode_responses=True)


@pytest.fixture()
def clean_prefix_env(monkeypatch):
    """Neither prefix variable is set, so a default really is a default."""
    for name in ("TINA4_SESSION_REDIS_PREFIX", "TINA4_SESSION_VALKEY_PREFIX"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name,handler_cls,host,port,prefix_env,db_env", BACKENDS)
def test_session_key_prefix_env_var_names_the_key_on_the_server(
    name, handler_cls, host, port, prefix_env, db_env, monkeypatch
):
    """The configured prefix is the one the SERVER really holds the key under."""
    if not _reachable(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")

    db = int(os.environ.get(db_env, "0") or 0)
    configured = f"itest{uuid.uuid4().hex[:8]}:"
    monkeypatch.setenv(prefix_env, configured)

    handler = handler_cls(host=host, port=port, db=db, ttl=60)
    sid = f"prefix-{uuid.uuid4().hex[:8]}"
    obs = _witness(host, port, db)
    try:
        handler.write(sid, {"seeded": True})
        assert obs.exists(f"{configured}{sid}") == 1, (
            f"{name}: {prefix_env}={configured} was ignored - nothing at "
            f"{configured}{sid} on the server"
        )
        # And the DEFAULT name must be absent, or the prefix was appended to
        # rather than used, and two deployments would still collide.
        assert obs.exists(f"tina4:session:{sid}") == 0, (
            f"{name}: the key was ALSO written under the default prefix"
        )
    finally:
        obs.delete(f"{configured}{sid}", f"tina4:session:{sid}")
        obs.close()


@pytest.mark.parametrize("name,handler_cls,host,port,prefix_env,db_env", BACKENDS)
def test_session_key_prefix_option_wins_over_the_env_var(
    name, handler_cls, host, port, prefix_env, db_env, monkeypatch
):
    """An explicit prefix= still beats the environment, as every other option does."""
    if not _reachable(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")

    db = int(os.environ.get(db_env, "0") or 0)
    monkeypatch.setenv(prefix_env, "fromenv:")
    explicit = f"explicit{uuid.uuid4().hex[:8]}:"

    handler = handler_cls(host=host, port=port, db=db, prefix=explicit, ttl=60)
    sid = f"prefix-{uuid.uuid4().hex[:8]}"
    obs = _witness(host, port, db)
    try:
        handler.write(sid, {"seeded": True})
        assert obs.exists(f"{explicit}{sid}") == 1, (
            f"{name}: an explicit prefix= lost to {prefix_env}"
        )
        assert obs.exists(f"fromenv:{sid}") == 0, (
            f"{name}: the env prefix was used even though prefix= was given"
        )
    finally:
        obs.delete(f"{explicit}{sid}", f"fromenv:{sid}")
        obs.close()


@pytest.mark.parametrize("name,handler_cls,host,port,prefix_env,db_env", BACKENDS)
def test_session_key_prefix_defaults_when_nothing_is_set(
    name, handler_cls, host, port, prefix_env, db_env, clean_prefix_env
):
    """NEGATIVE CONTROL: with nothing configured the key is still tina4:session:.

    Without this case, "always prepend whatever the variable holds" passes both
    cases above and renames every key in every deployment that never asked for a
    prefix - which on a session store logs everybody out at once.
    """
    if not _reachable(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")

    db = int(os.environ.get(db_env, "0") or 0)
    handler = handler_cls(host=host, port=port, db=db, ttl=60)
    assert handler._prefix == "tina4:session:", (
        f"{name}: the documented default was lost"
    )

    sid = f"prefix-{uuid.uuid4().hex[:8]}"
    obs = _witness(host, port, db)
    try:
        handler.write(sid, {"seeded": True})
        assert obs.exists(f"tina4:session:{sid}") == 1, (
            f"{name}: nothing at the default key on the server"
        )
    finally:
        obs.delete(f"tina4:session:{sid}")
        obs.close()
