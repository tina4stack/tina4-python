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
import re
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

    Harness shape is IDENTICAL across tina4-python / tina4-php / tina4-ruby so
    there are no cross-framework surprises:

    1. CLEAN child env (the real cure). We pass an explicit env with every
       TINA4_ key filtered out, so no stale TINA4_DEBUG leaks in from the parent
       and the temp .env alone decides debug. This is Python's idiomatic
       equivalent of Ruby's Process.spawn `unsetenv_others: true` (Python's
       `env=` already REPLACES the environment; Ruby MERGES, which is why the
       flake was Ruby-only). PYTHONUNBUFFERED=1 so the child's banner reaches the
       log the instant it prints, not on a block-buffer flush.
    2. IDENTITY-GUARDED readiness. Readiness waits for the child's OWN
       `Server: http://...:<thisport>` banner in its log - the same banner all
       four frameworks print once they have bound THIS port - before probing
       /__dev. A 200/404 on the port alone proves only that SOMETHING listens,
       not that it is OUR child; a port a foreign server already holds never
       yields our banner, so the boot times out and retries on a FRESH port.
    3. Poll /__dev and return its status (debug-on non-404 at once, debug-off a
       settled 404 by outlasting the window).

    No mocks: a real child, a real socket, real .env files."""
    boot_attempts = 5
    for attempt in range(boot_attempts):
        root = tmp_path / f"attempt{attempt}"
        (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
        if env_file is not None:
            (root / ".env").write_text(env_file, encoding="utf-8")
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_")}
        env.update({"TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true",
                    "TINA4_SECRET": SECRET, "TINA4_NO_TAKEOVER": "true",
                    "PYTHONUNBUFFERED": "1"})
        log = root / "serve.log"
        own_server = re.compile(rf"Server:\s+http://\S*:{port}\b")
        with open(log, "wb") as log_fh:
            proc = subprocess.Popen(
                [sys.executable, "-c", "from tina4_python.cli import main; main()",
                 "serve", "--no-browser", "--no-reload", "--host", "127.0.0.1", "--port", str(port), *flags],
                cwd=root, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            deadline = time.time() + 30
            owned = False
            while time.time() < deadline:
                if proc.poll() is not None:
                    break  # child exited (could not own a contended port) -> fresh port
                if own_server.search(log.read_text(encoding="utf-8", errors="replace")):
                    owned = True
                    break
                time.sleep(0.1)
            if owned:
                return _poll_dev(port)
            # The child never claimed THIS port; retry on a fresh one.
        finally:
            _terminate(proc)
    pytest.fail(f"serve never printed its own Server banner after {boot_attempts} attempts")


def test_serve_honours_debug_false_from_env_file(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=false\n") == 404


def test_serve_honours_debug_true_from_env_file(tmp_path):
    # Control: proves the /__dev probe can tell debug-on from debug-off.
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n") != 404


def test_production_flag_turns_debug_off(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n", "--production") == 404


def test_a_missing_env_file_does_not_enable_debug(tmp_path):
    assert _dev_status(tmp_path, None) == 404
