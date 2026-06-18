"""Session backend-failure policy (Auth+Sessions hardening, v3.13.x).

Contract (parity across all 4 frameworks): when a session backend
(Redis/Valkey/Mongo/Database) becomes unreachable *mid-request*, the framework
must **log loudly and degrade** — never silently lose data, and never let one
backend blip 500 every request (cascade outage). The default is:

  * read failure  → log an error, return an empty session (request still serves)
  * write failure → log an error, best-effort (dirty flag retained for retry)
  * destroy/gc failure → log an error, swallow

A *genuinely empty* result (no such session yet) is NOT a failure — the handler
returns ``{}`` without raising, so it must never be logged as an error.

``TINA4_SESSION_STRICT=true`` flips this to re-raise (the escape hatch that
mirrors the ``strict`` flag on events/seeding) for callers who would rather a
failed persist surface loudly.
"""
from __future__ import annotations

import pytest

from tina4_python.session import Session, SessionHandler


class _ExplodingHandler(SessionHandler):
    """A backend that raises on every operation — simulates an unreachable
    Redis/Valkey/Mongo/DB mid-request."""

    def read(self, session_id: str) -> dict:
        raise ConnectionError("backend unreachable")

    def write(self, session_id: str, data: dict, ttl: int = 0):
        raise ConnectionError("backend unreachable")

    def destroy(self, session_id: str):
        raise ConnectionError("backend unreachable")

    def gc(self, max_lifetime: int = 0):
        raise ConnectionError("backend unreachable")


class _EmptyHandler(SessionHandler):
    """A healthy backend that simply has no data for this session — returns
    ``{}`` WITHOUT raising. This is the normal 'no session yet' case and must
    never be treated as a backend error."""

    def __init__(self):
        self.reads = 0

    def read(self, session_id: str) -> dict:
        self.reads += 1
        return {}

    def write(self, session_id: str, data: dict, ttl: int = 0):
        pass

    def destroy(self, session_id: str):
        pass


@pytest.fixture
def captured_errors(monkeypatch):
    """Capture Log.error calls so we can assert the failure was logged
    (never silent)."""
    errors: list[str] = []
    from tina4_python.debug import Log

    monkeypatch.setattr(Log, "error", classmethod(lambda cls, msg, **kw: errors.append(msg)))
    return errors


# ── default policy: log-loud + degrade ──────────────────────────────────────


def test_read_failure_logs_and_degrades_to_empty(captured_errors):
    """An unreachable backend on start() must NOT raise — the request still
    gets a valid session id with empty data, and the failure is logged."""
    session = Session(handler=_ExplodingHandler())
    sid = session.start("sess-1")
    assert sid  # a session id is still issued
    assert session.all() == {}  # degraded to empty, not crashed
    assert any("read" in e and "failed" in e for e in captured_errors), (
        "a backend read failure must be logged, never silent"
    )


def test_write_failure_logs_and_is_best_effort(captured_errors):
    """An unreachable backend on save() must NOT raise — save() returns False,
    the dirty flag is retained (so a later save retries), and it is logged."""
    session = Session(handler=_ExplodingHandler())
    session.start("sess-2")
    session.set("user_id", 7)
    result = session.save()
    assert result is False  # write failed (reported, not crashed)
    assert session._dirty is True  # retained for retry
    assert any("write" in e and "failed" in e for e in captured_errors)


def test_destroy_failure_logs_and_does_not_crash(captured_errors):
    """destroy() on an unreachable backend logs but never raises (default)."""
    session = Session(handler=_ExplodingHandler())
    session.start("sess-3")
    session.destroy()  # must not raise
    assert any("destroy" in e and "failed" in e for e in captured_errors)


def test_gc_failure_logs_and_does_not_crash(captured_errors):
    session = Session(handler=_ExplodingHandler())
    session.gc()  # must not raise
    assert any("gc" in e and "failed" in e for e in captured_errors)


# ── the empty-but-healthy case must NOT be flagged as an error ───────────────


def test_empty_session_is_not_a_backend_error(captured_errors):
    """A healthy backend with no data returns {} WITHOUT raising — this is the
    normal 'no session yet' path and must produce ZERO error logs."""
    handler = _EmptyHandler()
    session = Session(handler=handler)
    session.start("brand-new")
    assert session.all() == {}
    assert handler.reads == 1
    assert captured_errors == [], (
        "an empty (but successful) read must never be logged as a failure"
    )


# ── strict opt-in: re-raise instead of degrade ──────────────────────────────


def test_strict_mode_reraises_read_failure(monkeypatch):
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    session = Session(handler=_ExplodingHandler())
    with pytest.raises(ConnectionError):
        session.start("sess-strict")


def test_strict_mode_reraises_write_failure(monkeypatch):
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    session = Session(handler=_ExplodingHandler())
    # start() reads first — that raises under strict, so seed state directly.
    session._session_id = "sess-strict-w"
    session.set("k", "v")
    with pytest.raises(ConnectionError):
        session.save()
