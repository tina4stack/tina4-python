# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression for tina4-python#278: the SMTP send timeout is configurable.

No mocks. A REAL TCP server accepts the connection and then says nothing, so
send() blocks waiting for the SMTP greeting. With the timeout left at its 30 s
default that is a 30 s hold; with a 1 s timeout the send must fail in about a
second. The wall-clock is the instrument: a configured 1 s timeout that is
honoured finishes well under the default, a hardcoded 30 s does not.
"""

import os
import socket
import threading
import time

import pytest

from tina4_python.messenger import Messenger


@pytest.fixture
def silent_smtp():
    """A server that accepts TCP connections and never sends a byte."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port = server.getsockname()[1]
    held = []
    stop = threading.Event()

    def accept_loop():
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                held.append(conn)  # keep it open, never reply
            except OSError:
                pass

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        server.close()


def _send(**kwargs):
    messenger = Messenger(host="127.0.0.1", encryption="none",
                          from_address="app@localhost", **kwargs)
    start = time.monotonic()
    result = messenger.send("someone@localhost", "test", "hello")
    elapsed = time.monotonic() - start
    # The host never speaks SMTP, so the send always fails - what matters is HOW
    # LONG it waited, and that the failure is reported AS a timeout.
    assert result["success"] is False
    return elapsed, result


def test_constructor_timeout_bounds_the_send_and_reports_a_timeout(silent_smtp):
    elapsed, result = _send(port=silent_smtp, timeout=1)
    assert elapsed < 8, f"a 1 s timeout should fail fast, not hold ~30 s (took {elapsed:.1f} s)"
    assert "tim" in str(result["message"]).lower(), \
        f"a silent server must be reported as a timeout, got {result['message']!r}"


def test_env_timeout_bounds_the_send(silent_smtp, monkeypatch):
    monkeypatch.setenv("TINA4_MAIL_TIMEOUT", "1")
    elapsed, _ = _send(port=silent_smtp)
    assert elapsed < 8, f"TINA4_MAIL_TIMEOUT=1 should fail fast (took {elapsed:.1f} s)"


def test_default_timeout_is_thirty_seconds():
    # The default is unchanged (no behaviour change for apps that set nothing).
    assert Messenger(host="127.0.0.1", encryption="none").timeout == 30


def test_a_bad_env_value_warns_once_and_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("TINA4_MAIL_TIMEOUT", "not-a-number")
    assert Messenger(host="127.0.0.1", encryption="none").timeout == 30


def test_a_zero_env_value_falls_back_to_the_default(monkeypatch):
    # Zero is garbage, not an opt-out: to the socket it means "do not wait at all".
    monkeypatch.setenv("TINA4_MAIL_TIMEOUT", "0")
    assert Messenger(host="127.0.0.1", encryption="none").timeout == 30


def test_an_explicit_sub_second_timeout_is_refused():
    # An explicit value is the caller's own instruction, so < 1 is a bug, not a default.
    with pytest.raises(ValueError):
        Messenger(host="127.0.0.1", encryption="none", timeout=0)


def test_smtp_timeout_env_is_no_longer_honoured(monkeypatch):
    # The SMTP_TIMEOUT fallback was dropped for parity with the PHP master:
    # only TINA4_MAIL_TIMEOUT configures the timeout now.
    monkeypatch.delenv("TINA4_MAIL_TIMEOUT", raising=False)
    monkeypatch.setenv("SMTP_TIMEOUT", "1")
    assert Messenger(host="127.0.0.1", encryption="none").timeout == 30
