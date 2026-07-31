# RFC 9110 s9.3.2: a HEAD response MUST NOT carry content. On EVERY path.
"""
Python already behaves correctly; this LOCKS IT IN, because Ruby did not.

Ruby stripped the body for a routed response, a 404 and a 405, but NOT for a
static asset - its static and swagger branches returned early and skipped the
strip. Measured 2026-07-31: Ruby returned 15 bytes where Python, PHP and Node
all returned 0.

Why it matters beyond conformance: HEAD is what link checkers, monitoring
probes and cache validators use precisely to AVOID transferring the body. A
HEAD that returns the body makes every one of those checks cost a full
download, silently.

Driven through the REAL ASGI app: the body is assembled from the
http.response.body messages, which is where a leak would actually show. A test
that stopped at handle() would be measuring the wrong layer - the mistake this
suite's sibling made earlier in this feature.

Same case names in all four frameworks.
"""
import asyncio

import pytest

from tina4_python.core.router import Router, get as route_get
from tina4_python.core.server import app


@pytest.fixture(autouse=True)
def _workspace(tmp_path, monkeypatch):
    (tmp_path / "src" / "public").mkdir(parents=True)
    (tmp_path / "src" / "public" / "asset.css").write_text("body { color: red; }")
    monkeypatch.chdir(tmp_path)
    Router.clear()

    @route_get("/routed")
    async def _routed(request, response):
        return response("hello from the route")

    yield tmp_path
    Router.clear()


def drive(method, path):
    """Return (status, body_bytes, headers) from the real ASGI app."""
    sent = []
    scope = {"type": "http", "method": method, "path": path, "query_string": b"",
             "headers": [], "client": ("127.0.0.1", 1)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], body, headers


def test_a_head_on_a_static_asset_carries_no_body():
    status, body, _ = drive("HEAD", "/asset.css")
    assert status == 200, "the static asset was not served at all"
    assert len(body) == 0, (
        f"HEAD returned {len(body)} bytes of the file - RFC 9110 s9.3.2 forbids "
        f"content in a HEAD response"
    )


def test_a_head_on_a_routed_response_carries_no_body():
    status, body, _ = drive("HEAD", "/routed")
    assert status == 200
    assert len(body) == 0


def test_a_head_on_a_404_carries_no_body():
    status, body, _ = drive("HEAD", "/definitely/not/a/route")
    assert status == 404
    assert len(body) == 0


def test_a_head_still_reports_the_content_length_the_get_would_have_sent(_workspace):
    """
    s9.3.2 SHOULD: the same headers as the equivalent GET. That is the whole
    point of a HEAD probe - a size estimate without the transfer.
    """
    _status, _body, headers = drive("HEAD", "/asset.css")
    assert "content-length" in headers, "HEAD dropped Content-Length, so the probe learns nothing"
    assert int(headers["content-length"]) == (_workspace / "src" / "public" / "asset.css").stat().st_size


def test_a_get_on_a_static_asset_still_returns_the_body():
    """NEGATIVE: stripping HEAD must not have broken GET."""
    status, body, _ = drive("GET", "/asset.css")
    assert status == 200
    assert b"color: red" in body
