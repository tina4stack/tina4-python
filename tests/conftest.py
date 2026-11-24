# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tina4 v3 test configuration

import os
import re as _re
import sys
from pathlib import Path

import pytest

# ── Pin every process to THIS checkout ─────────────────────────────────────
#
# The venv's editable install is one .pth line that points at ONE checkout.
# Run the suite from any other checkout (a git worktree, a lab copy) and any
# process whose sys.path misses this repo imports tina4_python from THAT
# checkout instead: the test then passes or fails on code that is not under
# test. MEASURED 2026-09-24 from a worktree: test_response_binary_body's child
# served the other checkout's /bin/send as text/html, and the `pytest` console
# script (not `python -m pytest`) imported the other checkout in-process too.
#
# 1. The pytest process: this repo goes first on sys.path.
# 2. Every Python child: PYTHONPATH starts with this repo plus tests/_child_guard,
#    whose sitecustomize.py aborts a child that still resolves another copy.
#    Children inherit it through os.environ; a test that must REPLACE
#    PYTHONPATH builds it with child_pythonpath() so the pin survives.
REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD_GUARD_DIR = REPO_ROOT / "tests" / "_child_guard"
_OUTER_PYTHONPATH = os.environ.get("PYTHONPATH", "")


def child_pythonpath(*front) -> str:
    """PYTHONPATH for a Python child: ``front`` entries, this repo, the guard."""
    entries = [str(entry) for entry in front] + [str(REPO_ROOT), str(CHILD_GUARD_DIR)]
    return os.pathsep.join(entries + ([_OUTER_PYTHONPATH] if _OUTER_PYTHONPATH else []))


if sys.path[:1] != [str(REPO_ROOT)]:
    sys.path.insert(0, str(REPO_ROOT))
os.environ["PYTHONPATH"] = child_pythonpath()

_loaded_tina4 = sys.modules.get("tina4_python")
if _loaded_tina4 is not None and not os.path.realpath(_loaded_tina4.__file__).startswith(
        os.path.realpath(REPO_ROOT) + os.sep):
    pytest.exit(f"pytest already imported tina4_python from {_loaded_tina4.__file__}, "
                f"not the checkout under test {REPO_ROOT}", returncode=4)

# No test may open a browser tab on the machine running the suite. Set before
# any test or child server reads it; a test that needs the browser path removes
# it from its own child's environment explicitly.
os.environ.setdefault("TINA4_NO_BROWSER", "true")


# ── The TINA4_REQUIRE_SERVICES gate (ADR-0069 addendum F) ────────────────
#
# With TINA4_REQUIRE_SERVICES set, a SKIP passes only when its reason carries a
# machine-readable ``[needs:X]`` tag AND X is excusable in this run:
#
#   - X is an OPTIONAL engine: excused only while that engine's coordinate env
#     var is unset. A run that never promised the engine stays green; a run
#     that set the coordinate (the lab sets all of them) fails if it skips.
#   - X is an ALWAYS-provisioned service: never excused.
#   - Any other X is a platform exclusion (os=..., runtime=..., absent-ext=...,
#     no-dac-override): always excused.
#   - No tag at all: fails.
#
# The same rule and the same tag names are used by all four frameworks. It
# replaced a phrase matcher (service keywords x "not reachable" / "refused"),
# under which any skip worded outside those lists - "no reachable", "...
# unavailable", Firebird, the graph engines - skipped green: a ghost test.
# Collection-time skips (``allow_module_level=True``) are gated too; they become
# collection errors. tests/test_require_services_gate.py runs a real pytest
# against this file.

# TINA4_TEST_POSTGRES_URL (a lab-only alias) is deliberately absent: the
# env-contract gate (tests/test_env_contract.py) rejects it in Python.
_OPTIONAL_ENGINE_COORDINATES = {
    "firebird": "TINA4_TEST_FIREBIRD_URL",
    "postgres": "TINA4_TEST_PG_URL",
    "postgis": "TINA4_TEST_POSTGIS_URL",
    "mysql": "TINA4_TEST_MYSQL_URL",
    "mssql": "TINA4_TEST_MSSQL_URL",
    "swoole": "TINA4_TEST_SWOOLE",
    "oidc": "TINA4_TEST_OIDC_ISSUER",
    "neo4j": "TINA4_TEST_NEO4J_URL",
    "memgraph": "TINA4_TEST_MEMGRAPH_URL",
    "arango": "TINA4_TEST_ARANGO_URL",
    "ultipa": "TINA4_TEST_ULTIPA_URL",
}
_ALWAYS_PROVISIONED = frozenset({
    "mongo", "redis", "valkey", "memcached", "rabbitmq", "kafka", "mqtt", "smtp", "imap", "s3",
})
_NEEDS_TAG = _re.compile(r"\[needs:([^\]\s]+)\]")


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _require_services():
    return _truthy(os.environ.get("TINA4_REQUIRE_SERVICES"))


def _skip_reason(report):
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr or "")


def _tag_is_excused(tag, environ):
    if tag in _ALWAYS_PROVISIONED:
        return False
    coordinate = _OPTIONAL_ENGINE_COORDINATES.get(tag)
    if coordinate is not None:
        return not (environ.get(coordinate) or "").strip()
    return True


def _skip_is_excused(reason, environ=None):
    """True when every [needs:X] tag in the reason is excusable in this run."""
    environ = os.environ if environ is None else environ
    tags = _NEEDS_TAG.findall(reason or "")
    return bool(tags) and all(_tag_is_excused(tag, environ) for tag in tags)


def _fail_untagged_skip(report):
    """Turn a skip that is not excused into a failure when services are required."""
    if not _require_services() or not report.skipped or hasattr(report, "wasxfail"):
        return
    reason = _skip_reason(report)
    if _skip_is_excused(reason):
        return
    report.outcome = "failed"
    report.longrepr = (
        "TINA4_REQUIRE_SERVICES is set, and this skip is not excused:\n  "
        + reason.strip()
        + "\nAn untagged skip, an always-provisioned service ([needs:mongo], ...) "
        "and an optional engine whose coordinate env var IS set all fail. "
        "Provision the service, or tag a genuine platform exclusion [needs:os=...]."
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    _fail_untagged_skip(outcome.get_result())


def pytest_configure(config):
    # An untagged module-level skip becomes a collection error. Keep collecting
    # and running everything else, so one missing service reports as one
    # error instead of aborting the whole suite.
    if _require_services():
        config.option.continue_on_collection_errors = True


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    _fail_untagged_skip(outcome.get_result())


# ── Log state isolation (every test gets a clean, unconfigured logger) ────
#
# tina4_python.debug.Log is a process-wide singleton: Log.configure() sets ONE
# class-level _snapshot object, and it stays whatever the last caller in the
# SAME pytest process left it as -- Log.reset() is the only thing that clears
# it. A per-FILE gate only ever runs its own tests, so a test that calls
# Log.configure(level="error"/"warning") and never restores it is invisible
# there; in the FULL suite, whatever test happens to run next inherits that
# leftover level/format/output and can fail for a reason that has nothing to
# do with its own assertions -- a shared-state leak, not a real regression in
# whatever test trips over it. Resetting before AND after every test (the same
# pattern test_log_contract.py / test_logger_fixture_contract.py already use
# locally) makes each test's Log configuration self-contained: the next use
# anywhere just resolves a fresh snapshot from whatever the environment says
# at that moment, exactly like a freshly-imported process would see.
@pytest.fixture(autouse=True)
def _tina4_log_state_isolation():
    from tina4_python.debug import Log
    Log.reset()
    yield
    Log.reset()


# ── A usable signing secret for every test (ADR-0079 s2) ──────────────────
#
# Auth refuses to sign with a blank or short TINA4_SECRET, and a server refuses
# to boot outside dev without one. Several suites set the secret once at import
# time; any earlier test that removes it then left them signing with the blank
# key, which USED to "work" (and forge-ably so). Each test now starts with a
# 32+ byte secret unless it already has one, and so does every child server it
# spawns from os.environ. A test that needs a blank secret removes it itself.
_TEST_SECRET = "tina4-python-test-suite-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _tina4_test_secret(monkeypatch):
    if len(os.environ.get("TINA4_SECRET", "").encode()) < 32:
        monkeypatch.setenv("TINA4_SECRET", _TEST_SECRET)
    yield


# ── Real child-server boot (shared by every test that spawns one) ─────────
#
# Four test files each carried their own copy of this, and each copy had the
# same race: _free_port() binds port 0, reads the number, CLOSES the socket, and
# only then does the child bind it. Anything on the machine can take the port in
# that gap, and a full suite boots a lot of servers. The child then dies with
# "address already in use" and the assertion said only "child server never bound
# the port" - the captured output was thrown away, so a lost race and a genuine
# server crash looked identical.
#
# boot_child_server() retries ONLY the lost race, which it identifies from the
# child's own output. Every other failure stops immediately and reports what the
# child printed, so a real bug still fails fast and legibly.

import signal as _signal
import socket as _socket
import subprocess as _subprocess
import sys as _sys
import time as _time


def _reset_inherited_signal_dispositions():  # pragma: no cover - runs in the child
    """Restore SIGHUP/SIGINT/SIGQUIT to SIG_DFL in a spawned test server.

    SIG_IGN is inherited across fork AND preserved across exec, so a child
    inherits whatever the harness that launched pytest was given. The lab
    runner starts the suite with `setsid nohup`, and nohup sets SIGHUP,
    SIGINT and SIGQUIT to SIG_IGN - measured on the running suite process:

        SigIgn: 0000000000000007      (bits 0,1,2 = HUP, INT, QUIT)

    A test that asserts a signal's DEFAULT disposition therefore proves
    nothing under that harness: `test_sighup_is_not_trapped_and_terminates_
    the_process` sent SIGHUP to a child that had inherited SIG_IGN, nothing
    happened, and the run failed on Linux while passing on macOS - where the
    suite is not run under nohup.

    Only SIGHUP was affected in practice: the framework TRAPS SIGINT, so
    those cases never depended on the inherited default. That is exactly why
    one test broke and the neighbouring ones did not, which made it look like
    a Linux behaviour difference in the framework rather than a harness
    artifact.

    Resetting here means the child always starts from the documented default,
    whatever launched the suite. POSIX-only; Windows has no SIGHUP/SIGQUIT and
    preexec_fn is not supported there, so spawn_kwargs() leaves it out.
    """
    for name in ("SIGHUP", "SIGINT", "SIGQUIT"):
        sig = getattr(_signal, name, None)
        if sig is not None:
            try:
                _signal.signal(sig, _signal.SIG_DFL)
            except (OSError, ValueError):
                pass


IS_WINDOWS = _sys.platform == "win32"


def spawn_kwargs(new_session: bool = False) -> dict:
    """Popen kwargs for a test child, portable across POSIX and Windows.

    POSIX: the child resets the signal dispositions it inherited (see
    _reset_inherited_signal_dispositions) and, with new_session, becomes the
    leader of its own session/process group (pgid == pid), so a test can signal
    the whole group without reaching the pytest runner.

    Windows: preexec_fn and sessions do not exist (Popen raises "preexec_fn is
    not supported on Windows platforms"). The equivalent of a new session is a
    new console process GROUP: CTRL_BREAK_EVENT can then be sent to the child
    alone (send_graceful_shutdown) and kill_process_tree() reaps it.
    """
    if IS_WINDOWS:
        return {"creationflags": _subprocess.CREATE_NEW_PROCESS_GROUP} if new_session else {}
    return {"start_new_session": new_session,
            "preexec_fn": _reset_inherited_signal_dispositions}


def send_graceful_shutdown(proc) -> None:
    """Ask a child server to shut down the way an operator would.

    POSIX: SIGTERM to the child's process group (boot with new_session=True).
    Windows: CTRL_BREAK_EVENT to the child's console process group, the signal
    a Windows service manager or console sends; SIGTERM cannot be delivered to
    another process there (os.kill(pid, SIGTERM) is TerminateProcess).
    """
    if IS_WINDOWS:
        proc.send_signal(_signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(proc.pid, _signal.SIGTERM)


def kill_process_tree(proc) -> None:
    """Hard-kill a child and everything it started; never raises, then reaps.

    POSIX: SIGKILL to the process group (the child must be a group leader).
    Windows: taskkill /T /F walks the child's process tree.
    """
    if proc is None:
        return
    try:
        if IS_WINDOWS:
            if proc.poll() is None:
                _subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
                                check=False)
                if proc.poll() is None:
                    proc.kill()
        else:
            os.killpg(proc.pid, _signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


_ADDR_IN_USE = ("address already in use", "address in use", "eaddrinuse",
                "errno 48", "errno 98", "oserror: [errno 48]", "oserror: [errno 98]")


def process_rss_mb(pid: int, include_children: bool = False) -> float:
    """Resident memory of a live process, in MB, read from the OS.

    POSIX: ``ps`` RSS (with include_children, the process plus its direct
    children). Windows has no ``ps`` that reports RSS, so the same measurement
    comes from the kernel's working-set size (K32GetProcessMemoryInfo); a Tina4
    test server there is a single process, so there are no children to add.
    Returns 0.0 when the process cannot be read, which callers assert against.
    """
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        query_limited_information = 0x1000
        handle = kernel32.OpenProcess(query_limited_information, False, pid)
        if not handle:
            return 0.0
        try:
            counters = _Counters()
            counters.cb = ctypes.sizeof(counters)
            if not kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return 0.0
            return counters.WorkingSetSize / (1024 * 1024)
        finally:
            kernel32.CloseHandle(handle)

    out = _subprocess.run(["ps", "-Ao", "rss,pid,ppid"], capture_output=True, text=True,
                          check=False).stdout
    total = 0
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        rss, this_pid, parent = parts[0], parts[1], parts[2]
        if this_pid == str(pid) or (include_children and parent == str(pid)):
            try:
                total += int(rss)
            except ValueError:
                pass
    return total / 1024


def _host_can_create_symlinks() -> bool:
    """Probe it, never assume it: Windows creates symlinks only with Developer
    Mode or an elevated token (otherwise WinError 1314); POSIX always can."""
    import tempfile
    probe_dir = tempfile.mkdtemp(prefix="tina4-symlink-probe-")
    target = os.path.join(probe_dir, "target")
    link = os.path.join(probe_dir, "link")
    try:
        open(target, "w").close()
        os.symlink(target, link)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        for path in (link, target):
            try:
                os.unlink(path)
            except OSError:
                pass
        try:
            os.rmdir(probe_dir)
        except OSError:
            pass


HOST_CAN_CREATE_SYMLINKS = _host_can_create_symlinks()

# For a test whose subject is a symlink. On a host that cannot make one, the test
# cannot exist; the tag excuses it under TINA4_REQUIRE_SERVICES as a platform
# exclusion, and it runs on any host that can (Linux CI, Windows Developer Mode).
needs_symlinks = pytest.mark.skipif(
    not HOST_CAN_CREATE_SYMLINKS,
    reason="[needs:symlink-privilege] this host cannot create symlinks "
           "(Windows needs Developer Mode or an elevated shell)",
)


def anchor_pytest_project(project) -> None:
    """Give a throwaway project its OWN pytest config before a nested pytest run.

    pytest picks its rootdir and inifile by climbing from the test path to the
    first config file above it. A project under tmp_path has none of its own, so
    a nested run adopts whatever sits above the temp dir. MEASURED on a Windows
    host whose %TEMP% held a stray pyproject.toml with [tool.pytest.ini_options]:
    every nested run took %TEMP% itself as its rootdir, scanned it while other
    processes created and removed directories there, and died at collection with
    FileNotFoundError. A real Tina4 project carries its own config, so the test
    project does too.
    """
    from pathlib import Path as _Path
    ini = _Path(project) / "pytest.ini"
    if not ini.exists():
        ini.write_text("[pytest]\n", encoding="utf-8")


def free_port() -> int:
    """A port that was free a moment ago. Inherently racy: use boot_child_server."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def read_child_log(proc) -> str:
    """Whatever the child printed so far, WITHOUT touching the process.

    Only works for a child booted with ``log_dir=`` (its output went to a file).
    A PIPE child has to be reaped before its pipe can be drained, which is what
    :func:`_child_output` does; this one is safe to call on a live server.
    """
    log_path = getattr(proc, "tina4_log_path", None)
    if log_path is None:
        return "(child was booted without log_dir — output is on a pipe)"
    try:
        return log_path.read_text(errors="replace").strip()
    except OSError as exc:  # never let diagnostics mask the real failure
        return f"(could not read child log {log_path}: {exc})"


def _child_output(proc) -> str:
    """Whatever the child printed, without hanging if it is still alive."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                proc.kill()
        if getattr(proc, "tina4_log_path", None) is not None:
            return read_child_log(proc)
        out = proc.stdout.read() if proc.stdout else b""
        return out.decode(errors="replace").strip() if isinstance(out, bytes) else str(out).strip()
    except Exception as exc:  # never let diagnostics mask the real failure
        return f"(could not read child output: {exc})"


def boot_child_server(tmp_path, write_app, extra_env=None, attempts: int = 3,
                      boot_timeout: float = 25.0, unset_env=(), ready=None,
                      log_dir=None, new_session: bool = False, fixed_port=None):
    """Start a REAL child server and wait until it is ready.

    write_app(project_dir, port) writes app.py (and anything else) for that port.
    unset_env names variables the outer environment must not leak into the child.
    ready(port) -> bool decides readiness; the default is "the port accepts a
    connection". A caller whose readiness is really about CONTENT (the dev-reload
    test must know which version is being served before it edits anything) passes
    its own check rather than settling for an open socket.

    The child's stdout+stderr always go to a FILE, recorded as
    ``proc.tina4_log_path`` (read it live with read_child_log). log_dir picks the
    directory; without it the log lands under ``tmp_path / "child-logs"``. A pipe
    nobody drains fills (64KB on Linux, ~4KB on Windows) and wedges the child
    mid-write.

    new_session puts the child in its own session/process group (pgid == pid) on
    POSIX, or its own console process group on Windows, so a test can signal it
    (send_graceful_shutdown / kill_process_tree) without signalling the pytest
    runner that spawned it. Required for any test that signals the server.

    fixed_port pins the base port instead of picking a random free one. Needed
    whenever the CALLER must coordinate a sibling port around the base (e.g. the
    dual-port suite pre-binds base+1000 to prove a busy AI port is skipped
    non-fatally, and cannot know which base a random free_port() would choose).

    Returns (proc, port); the caller terminates proc in a finally block.
    """
    is_ready = ready or port_open
    from pathlib import Path as _Path
    failures = []

    for attempt in range(1, attempts + 1):
        port = fixed_port if fixed_port is not None else free_port()
        proj = tmp_path / f"srv_{port}"
        (proj / "src" / "routes").mkdir(parents=True, exist_ok=True)
        write_app(proj, port)

        env = {
            **os.environ,
            "PYTHONPATH": child_pythonpath(),
            "TINA4_OVERRIDE_CLIENT": "true",
            "TINA4_NO_BROWSER": "true",
            "TINA4_SUPPRESS": "true",
            "TINA4_NO_AI_PORT": "true",
            "PORT": str(port),
        }
        for name in unset_env:
            env.pop(name, None)
        if extra_env:
            env.update(extra_env(port) if callable(extra_env) else extra_env)

        # Every spawned child must sign with a valid secret. The autouse
        # _tina4_test_secret fixture guarantees one on the parent os.environ,
        # but a class/module-scoped server fixture boots BEFORE any
        # function-scoped fixture runs, so its child would inherit no secret and
        # refuse to boot (ADR-0079 s2). Fill a valid one unless the test
        # deliberately unset TINA4_SECRET (e.g. to exercise the dev-mint path).
        if "TINA4_SECRET" not in unset_env and len(env.get("TINA4_SECRET", "").encode()) < 32:
            env["TINA4_SECRET"] = _TEST_SECRET

        # ALWAYS a file, never an undrained pipe. A pipe nobody reads fills and
        # then blocks the child on its next log write: at 64KB on Linux, but at
        # ~4KB on Windows (CreatePipe's default), where a module-scoped server
        # wedged after about fifteen requests' worth of access-log lines and
        # every later request timed out.
        log_dir_path = _Path(log_dir if log_dir is not None else tmp_path / "child-logs")
        log_dir_path.mkdir(parents=True, exist_ok=True)
        log_path = log_dir_path / f"server_{port}.log"

        # A file the child owns outright beats a pipe: nothing has to drain it,
        # so the server can log all day without blocking, and the test can read
        # it while the server is still running.
        sink = open(log_path, "wb")
        try:
            proc = _subprocess.Popen(
                [_sys.executable, "app.py"], cwd=str(proj), env=env,
                stdout=sink, stderr=_subprocess.STDOUT,
                **spawn_kwargs(new_session),
            )
        finally:
            sink.close()  # the child kept its own dup of the fd
        proc.tina4_log_path = log_path

        deadline = _time.time() + boot_timeout
        died = False
        while _time.time() < deadline:
            if is_ready(port):
                return proc, port
            if proc.poll() is not None:
                died = True
                break
            _time.sleep(0.05)

        out = _child_output(proc)
        why = "exited during startup" if died else f"never became ready on port {port} in {boot_timeout}s"
        failures.append(f"attempt {attempt}/{attempts} (port {port}): {why}\n{out}")

        # Retry only the port race. Anything else is a real failure: report it now.
        if not any(marker in out.lower() for marker in _ADDR_IN_USE):
            break

    raise AssertionError(
        "child server never became ready:\n\n" + "\n\n".join(failures)
    )


def mongo_uri_with_option(uri: str, option: str) -> str:
    """Append one connection-string option to a MongoDB URI of ANY shape.

    The separator depends on whether the URI already has a PATH, not merely
    whether it has a query string. A mongodb URI needs a "/" before its query,
    but appending "/?" to a URI that already carries a database produces
    ".../tina4_py/?x=1" -- the driver then reads the database name as
    "tina4_py/" and rejects the whole string with InvalidURI.

    MEASURED against pymongo: the hand-rolled `"&" if "?" in uri else "/?"`
    join this replaces broke 3 of 6 real URI shapes -- host/db, a bare trailing
    slash, and mongodb+srv://.../db, which is the ordinary Atlas connection
    string. It only ever looked correct because TINA4_TEST_MONGO_URI happened
    to be the bare host:port form; the moment per-framework test isolation
    pointed it at a URI carrying a database, every caller failed at once.
    """
    if "?" in uri:
        return uri + "&" + option
    _, _, after_scheme = uri.partition("://")
    return uri + ("?" if "/" in after_scheme else "/?") + option


# ── SSRF guard opt-out for local-listener tests (ADR-0084) ──────────────────
#
# The Api client and Web Push refuse private/internal addresses by default, so
# every existing suite that points them at a 127.0.0.1 test server would now be
# refused. The suite legitimately talks to loopback (exactly the internal-service
# case TINA4_ALLOW_PRIVATE_REQUESTS exists for), so it opts in by default. The
# dedicated guard suite (tests/test_ssrf_guard_contract.py) clears this in its
# own autouse fixture, which runs after this one, so it still proves the
# default-blocked behaviour.
@pytest.fixture(autouse=True)
def _tina4_allow_private_requests_for_local_listeners():
    saved = os.environ.get("TINA4_ALLOW_PRIVATE_REQUESTS")
    os.environ["TINA4_ALLOW_PRIVATE_REQUESTS"] = "true"
    yield
    if saved is None:
        os.environ.pop("TINA4_ALLOW_PRIVATE_REQUESTS", None)
    else:
        os.environ["TINA4_ALLOW_PRIVATE_REQUESTS"] = saved
