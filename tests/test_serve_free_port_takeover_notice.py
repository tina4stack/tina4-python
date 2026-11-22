# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""`tina4python serve` must only say a port is in use when something holds it.

take_over_port() refused outside dev mode, and when takeover was opted out,
before it looked for a holder. So with debug off (or --no-kill) every start
printed "Port N is in use ..." on a port nothing held, and a production operator
was told a free port was taken. Parity with tina4-php#362.

No mocks: real sockets, and the real CLI in a child process on its own port.
The held-port cases are the controls: the notice must still appear when the port
really is taken.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time

from conftest import kill_process_tree, send_graceful_shutdown, spawn_kwargs
from tina4_python.core.port_takeover import NOTHING, REFUSED_PROD, take_over_port

SECRET = "serve-free-port-secret-0123456789abcdef"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _hold_port() -> tuple[socket.socket, int]:
    """A live listener on 127.0.0.1 without SO_REUSEADDR, so a later bind fails on every OS."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(5)
    return holder, holder.getsockname()[1]


def _serve(tmp_path, port: int, extra_env: dict[str, str], *flags: str):
    root = tmp_path / f"app{port}"
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_")}
    env.update({"TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true",
                "TINA4_SECRET": SECRET, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"})
    env.update(extra_env)
    log = root / "serve.log"
    with open(log, "wb") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, "-c", "from tina4_python.cli import main; main()",
             "serve", *flags, "--no-browser", "--no-reload", "--host", "127.0.0.1", "--port", str(port)],
            cwd=root, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            **spawn_kwargs(new_session=True),
        )
    return proc, log


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        send_graceful_shutdown(proc)
        proc.wait(timeout=10)
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        kill_process_tree(proc)


def _read(log) -> str:
    return log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""


def _output_once_serving(tmp_path, extra_env: dict[str, str], *flags: str) -> str:
    """Boot serve on a free port, wait for its own Server banner, return its output."""
    port = _free_port()
    proc, log = _serve(tmp_path, port, extra_env, *flags)
    own_server = re.compile(rf"Server:\s+http://\S*:{port}\b")
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if own_server.search(_read(log)):
                return _read(log)
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        raise AssertionError(f"serve never came up on free port {port}:\n{_read(log)}")
    finally:
        _terminate(proc)


# ── the shared helper, directly ──────────────────────────────────────────

def test_a_free_port_is_not_refused_outside_dev_mode():
    result = take_over_port(_free_port(), dev=False, no_takeover=False, host="127.0.0.1")
    assert result.status == NOTHING
    assert result.message == ""


def test_a_free_port_is_not_refused_when_opted_out():
    result = take_over_port(_free_port(), dev=True, no_takeover=True, host="127.0.0.1")
    assert result.status == NOTHING
    assert result.message == ""


def test_a_held_port_is_still_refused_outside_dev_mode():
    holder, port = _hold_port()
    try:
        result = take_over_port(port, dev=False, no_takeover=False, host="127.0.0.1")
    finally:
        holder.close()
    assert result.status == REFUSED_PROD
    assert f"Port {port} is in use" in result.message


# ── the real CLI ─────────────────────────────────────────────────────────

def test_serve_with_debug_off_says_nothing_about_a_free_port(tmp_path):
    output = _output_once_serving(tmp_path, {"TINA4_DEBUG": "false"})
    assert "is in use" not in output


def test_serve_with_no_kill_says_nothing_about_a_free_port(tmp_path):
    output = _output_once_serving(tmp_path, {"TINA4_DEBUG": "true"}, "--no-kill")
    assert "is in use" not in output


def test_serve_with_debug_off_still_refuses_a_held_port(tmp_path):
    holder, port = _hold_port()
    proc, log = _serve(tmp_path, port, {"TINA4_DEBUG": "false"})
    notice = f"Port {port} is in use; takeover is disabled outside dev mode"
    try:
        deadline = time.time() + 30
        while time.time() < deadline and notice not in _read(log) and proc.poll() is None:
            time.sleep(0.1)
    finally:
        _terminate(proc)
        holder.close()
    assert notice in _read(log)
