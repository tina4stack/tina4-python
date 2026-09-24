# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# Dev-surface gate contract (release security boundaries) - REAL dispatch, no mocks.
"""
Drives the existing dev-admin security decisions through the
REAL ASGI front controller (``tina4_python.core.server.app``) with a controllable
socket peer, Host header and Sec-Fetch-Site header. The witness of every case is a
real side effect: a secret that is not returned, a file that is not written, a
table that still exists, a socket that is closed instead of accepted.
"""
import asyncio
import json as _json
import os

import pytest

from test_dev_admin_conformance import _dispatch

SECRET = "dev-surface-secret-0078"


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """A real project tree named ``app`` with a sibling ``app-sibling`` that
    shares its name as a prefix, a real .env and a real SQLite database."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / ".env").write_text(f"TINA4_SECRET={SECRET}\n")
    (app_dir / "readme.txt").write_text("public-readme\n")
    (app_dir / "src" / "templates" / "pages").mkdir(parents=True)
    (app_dir / "src" / "templates" / "pages" / "hello.twig").write_text("PAGE-OK")
    (app_dir / "src" / "templates" / "partial_secret.twig").write_text("PARTIAL-LEAK")
    (app_dir / "outside.twig").write_text("ROOT-LEAK")
    sibling = tmp_path / "app-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SIBLING-LEAK")
    monkeypatch.chdir(app_dir)
    for var in ("TINA4_MCP", "TINA4_MCP_REMOTE", "TINA4_MCP_TOKEN", "TINA4_API_KEY", "TINA4_HOST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    return app_dir


# ── Resolve first, then check the secret denylist ────────────────────────────

def test_a_dotenv_path_with_a_trailing_dot_segment_is_refused(project_dir):
    for trick in (".env/.", ".env/x/..", "src/../.env", "./.env"):
        for endpoint in ("/__dev/api/file", "/__dev/api/file/raw"):
            status, body, _ = _dispatch("GET", f"{endpoint}?path={trick}")
            assert status in (403, 404), f"{endpoint}?path={trick} -> {status}"
            assert SECRET.encode() not in body, f"{endpoint}?path={trick} served .env"


def test_a_symlink_to_dotenv_is_refused(project_dir):
    os.symlink(project_dir / ".env", project_dir / "innocent.txt")
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=innocent.txt")
    assert status == 403
    assert SECRET.encode() not in body


def test_a_sibling_prefix_directory_is_outside_the_project(project_dir):
    for endpoint in ("/__dev/api/file", "/__dev/api/file/raw"):
        status, body, _ = _dispatch("GET", f"{endpoint}?path=../app-sibling/secret.txt")
        assert status == 403, f"{endpoint} -> {status}"
        assert b"SIBLING-LEAK" not in body
    status, _, _ = _dispatch(
        "POST", "/__dev/api/file/save", headers={"sec-fetch-site": "same-origin"},
        json={"path": "../app-sibling/written.txt", "content": "x"})
    assert status == 403
    assert not (project_dir.parent / "app-sibling" / "written.txt").exists()


def test_metrics_file_refuses_a_path_outside_the_project(project_dir):
    outside = project_dir.parent / "app-sibling" / "secret.txt"
    status, _, _ = _dispatch("GET", f"/__dev/api/metrics/file?path={outside}")
    assert status == 403
    status, _, _ = _dispatch("GET", "/__dev/api/metrics/file?path=../app-sibling/secret.txt")
    assert status == 403


# ── Reads carry the same gate as writes ──────────────────────────────────────

def test_a_cross_origin_read_is_refused(project_dir):
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt",
                                headers={"sec-fetch-site": "cross-site"})
    assert status == 403
    assert b"public-readme" not in body
    # Positive control: the same read from the dashboard itself succeeds.
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt",
                                headers={"sec-fetch-site": "same-origin"})
    assert status == 200
    assert b"public-readme" in body


def test_a_same_site_fetch_is_refused(project_dir):
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt",
                                headers={"sec-fetch-site": "same-site"})
    assert status == 403
    assert b"public-readme" not in body
    probe = project_dir / "same_site_probe.txt"
    status, _, _ = _dispatch("POST", "/__dev/api/file/save",
                             headers={"sec-fetch-site": "same-site"},
                             json={"path": "same_site_probe.txt", "content": "x"})
    assert status == 403
    assert not probe.exists()


def test_a_non_loopback_peer_cannot_read(project_dir):
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt",
                                client=("203.0.113.9", 5555))
    assert status == 403
    assert b"public-readme" not in body


# ── Host allow-list (DNS rebinding) ──────────────────────────────────────────

def test_a_foreign_host_header_is_refused(project_dir):
    for path in ("/__dev", "/__dev/api/status", "/__dev/api/file?path=readme.txt"):
        status, body, _ = _dispatch("GET", path, headers={"host": "rebind.evil.example:7145"})
        assert status == 403, f"{path} with a foreign Host -> {status}"
        assert b"public-readme" not in body


def test_a_loopback_host_header_is_allowed(project_dir, monkeypatch):
    for host in ("localhost:7145", "127.0.0.1:7145", "[::1]:7145", "localhost"):
        status, _, _ = _dispatch("GET", "/__dev/api/status", headers={"host": host})
        assert status == 200, f"Host {host} -> {status}"
    monkeypatch.setenv("TINA4_HOST", "devbox.internal")
    status, _, _ = _dispatch("GET", "/__dev/api/status", headers={"host": "devbox.internal:7145"})
    assert status == 200


def test_a_foreign_host_cannot_reach_mcp(project_dir):
    status, body, _ = _dispatch("GET", "/__dev/api/mcp/tools",
                                headers={"host": "rebind.evil.example"})
    assert status == 403
    assert b'"name"' not in body
    status, _, _ = _dispatch("POST", "/__dev/mcp", headers={"host": "rebind.evil.example"},
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert status == 403


def _ws_open(host):
    """Open the real /__dev_reload socket through the ASGI app; return the first
    message the server sends (websocket.accept or websocket.close)."""
    from tina4_python.core import server
    server._register_dev_reload_ws()
    sent = []
    inbox = [{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}]

    async def receive():
        if inbox:
            return inbox.pop(0)
        await asyncio.sleep(3600)

    async def send(message):
        sent.append(message)

    scope = {"type": "websocket", "path": "/__dev_reload", "raw_path": b"/__dev_reload",
             "query_string": b"", "headers": [(b"host", host.encode())],
             "client": ("127.0.0.1", 40000), "server": ("localhost", 7145),
             "scheme": "ws", "subprotocols": []}
    asyncio.run(asyncio.wait_for(server.app(scope, receive, send), 5))
    return sent[0]["type"]


def test_a_foreign_host_cannot_open_the_reload_socket(project_dir):
    assert _ws_open("rebind.evil.example:7145") == "websocket.close"
    assert _ws_open("localhost:7145") == "websocket.accept"


# ── Only TINA4_MCP_TOKEN unlocks the remote dev surface ──────────────────────

def test_the_api_key_does_not_unlock_dev_writes(project_dir, monkeypatch):
    monkeypatch.setenv("TINA4_API_KEY", "app-api-key")
    probe = project_dir / "api_key_probe.txt"
    for headers in ({"authorization": "Bearer app-api-key"}, {"x-api-key": "app-api-key"}):
        status, _, _ = _dispatch("POST", "/__dev/api/file/save", client=("203.0.113.9", 5555),
                                 headers=headers,
                                 json={"path": "api_key_probe.txt", "content": "x"})
        assert status == 403
        assert not probe.exists()
    monkeypatch.setenv("TINA4_MCP", "true")
    monkeypatch.setenv("TINA4_MCP_REMOTE", "true")
    status, body, _ = _dispatch("GET", "/__dev/api/mcp/tools", client=("203.0.113.9", 5555),
                                headers={"authorization": "Bearer app-api-key"})
    assert status == 200  # accepted MCP transport API-key fallback
    # Positive control: the MCP token does unlock the same write.
    monkeypatch.setenv("TINA4_MCP_TOKEN", "mcp-token-0078")
    monkeypatch.setenv("TINA4_HOST", "devbox.lan")
    status, _, _ = _dispatch("POST", "/__dev/api/file/save", client=("203.0.113.9", 5555),
                             headers={"authorization": "Bearer mcp-token-0078",
                                      "host": "devbox.lan:7145"},
                             json={"path": "api_key_probe.txt", "content": "ok"})
    assert status == 200
    assert probe.read_text() == "ok"


# ── Table viewer takes only a real table name ────────────────────────────────

def test_table_info_rejects_an_unknown_table_name(project_dir, monkeypatch):
    from tina4_python.database import Database
    db_file = project_dir / "surface.db"
    monkeypatch.setenv("TINA4_DATABASE_URL", f"sqlite:///{db_file}")
    db = Database(f"sqlite:///{db_file}")
    db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO people (name) VALUES ('ada')")
    db.commit()
    db.close()

    status, body, _ = _dispatch("GET", "/__dev/api/table?name=people")
    assert status == 200
    assert b"ada" in body

    for bad in ("(SELECT 'INJECTED' AS leak)", "people WHERE 1=0 UNION SELECT 1,'INJECTED'",
                "no_such_table"):
        status, body, _ = _dispatch("GET", f"/__dev/api/table?name={bad}")
        assert status == 404, f"name={bad} -> {status}"
        assert b"INJECTED" not in body


# ── Template auto-routing stays inside the pages root ────────────────────────

def test_template_auto_routing_cannot_leave_the_templates_root(project_dir):
    status, body, _ = _dispatch("GET", "/hello")
    assert status == 200 and b"PAGE-OK" in body
    for path in ("/../partial_secret", "/../../outside", "/sub/../../partial_secret"):
        status, body, _ = _dispatch("GET", path)
        assert b"PARTIAL-LEAK" not in body, f"{path} rendered a template outside pages/"
        assert b"ROOT-LEAK" not in body, f"{path} rendered a file outside the templates root"


# ── Registration must retain the debug gate ───────────────────────────────

def test_register_does_not_mount_an_ungated_dev_route(project_dir, monkeypatch):
    from tina4_python import dev_admin
    dev_admin.register()
    monkeypatch.setenv("TINA4_DEBUG", "false")
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt")
    assert status == 404
    assert b"public-readme" not in body


def test_matching_fetch_metadata_does_not_override_a_foreign_origin(project_dir):
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt",
        headers={"host": "localhost:7145", "sec-fetch-site": "same-origin", "origin": "https://localhost:7145"})
    assert status == 403
    assert b"public-readme" not in body


@pytest.mark.parametrize("headers", [{"host": "foreign.example"}, {"host": "localhost", "origin": "https://foreign.example"}])
def test_dedicated_token_does_not_bypass_host_or_origin(project_dir, monkeypatch, headers):
    monkeypatch.setenv("TINA4_MCP_TOKEN", "synthetic-token")
    status, body, _ = _dispatch("GET", "/__dev/api/file?path=readme.txt", client=("203.0.113.9", 5555),
        headers={**headers, "authorization": "Bearer synthetic-token"})
    assert status == 403
    assert b"public-readme" not in body


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "POST"])
def test_every_dev_method_requires_raw_peer_trust(project_dir, method):
    status, body, _ = _dispatch(method, "/__dev/api/file?path=readme.txt", client=("203.0.113.9", 5555),
        headers={"x-forwarded-for": "127.0.0.1", "host": "localhost"})
    assert status == 403
    assert b"public-readme" not in body
