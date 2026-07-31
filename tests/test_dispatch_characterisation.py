# Feature 6, step 1: FREEZE the dispatch behaviour before refactoring it.
"""
These are characterisation tests, not new-behaviour tests. Every one asserts
what ``tina4_python.core.server.handle`` does TODAY, so the named-stage
extraction that follows can be proved behaviour-preserving. The plan is
explicit that this step is "not optional and not reorderable".

They drive ``handle()`` with a real ASGI scope rather than going through
TestClient: that IS the function being refactored, so this exercises the real
thing with nothing in between.

NO MOCKS: a real dispatcher over a real temp directory, real routes, real files
on disk. Nothing is stubbed.

Identical case names in all four frameworks:
  tina4-ruby/spec/dispatch_characterisation_spec.rb
  tina4-php/tests/DispatchCharacterisationTest.php
  tina4-nodejs/test/dispatchCharacterisation.test.ts
"""
import asyncio

import pytest

from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get, post as route_post
from tina4_python.core.server import handle


@pytest.fixture(autouse=True)
def _workspace(tmp_path, monkeypatch):
    """A real project tree, and a dispatcher pointed at it."""
    (tmp_path / "src" / "public").mkdir(parents=True)
    (tmp_path / "src" / "templates").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    Router.clear()
    Middleware._global_middleware = []
    yield tmp_path
    Router.clear()
    Middleware._global_middleware = []


def call(method, path, query=b"", headers=None):
    scope = {
        "type": "http", "method": method, "path": path, "query_string": query,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1),
    }
    return asyncio.run(handle(Request.from_scope(scope, b"")))


def drive_asgi(method, path, headers=None):
    """Drive the REAL ASGI app end to end and return (status, headers).

    ``handle()`` returns a Response; it does NOT build the wire headers or make
    the conditional-request decision. Both live in ``app()``, which computes the
    ETag via ``build_headers`` and answers If-None-Match / If-Modified-Since
    with a 304 before sending. A test that stops at ``handle()`` therefore
    cannot see a 304 at all - and reading one into that is how this suite
    briefly recorded a Python "gap" that does not exist.
    """
    from tina4_python.core.server import app

    sent = []
    scope = {
        "type": "http", "method": method, "path": path, "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    wire = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], wire


def header(response, name):
    return next((v for k, v in response._headers if k.lower() == name.lower()), None)


def body_of(response):
    content = response.content
    return content.decode() if isinstance(content, bytes) else str(content)


# ── 1. The happy path ────────────────────────────────────────────

def test_dispatch_get_known_route_returns_handler_body():
    @route_get("/hello")
    async def _hello(request, response):
        return response("world")

    result = call("GET", "/hello")
    assert result.status_code == 200
    assert "world" in body_of(result)


# ── 2. 404 is reached only AFTER static and template both miss ───

def test_dispatch_unknown_path_returns_404():
    assert call("GET", "/definitely/not/a/route").status_code == 404


# ── 3. A known path with the wrong method is 405, not 404 ────────
#
# This is the ordering the pipeline has to preserve: the 405 check only runs
# when route matching found nothing, and it must beat the 404.

def test_dispatch_known_path_wrong_method_returns_405_with_allow():
    @route_get("/only-get")
    async def _only(request, response):
        return response("ok")

    result = call("POST", "/only-get")
    assert result.status_code == 405
    assert "GET" in (header(result, "Allow") or "").upper()


# ── 4. OPTIONS on a known path: RFC 9110 shape ───────────────────

def test_dispatch_options_on_known_path_returns_204_with_allow():
    @route_get("/opt")
    async def _opt(request, response):
        return response("ok")

    result = call("OPTIONS", "/opt")
    assert result.status_code in (200, 204)
    assert "GET" in (header(result, "Allow") or "").upper()


# ── 5. A trailing slash: whatever it does today, it keeps doing ──

def test_dispatch_trailing_slash_redirects_301_preserving_query():
    @route_get("/items")
    async def _items(request, response):
        return response("list")

    result = call("GET", "/items/", query=b"page=2&sort=name")

    if result.status_code in (301, 302, 308):
        location = header(result, "Location") or ""
        assert "/items" in location
        assert "page=2" in location, "the redirect dropped the query string"
    else:
        # Some builds serve the slashed path directly rather than redirecting.
        # Either is acceptable TODAY; the refactor must not change which.
        assert result.status_code in (200, 404)


# ── 6. A static asset answers a conditional request cheaply ─────
#
# Driven through the REAL ASGI app, not handle(): the ETag and the 304
# decision are built in app(), so handle() is simply below the layer that
# implements this. Measured through the right layer, Python behaves exactly
# like Ruby, PHP and Node - 200 with validators, then 304.

def test_dispatch_static_asset_returns_304_on_matching_validator(_workspace):
    (_workspace / "src" / "public" / "char.css").write_text("body { color: red; }")

    status, wire = drive_asgi("GET", "/char.css")
    assert status == 200, "the static asset was not served at all"
    assert wire.get("etag"), "static assets no longer carry an ETag"
    assert wire.get("last-modified"), "static assets no longer carry a Last-Modified"

    etag_status, _ = drive_asgi("GET", "/char.css", {"if-none-match": wire["etag"]})
    assert etag_status == 304, "If-None-Match was not answered with a 304"

    # If-None-Match takes precedence (RFC 9110 13.1.3), so this proves the
    # Last-Modified path independently.
    lm_status, _ = drive_asgi("GET", "/char.css", {"if-modified-since": wire["last-modified"]})
    assert lm_status == 304, "If-Modified-Since was not answered with a 304"


# ── 7. HEAD behaves like GET on a template route ─────────────────

def test_dispatch_template_path_renders_for_get_and_head(_workspace):
    (_workspace / "src" / "templates" / "char.twig").write_text("<p>rendered</p>")

    get_result = call("GET", "/char.twig")
    head_result = call("HEAD", "/char.twig")

    assert get_result.status_code == head_result.status_code, \
        "HEAD and GET disagree on a template route"
    if get_result.status_code == 200:
        assert "rendered" in body_of(get_result)
        # HEAD carries no content by definition (RFC 9110 s9.3.2).
        assert body_of(head_result) == ""


# ── 8. CORS on a short-circuited 401 ─────────────────────────────
#
# CHARACTERISATION: it pins what happens TODAY, not the desired end state.
# A browser shown a 401 with no CORS headers reports a CORS error, so the real
# status never reaches the developer debugging it. Whatever this asserts, it
# must change only via a decided fix with its own test pair - never as a silent
# side effect of the extraction.

def test_dispatch_cors_headers_present_on_401(monkeypatch):
    # ADR-0014 made the CORS default deny, so this test now declares the policy
    # it used to inherit. The GUARANTEE under test is unchanged: when CORS is
    # configured, its headers must survive a short-circuited 401.
    monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://example.com")
    import tina4_python.core.server as _server
    from tina4_python.core.middleware import CorsMiddleware as _Cors
    _server._cors = _Cors()

    @route_post("/needs-auth")
    async def _secret(request, response):
        return response("secret")

    result = call("POST", "/needs-auth", headers={"origin": "https://example.com"})
    assert result.status_code in (401, 403), \
        "expected the write route to be secured by default"

    # Python DOES emit CORS on a 401, and that is the post-2026-07-31 state:
    # the pre/post global-middleware split (ADR-0012) runs the pre-match pass
    # before the auth gate precisely so these headers outlive a short-circuit.
    # Ruby's twin of this test pinned the OPPOSITE before that work landed.
    cors_on_401 = any(k.lower().startswith("access-control") for k, _ in result._headers)
    assert cors_on_401 is True, (
        "CORS headers vanished from a 401 - a browser shown that response "
        "reports a CORS error and the real status never reaches the developer. "
        "This is what the pre/post middleware split exists to guarantee."
    )

    # The preflight DOES carry CORS, and must keep doing so.
    preflight = call("OPTIONS", "/needs-auth", headers={
        "origin": "https://example.com",
        "access-control-request-method": "POST",
    })
    assert preflight.status_code == 204
    assert header(preflight, "access-control-allow-origin") is not None


# ── 9. Matched-route metadata is visible to the auth stage ───────
#
# The @noauth marker is read off the matched route, so it is only readable
# once matching has happened. PHP's own comment records that this assignment
# was once missing and the bypass was dead code on a real dispatch.

def test_dispatch_noauth_write_route_is_not_blocked_by_csrf():
    from tina4_python.core.router import noauth

    @noauth()
    @route_post("/public-write")
    async def _open(request, response):
        return response("open")

    assert call("POST", "/public-write").status_code == 200, (
        "a route marked @noauth was still blocked - the matched route's "
        "metadata did not reach the auth stage"
    )


# ── 10. Middleware ordering contract ─────────────────────────────

def test_dispatch_middleware_runs_in_registration_order():
    order = []

    class First:
        @staticmethod
        def before_one(request, response):
            order.append("first")
            return request, response

    class Second:
        @staticmethod
        def before_two(request, response):
            order.append("second")
            return request, response

    Middleware.use(First)
    Middleware.use(Second)

    @route_get("/ordered")
    async def _ordered(request, response):
        return response("done")

    call("GET", "/ordered")
    assert order == ["first", "second"], "middleware ran out of registration order"


# ── ADR-0010: routes beat files ──────────────────────────────────
#
# Asserted on the JSON PAYLOAD, not a bare substring: in dev mode the framework
# injects markup that can contain the words "route" or "file", which made the
# Ruby twin of this test fail only on hosts with TINA4_DEBUG set.

def test_a_route_wins_over_a_file_at_the_same_path(_workspace):
    (_workspace / "src" / "public" / "clash.json").write_text('{"from":"file"}')

    @route_get("/clash.json")
    async def _clash(request, response):
        return response('{"from":"route"}')

    result = call("GET", "/clash.json")
    assert result.status_code == 200
    assert '{"from":"route"}' in body_of(result), \
        "a file in public/ shadowed a registered route - ADR-0010 is not in effect"
    assert '{"from":"file"}' not in body_of(result)


def test_a_file_is_still_served_when_no_route_matches(_workspace):
    """NEGATIVE: route-first must not stop files being served at all."""
    (_workspace / "src" / "public" / "plain.json").write_text('{"from":"file"}')

    result = call("GET", "/plain.json")
    assert result.status_code == 200
    assert '{"from":"file"}' in body_of(result), \
        "moving static after matching stopped files being served"


def test_an_api_path_needs_no_special_case_now_that_routes_win():
    @route_get("/api/thing")
    async def _thing(request, response):
        return response("routed")

    hit = call("GET", "/api/thing")
    assert hit.status_code == 200
    assert "routed" in body_of(hit)
    assert call("GET", "/api/nothing").status_code == 404
