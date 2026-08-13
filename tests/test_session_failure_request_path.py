"""SESSION CONTRACT: a backend failure is LOUD, then degrades - on the REAL request path.

ADR-0021: a backend that becomes unreachable is LOGGED and then degraded - the
read yields an empty session, save() returns false, and the request STILL
SERVES. It is never silent. TINA4_SESSION_STRICT re-raises instead.

WHY THIS FILE EXISTS, and why it is separate from test_session_backend_failure.py.

That file proves the policy on the Session OBJECT, thoroughly, against real
unreachable services. This file proves it on the HTTP REQUEST PATH, which is a
different code path and was NOT covered - and that is exactly where the policy
was missing. Measured at v3 HEAD, tina4_python/core/server.py:1404-1405:

    except Exception:
        pass  # Session module not available - session stays None

One bare except wrapping the whole session block: the import, the cookie parse,
the Session() construction, sess.start(), the assignment and gc. Its comment
claims it is there for a missing session module, but it swallows EVERYTHING:

  * a handler that cannot CONSTRUCT (the database backend opens its connection
    and issues DDL in its constructor, which sits outside Session's policy),
  * the deliberate ValueError for an unknown TINA4_SESSION_BACKEND - the loud
    refusal that test_session_backend_validation.py exists to guarantee, made
    silent again by the one caller that matters,
  * and every TINA4_SESSION_STRICT re-raise, which makes STRICT MODE INERT on
    the request path.

The operator symptom is users being mysteriously logged out with no signal
anywhere: request.session is simply None and nothing is written to any log.

THE OTHER HALF OF THE RULE, and the easy thing to get wrong when making failures
loud: a genuinely EMPTY session is NOT an error and must never be logged as one.
A first-time visitor with no cookie, and a cookie whose session the store has
never heard of, are both ordinary. If those log an error, the log fills with
noise and the real outage is invisible - which is the same blindness the fix was
meant to cure. Case 3 is that control and it is not optional.

NO MOCKS. The unreachable backend is a genuinely closed TCP port, the logger is
the real logger writing real bytes to a real file which the test reads back, and
the request goes through TestClient, which dispatches the real ASGI scope
through the real front controller in tina4_python.core.server.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

os.environ.setdefault("TINA4_SECRET", "session-failure-request-path-secret")

from tina4_python.core.router import get
from tina4_python.test_client import TestClient

# A well-formed session id for a session the store has never heard of. Without a
# COOKIE the request path takes the "brand new session" branch and never calls
# start(), so the backend is never touched and an "unreachable backend" case
# would pass while proving nothing. Learned the hard way: the strict-mode case
# below returned a cheerful 200 for exactly that reason.
EXISTING_SESSION_COOKIE = {"cookie": "tina4_session=" + ("a1b2c3d4" * 8)}


def _closed_port() -> int:
    """Bind a port, learn its number, close it. Nothing is listening after this."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return port


def _reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _RealLogSink:
    """Reads the bytes the REAL logger actually wrote to a real file.

    Not a capture double: Log.error runs its real body - level gating, output
    routing, JSON structuring, the file write - and we read the file afterwards,
    exactly as an operator would.
    """

    def __init__(self, directory: Path):
        self._path = directory / "tina4.log"
        self._mark = 0

    def mark(self) -> None:
        self._mark = self._path.stat().st_size if self._path.exists() else 0

    def errors(self) -> list[str]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self._mark)
            body = handle.read()
        out = []
        for line in body.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(entry.get("level", "")).lower() == "error":
                out.append(str(entry.get("message", "")))
        return out


@pytest.fixture
def log_sink(tmp_path, monkeypatch):
    """Point the REAL logger at a real file, then put it back."""
    from tina4_python.debug import Log

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
    monkeypatch.setenv("TINA4_LOG_DIR", str(log_dir))
    monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
    monkeypatch.setenv("TINA4_LOG_LEVEL", "debug")

    # The 3.14 logger-conformance refactor (tina4_python/debug/__init__.py)
    # replaced the old per-attribute state (_writer/_error_writer/
    # _stdout_enabled/_file_enabled/_format_mode/_level/_is_production) with
    # one atomic _Snapshot object on Log._snapshot. Saving/restoring that
    # single reference is the equivalent save-and-restore against the
    # shipped internals.
    saved_snapshot = Log._snapshot
    Log.configure(log_dir=str(log_dir), level="debug")

    sink = _RealLogSink(log_dir)
    # Driver sanity. Without this, "was logged" would be vacuous and "logged
    # nothing" would be trivially true - the control would prove the opposite of
    # what it claims.
    sink.mark()
    Log.error("sink-selftest")
    assert any("sink-selftest" in message for message in sink.errors()), (
        f"the real logger wrote nothing to {log_dir / 'tina4.log'} - every log "
        "assertion in this file would be meaningless"
    )

    yield sink

    Log._snapshot = saved_snapshot


@pytest.fixture(autouse=True)
def _probe_route():
    """A real route, registered through the real router, that reports the session."""

    @get("/session-failure-probe")
    async def _probe(request, response):
        session = getattr(request, "session", None)
        return response({
            "session_present": session is not None,
            "data": session.all() if session is not None else None,
        })

    yield


def test_a_backend_failure_on_the_request_path_is_logged_not_silent(log_sink, monkeypatch):
    """An unusable session backend must leave a record an operator can find.

    TINA4_SESSION_BACKEND is set to a name the framework deliberately refuses.
    That refusal is a loud ValueError by design, and the request path used to
    swallow it whole - request.session became None with nothing logged anywhere.
    """
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "redsi")  # a real typo, deliberately refused
    log_sink.mark()

    TestClient().get("/session-failure-probe")

    errors = log_sink.errors()
    assert any("session" in message.lower() for message in errors), (
        "an unusable session backend produced NO error log on the real request "
        f"path - the operator has no signal at all. Errors seen: {errors!r}"
    )


def test_a_backend_failure_on_the_request_path_still_serves_the_request(log_sink, monkeypatch):
    """Loud is only half the rule: the request must still be SERVED.

    Degrading means the user gets their page without a session, not a 500. This
    is what separates a degrade from an outage.
    """
    port = _closed_port()
    assert not _reachable("127.0.0.1", port), (
        f"127.0.0.1:{port} answered - it was supposed to be closed, so this case "
        "would not be testing an unreachable backend at all"
    )
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "redis")
    monkeypatch.setenv("TINA4_SESSION_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("TINA4_SESSION_REDIS_PORT", str(port))
    log_sink.mark()

    result = TestClient().get("/session-failure-probe", headers=EXISTING_SESSION_COOKIE)

    assert result.status == 200, (
        f"an unreachable session backend returned {result.status} instead of "
        "serving the request without a session"
    )
    assert any("session" in message.lower() for message in log_sink.errors()), (
        "the request served, but the unreachable backend was not logged - "
        "degrading silently is the defect, not the fix"
    )


def test_an_empty_session_on_the_request_path_is_not_logged_as_a_failure(log_sink, tmp_path, monkeypatch):
    """NEGATIVE CONTROL, and the one most likely to be got wrong.

    A first-time visitor has no cookie and therefore an empty session. That is
    ORDINARY, not a failure. If making failures loud also makes this loud, the
    log fills with noise on every new visitor and the real outage becomes
    invisible - the same blindness the fix was meant to cure.

    Without this case, "log an error unconditionally" passes both cases above.
    """
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "file")
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))
    log_sink.mark()

    fresh = TestClient().get("/session-failure-probe")
    unknown = TestClient().get("/session-failure-probe", headers=EXISTING_SESSION_COOKIE)

    assert fresh.status == 200 and unknown.status == 200
    session_errors = [m for m in log_sink.errors() if "session" in m.lower()]
    assert not session_errors, (
        "a healthy backend with an EMPTY session logged an error. An empty "
        f"session is not a failure. Logged: {session_errors!r}"
    )


def test_strict_mode_on_the_request_path_refuses_instead_of_degrading(log_sink, monkeypatch):
    """TINA4_SESSION_STRICT must actually reach the request path.

    Strict mode exists so an operator can choose "fail the request" over "serve
    it without a session". Swallowed by the bare except, it was INERT here: the
    request returned a cheerful 200 while the session silently did not exist,
    which is precisely the outcome strict mode is chosen to prevent.
    """
    port = _closed_port()
    assert not _reachable("127.0.0.1", port)
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "redis")
    monkeypatch.setenv("TINA4_SESSION_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("TINA4_SESSION_REDIS_PORT", str(port))
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    log_sink.mark()

    # The contract word is RE-RAISES. The raise leaves the request path and is
    # turned into a 500 by the ASGI server, which is the loud outcome strict
    # mode is chosen for. Asserting the raise is the precise contract; asserting
    # a status code would be asserting uvicorn's behaviour, not Tina4's.
    with pytest.raises(Exception) as raised:
        TestClient().get("/session-failure-probe", headers=EXISTING_SESSION_COOKIE)

    # It must surface the REAL driver error, not a generic wrapper. A strict mode
    # that raises something opaque tells the operator no more than silence did.
    message = f"{type(raised.value).__name__}: {raised.value}"
    assert "connect" in message.lower() or "refused" in message.lower(), (
        f"strict mode raised, but not with the real backend failure: {message}"
    )
    assert any("session" in entry.lower() for entry in log_sink.errors()), (
        "strict mode raised without logging first - loud must mean logged AND "
        "raised, or the log has a hole exactly where the outage is"
    )
