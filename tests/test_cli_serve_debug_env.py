"""`tina4python serve` honours .env and --production for TINA4_DEBUG (ADR-0079 s3).

`serve` used to call os.environ.setdefault("TINA4_DEBUG", "true") BEFORE .env was
loaded, and .env loads without overriding, so a project's TINA4_DEBUG=false was
ignored; --production was parsed and never read. Debug decides whether /__dev is
mounted, so each case boots the real CLI in a child process on its own port and
asks the live server for /__dev: 404 means debug is off, anything else means on.

Case names match the auth_token_contract.json "debug-is-explicit" invariant.
No mocks: a real process, a real socket, a real .env file.
"""
from __future__ import annotations

import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

SECRET = "cli-serve-debug-secret-0123456789abcdef"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _status(port: int, path: str, timeout: float = 2.0) -> int | None:
    """GET http://127.0.0.1:<port><path>; HTTP status, or None on a socket error."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as reply:
            return reply.status
    except urllib.error.HTTPError as err:
        return err.code
    except OSError:
        return None


def _poll_dev(port: int, settle: float = 5.0) -> int:
    """Poll /__dev until it settles. Return the first non-404 the instant it
    appears (debug mounted it), or a settled 404 after the window (genuinely
    off) - neither answer weakened."""
    deadline = time.time() + settle
    last = 404
    while True:
        status = _status(port, "/__dev")
        if status is not None and status != 404:
            return status
        if status is not None:
            last = status
        if time.time() >= deadline:
            return last
        time.sleep(0.1)


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass


def _dev_status(tmp_path, env_file: str | None, *flags: str) -> int:
    """Boot `tina4python serve` and return the HTTP status of GET /__dev.

    PORT IDENTITY (the flake this guards): _free_port hands out an ephemeral
    port that, under load, a DIFFERENT debug-off server may already hold (a
    prior case's child lingering on the reused port). With TINA4_NO_TAKEOVER
    our debug-on child cannot evict it, so a bare /__dev probe would hit the
    FOREIGN server and read its 404 as the answer - a 200/404 on the port proves
    only that SOMETHING listens, not that it is OUR child. So each boot plants a
    per-boot UNIQUE readiness route (/ready_<token>) that only OUR child serves;
    readiness waits for a 200 on THAT (a foreign server 404s it), and only then
    polls /__dev. A contended port never yields our token, so the boot times out
    and retries on a FRESH port instead of trusting a stranger. Mirrors the Ruby
    ShutdownProbe identity guard (tina4-ruby) and the Node /fast readiness
    (tina4-nodejs loopBlockWatchdog). No mocks: a real child, a real socket."""
    boot_attempts = 5
    for _ in range(boot_attempts):
        token = secrets.token_hex(8)
        ready_path = f"/ready_{token}"
        root = tmp_path / token
        (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
        (root / "src" / "routes" / "ready.py").write_text(
            "from tina4_python.core.router import get\n\n\n"
            f"@get({ready_path!r})\n"
            "async def ready(request, response):\n"
            "    return response('ok')\n",
            encoding="utf-8",
        )
        if env_file is not None:
            (root / ".env").write_text(env_file, encoding="utf-8")
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_")}
        env.update({"TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true",
                    "TINA4_SECRET": SECRET, "TINA4_NO_TAKEOVER": "true"})
        proc = subprocess.Popen(
            [sys.executable, "-c", "from tina4_python.cli import main; main()",
             "serve", "--no-browser", "--no-reload", "--host", "127.0.0.1", "--port", str(port), *flags],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.time() + 30
            owned = False
            while time.time() < deadline:
                if proc.poll() is not None:
                    break  # child exited (could not own the contended port) -> fresh port
                if _status(port, ready_path) == 200:
                    owned = True
                    break
                time.sleep(0.1)
            if owned:
                return _poll_dev(port)
            # The port was not ours this attempt; retry on a fresh one.
        finally:
            _terminate(proc)
    pytest.fail(f"serve never owned its own port after {boot_attempts} attempts")


def test_serve_honours_debug_false_from_env_file(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=false\n") == 404


def test_serve_honours_debug_true_from_env_file(tmp_path):
    # Control: proves the /__dev probe can tell debug-on from debug-off.
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n") != 404


def test_production_flag_turns_debug_off(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n", "--production") == 404


def test_a_missing_env_file_does_not_enable_debug(tmp_path):
    assert _dev_status(tmp_path, None) == 404
