# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SSRF guard (ADR-0084) - the Python runner for ssrf_guard_contract.json.

tests/fixtures/ssrf_guard_contract.json is a copy of
tina4-documentation/plan/v3/fixtures/ssrf_guard_contract.json. Every address in
the fixture is fed to the real classifier; the request cases drive the real Api
client and the real Push sender against a REAL loopback listener - no mocks, no
canned transport. 127.0.0.1 is blocked by default, so the loopback listener is
reached via the explicit allow-list; the opt-out is proved with a positive twin.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tina4_python.api import Api
from tina4_python.push import Push, PushError
from tina4_python import ssrf

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ssrf_guard_contract.json").read_text())


@pytest.fixture(autouse=True)
def _clear_opt_out():
    saved = os.environ.get(ssrf.ALLOW_PRIVATE_ENV)
    os.environ.pop(ssrf.ALLOW_PRIVATE_ENV, None)
    yield
    if saved is None:
        os.environ.pop(ssrf.ALLOW_PRIVATE_ENV, None)
    else:
        os.environ[ssrf.ALLOW_PRIVATE_ENV] = saved


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b"")

    def log_message(self, *args):
        pass


class _RedirectHandler(BaseHTTPRequestHandler):
    redirect_to = "http://169.254.169.254/latest/meta-data/"

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", self.redirect_to)
        self.end_headers()

    def log_message(self, *args):
        pass


def _serve(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


# ── SSRF-CLASSIFY ────────────────────────────────────────────────────────────

def test_blocks_loopback_by_default():
    assert ssrf.is_blocked_address("127.0.0.1") is True
    assert ssrf.is_blocked_address("::1") is True


def test_blocks_cloud_metadata_address():
    assert ssrf.is_blocked_address("169.254.169.254") is True


def test_blocks_private_and_cgnat_ranges():
    for case in FIXTURE["addresses"]:
        assert ssrf.is_blocked_address(case["ip"]) is case["blocked"], case["ip"]


def test_allows_a_public_address():
    assert ssrf.is_blocked_address("8.8.8.8") is False
    assert ssrf.is_blocked_address("2606:4700:4700::1111") is False


def test_rejects_a_non_http_scheme():
    for case in FIXTURE["schemes"]:
        if case["allowed"]:
            continue
        with pytest.raises(ssrf.SsrfError):
            ssrf.guard_url(f"{case['scheme']}://example.com/x")


# ── SSRF-REQUEST ─────────────────────────────────────────────────────────────

def test_api_blocks_request_to_loopback_by_default():
    server, _ = _serve(_OkHandler)
    try:
        port = server.server_address[1]
        result = Api().get(f"http://127.0.0.1:{port}/")
        assert result["http_code"] is None
        assert result["error"] and ssrf.ALLOW_PRIVATE_ENV in result["error"]
    finally:
        server.shutdown()


def test_api_allows_request_with_opt_out():
    server, _ = _serve(_OkHandler)
    try:
        port = server.server_address[1]
        os.environ[ssrf.ALLOW_PRIVATE_ENV] = "true"
        result = Api().get(f"http://127.0.0.1:{port}/")
        assert result["http_code"] == 200
        # and the explicit allow-list works with the opt-out OFF
        os.environ.pop(ssrf.ALLOW_PRIVATE_ENV, None)
        allowed = Api(allow_hosts=["127.0.0.1"]).get(f"http://127.0.0.1:{port}/")
        assert allowed["http_code"] == 200
    finally:
        server.shutdown()


def test_api_blocks_redirect_hop_to_private():
    server, _ = _serve(_RedirectHandler)
    try:
        port = server.server_address[1]
        # The loopback listener is allowed by the allow-list; its 302 target
        # (169.254.169.254) is NOT, so it is refused at the hop.
        result = Api(allow_hosts=["127.0.0.1"]).get(f"http://127.0.0.1:{port}/")
        assert result["http_code"] is None
        assert result["error"] and "169.254.169.254" in result["error"]
    finally:
        server.shutdown()


def test_web_push_blocked_to_private_endpoint_unless_opted_in():
    keys = Push.generate_keys()
    subject = "mailto:ops@example.com"
    subscription = {
        "endpoint": "http://169.254.169.254/push/AAA",
        "keys": {"p256dh": Push.generate_keys()["publicKey"], "auth": "AAAAAAAAAAAAAAAAAAAAAA"},
    }
    push = Push(subject=subject, public_key=keys["publicKey"], private_key=keys["privateKey"])
    with pytest.raises(PushError) as excinfo:
        push.send(subscription, {"title": "hi"})
    assert ssrf.ALLOW_PRIVATE_ENV in str(excinfo.value)
