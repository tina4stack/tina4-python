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


def _dev_status(tmp_path, env_file: str | None, *flags: str) -> int:
    """Boot `tina4python serve` and return the HTTP status of GET /__dev."""
    (tmp_path / "src" / "routes").mkdir(parents=True, exist_ok=True)
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_")}
    env.update({"TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true",
                "TINA4_SECRET": SECRET, "TINA4_NO_TAKEOVER": "true"})
    proc = subprocess.Popen(
        [sys.executable, "-c", "from tina4_python.cli import main; main()",
         "serve", "--no-browser", "--no-reload", "--host", "127.0.0.1", "--port", str(port), *flags],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"serve exited early ({proc.returncode}): {proc.stdout.read().decode()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/__dev", timeout=2) as reply:
                    return reply.status
            except urllib.error.HTTPError as err:
                return err.code
            except OSError:
                time.sleep(0.2)
        pytest.fail("serve never answered on its port")
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def test_serve_honours_debug_false_from_env_file(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=false\n") == 404


def test_serve_honours_debug_true_from_env_file(tmp_path):
    # Control: proves the /__dev probe can tell debug-on from debug-off.
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n") != 404


def test_production_flag_turns_debug_off(tmp_path):
    assert _dev_status(tmp_path, "TINA4_DEBUG=true\n", "--production") == 404


def test_a_missing_env_file_does_not_enable_debug(tmp_path):
    assert _dev_status(tmp_path, None) == 404
