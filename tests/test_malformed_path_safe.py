"""Malformed request paths must not crash the worker (#33 lock-in, Python-safe).

nodejs #33: ``GET //`` (also ``///``, ``/\\``) crashed the Node worker in
PRODUCTION because ``new URL(req.url, base)`` threw ``ERR_INVALID_URL`` before
the dispatch try/catch, and the ``uncaughtException`` net only registered under
``TINA4_DEBUG`` — an unauthenticated remote DoS (scanners send ``//`` routinely).

Python is verified SAFE: it takes the path as an opaque ASGI ``scope["path"]``
string with no throwing URL parser, plus per-request isolation, so a malformed
path is just a route miss -> a clean 4xx. This test locks that in against a
regression, at two layers, with NO mocks:

* the in-process ``TestClient`` (real ``Router.match``), and
* the REAL ASGI ``app`` entry point (``Request.from_scope`` + ``handle`` — the
  exact code uvicorn/hypercorn/granian drive), asserting a 4xx AND that the
  worker still serves the NEXT request (the Node bug killed the process here).
"""
from __future__ import annotations

import pytest

from tina4_python.core.router import get
from tina4_python.core.server import app
from tina4_python.test_client import TestClient

# The paths a scanner throws at a server; each crashed the Node worker (#33).
MALFORMED_PATHS = ["//", "///", "/\\", "//evil.com"]


async def _drive_asgi(method: str, path: str, body: bytes = b""):
    """Drive the real ASGI ``app`` with a raw scope path, exactly as an ASGI
    server would, and return ``(status, body_bytes)``. Raises if ``app`` does."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)

    status = next(
        (m["status"] for m in sent if m.get("type") == "http.response.start"),
        None,
    )
    body_bytes = b"".join(
        m.get("body", b"") for m in sent if m.get("type") == "http.response.body"
    )
    return status, body_bytes


class TestMalformedPathIsSafe:
    def setup_method(self, _method):
        # A real route registered fresh each test so the "worker still serves
        # the next request" assertion is meaningful (immune to suites that
        # clear the route registry between tests).
        @get("/__issue33/alive")
        async def _alive(request, response):
            return response({"ok": True})

    @pytest.mark.parametrize("path", MALFORMED_PATHS)
    def test_testclient_malformed_path_returns_4xx(self, path):
        """In-process dispatch of a malformed path is a clean route miss, not
        a raise."""
        res = TestClient().get(path)
        assert 400 <= res.status < 500, \
            f"{path!r} must be a 4xx route miss, got {res.status}"

    @pytest.mark.parametrize("path", MALFORMED_PATHS)
    async def test_asgi_app_malformed_path_does_not_crash(self, path):
        """The real ASGI entry point returns a 4xx and never raises on a
        malformed opaque path."""
        status, _ = await _drive_asgi("GET", path)
        assert status is not None and 400 <= status < 500, \
            f"{path!r} must yield a 4xx from the ASGI app, got {status}"

    async def test_worker_survives_and_serves_next_request(self):
        """A malformed path followed by a normal one on the same app: the
        worker must still serve the good route (the Node process died here)."""
        bad_status, _ = await _drive_asgi("GET", "//")
        assert 400 <= bad_status < 500

        good_status, good_body = await _drive_asgi("GET", "/__issue33/alive")
        assert good_status == 200, "worker did not survive the malformed request"
        assert b'"ok"' in good_body
