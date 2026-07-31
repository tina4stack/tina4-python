"""Graceful shutdown — the signal contract, pinned on a REAL server process.

Feature 9's contract (identical in Python, PHP, Ruby and Node):

  1. SIGTERM and SIGINT are trapped and run the SAME graceful shutdown.
  2. SIGHUP is deliberately NOT trapped — the Rust CLI owns file watching and
     production logs go to stdout, so neither Puma's log-reopen nor gunicorn's
     config-reload use for SIGHUP is a Tina4 need. This file pins the
     non-handling so nobody "fixes" it by accident.
  3. The listening socket stops accepting FIRST. A connection that arrives after
     the signal gets a clean CONNECTION REFUSED — not a 503, not a TCP reset.
  4. In-flight requests drain: a request already being handled runs to
     completion and its full response is written.
  5. The drain is bounded by TINA4_SHUTDOWN_TIMEOUT (default 30s). On timeout
     the server warns and forces the rest closed rather than hanging forever.
  6. Background tasks are stopped and DB connections closed before exit.
  7. Live WebSockets get RFC 6455 close code 1001 ("going away").
  8. Exit code 0 on a clean drained shutdown.

NO MOCKS anywhere. Every case spawns a REAL child server, drives a REAL socket,
sends a REAL signal to that process, and reads the REAL outcome and exit status.
Calling the handler function directly would prove nothing about signal delivery.

Process hygiene: every child is booted into its OWN session (pgid == pid) with
its output on a FILE, and every test kills the whole process GROUP in a finally.
A pipe nobody drains wedges a piped test run; a child left in the runner's group
means a stray killpg would take pytest with it.
"""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from conftest import boot_child_server, read_child_log

# A request slow enough that a signal always lands mid-flight, but short enough
# that the whole file stays quick. The drain therefore takes ~SLOW_SECONDS minus
# SIGNAL_AFTER_SECONDS.
SLOW_SECONDS = 2.0
SIGNAL_AFTER_SECONDS = 0.6

# The bounded-drain case needs a handler that outlives the bound by a wide
# margin, so "it exited early" cannot be luck.
VERY_SLOW_SECONDS = 5.0


# ── the child application under test ──────────────────────────────────────

def _app_source(port: int, *, background_task: bool = False,
                websocket_route: bool = False, database: str = "") -> str:
    """Source for a real Tina4 app exposing the routes each case needs.

    /slow      — takes SLOW_SECONDS, then answers 200 "drained"
    /very-slow — takes VERY_SLOW_SECONDS (only the timeout case uses it)
    /ping      — answers immediately, proves the server is up

    asyncio.sleep is not signal-interruptible, so unlike PHP's usleep and Ruby's
    sleep it cannot return early on EINTR and fake a drain that never happened.
    """
    lines = [
        "import asyncio",
        "from tina4_python import get",
        "from tina4_python.core.server import start",
        "",
        "@get('/ping')",
        "async def ping(request, response):",
        "    return response('pong')",
        "",
        "@get('/slow')",
        "async def slow(request, response):",
        f"    await asyncio.sleep({SLOW_SECONDS})",
        "    return response('drained')",
        "",
        "@get('/very-slow')",
        "async def very_slow(request, response):",
        f"    await asyncio.sleep({VERY_SLOW_SECONDS})",
        "    return response('drained')",
        "",
    ]
    if database:
        lines += [
            "from tina4_python.database import Database",
            "from tina4_python.orm import bind_database",
            f"_db = Database({database!r})",
            "bind_database(_db)",
            "_db.execute('CREATE TABLE IF NOT EXISTS shutdown_probe (id INTEGER)')",
            "",
        ]
    if background_task:
        # A SYNC callback is the harder case: it runs on the server's
        # ThreadPoolExecutor, whose worker threads are non-daemon and are joined
        # at interpreter exit. If shutdown left it ticking, the process hangs.
        lines += [
            "import time as _time",
            "from tina4_python.core.server import background",
            "def _tick():",
            "    _time.sleep(0.05)",
            "background(_tick, interval=0.2)",
            "",
        ]
    if websocket_route:
        lines += [
            "from tina4_python.core.router import websocket",
            "@websocket('/ws/probe')",
            "async def probe(connection, event, data):",
            "    pass",
            "",
        ]
    lines.append(f"start(port={port}, no_browser=True, no_reload=True)")
    return "\n".join(lines) + "\n"


def _boot(tmp_path: Path, *, extra_env=None, **app_options):
    """Start a REAL child server in its own process group, output on a file.

    TINA4_DEBUG=true pins the child to Tina4's OWN built-in asyncio server. With
    debug off, ``run()`` hands the socket to whichever production ASGI server
    happens to be importable (uvicorn > hypercorn > granian), and that server —
    not Tina4 — owns the shutdown. Leaving it unset would make these tests
    silently measure uvicorn on a machine that has it and Tina4 on one that does
    not; both the assertions and the code under test would change with the venv.
    """
    env = {"TINA4_DEBUG": "true"}
    if extra_env:
        env.update(extra_env)

    def write_app(proj: Path, port: int) -> None:
        (proj / "app.py").write_text(_app_source(port, **app_options))

    return boot_child_server(
        tmp_path, write_app,
        extra_env=env,
        log_dir=tmp_path / "logs",
        new_session=True,
        # The drain bound is under test — never let the outer environment set it.
        unset_env=("TINA4_SHUTDOWN_TIMEOUT",),
    )


def _reap(proc):
    """Kill the whole process GROUP. Safe because the child is a group leader."""
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


# ── real socket helpers ───────────────────────────────────────────────────

def _begin_request(port: int, path: str, timeout: float = 30.0) -> socket.socket:
    """Send a real HTTP request and return the socket WITHOUT reading the reply,
    so the caller can signal the server while the handler is still running."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode()
    )
    return sock


def _read_all(sock: socket.socket) -> bytes:
    """Drain the connection to EOF."""
    chunks = []
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        pass
    finally:
        sock.close()
    return b"".join(chunks)


def _wait_for_exit(proc, timeout: float = 30.0) -> float:
    """Block until the child exits; return how long it took."""
    started = time.monotonic()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AssertionError(
            f"server never exited in the {timeout:g}s after the signal — shutdown hung"
        ) from None
    return time.monotonic() - started


def _connect_refused(port: int, budget: float):
    """Hammer the port until it refuses or *budget* seconds run out. Returns
    (error_or_None, seconds_waited)."""
    started = time.monotonic()
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                pass
        except OSError as exc:
            return exc, time.monotonic() - started
        waited = time.monotonic() - started
        if waited >= budget:
            return None, waited
        time.sleep(0.02)


# ── the shared contract cases ─────────────────────────────────────────────

def test_sigterm_lets_the_in_flight_request_finish(tmp_path):
    """SIGTERM lets the in-flight request finish"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        sock = _begin_request(port, "/slow")
        time.sleep(SIGNAL_AFTER_SECONDS)
        os.kill(proc.pid, signal.SIGTERM)

        raw = _read_all(sock).decode(errors="replace")
        assert raw.startswith("HTTP/1.1 200"), f"in-flight request was cut short: {raw!r}"
        assert raw.rstrip().endswith("drained"), f"response body truncated: {raw!r}"
        assert proc.wait(timeout=15) == 0
    finally:
        _reap(proc)


def test_sigterm_stops_accepting_new_connections(tmp_path):
    """SIGTERM stops accepting new connections"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        # Hold a request open so the process is still alive (draining) while we
        # probe the listener — otherwise "refused" could just mean "exited".
        sock = _begin_request(port, "/slow")
        time.sleep(SIGNAL_AFTER_SECONDS)
        os.kill(proc.pid, signal.SIGTERM)

        # The listener must close FIRST, not at the END of the drain. Budget
        # half the remaining drain: closing first takes milliseconds, closing
        # last takes the whole 1.4s, so the two outcomes are never confusable.
        drain_remaining = SLOW_SECONDS - SIGNAL_AFTER_SECONDS
        refusal, waited = _connect_refused(port, budget=drain_remaining / 2)
        assert proc.poll() is None, (
            "server exited before the drain finished — this case has to probe a "
            "server that is still draining, or 'refused' just means 'gone'"
        )
        assert refusal is not None, (
            f"listener was still accepting {waited:.2f}s after SIGTERM, with "
            f"{drain_remaining:.1f}s of drain still to run — it must stop "
            f"accepting FIRST, before draining"
        )
        assert isinstance(refusal, ConnectionRefusedError), (
            f"a post-signal connection must get a clean CONNECTION REFUSED, "
            f"not {type(refusal).__name__}: {refusal}"
        )
        # And the request that was already in flight still completed.
        assert b"drained" in _read_all(sock)
        assert proc.wait(timeout=15) == 0
    finally:
        _reap(proc)


def test_sigterm_exits_with_code_0(tmp_path):
    """SIGTERM exits with code 0"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        os.kill(proc.pid, signal.SIGTERM)
        _wait_for_exit(proc, timeout=15)
        assert proc.returncode == 0, (
            f"a handled SIGTERM must halt 0 (gunicorn and Puma both do); "
            f"got {proc.returncode}"
        )
    finally:
        _reap(proc)


def _try_listen(port: int) -> OSError | None:
    """Try to become the listener on *port* exactly the way a restarting Tina4
    server would: the same 0.0.0.0 wildcard (see resolve_config's default_host)
    with SO_REUSEADDR. Returns the OSError on failure, None on success.

    Both details matter. SO_REUSEADDR keeps a TIME_WAIT connection this test
    left behind from reading as a leaked listener, while still being refused by
    a socket that is genuinely still listening. Binding 127.0.0.1 instead of the
    wildcard would succeed even against the live server and prove nothing.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("0.0.0.0", port))
        listener.listen(1)
        return None
    except OSError as exc:
        return exc
    finally:
        listener.close()


def test_sigterm_releases_the_listening_port(tmp_path):
    """SIGTERM releases the listening port"""
    proc = None
    try:
        proc, port = _boot(tmp_path)

        # Prove the check can fail: while the server holds the port, this bind
        # must be refused. Without this the success below could mean anything.
        assert _try_listen(port) is not None, (
            f"port {port} was bindable while the server was still listening — "
            f"this test cannot detect a leaked socket"
        )

        sock = _begin_request(port, "/slow")
        time.sleep(SIGNAL_AFTER_SECONDS)
        os.kill(proc.pid, signal.SIGTERM)
        _read_all(sock)
        _wait_for_exit(proc, timeout=15)

        failure = _try_listen(port)
        assert failure is None, f"port {port} was not released after shutdown: {failure}"
    finally:
        _reap(proc)


def test_sigint_lets_the_in_flight_request_finish(tmp_path):
    """SIGINT lets the in-flight request finish"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        sock = _begin_request(port, "/slow")
        time.sleep(SIGNAL_AFTER_SECONDS)
        os.kill(proc.pid, signal.SIGINT)

        raw = _read_all(sock).decode(errors="replace")
        assert raw.startswith("HTTP/1.1 200"), f"in-flight request was cut short: {raw!r}"
        assert raw.rstrip().endswith("drained"), f"response body truncated: {raw!r}"
    finally:
        _reap(proc)


def test_sigint_exits_with_code_0(tmp_path):
    """SIGINT exits with code 0"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        os.kill(proc.pid, signal.SIGINT)
        _wait_for_exit(proc, timeout=15)
        assert proc.returncode == 0, (
            f"SIGINT must run the SAME graceful shutdown as SIGTERM and halt 0, "
            f"not surface as a KeyboardInterrupt traceback; got {proc.returncode}\n"
            f"{read_child_log(proc)}"
        )
    finally:
        _reap(proc)


def test_sighup_is_not_trapped_and_terminates_the_process(tmp_path):
    """SIGHUP is not trapped and terminates the process"""
    proc = None
    try:
        proc, port = _boot(tmp_path)
        os.kill(proc.pid, signal.SIGHUP)
        _wait_for_exit(proc, timeout=15)

        # Popen reports -N when a child was killed BY signal N. A clean 0 here
        # would mean somebody quietly started trapping SIGHUP.
        assert proc.returncode == -signal.SIGHUP, (
            f"SIGHUP is deliberately NOT trapped: the process must die BY the "
            f"signal (returncode {-signal.SIGHUP}), got {proc.returncode}"
        )
    finally:
        _reap(proc)


def test_a_registered_background_task_does_not_block_shutdown(tmp_path):
    """a registered background task does not block shutdown"""
    proc = None
    try:
        proc, port = _boot(tmp_path, background_task=True)
        # Let the task tick at least twice so it is genuinely running.
        time.sleep(0.6)
        os.kill(proc.pid, signal.SIGTERM)
        elapsed = _wait_for_exit(proc, timeout=15)

        assert proc.returncode == 0, (
            f"a ticking background task must not change the exit status; "
            f"got {proc.returncode}\n{read_child_log(proc)}"
        )
        assert elapsed < 10.0, (
            f"shutdown took {elapsed:.2f}s with a background task registered — "
            f"the task is holding the process open"
        )
    finally:
        _reap(proc)


def test_tina4_shutdown_timeout_bounds_the_drain(tmp_path):
    """TINA4_SHUTDOWN_TIMEOUT bounds the drain"""
    proc = None
    try:
        proc, port = _boot(tmp_path, extra_env={"TINA4_SHUTDOWN_TIMEOUT": "1"})
        sock = _begin_request(port, "/very-slow")
        time.sleep(SIGNAL_AFTER_SECONDS)
        os.kill(proc.pid, signal.SIGTERM)

        elapsed = _wait_for_exit(proc, timeout=VERY_SLOW_SECONDS + 10.0)
        _read_all(sock)  # the in-flight request IS cut short — that is the point

        assert elapsed < VERY_SLOW_SECONDS - 1.0, (
            f"TINA4_SHUTDOWN_TIMEOUT=1 must bound the drain, but shutdown took "
            f"{elapsed:.2f}s against a {VERY_SLOW_SECONDS}s handler — the bound "
            f"is decorative"
        )
        assert proc.returncode == 0, (
            f"a bounded shutdown still exits 0; got {proc.returncode}"
        )
        log = read_child_log(proc)
        assert "TINA4_SHUTDOWN_TIMEOUT" in log, (
            f"the forced close must log a warning naming the timeout; log was:\n{log}"
        )
    finally:
        _reap(proc)


# ── the two contract clauses with no shared case name (Python-scoped) ──────
#
# Clauses 6 (close DB connections) and 7 (RFC 6455 close code 1001) are part of
# the agreed contract but the shared case-name list does not cover them, so they
# are pinned here rather than left unproven.

def test_live_websockets_get_close_code_1001(tmp_path):
    """A live WebSocket is told 'going away' (RFC 6455 1001) before the socket dies."""
    proc = None
    try:
        proc, port = _boot(tmp_path, websocket_route=True)

        # Real RFC 6455 handshake over a real socket.
        import base64
        key = base64.b64encode(os.urandom(16)).decode()
        sock = socket.create_connection(("127.0.0.1", port), timeout=20)
        sock.sendall(
            f"GET /ws/probe HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        handshake = sock.recv(4096)
        assert b"101 Switching Protocols" in handshake, handshake

        os.kill(proc.pid, signal.SIGTERM)
        frame = _read_all(sock)

        assert len(frame) >= 4, f"no close frame arrived, got {frame!r}"
        assert frame[0] & 0x0F == 0x8, f"expected an RFC 6455 close frame, got {frame!r}"
        payload_length = frame[1] & 0x7F
        assert payload_length >= 2, f"close frame carried no status code: {frame!r}"
        code = int.from_bytes(frame[2:4], "big")
        assert code == 1001, (
            f"a shutting-down server must send close code 1001 (going away), got {code}"
        )
        assert proc.wait(timeout=15) == 0
    finally:
        _reap(proc)


def test_shutdown_closes_bound_databases_on_a_real_server(tmp_path):
    """A real shutting-down server closes the database it bound at boot."""
    proc = None
    try:
        db_path = tmp_path / "app.db"
        proc, port = _boot(tmp_path, database=f"sqlite:///{db_path}")
        os.kill(proc.pid, signal.SIGTERM)
        _wait_for_exit(proc, timeout=15)

        log = read_child_log(proc)
        assert "Database connections closed" in log, (
            f"shutdown must close the bound database (Ruby's Tina4::Shutdown "
            f"already does); log was:\n{log}"
        )
        assert proc.returncode == 0
    finally:
        _reap(proc)


def test_close_bound_databases_really_closes_them(tmp_path):
    """_close_bound_databases() shuts real SQLite connections, default and named."""
    import sqlite3

    from tina4_python.core.server import _close_bound_databases
    from tina4_python.database import Database
    from tina4_python.orm import model as orm_model

    default_path = tmp_path / "default.db"
    named_path = tmp_path / "analytics.db"
    saved_default, saved_named = orm_model._database, dict(orm_model._databases)
    try:
        default_db = Database(f"sqlite:///{default_path}")
        named_db = Database(f"sqlite:///{named_path}")
        orm_model._database = default_db
        orm_model._databases = {"analytics": named_db}

        # Real work on a real file, so a real connection is genuinely open, and
        # keep the real sqlite3.Connection so we can prove it was CLOSED rather
        # than merely dropped from the adapter.
        real_connections = []
        for db in (default_db, named_db):
            db.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER)")
            db.execute("INSERT INTO probe (id) VALUES (1)")
            db.commit()
            assert db.fetch_one("SELECT count(*) AS n FROM probe")["n"] == 1
            real_connections.append(db._adapter._conn)
            real_connections[-1].execute("SELECT 1")  # positive: it works now

        assert _close_bound_databases() == 2

        # Negative side: the REAL driver connections are genuinely shut.
        for conn in real_connections:
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

        # A second pass is harmless — shutdown must never fail on a closed handle.
        _close_bound_databases()
    finally:
        orm_model._database, orm_model._databases = saved_default, saved_named


def test_invalid_shutdown_timeout_falls_back_to_30_seconds(monkeypatch):
    """An unusable TINA4_SHUTDOWN_TIMEOUT warns and uses 30s, never a silent 0."""
    from tina4_python.core.server import DEFAULT_SHUTDOWN_TIMEOUT, _resolve_shutdown_timeout

    monkeypatch.delenv("TINA4_SHUTDOWN_TIMEOUT", raising=False)
    assert _resolve_shutdown_timeout() == DEFAULT_SHUTDOWN_TIMEOUT == 30.0

    monkeypatch.setenv("TINA4_SHUTDOWN_TIMEOUT", "5")
    assert _resolve_shutdown_timeout() == 5.0

    for bad in ("0", "-1", "abc", "  ", "None"):
        monkeypatch.setenv("TINA4_SHUTDOWN_TIMEOUT", bad)
        assert _resolve_shutdown_timeout() == DEFAULT_SHUTDOWN_TIMEOUT, (
            f"TINA4_SHUTDOWN_TIMEOUT={bad!r} must fall back to 30s, never 0"
        )
