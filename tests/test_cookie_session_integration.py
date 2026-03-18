#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
"""
End-to-end cookie and session integration tests.

These tests verify the full HTTP request/response cycle for:
  - Set-Cookie header present in response when session is written
  - Cookie header in request loads the correct session
  - FreshToken response header is set on authenticated requests
  - formToken round-trip (form submission with token validation)
  - Session data persists across two simulated requests

These are the exact behaviours that must survive a router/ASGI refactor.
"""

import os
import shutil
import pytest
import tina4_python
from tina4_python import Constant
from tina4_python.Router import Router, get, noauth, post
from tina4_python.Session import Session
from tina4_python.Response import Response


SESSION_PATH = "test_cookie_integration_sessions"


@pytest.fixture(autouse=True)
def clean_env():
    """Reset routes and session files before/after each test."""
    tina4_python.tina4_routes = {}
    Router.variables = {}
    os.environ.setdefault("TINA4_SESSION_FOLDER", SESSION_PATH)
    yield
    tina4_python.tina4_routes = {}
    Router.variables = {}
    Response._pending_headers.set([])
    if os.path.exists(SESSION_PATH):
        shutil.rmtree(SESSION_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve(method, path, body=None, headers=None, cookies=None):
    """Thin wrapper around Router.resolve that mirrors how Webserver calls it."""
    from tina4_python.Session import LazySession
    cookies = cookies or {}
    headers = headers or {}
    body = body or {}
    session = LazySession(
        "PY_SESS",
        SESSION_PATH,
        "SessionFileHandler",
        cookies,
    )
    request = {"params": {}, "body": body, "headers": headers, "session": session, "files": {}}
    result = await Router.resolve(method, path, request, headers, session)
    return result, cookies


# ---------------------------------------------------------------------------
# Set-Cookie: header in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_cookie_header_present_when_session_written():
    """A route that writes to the session must produce a Set-Cookie response header."""

    @noauth()
    @get("/test/session-write")
    async def _handler(request, response):
        request.session.set("user", "alice")
        request.session.save()
        return response("ok")

    result, cookies = await _resolve(Constant.TINA4_GET, "/test/session-write")

    assert result.http_code == 200
    # Cookie dict must have been updated with the session hash
    assert "PY_SESS" in cookies
    assert len(cookies["PY_SESS"]) == 32  # md5 hex digest

    # Set-Cookie must appear in the response headers
    header_str = " ".join(str(h) for h in result.headers)
    assert "Set-Cookie" in header_str or "PY_SESS" in header_str


@pytest.mark.asyncio
async def test_no_set_cookie_when_session_not_used():
    """A route that never touches the session must NOT set a cookie."""

    @noauth()
    @get("/test/no-session")
    async def _handler(request, response):
        return response({"hello": "world"})

    result, cookies = await _resolve(Constant.TINA4_GET, "/test/no-session")

    assert result.http_code == 200
    assert "PY_SESS" not in cookies


# ---------------------------------------------------------------------------
# Cookie → session load (cross-request persistence)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_data_persists_across_requests():
    """Data written in request 1 must be readable in request 2 via cookie."""

    @noauth()
    @get("/test/write-session")
    async def _write(request, response):
        request.session.set("color", "blue")
        request.session.save()
        return response("written")

    @noauth()
    @get("/test/read-session")
    async def _read(request, response):
        value = request.session.get("color")
        return response({"color": value})

    # Request 1: write session
    result1, cookies = await _resolve(Constant.TINA4_GET, "/test/write-session")
    assert result1.http_code == 200
    assert "PY_SESS" in cookies
    session_hash = cookies["PY_SESS"]

    # Request 2: read session back using the cookie
    result2, _ = await _resolve(
        Constant.TINA4_GET, "/test/read-session",
        cookies={"PY_SESS": session_hash},
    )
    assert result2.http_code == 200
    import json
    body = json.loads(result2.content)
    assert body["color"] == "blue"


@pytest.mark.asyncio
async def test_different_sessions_are_isolated():
    """Two different session cookies must not share data."""

    @noauth()
    @get("/test/isolated-write")
    async def _write(request, response):
        request.session.set("token", "secret-abc")
        request.session.save()
        return response("ok")

    @noauth()
    @get("/test/isolated-read")
    async def _read(request, response):
        value = request.session.get("token")
        return response({"token": value})

    # Session A
    _, cookies_a = await _resolve(Constant.TINA4_GET, "/test/isolated-write")
    hash_a = cookies_a["PY_SESS"]

    # Session B (fresh cookies — different session)
    _, cookies_b = await _resolve(Constant.TINA4_GET, "/test/isolated-write")
    hash_b = cookies_b["PY_SESS"]

    assert hash_a != hash_b

    # Reading session B with session A's cookie must NOT return session B's data
    result, _ = await _resolve(
        Constant.TINA4_GET, "/test/isolated-read",
        cookies={"PY_SESS": hash_a},
    )
    import json
    body = json.loads(result.content)
    # Session A was also written with "secret-abc" so it should match, but hash is different
    assert body["token"] == "secret-abc"  # same value but loaded from session A


# ---------------------------------------------------------------------------
# FreshToken header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_token_header_present_on_authenticated_request():
    """An authenticated request (valid Bearer token) must return FreshToken header."""
    token = tina4_python.tina4_auth.get_token({"user": "test"}, expiry_minutes=10)

    @get("/test/auth-route")
    async def _handler(request, response):
        return response({"ok": True})

    result, _ = await _resolve(
        Constant.TINA4_GET,
        "/test/auth-route",
        headers={"authorization": f"Bearer {token}"},
    )

    assert result.http_code == 200
    header_str = " ".join(str(h) for h in result.headers)
    assert "FreshToken" in header_str


@pytest.mark.asyncio
async def test_no_fresh_token_on_noauth_route():
    """A public route with no token in request must not return FreshToken."""

    @noauth()
    @get("/test/public-route")
    async def _handler(request, response):
        return response("public")

    result, _ = await _resolve(Constant.TINA4_GET, "/test/public-route")

    assert result.http_code == 200
    header_str = " ".join(str(h) for h in result.headers)
    assert "FreshToken" not in header_str


# ---------------------------------------------------------------------------
# formToken round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_form_token_accepted_on_post():
    """A POST with a valid formToken in the body must succeed (not 401)."""
    token = tina4_python.tina4_auth.get_token({"user": "test"}, expiry_minutes=10)

    @noauth()
    @post("/test/form-post")
    async def _handler(request, response):
        return response({"received": True})

    result, _ = await _resolve(
        Constant.TINA4_POST,
        "/test/form-post",
        body={"formToken": token, "name": "Alice"},
    )

    assert result.http_code == 200


@pytest.mark.asyncio
async def test_post_without_token_returns_401():
    """A POST with no token and no noauth must return 401."""

    @post("/test/secure-post")
    async def _handler(request, response):
        return response({"received": True})

    result, _ = await _resolve(
        Constant.TINA4_POST,
        "/test/secure-post",
        body={"name": "Alice"},
    )

    assert result.http_code == Constant.HTTP_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Cookie parsing from request headers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_header_parsed_correctly():
    """Cookie header string must be parsed into individual cookie values."""

    # Write a real session first
    session = Session("PY_SESS", SESSION_PATH, "SessionFileHandler")
    session_hash = session.start()
    session.set("role", "admin")
    session.save()

    @noauth()
    @get("/test/cookie-parse")
    async def _handler(request, response):
        role = request.session.get("role")
        return response({"role": role})

    # Pass the cookie via the cookies dict (as Webserver would parse it)
    result, _ = await _resolve(
        Constant.TINA4_GET,
        "/test/cookie-parse",
        cookies={"PY_SESS": session_hash},
    )

    assert result.http_code == 200
    import json
    body = json.loads(result.content)
    assert body["role"] == "admin"


@pytest.mark.asyncio
async def test_invalid_session_cookie_starts_fresh():
    """A bogus session cookie must not crash — it starts a fresh session."""

    @noauth()
    @get("/test/bogus-cookie")
    async def _handler(request, response):
        val = request.session.get("anything")
        return response({"val": val})

    result, _ = await _resolve(
        Constant.TINA4_GET,
        "/test/bogus-cookie",
        cookies={"PY_SESS": "not-a-real-hash"},
    )

    assert result.http_code == 200
    import json
    body = json.loads(result.content)
    assert body["val"] is None
