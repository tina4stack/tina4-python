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
    preexec_fn is not supported there.
    """
    for name in ("SIGHUP", "SIGINT", "SIGQUIT"):
        sig = getattr(_signal, name, None)
        if sig is not None:
            try:
                _signal.signal(sig, _signal.SIG_DFL)
            except (OSError, ValueError):
                pass


_ADDR_IN_USE = ("address already in use", "address in use", "eaddrinuse",
                "errno 48", "errno 98", "oserror: [errno 48]", "oserror: [errno 98]")


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

    log_dir sends the child's stdout+stderr to a FILE instead of a pipe, and
    records it as ``proc.tina4_log_path``. Use it whenever the test needs to read
    what the server logged while it is still alive, or whenever the child may
    outlive a readiness check — a pipe nobody drains fills at 64KB and wedges the
    child mid-write.

    new_session puts the child in its own session/process group (pgid == pid), so
    a test can ``os.killpg(proc.pid, ...)`` without signalling the pytest runner
    that spawned it. Required for any test that signals the server.

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

        log_path = None
        if log_dir is not None:
            log_path = _Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            log_path = log_path / f"server_{port}.log"

        # A file the child owns outright beats a pipe: nothing has to drain it,
        # so the server can log all day without blocking, and the test can read
        # it while the server is still running.
        sink = open(log_path, "wb") if log_path is not None else None
        try:
            proc = _subprocess.Popen(
                [_sys.executable, "app.py"], cwd=str(proj), env=env,
                stdout=sink or _subprocess.PIPE, stderr=_subprocess.STDOUT,
                start_new_session=new_session,
                preexec_fn=_reset_inherited_signal_dispositions,
            )
        finally:
            if sink is not None:
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
