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

---------------------------------------------------------------------------
A PERMISSION TEST IN A SUITE THAT RUNS AS ROOT.

Case (3) asserts a real EACCES, and root holds CAP_DAC_OVERRIDE -- it writes
straight through a 0400 file, so ``chmod`` denies it nothing and no denial is
reachable. The test skipped ``[needs:no-dac-override]`` on every lab run: the
one environment where it most needed to run was the one place it never did.

It now stops being root for the length of the failing write (``os.seteuid`` to
an unprivileged account; the SAVED uid stays 0, so ``seteuid`` back in a
``finally`` restores it unconditionally -- a leaked euid would not fail here, it
would fail in some unrelated later test as a permission error nobody could trace
back). The kernel then enforces the bits for real and raises the genuine EACCES
the test exists to assert, rather than a substitute denial (EROFS from a
read-only mount, EPERM from an immutable file) with a different errno.

Two things that look like details and are not, both learned by getting them
wrong first:

  * EXACTLY ONE THING MAY BE DENIED, and it is the session file. Dropping the
    uid denies the LOGGER too -- ``Log.error`` could not open ``tina4.log``
    inside the framework's own ``except`` block, so the EACCES under test never
    got recorded. The log directory therefore lives in the same reachable root
    and is handed to the dropped uid.
  * IT MUST BE THE FILE'S BITS, NOT THE PATH TO IT. ``tmp_path`` lives under
    ``/tmp/pytest-of-root/pytest-N/``, whose parents are 0700 root-owned: a
    dropped uid cannot traverse there AT ALL, so every denial would be a
    directory-traversal EACCES and the test would pass for the wrong reason even
    while passing. The fixture root is its own 0755 ``mkdtemp``, and the two
    positive controls inside the same window prove reachability by measurement
    instead of assuming it.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import socket
import stat
import uuid
from pathlib import Path

try:                      # POSIX only -- the uid drop below is a POSIX mechanism
    import pwd
except ImportError:       # pragma: no cover - Windows
    pwd = None

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


def _point_the_real_logger_at(directory: Path, monkeypatch) -> _RealLogSink:
    """Send the REAL logger's output into ``directory``, and prove it lands there.

    TINA4_LOG_DIR is SET as well as passed, because ``Log.configure`` resolves the
    directory as ``os.environ.get("TINA4_LOG_DIR", log_dir)`` -- the env beats the
    explicit argument, so re-pointing the logger by argument alone leaves it
    writing to wherever the env still says.
    """
    from tina4_python.debug import Log

    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
    monkeypatch.setenv("TINA4_LOG_DIR", str(directory))
    monkeypatch.setenv("TINA4_LOG_FORMAT", "json")
    monkeypatch.setenv("TINA4_LOG_LEVEL", "debug")
    # An explicit TINA4_LOG_FILE would route the output through _StdlibFileWriter
    # to a path of its own choosing and the sink would read an empty file.
    monkeypatch.delenv("TINA4_LOG_FILE", raising=False)
    Log.configure(log_dir=str(directory), level="debug")

    sink = _RealLogSink(directory)
    # Driver sanity: the sink must be able to see a real record, otherwise every
    # "was logged" assertion below would be vacuous and every "logged nothing"
    # assertion would be trivially true.
    sink.mark()
    Log.error("sink-selftest")
    assert any("sink-selftest" in m for m in sink.errors()), (
        f"the real logger wrote nothing to {directory / 'tina4.log'} -- "
        "every log assertion in this file would be meaningless"
    )
    return sink


@pytest.fixture
def log_sink(tmp_path, monkeypatch):
    """Point the REAL logger at a real file, then put it back.

    The 3.14 logger-conformance refactor (tina4_python/debug/__init__.py)
    replaced the old per-attribute state (``_writer``/``_error_writer``/
    ``_stdout_enabled``/``_file_enabled``/``_format_mode``/``_level``/
    ``_is_production``) with one atomic ``_Snapshot`` object on
    ``Log._snapshot``. Saving/restoring that single reference is the
    equivalent save-and-restore against the shipped internals.
    """
    from tina4_python.debug import Log

    saved_snapshot = Log._snapshot

    yield _point_the_real_logger_at(tmp_path / "logs", monkeypatch)

    Log._snapshot = saved_snapshot


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


def _permission_bits_are_enforced() -> bool:
    """Can a write through a 0400 file actually be refused in this process?

    The guard here used to ask ``os.geteuid() == 0``, which is a PROXY for the
    property the test needs rather than the property itself. Root walks through
    the permission bits via CAP_DAC_OVERRIDE, not by being uid 0 -- a process can
    DROP that capability and stay root (``setpriv --bounding-set=-dac_override``),
    and then 0400 denies it like anyone else. The proxy answered "skip" for a
    process that could have run the test perfectly well, so on any host whose
    suite runs as root -- the lab, every time -- this never ran at all.

    Ask the kernel instead of inferring from the uid.
    """
    probe = tempfile.NamedTemporaryFile(delete=False)
    probe.write(b"x")
    probe.close()
    try:
        os.chmod(probe.name, 0o400)
        try:
            with open(probe.name, "a"):
                return False          # the write was allowed: bits do not bind
        except PermissionError:
            return True
    finally:
        os.chmod(probe.name, 0o600)   # a 0400 fixture must still be removable
        os.unlink(probe.name)


NO_DENIAL_REASON = (
    "[needs:no-dac-override] this process writes straight through a 0400 file "
    "(root holding CAP_DAC_OVERRIDE) AND cannot drop the effective uid to an "
    "unprivileged account (no os.seteuid, or no unprivileged account exists), so "
    "no real denial can be produced here"
)


def _current_euid() -> int:
    """This process's effective uid, or -1 where the platform has no such thing."""
    return os.geteuid() if hasattr(os, "geteuid") else -1


def _droppable_unprivileged_uid() -> int | None:
    """A uid we can drop the EFFECTIVE uid to and come back from, or None.

    Only the effective uid moves. The REAL and SAVED uids stay 0, which is what
    makes the drop reversible -- ``seteuid(0)`` is permitted afterwards precisely
    because 0 is still the saved uid.
    """
    if pwd is None or not hasattr(os, "seteuid") or _current_euid() != 0:
        return None
    for account in ("nobody", "nfsnobody", "daemon"):
        try:
            return pwd.getpwnam(account).pw_uid
        except KeyError:
            continue
    return None


def _uid_the_denied_write_runs_as() -> int:
    """Which uid must be refused, and skip ONLY if no uid can be refused at all.

    Unprivileged already: our own -- the bits bind, nothing to do. Root: an
    account we drop to, because root is exempt from the bits it is setting.
    """
    if _permission_bits_are_enforced():
        return _current_euid()
    dropped = _droppable_unprivileged_uid()
    if dropped is None:
        pytest.skip(NO_DENIAL_REASON)
    return dropped


@contextlib.contextmanager
def _running_as(uid: int):
    """Run the block with the kernel enforcing permission bits against ``uid``.

    Process-wide for its duration (glibc propagates a setxid across every thread,
    as POSIX requires), so keep the block down to the operations under test.
    """
    if uid == _current_euid():
        yield                       # already unprivileged: the bits already bind
        return
    restore = _current_euid()
    os.seteuid(uid)
    try:
        yield
    finally:
        # UNCONDITIONAL. A leaked dropped euid does not fail here -- it fails in
        # some unrelated later test, looking like anything except this.
        os.seteuid(restore)


def _hand_directory_to(directory: Path, uid: int) -> None:
    """Give ``uid`` ownership of ``directory`` and everything already in it."""
    if uid == _current_euid():
        return                      # it is already ours
    os.chown(directory, uid, -1)
    for child in directory.iterdir():
        os.chown(child, uid, -1)


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


def test_write_fails_after_a_successful_start_with_a_real_eacces(log_sink, monkeypatch):
    """The mid-request death case, produced rather than simulated.

    A REAL FileSessionHandler writes successfully, then the real session FILE is
    made read-only so the NEXT write takes a real EACCES from the real kernel --
    with the process actually subject to the bits for the length of that write
    (see "A PERMISSION TEST IN A SUITE THAT RUNS AS ROOT" in the module
    docstring; ``log_sink`` is taken for its save/restore of the logger, then
    re-pointed below because its directory is deliberately unreachable).
    """
    denied_uid = _uid_the_denied_write_runs_as()

    # NOT tmp_path: its parents are 0700 root-owned, so an unprivileged uid is
    # refused at the traversal and never reaches the file whose bits are the
    # subject of the test. 0755 mkdtemp, walkable by anyone.
    reachable_root = Path(tempfile.mkdtemp(prefix="tina4-eacces-"))
    try:
        os.chmod(reachable_root, 0o755)
        # The logger must keep working while the session write is refused:
        # exactly one thing is under denial here, and it is not the audit trail.
        sink = _point_the_real_logger_at(reachable_root / "logs", monkeypatch)
        _hand_directory_to(reachable_root / "logs", denied_uid)

        sessions = reachable_root / "sessions"
        handler = FileSessionHandler(path=str(sessions))
        session = Session(handler=handler)
        sid = session.start("sess-eacces")
        session.set("stage", "one")
        assert session.save() is True, "the first write must genuinely succeed"

        session_file = handler._file(sid)
        assert session_file.exists(), "start()+save() must have created a real file"

        # The DIRECTORY is handed over whole, so nothing but the file's own bits
        # is left to do the denying -- and the file goes over with it, so the
        # denial is the OWNER's read-only bit ("mine, and read-only"), not the
        # weaker "someone else's".
        _hand_directory_to(sessions, denied_uid)
        session_file.chmod(stat.S_IRUSR)  # 0400 -- read-only, on the FILE not the dir

        session.set("stage", "two")
        sink.mark()
        traversal_control = sessions / "the-directory-is-writable.txt"
        with _running_as(denied_uid):
            # POSITIVE CONTROLS, in the same window as the failure: this uid can
            # CREATE a file in that directory, and can READ the session file
            # itself. Path reachable, file reachable -- so the only thing left to
            # refuse the write is the write bit on that one file.
            traversal_control.write_text("reachable", encoding="utf-8")
            session_file.read_text(encoding="utf-8")
            persisted = session.save()

        assert persisted is False, "a real EACCES must be reported, not swallowed"
        assert session._dirty is True, "dirty flag must be retained so a later save retries"
        assert traversal_control.read_text(encoding="utf-8") == "reachable", (
            "the denied uid could not even write this directory, so the failure "
            "below would be an unreachable path rather than the session file"
        )

        errors = sink.errors()
        assert any("write" in e and "failed" in e for e in errors)
        assert any("FileSessionHandler" in e for e in errors)
        # errno, not wording: strerror is localised, [Errno 13] is not.
        eacces = [e for e in errors if "errno 13" in e.lower()]
        assert eacces, f"the logged cause must be the real EACCES. Got: {errors}"
        assert all(str(session_file) in e for e in eacces), (
            "the EACCES must name the SESSION FILE. Any other path means the "
            f"kernel refused a directory traversal, not the file's own bits. "
            f"Got: {eacces}"
        )
    finally:
        shutil.rmtree(reachable_root, ignore_errors=True)


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
