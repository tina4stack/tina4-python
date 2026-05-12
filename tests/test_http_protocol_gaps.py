"""
RFC 9110 conformance — HTTP method handling gaps in tina4-python's Router.

Same regression class as tina4-php#135's sibling and the 24stack v3.11.36
report against tina4-php: `Router.get('/foo')` returns 404 on HEAD instead
of serving GET-without-body.

Tests are written BEFORE the fix lands — expect failures on 3.12.6, all
green after the patch. Mirrors tests/HttpProtocolGapsTest.php so the
cross-framework contract stays identical.
"""

import pytest

from tina4_python.core.request import Request
from tina4_python.core.router import Router
from tina4_python.core.server import handle


@pytest.fixture(autouse=True)
def clear_routes():
    Router.clear()
    yield
    Router.clear()


def _make_request(method: str, path: str, headers: dict | None = None) -> Request:
    """Build a Request matching what the ASGI/socket layer would produce."""
    req = Request()
    req.method = method.upper()
    req.path = path
    req.headers = headers or {}
    return req


async def _dispatch(method: str, path: str, headers: dict | None = None):
    return await handle(_make_request(method, path, headers))


def _header(resp, name: str) -> str | None:
    """Case-insensitive header lookup against Response._headers (list of
    (name, value) tuples). Returns None if absent.
    """
    target = name.lower()
    for h_name, h_value in getattr(resp, "_headers", []):
        if h_name.lower() == target:
            return h_value
    return None


# ── Group 1: HEAD auto-fallback to GET ────────────────────────────────


async def test_head_on_get_route_returns_200():
    async def handler(req, res):
        return res.json({"ok": True})

    Router.get("/welcome", handler)

    resp = await _dispatch("HEAD", "/welcome")
    assert resp.status_code == 200, (
        "HEAD MUST succeed on every route registered as GET (RFC 9110 §9.3.2)"
    )


async def test_head_response_body_is_empty():
    async def handler(req, res):
        return res.json({"heavy": "x" * 5000})

    Router.get("/welcome", handler)

    resp = await _dispatch("HEAD", "/welcome")
    body = resp.content if isinstance(resp.content, (bytes, bytearray)) else (resp.content or b"")
    assert body == b"" or body == "", (
        "RFC 9110 §9.3.2: server MUST NOT send content in a HEAD response"
    )


async def test_head_carries_same_content_type_as_get():
    async def handler(req, res):
        return res.json({"ok": True})

    Router.get("/welcome", handler)

    resp = await _dispatch("HEAD", "/welcome")
    assert "application/json" in (resp.content_type or ""), (
        "HEAD SHOULD send the same headers the GET would have sent"
    )


async def test_head_on_nonexistent_path_still_404():
    async def handler(req, res):
        return res.json({"ok": True})

    Router.get("/welcome", handler)

    resp = await _dispatch("HEAD", "/does/not/exist")
    assert resp.status_code == 404


async def test_head_on_post_only_path_returns_405():
    async def handler(req, res):
        return res.json({"created": True})

    Router.post("/submit", handler)

    resp = await _dispatch("HEAD", "/submit")
    assert resp.status_code == 405, (
        "HEAD only auto-falls back to GET, never to other methods"
    )
    allow = _header(resp, "Allow") or ""
    assert "POST" in allow, "405 MUST include Allow listing real methods"


# ── Group 2: 405 Method Not Allowed + Allow header ────────────────────


async def test_wrong_method_on_existing_path_returns_405_not_404():
    async def handler(req, res):
        return res.json({"ok": True})

    Router.post("/submit", handler)

    resp = await _dispatch("GET", "/submit")
    assert resp.status_code == 405, (
        "RFC 9110 §15.5.6: wrong method on existing path is 405, not 404"
    )


async def test_405_includes_allow_header_listing_valid_methods():
    async def h(req, res):
        return res.json({})

    Router.get("/x", h)
    Router.post("/x", h)

    resp = await _dispatch("PUT", "/x")
    assert resp.status_code == 405

    allow = _header(resp, "Allow") or ""
    allowed = [m.strip() for m in allow.split(",")]
    assert "GET" in allowed, "Allow MUST list every supported method (RFC 9110 §10.2.1)"
    assert "POST" in allowed
    assert "PUT" not in allowed, "PUT is what was asked — must NOT be in Allow"


async def test_allow_includes_head_and_options_when_get_registered():
    async def h(req, res):
        return res.json({})

    Router.get("/page", h)

    resp = await _dispatch("PUT", "/page")
    assert resp.status_code == 405

    allow = _header(resp, "Allow") or ""
    allowed = [m.strip() for m in allow.split(",")]
    assert "GET" in allowed
    assert "HEAD" in allowed, "HEAD MUST appear in Allow whenever GET is registered"
    assert "OPTIONS" in allowed, "OPTIONS MUST appear in Allow for any path the router knows about"


# ── Group 3: Generic OPTIONS handler ───────────────────────────────────


async def test_options_on_existing_path_returns_204():
    async def h(req, res):
        return res.json({})

    Router.get("/foo", h)

    resp = await _dispatch("OPTIONS", "/foo")
    assert resp.status_code == 204, (
        "RFC 9110 §9.3.7: OPTIONS on an existing resource returns 204 No Content"
    )


async def test_options_allow_includes_all_registered_methods():
    async def h(req, res):
        return res.json({})

    Router.get("/r", h)
    Router.post("/r", h)
    Router.delete("/r", h)

    resp = await _dispatch("OPTIONS", "/r")
    allow = _header(resp, "Allow") or ""
    allowed = [m.strip() for m in allow.split(",")]

    for expected in ("GET", "POST", "DELETE", "HEAD", "OPTIONS"):
        assert expected in allowed, f"OPTIONS Allow header missing {expected}"
    assert "PUT" not in allowed
    assert "PATCH" not in allowed


async def test_options_on_nonexistent_path_returns_404():
    async def h(req, res):
        return res.json({})

    Router.get("/exists", h)

    resp = await _dispatch("OPTIONS", "/does/not/exist")
    assert resp.status_code == 404


# ── Group 4: TRACE / CONNECT explicit rejection ────────────────────────


async def test_trace_returns_405_on_existing_path():
    async def h(req, res):
        return res.json({})

    Router.get("/x", h)

    resp = await _dispatch("TRACE", "/x")
    assert resp.status_code == 405, (
        "TRACE on an existing path must be 405; we never support TRACE (security)"
    )
    allow = _header(resp, "Allow") or ""
    assert "TRACE" not in [m.strip() for m in allow.split(",")]


async def test_connect_returns_405_on_existing_path():
    async def h(req, res):
        return res.json({})

    Router.get("/x", h)

    resp = await _dispatch("CONNECT", "/x")
    assert resp.status_code == 405, (
        "CONNECT is for proxies; an origin server must reject it"
    )
    allow = _header(resp, "Allow") or ""
    assert "CONNECT" not in [m.strip() for m in allow.split(",")]


# ── Group 5: Explicit head() / options() registration ─────────────────


async def test_explicit_head_route_is_honoured():
    async def get_handler(req, res):
        return res.json({"from": "get"})

    async def head_handler(req, res):
        res.header("X-Probe-Source", "custom-head")
        return res.json({})

    Router.get("/probe", get_handler)
    Router.head("/probe", head_handler)

    resp = await _dispatch("HEAD", "/probe")
    assert resp.status_code == 200
    assert _header(resp, "X-Probe-Source") == "custom-head", (
        "Explicit Router.head() registration must override the GET auto-fallback"
    )


async def test_explicit_options_route_is_honoured():
    async def get_h(req, res):
        return res.json({})

    async def options_h(req, res):
        res.header("X-Custom-Options", "yes")
        return res.json({"custom": True})

    Router.get("/cfg", get_h)
    Router.options("/cfg", options_h)

    resp = await _dispatch("OPTIONS", "/cfg")
    assert _header(resp, "X-Custom-Options") == "yes", (
        "Explicit Router.options() registration must override the generic 204 handler"
    )


# ── Group 6: HEAD body strip is unconditional ─────────────────────────


async def test_explicit_head_handler_body_also_stripped():
    async def head_h(req, res):
        return res.json({"accidentally": "returned a body"})

    Router.head("/x", head_h)

    resp = await _dispatch("HEAD", "/x")
    assert resp.status_code == 200
    body = resp.content if isinstance(resp.content, (bytes, bytearray)) else (resp.content or b"")
    assert body == b"" or body == "", (
        "HEAD body strip is unconditional — RFC 9110 §9.3.2 is a MUST, not a SHOULD"
    )


async def test_head_response_still_has_content_length():
    async def h(req, res):
        return res.json({"msg": "hi"})

    Router.get("/sized", h)

    resp = await _dispatch("HEAD", "/sized")
    cl = _header(resp, "Content-Length")
    assert cl is not None, "HEAD SHOULD set Content-Length to what GET would have sent"
    assert int(cl) > 0, "Content-Length must reflect the actual body size, not 0"
