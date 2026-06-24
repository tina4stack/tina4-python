"""Behavioural tests for Server cross-framework parity: handle(), start(), stop().

Mirrors tina4-ruby spec/server_parity_spec.rb and tina4-nodejs
test/serverParity.test.ts: handle() dispatches a real Request through the
router and returns the handler's Response; start() binds a real port and serves
a real loopback request; stop() shuts the listener down and releases the port.
No mocks - handle() runs in-process, start()/stop() run in a real child server
(Python's stop() sends SIGTERM to its own process, so it cannot be exercised
in-process without killing the test runner).
"""

import socket
import subprocess
import sys
import time
import http.client
from pathlib import Path

import pytest

from tina4_python.core.request import Request
from tina4_python.core.router import Router
from tina4_python.core.server import handle

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_request(method: str, path: str, headers: dict | None = None) -> Request:
    req = Request()
    req.method = method.upper()
    req.path = path
    req.headers = headers or {}
    return req


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def test_handle_dispatches_a_real_request():
    """handle() routes a real Request through the router and returns the
    handler's actual Response (not just that the symbol is callable)."""
    Router.clear()

    async def handler(req, res):
        return res.json({"pong": True, "framework": "tina4-python"})

    Router.get("/__parity/ping", handler)
    try:
        resp = await handle(_make_request("GET", "/__parity/ping"))
        assert resp.status_code == 200
        assert "application/json" in (resp.content_type or "")
        body = resp.content.decode() if isinstance(resp.content, (bytes, bytearray)) else resp.content
        assert '"pong"' in body and "true" in body.lower()
    finally:
        Router.clear()


def _http_get(port: int, path: str, timeout: float = 5.0):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, r.read().decode("utf-8", "replace")
    finally:
        conn.close()


def _port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def test_start_serves_a_real_route_then_stop_releases_the_port(tmp_path):
    """start() binds the port and serves a real request; stop() shuts the
    listener down and releases the port - exercised in a real child server."""
    port = _free_port()
    proj = tmp_path / "srv"
    (proj / "src" / "routes").mkdir(parents=True)
    # A real app: register routes, then start() the server (a thin wrapper around
    # run()). /__parity/shutdown calls stop() on a short delay so the response is
    # flushed before SIGTERM lands.
    (proj / "app.py").write_text(
        "import threading, time\n"
        "from tina4_python import get\n"
        "from tina4_python.core.server import start, stop\n\n"
        "@get('/__parity/ping')\n"
        "async def ping(request, response):\n"
        "    return response('pong')\n\n"
        "@get('/__parity/shutdown')\n"
        "async def shutdown(request, response):\n"
        "    threading.Thread(target=lambda: (time.sleep(0.3), stop()), daemon=True).start()\n"
        "    return response('stopping')\n\n"
        f"start(port={port}, no_browser=True, no_reload=True)\n"
    )
    env = {
        **__import__("os").environ,
        "PYTHONPATH": str(REPO_ROOT),
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_AI_PORT": "true",
        "PORT": str(port),
    }
    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=str(proj), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        # Wait for start() to bind + serve.
        deadline = time.time() + 25
        while time.time() < deadline and not _port_open(port):
            assert proc.poll() is None, "server exited during startup"
            time.sleep(0.2)
        assert _port_open(port), "start() never bound the port"

        # start() serves a real route over a real loopback connection.
        status, body = _http_get(port, "/__parity/ping")
        assert status == 200 and "pong" in body

        # Trigger stop() and confirm the listener goes away (port released).
        try:
            _http_get(port, "/__parity/shutdown")
        except Exception:
            pass
        gone_deadline = time.time() + 15
        while time.time() < gone_deadline and _port_open(port):
            time.sleep(0.2)
        assert not _port_open(port), "stop() did not release the port"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
