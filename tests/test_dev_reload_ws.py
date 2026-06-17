"""Tests for the WebSocket-primary DevReload path.

DevReload is WebSocket-primary: ``POST /__dev/api/reload`` re-imports the
changed module in-process and then broadcasts an instant reload message to
every browser connected on ``/__dev_reload``. The mtime poll is only a
fallback. These tests cover both halves:

* ``_api_reload`` invokes the WebSocket broadcast with ``path="/__dev_reload"``
  and a JSON ``{type, file, mtime}`` payload (CSS vs code distinction).
* A real browser connecting on ``/__dev_reload`` receives the broadcast
  end-to-end against a live server (no Rust CLI — the POST is issued directly,
  exactly as the CLI watcher does), and the server is not respawned.
"""
import asyncio
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Unit: _api_reload broadcasts on /__dev_reload ───────────────────────────

class _Req:
    def __init__(self, body=None):
        self.body = body or {}
        self.params = {}


def _resp_factory():
    captured = []

    def resp(data, code=200):
        captured.append((data, code))
        return data

    resp.captured = captured
    return resp


async def test_api_reload_broadcasts_reload_payload(monkeypatch):
    """A code change broadcasts type=reload on /__dev_reload with file+mtime."""
    from tina4_python.dev_admin import _api_reload
    from tina4_python.core import server

    sent = []

    async def fake_broadcast(message, exclude=None, path=None):
        sent.append({"message": message, "path": path})

    monkeypatch.setattr(server._ws_manager, "broadcast", fake_broadcast)

    req = _Req({"type": "code", "file": "src/routes/index.py"})
    result = await _api_reload(req, _resp_factory())

    assert result["ok"] is True
    assert result["type"] == "code"
    # Exactly one broadcast, on the dev-reload path.
    assert len(sent) == 1
    assert sent[0]["path"] == "/__dev_reload"
    payload = json.loads(sent[0]["message"])
    assert payload["type"] == "reload"  # code normalised to reload on the wire
    assert payload["file"] == "src/routes/index.py"
    assert isinstance(payload["mtime"], int)


async def test_api_reload_broadcasts_css_type(monkeypatch):
    """A CSS change broadcasts type=css so the client swaps stylesheets."""
    from tina4_python.dev_admin import _api_reload
    from tina4_python.core import server

    sent = []

    async def fake_broadcast(message, exclude=None, path=None):
        sent.append({"message": message, "path": path})

    monkeypatch.setattr(server._ws_manager, "broadcast", fake_broadcast)

    req = _Req({"type": "css", "file": "src/public/css/app.css"})
    await _api_reload(req, _resp_factory())

    assert len(sent) == 1
    payload = json.loads(sent[0]["message"])
    assert payload["type"] == "css"
    assert payload["file"] == "src/public/css/app.css"


async def test_api_reload_survives_broadcast_failure(monkeypatch):
    """A broadcast exception never 500s the reload endpoint."""
    from tina4_python.dev_admin import _api_reload
    from tina4_python.core import server

    async def boom(message, exclude=None, path=None):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(server._ws_manager, "broadcast", boom)

    req = _Req({"type": "code", "file": "src/routes/x.py"})
    result = await _api_reload(req, _resp_factory())
    assert result["ok"] is True  # endpoint still succeeds


async def test_dev_reload_ws_route_registered():
    """Registering the /__dev_reload route makes it matchable (debug mode)."""
    from tina4_python.core.router import Router
    from tina4_python.core.server import _register_dev_reload_ws

    _register_dev_reload_ws()
    route, _params = Router.match_ws("/__dev_reload")
    assert route is not None
    assert route["path"] == "/__dev_reload"


# ── Integration: live server, real WebSocket round-trip ─────────────────────

def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _ws_recv_one(host, port, path, timeout):
    """Connect a raw RFC 6455 client, return (connected, first_text_payload)."""
    reader, writer = await asyncio.open_connection(host, port)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write(req.encode())
    await writer.drain()
    resp = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    if b"101" not in resp.split(b"\r\n")[0]:
        writer.close()
        return False, None
    # Read one frame.
    b1 = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
    length = b1[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]
    if b1[1] & 0x80:  # masked (servers don't mask, but be safe)
        await reader.readexactly(4)
    payload = await reader.readexactly(length) if length else b""
    writer.close()
    return True, payload.decode("utf-8", errors="replace")


def _post_reload(host, port, body):
    import http.client
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("POST", "/__dev/api/reload", json.dumps(body),
                 {"Content-Type": "application/json"})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def _http_get(host, port, path):
    import http.client
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    data = r.read().decode("utf-8", errors="replace")
    conn.close()
    return r.status, data


async def test_live_ws_reload_roundtrip(tmp_path):
    """End-to-end: edit a route, POST reload, browser WS receives it; no respawn."""
    # Scaffold a throwaway project that imports the framework under test.
    proj = tmp_path / "app"
    routes = proj / "src" / "routes"
    routes.mkdir(parents=True)
    (proj / ".env").write_text(
        "TINA4_DEBUG=true\nTINA4_LOG_LEVEL=ERROR\nTINA4_OVERRIDE_CLIENT=true\n"
    )
    (proj / "app.py").write_text("from tina4_python.core import run\nrun()\n")
    index = routes / "index.py"
    index.write_text(
        "from tina4_python import get\n\n\n"
        "@get('/')\nasync def home(request, response):\n"
        "    return response('<h1>Version 1</h1>')\n"
    )

    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["TINA4_NO_BROWSER"] = "true"
    env["TINA4_SUPPRESS"] = "true"
    env["TINA4_NO_AI_PORT"] = "true"  # don't also claim port+1000
    env["PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(proj), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        # Wait for the server to accept connections.
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            try:
                status, body = _http_get("127.0.0.1", port, "/")
                if status == 200 and "Version 1" in body:
                    ready = True
                    break
            except OSError:
                pass
            await asyncio.sleep(0.2)
        assert ready, "server did not start serving Version 1"
        assert proc.poll() is None, "server process exited during startup"
        pid_before = proc.pid

        # Connect a browser-like WS client; once it's up, edit + POST.
        async def _client():
            return await _ws_recv_one("127.0.0.1", port, "/__dev_reload", timeout=15)

        client_task = asyncio.create_task(_client())
        await asyncio.sleep(0.5)  # let the upgrade complete and register

        # Edit the handler V1 -> V2 on disk, then POST the reload the CLI would.
        # Bump the mtime explicitly so the in-process re-import (which is
        # mtime-gated) detects the change regardless of filesystem timestamp
        # granularity — a real editor save always advances mtime.
        index.write_text(
            "from tina4_python import get\n\n\n"
            "@get('/')\nasync def home(request, response):\n"
            "    return response('<h1>Version 2</h1>')\n"
        )
        future = time.time() + 5
        os.utime(index, (future, future))
        status, _ = _post_reload("127.0.0.1", port, {"type": "code", "file": "src/routes/index.py"})
        assert status == 200

        connected, payload = await asyncio.wait_for(client_task, timeout=15)
        # (a) WS client received the broadcast.
        assert connected, "WebSocket handshake failed (/__dev_reload not registered?)"
        assert payload is not None
        msg = json.loads(payload)
        assert msg["type"] == "reload"
        assert msg["file"] == "src/routes/index.py"

        # (b) In-process re-import — V2 is served, no restart.
        status, body = _http_get("127.0.0.1", port, "/")
        assert status == 200
        assert "Version 2" in body

        # (c) Same process — no respawn.
        assert proc.poll() is None
        assert proc.pid == pid_before
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
