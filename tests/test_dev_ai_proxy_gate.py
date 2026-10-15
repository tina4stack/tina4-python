# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The dev-admin routes outside /__dev take the /__dev gate.

``POST /ai/api/chat`` forwards a prompt to the developer's AI gateway and
returns the reply; ``/ai``, ``/vision``, ``/embed``, ``/image`` and ``/rag``
report the configured service URLs. They are served by the dev admin but sit
outside the ``/__dev`` prefix, so they must still pass the same Host,
same-origin and loopback-peer checks.

REAL dispatch through the ASGI front controller and a real stand-in gateway
socket: the witness is whether the gateway is reached.
"""
import http.server
import json
import threading

import pytest

from test_dev_admin_conformance import _dispatch

PROMPT = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": False}
REPLY = "GATEWAY-REPLY-0f3a"


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            hits.append(self.path)
            body = json.dumps({"message": {"role": "assistant", "content": REPLY}, "done": True}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.chdir(tmp_path)
    for var in ("TINA4_MCP", "TINA4_MCP_REMOTE", "TINA4_MCP_TOKEN", "TINA4_API_KEY",
                "TINA4_HOST", "TINA4_DEV_ALLOWED_PEERS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.setenv("TINA4_AI_URL", f"http://127.0.0.1:{server.server_port}/api/chat")
    yield hits
    server.shutdown()
    server.server_close()


def test_a_non_loopback_peer_cannot_use_the_ai_proxy(gateway):
    status, body, _ = _dispatch("POST", "/ai/api/chat", json=PROMPT, client=("203.0.113.9", 5555))
    assert status == 403
    assert REPLY.encode() not in body
    assert gateway == []


def test_a_cross_origin_page_cannot_use_the_ai_proxy(gateway):
    for headers in ({"origin": "http://evil.example"}, {"sec-fetch-site": "cross-site"}):
        status, body, _ = _dispatch("POST", "/ai/api/chat", json=PROMPT, headers=headers)
        assert status == 403, headers
        assert REPLY.encode() not in body
    assert gateway == []


def test_a_foreign_host_cannot_use_the_ai_proxy(gateway):
    status, body, _ = _dispatch("POST", "/ai/api/chat", json=PROMPT,
                                headers={"host": "rebind.evil.example:7145"})
    assert status == 403
    assert REPLY.encode() not in body
    assert gateway == []


def test_the_dashboard_can_use_the_ai_proxy(gateway):
    status, body, _ = _dispatch("POST", "/ai/api/chat", json=PROMPT,
                                headers={"sec-fetch-site": "same-origin"})
    assert status == 200
    assert REPLY.encode() in body
    assert gateway == ["/api/chat"]


@pytest.mark.parametrize("path", ["/ai", "/vision", "/embed", "/image", "/rag"])
def test_service_probes_are_refused_to_a_non_loopback_peer(gateway, path):
    status, body, _ = _dispatch("GET", path, client=("203.0.113.9", 5555))
    assert status == 403
    assert b"127.0.0.1" not in body and b"localhost" not in body
    status, _, _ = _dispatch("GET", path)
    assert status == 200
