"""Session backend-failure policy (Auth+Sessions hardening, v3.13.x). NO DOUBLES.

Contract (parity across all 4 frameworks): when a session backend
(Redis/Valkey/Mongo/Database) becomes unreachable *mid-request*, the framework
must **log loudly and degrade** -- never silently lose data, and never let one
backend blip 500 every request (cascade outage). The default is:

  * read failure      -> log an error, return an empty session (request serves)
  * write failure     -> log an error, best-effort (dirty flag kept for retry)
  * destroy/gc failure-> log an error, swallow

A *genuinely empty* result (no such session yet) is NOT a failure -- the handler
returns ``{}`` without raising, so it must never be logged as an error.

``TINA4_SESSION_STRICT=true`` flips this to re-raise.

---------------------------------------------------------------------------
WHAT THIS FILE USED TO BE -- and why every line of it was untrustworthy.

It declared two in-test SessionHandler subclasses, ``_ExplodingHandler`` and
``_EmptyHandler``. It is the exact twin of tina4-php's ``ThrowingSessionHandler``,
tina4-ruby's ``RaisingHandler`` and tina4-nodejs's ``ExplodingHandler`` -- the
same double, ported four ways, each with a matching ``Empty*`` "positive control"
that also could not fail.

``_ExplodingHandler`` raised the BUILTIN ``ConnectionError``. Measured on this
tree, a real unreachable Redis raises ``redis.exceptions.ConnectionError``, whose
MRO is ``RedisError -> Exception``: it is **not** a subclass of the builtin. So
``test_strict_mode_reraises_read_failure``, which asserted
``pytest.raises(ConnectionError)``, was calibrated to the fake and would NOT have
matched the real driver error. That is the whole hazard in one line: if the
framework's ``except`` clause were narrower than the double assumed, every test
here stayed green while production 500'd on every request -- the precise cascade
outage the file exists to prevent.

``_EmptyHandler`` was the worse of the two. It asserted "an empty healthy read
logs ZERO errors" against a handler that CANNOT fail, so it could never catch the
regression it existed for: a real server's ``$-1\\r\\n`` null bulk reply being
misclassified by the TRANSPORT as an error. That misclassification lives in the
transport, and the transport never ran.

The ``captured_errors`` fixture monkeypatched ``Log.error`` to append to a list.
Every "is LOGGED (never silent)" claim was therefore a substring check on a
function the test itself installed. ``Log.error``'s real body -- level gating,
``TINA4_LOG_OUTPUT`` routing, JSON structuring, the file write -- never executed,
so a regression that made ``Log.error`` silently drop the record in production
still read PASS.

---------------------------------------------------------------------------
WHAT IT IS NOW -- real drivers, a real log sink, no stand-ins.

 (1) UNREACHABLE BACKEND: the REAL ``RedisSessionHandler`` / the REAL
     ``MongoDBSessionHandler`` pointed at a genuinely closed port, obtained by
     bind-then-release. Every operation fails with a real ECONNREFUSED through
     the real driver. Needs no service, so it never skips.
 (2) EMPTY-BUT-HEALTHY: the REAL ``RedisSessionHandler`` against LIVE Redis,
     reading a fresh ``uuid4`` key that provably does not exist -- a real
     ``$-1`` null bulk reply off the wire. Skips loudly naming host and port.
 (3) WRITE FAILS AFTER A SUCCESSFUL START: the REAL ``FileSessionHandler`` in a
     real temp dir. ``start()`` writes for real, then the session FILE is
     chmod 0400 so the NEXT write takes a real EACCES from the real kernel.

LOGGING is measured by pointing the REAL logger at a real file
(``TINA4_LOG_OUTPUT=file`` + ``TINA4_LOG_DIR`` + ``TINA4_LOG_FORMAT=json``) and
reading the bytes it actually wrote, delta-per-scenario.

POSIX detail, measured not assumed (same finding as the Node conversion): chmod
0500 on the session DIRECTORY does NOT block the write. ``write_text`` on an
EXISTING path needs write permission on the FILE; directory permission governs
create/unlink/rename.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import uuid
from pathlib import Path

import pytest

from tina4_python.session import Session, FileSessionHandler
from tina4_python.session_handlers.redis_handler import RedisSessionHandler
from tina4_python.session_handlers.mongodb_handler import MongoDBSessionHandler

_REDIS_HOST = os.environ.get("TINA4_TEST_REDIS_HOST", "127.0.0.1")
_REDIS_PORT = int(os.environ.get("TINA4_TEST_REDIS_PORT", "6379"))


def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _closed_port() -> int:
    """A port that is genuinely closed: bind it, read it, release it.

    Not a simulation of refusal -- the kernel refuses the connect for real.
    """
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


# ── the real log sink ────────────────────────────────────────────────────────


class _RealLogSink:
    """Reads the bytes the REAL logger actually wrote to a real file.

    This is not a capture double: ``Log.error`` runs its real body -- level
    gating, TINA4_LOG_OUTPUT routing, JSON structuring, the file write -- and we
    read the file afterwards, exactly as an operator would.
    """

    def __init__(self, directory: Path):
        self._path = directory / "tina4.log"
        self._mark = 0

    def mark(self) -> None:
        """Ignore everything logged before the scenario under test."""
        self._mark = self._path.stat().st_size if self._path.exists() else 0

    def lines(self) -> list[str]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self._mark)
            return [line for line in handle.read().splitlines() if line.strip()]

    def errors(self) -> list[str]:
        """Only the ERROR records, parsed out of the REAL JSON the logger wrote."""
        out = []
        for line in self.lines():
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

    saved = {
        name: getattr(Log, name)
        for name in ("_writer", "_error_writer", "_stdout_enabled",
                     "_file_enabled", "_format_mode", "_level", "_is_production")
    }
    Log.configure(log_dir=str(log_dir), level="debug")

    sink = _RealLogSink(log_dir)
    # Driver sanity: the sink must be able to see a real record, otherwise every
    # "was logged" assertion below would be vacuous and every "logged nothing"
    # assertion would be trivially true.
    sink.mark()
    Log.error("sink-selftest")
    assert any("sink-selftest" in m for m in sink.errors()), (
        f"the real logger wrote nothing to {log_dir / 'tina4.log'} -- "
        "every log assertion in this file would be meaningless"
    )

    yield sink

    for name, value in saved.items():
        setattr(Log, name, value)


@pytest.fixture
def unreachable_redis():
    """The REAL RedisSessionHandler against a genuinely closed port."""
    port = _closed_port()
    assert not _reachable("127.0.0.1", port, timeout=0.5), (
        f"127.0.0.1:{port} answered -- it was supposed to be closed, so every "
        "'unreachable backend' case here would be vacuous"
    )
    return RedisSessionHandler(host="127.0.0.1", port=port, ttl=60)


@pytest.fixture
def unreachable_mongo():
    """The REAL MongoDBSessionHandler against a genuinely closed port.

    The short timeouts go through the URL because the handler exposes no knob
    for them (see the note in the module docstring of the findings report): the
    shipped default is a 30 second server-selection timeout.
    """
    port = _closed_port()
    assert not _reachable("127.0.0.1", port, timeout=0.5)
    return MongoDBSessionHandler(
        url=f"mongodb://127.0.0.1:{port}/?serverSelectionTimeoutMS=800&connectTimeoutMS=800",
        ttl=60,
    )


# ── default policy: log-loud + degrade, driven by a real refused connection ──


def test_read_failure_logs_and_degrades_to_empty(log_sink, unreachable_redis):
    """A real ECONNREFUSED on start() must NOT raise: the request still gets a
    session id with empty data, and the REAL logger records the REAL cause."""
    log_sink.mark()
    session = Session(handler=unreachable_redis)
    sid = session.start("sess-1")

    assert sid
    assert session.all() == {}, "must degrade to empty, not crash"

    errors = log_sink.errors()
    assert any("read" in e and "failed" in e for e in errors), (
        f"a backend read failure must be logged, never silent. Got: {errors}"
    )
    assert any("RedisSessionHandler" in e for e in errors), (
        "the log must name the backend that failed"
    )
    # The cause must be the REAL driver's message, not a string this test chose.
    assert any("refused" in e.lower() for e in errors), (
        f"the logged cause must be the real ECONNREFUSED. Got: {errors}"
    )


def test_write_failure_logs_and_is_best_effort(log_sink, unreachable_redis):
    """save() against a real refused connection returns False, keeps the dirty
    flag for a later retry, and is logged."""
    log_sink.mark()
    session = Session(handler=unreachable_redis)
    session.start("sess-2")
    session.set("user_id", 7)

    assert session.save() is False
    assert session._dirty is True, "dirty flag must be retained so a later save retries"
    assert any("write" in e and "failed" in e for e in log_sink.errors())


def test_destroy_failure_logs_and_does_not_crash(log_sink, unreachable_mongo):
    log_sink.mark()
    session = Session(handler=unreachable_mongo)
    session._session_id = "sess-3"
    session.destroy()  # must not raise
    assert any("destroy" in e and "failed" in e for e in log_sink.errors())


def test_gc_failure_logs_and_does_not_crash(log_sink, unreachable_mongo):
    log_sink.mark()
    session = Session(handler=unreachable_mongo)
    session.gc()  # must not raise
    assert any("gc" in e and "failed" in e for e in log_sink.errors())


def test_write_fails_after_a_successful_start_with_a_real_eacces(log_sink, tmp_path):
    """The mid-request death case, produced rather than simulated.

    A REAL FileSessionHandler writes successfully, then the real session FILE is
    made read-only so the NEXT write takes a real EACCES from the real kernel.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: chmod 0400 does not deny root, so no real EACCES")

    handler = FileSessionHandler(path=str(tmp_path / "sessions"))
    session = Session(handler=handler)
    sid = session.start("sess-eacces")
    session.set("stage", "one")
    assert session.save() is True, "the first write must genuinely succeed"

    session_file = handler._file(sid)
    assert session_file.exists(), "start()+save() must have created a real file"
    session_file.chmod(stat.S_IRUSR)  # 0400 -- read-only, on the FILE not the dir

    log_sink.mark()
    session.set("stage", "two")
    assert session.save() is False, "a real EACCES must be reported, not swallowed"
    assert session._dirty is True

    errors = log_sink.errors()
    assert any("write" in e and "failed" in e for e in errors)
    assert any("FileSessionHandler" in e for e in errors)
    assert any(
        "denied" in e.lower() or "errno 13" in e.lower() for e in errors
    ), f"the logged cause must be the real EACCES. Got: {errors}"

    session_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # so tmp_path can be cleaned


# ── the empty-but-healthy case, read off a real server ──────────────────────


@pytest.mark.skipif(
    not _reachable(_REDIS_HOST, _REDIS_PORT),
    reason=f"redis not reachable at {_REDIS_HOST}:{_REDIS_PORT}",
)
def test_empty_but_healthy_read_is_not_a_backend_error(log_sink):
    """A HEALTHY server with no data for this id: a real null bulk reply.

    The deleted ``_EmptyHandler`` could not fail, so it could never catch the
    regression this exists for -- a real empty reply being misclassified by the
    transport as an error. The transport now runs.
    """
    handler = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=60)
    try:
        never_written = f"absent-{uuid.uuid4().hex}"
        log_sink.mark()
        session = Session(handler=handler)
        session.start(never_written)

        assert session.all() == {}
        assert log_sink.errors() == [], (
            "an empty (but successful) read must never be logged as a failure"
        )
    finally:
        handler.close()


@pytest.mark.skipif(
    not _reachable(_REDIS_HOST, _REDIS_PORT),
    reason=f"redis not reachable at {_REDIS_HOST}:{_REDIS_PORT}",
)
def test_negative_control_a_healthy_backend_really_round_trips(log_sink):
    """NEGATIVE CONTROL for the test above.

    "Logged zero errors" is also true of a backend that silently does nothing,
    so on the same live server we prove a real value crosses a process boundary:
    a SECOND Session on a SECOND handler resumes the id and finds it.

    ADR-0021: the id must be the one ``start()`` ISSUES. A well-formed id the
    store has never held is discarded (session fixation), so
    ``start("roundtrip-<hex>")`` mints a fresh id, writes under THAT, and the
    reader then resumes an id that was never written -- the round trip would be
    measured against the wrong key.
    """
    writer = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=60)
    sid = None
    try:
        log_sink.mark()
        session = Session(handler=writer, ttl=600)
        sid = session.start()
        session.set("user_id", 42)
        assert session.save() is True

        reader_handler = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=60)
        resumed = Session(handler=reader_handler, ttl=600)
        assert resumed.start(sid) == sid, "the stored id was not adopted on resume"
        assert resumed.get("user_id") == 42, "the value never reached Redis"
        reader_handler.close()

        assert log_sink.errors() == [], "a healthy round-trip must log no errors"
    finally:
        if sid is not None:
            writer.destroy(sid)
        writer.close()


def test_negative_control_uncontended_gc_logs_nothing(log_sink, tmp_path):
    """A real, writable FileSessionHandler: gc() must be silent on success.

    Without this, a change that made every gc() log an error would still pass
    the failure tests above.
    """
    handler = FileSessionHandler(path=str(tmp_path / "gc-sessions"))
    handler.write("gc-1", {"a": 1}, 60)
    log_sink.mark()
    Session(handler=handler).gc()
    assert log_sink.errors() == []


# ── strict opt-in: re-raise the REAL driver error ───────────────────────────


def test_strict_mode_reraises_the_real_driver_error_on_read(monkeypatch, unreachable_redis):
    """Locks in the calibration bug the double hid.

    The deleted test asserted ``pytest.raises(ConnectionError)`` -- the BUILTIN.
    redis-py raises ``redis.exceptions.ConnectionError``, which does NOT inherit
    from it, so that assertion was true only of the fake.
    """
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    session = Session(handler=unreachable_redis)

    with pytest.raises(Exception) as caught:
        session.start("sess-strict")

    assert type(caught.value).__module__.startswith("redis."), (
        f"expected the real redis driver error, got {type(caught.value)!r}"
    )
    assert not isinstance(caught.value, ConnectionError), (
        "regression guard: the real driver error is NOT the builtin ConnectionError, "
        "so any except/assert narrowed to the builtin silently stops matching"
    )
    assert "refused" in str(caught.value).lower()


def test_strict_mode_reraises_the_real_driver_error_on_write(monkeypatch, unreachable_redis):
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    session = Session(handler=unreachable_redis)
    # start() reads first, which raises under strict, so seed the state directly.
    session._session_id = "sess-strict-w"
    session.set("k", "v")

    with pytest.raises(Exception) as caught:
        session.save()

    assert type(caught.value).__module__.startswith("redis.")


@pytest.mark.skipif(
    not _reachable(_REDIS_HOST, _REDIS_PORT),
    reason=f"redis not reachable at {_REDIS_HOST}:{_REDIS_PORT}",
)
def test_negative_control_strict_mode_is_silent_on_a_healthy_backend(monkeypatch, log_sink):
    """NEGATIVE CONTROL: strict must not turn a WORKING backend into an error.

    Without this, "strict raises" would still pass for an implementation that
    raises unconditionally.
    """
    monkeypatch.setenv("TINA4_SESSION_STRICT", "true")
    handler = RedisSessionHandler(host=_REDIS_HOST, port=_REDIS_PORT, ttl=60)
    sid = f"strict-ok-{uuid.uuid4().hex}"
    try:
        log_sink.mark()
        session = Session(handler=handler, ttl=600)
        session.start(sid)          # must not raise
        session.set("ok", True)
        assert session.save() is True
        assert log_sink.errors() == []
    finally:
        handler.destroy(sid)
        handler.close()
