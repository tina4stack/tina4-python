"""Memcached session backend — against a REAL memcached server.

Memcached was one of the seven CACHE backends in all four frameworks but was not
a session backend in any of them, even though it is the classic PHP session
store. This is the parity feature that closes that gap.

NO MOCKS. Every assertion drives a live memcached over TCP. If the server is not
reachable the module skips, unless TINA4_REQUIRE_SERVICES is set — then a missing
service is a FAILURE, because a suite that silently skips its only real
verification is not verification.
"""
import os
import socket
import time

import pytest

from tina4_python.session_handlers import MemcachedSessionHandler

HOST = os.environ.get("TINA4_TEST_MEMCACHED_HOST", "127.0.0.1")
PORT = int(os.environ.get("TINA4_TEST_MEMCACHED_PORT", "11211"))


def _reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


if not _reachable():
    if os.environ.get("TINA4_REQUIRE_SERVICES"):
        raise RuntimeError(
            f"TINA4_REQUIRE_SERVICES is set but memcached is not reachable at {HOST}:{PORT}"
        )
    pytest.skip(f"memcached not reachable at {HOST}:{PORT}", allow_module_level=True)


@pytest.fixture
def handler():
    return MemcachedSessionHandler(host=HOST, port=PORT, prefix="tina4:test:session:")


SESSION = {"_created": 1, "_accessed": 2, "user_id": 7, "nested": {"a": [1, 2, 3], "flag": True}}


def test_write_then_read_returns_the_same_session(handler):
    handler.write("sid-basic", dict(SESSION), 60)
    assert handler.read("sid-basic") == SESSION
    handler.destroy("sid-basic")


def test_a_miss_returns_an_empty_dict_not_an_error(handler):
    """A miss and a failure must be different outcomes.

    Collapsing them is how a dead cache silently logs every user out instead of
    surfacing an outage.
    """
    assert handler.read("sid-definitely-not-present") == {}


def test_destroy_removes_the_session(handler):
    handler.write("sid-destroy", dict(SESSION), 60)
    assert handler.read("sid-destroy") != {}
    handler.destroy("sid-destroy")
    assert handler.read("sid-destroy") == {}


def test_destroying_an_absent_session_is_not_an_error(handler):
    """Idempotent destroy — logout twice must not raise."""
    handler.destroy("sid-never-existed")


def test_a_write_overwrites_the_previous_value(handler):
    handler.write("sid-over", {"v": 1}, 60)
    handler.write("sid-over", {"v": 2}, 60)
    assert handler.read("sid-over") == {"v": 2}
    handler.destroy("sid-over")


def test_the_ttl_actually_expires_the_session(handler):
    """Expiry is memcached's own, which is why gc() is a no-op here."""
    handler.write("sid-ttl", dict(SESSION), 1)
    assert handler.read("sid-ttl") != {}
    time.sleep(2.5)
    assert handler.read("sid-ttl") == {}


def test_a_long_session_id_is_hashed_rather_than_truncated(handler):
    """Memcached rejects keys over 250 bytes.

    Truncating would let two different sessions collide on one key - one user
    reading another's session. Hashing keeps them distinct.
    """
    a, b = "x" * 400, "x" * 399 + "y"
    handler.write(a, {"who": "a"}, 60)
    handler.write(b, {"who": "b"}, 60)
    assert handler.read(a) == {"who": "a"}
    assert handler.read(b) == {"who": "b"}
    handler.destroy(a)
    handler.destroy(b)


def test_a_session_id_containing_a_space_is_still_usable(handler):
    """A space is illegal in a memcached key and would be a protocol error."""
    sid = "has a space"
    handler.write(sid, {"ok": True}, 60)
    assert handler.read(sid) == {"ok": True}
    handler.destroy(sid)


def test_negative_an_unreachable_server_raises_rather_than_reading_empty():
    """The whole point of the miss/failure split.

    An unreachable backend must RAISE so the Session layer logs loud and
    degrades. Returning {} would be indistinguishable from "no session yet",
    which silently logs every user out during an outage.
    """
    dead = MemcachedSessionHandler(host="127.0.0.1", port=59999, timeout=1)
    with pytest.raises(RuntimeError, match="Memcached session backend"):
        dead.read("sid-any")
    with pytest.raises(RuntimeError, match="Memcached session backend"):
        dead.write("sid-any", {"a": 1}, 60)


def test_gc_is_a_no_op_because_memcached_expires_its_own_keys(handler):
    handler.gc(3600)


def test_the_session_backend_env_var_selects_memcached(monkeypatch):
    """TINA4_SESSION_BACKEND=memcached must resolve to this handler.

    A handler nothing can select is not a backend.
    """
    from tina4_python.session import Session

    monkeypatch.setenv("TINA4_SESSION_BACKEND", "memcached")
    monkeypatch.setenv("TINA4_SESSION_MEMCACHED_HOST", HOST)
    monkeypatch.setenv("TINA4_SESSION_MEMCACHED_PORT", str(PORT))
    assert isinstance(Session()._handler, MemcachedSessionHandler)

    # The "memcache" spelling is accepted too - both appear in the wild.
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "memcache")
    assert isinstance(Session()._handler, MemcachedSessionHandler)


def test_a_full_session_lifecycle_runs_through_the_session_object(monkeypatch):
    """End to end through Session, not just the handler."""
    from tina4_python.session import Session

    monkeypatch.setenv("TINA4_SESSION_BACKEND", "memcached")
    monkeypatch.setenv("TINA4_SESSION_MEMCACHED_HOST", HOST)
    monkeypatch.setenv("TINA4_SESSION_MEMCACHED_PORT", str(PORT))

    session = Session()
    sid = session.start()
    session.set("user_id", 42)
    session.save()

    reopened = Session()
    reopened.start(sid)
    assert reopened.get("user_id") == 42

    reopened.destroy()
    assert Session().start(sid) is not None
    assert Session().get("user_id") is None
