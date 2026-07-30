# Tina4 v3 test configuration

import os

import pytest

# Provisioned real services (and their client libraries). CI stands all of these
# up, so an integration test should never skip in CI. Firebird is deliberately
# NOT in this list -- it is not provisioned, so its skips stay green. MySQL and
# MSSQL joined the provisioned set in 3.13.44 (#262), so their reachability /
# driver skips now fail the gate too.
_SERVICE_KEYWORDS = (
    "postgres", "postgresql", "psycopg2",
    "mysql",            # also matches "mysql-connector-python"
    "mssql", "sqlserver", "pymssql",
    "redis", "valkey", "memcached",
    "pymemcache",       # the memcached CLIENT: "memcached" does not match it
    "mongo",            # also matches "pymongo"
    "rabbit", "amqp",
    "pika",             # the RabbitMQ CLIENT: "rabbit"/"amqp" do not match it
    "kafka",            # also matches "rdkafka" / "confluent-kafka"
    "mqtt", "mosquitto",  # Mosquitto (+ EMQX) for the MQTT tests
    # GreenMail (real SMTP 3025 / IMAP 3143) for the Messenger round-trip tests.
    # test_messenger.py has ALWAYS claimed in a comment that its "GreenMail
    # SMTP/IMAP not reachable" skip was upgraded here -- it was not, because no
    # mail keyword existed in this tuple, so every one of those live tests could
    # skip green in CI forever behind a comment saying it could not.
    "greenmail", "smtp", "imap",
)
# A keyword must match the text the test ACTUALLY skips with, and tests skip on
# the CLIENT LIBRARY name as often as the service name. Where the two differ and
# the service name is not a substring of the client's, BOTH belong above:
# "pika not installed" and "pymemcache not installed" matched nothing and passed
# green, which is how six live RabbitMQ tests sat silently skipping on a host
# that had every service running. ("kafka" happens to be a substring of
# "confluent-kafka" and "psycopg2"/"pymssql" are listed explicitly, so those were
# already covered -- the gap was only where neither held.)
#
# pyodbc is deliberately NOT here. There is no ODBC service in the lab or in CI,
# so -- exactly like Firebird -- an ODBC skip is a genuinely-unprovisioned skip
# and must stay green. Add it the day an ODBC service is provisioned.
_UNAVAILABLE_HINTS = (
    "not reachable", "unreachable", "not running", "not set",
    "not installed", "could not connect", "not available", "refused",
)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _require_services():
    return _truthy(os.environ.get("TINA4_REQUIRE_SERVICES"))


def _is_provisioned_service_skip(reason):
    low = (reason or "").lower()
    return any(k in low for k in _SERVICE_KEYWORDS) and any(h in low for h in _UNAVAILABLE_HINTS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """When TINA4_REQUIRE_SERVICES is set, turn a skip caused by a PROVISIONED
    service being unavailable into a hard FAILURE.

    CI provisions PostgreSQL, MySQL, MSSQL, Redis, Valkey, Memcached, MongoDB,
    RabbitMQ, and Kafka and sets every TINA4_TEST_* URL, so these integration
    tests must run. A skip that names one of those services (or its client
    library) means the service or driver silently went missing -- the exact gap
    that let the migration and queue bugs ship green. Firebird is not
    provisioned, so its skips never match these keywords and stay green.
    """
    outcome = yield
    report = outcome.get_result()
    if not _require_services() or not report.skipped:
        return
    try:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    except Exception:
        reason = str(getattr(report, "longrepr", ""))
    if _is_provisioned_service_skip(reason):
        report.outcome = "failed"
        report.longrepr = (
            "TINA4_REQUIRE_SERVICES is set, but this real-service test SKIPPED "
            "because a provisioned service or client library is missing:\n  "
            + reason.strip()
            + "\nProvision the service / install the client, or unset TINA4_REQUIRE_SERVICES."
        )


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

import socket as _socket
import subprocess as _subprocess
import sys as _sys
import time as _time

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


def _child_output(proc) -> str:
    """Whatever the child printed, without hanging if it is still alive."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except _subprocess.TimeoutExpired:
                proc.kill()
        out = proc.stdout.read() if proc.stdout else b""
        return out.decode(errors="replace").strip() if isinstance(out, bytes) else str(out).strip()
    except Exception as exc:  # never let diagnostics mask the real failure
        return f"(could not read child output: {exc})"


def boot_child_server(tmp_path, write_app, extra_env=None, attempts: int = 3,
                      boot_timeout: float = 25.0, unset_env=(), ready=None):
    """Start a REAL child server and wait until it is ready.

    write_app(project_dir, port) writes app.py (and anything else) for that port.
    unset_env names variables the outer environment must not leak into the child.
    ready(port) -> bool decides readiness; the default is "the port accepts a
    connection". A caller whose readiness is really about CONTENT (the dev-reload
    test must know which version is being served before it edits anything) passes
    its own check rather than settling for an open socket.

    Returns (proc, port); the caller terminates proc in a finally block.
    """
    is_ready = ready or port_open
    from pathlib import Path as _Path
    repo_root = _Path(__file__).resolve().parent.parent
    failures = []

    for attempt in range(1, attempts + 1):
        port = free_port()
        proj = tmp_path / f"srv_{port}"
        (proj / "src" / "routes").mkdir(parents=True, exist_ok=True)
        write_app(proj, port)

        env = {
            **os.environ,
            "PYTHONPATH": str(repo_root),
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

        proc = _subprocess.Popen(
            [_sys.executable, "app.py"], cwd=str(proj), env=env,
            stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
        )

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
