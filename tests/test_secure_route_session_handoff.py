# Secure route hands the validated principal + session + cookies to the handler.
"""
Regresses tina4-nodejs#57 (reported on 3.13.103): a login route stores a signed
token in the session, a later SECURE GET is router-authenticated via the returned
session cookie (a request WITHOUT the cookie gets 401), but the report says the
handler saw request.user, request.session and request.cookies as UNAVAILABLE.
Expected: the secure handler receives the validated principal AND the session.

Driven through the REAL dispatcher (`tina4_python.core.server.handle`) with real
ASGI scopes and a real session-cookie round trip. NO MOCKS.

Flow (exactly the reporter's):
  1. POST /api/login (public) stores a signed token in the session -> Set-Cookie.
  2. GET /api/secure (secured) WITHOUT the cookie -> 401 (the router gate works).
  3. GET /api/secure WITH the session cookie -> 200, and the handler sees:
       - request.user = the validated principal (user_id == 1), not None/True
       - request.session.get("token") = the token a PRIOR request stored
       - request.cookies carrying the session cookie

Mutation-proved: this is authentication-via-session-cookie. If the auth gate
stopped attaching request.user, or the session/cookies were not loaded for a
secured GET, case 3 goes red on the wire.

Same case names in all four:
  tina4-php/tests/SecureRouteSessionHandoffTest.php
  tina4-ruby/spec/secure_route_session_handoff_spec.rb
  tina4-nodejs/test/secureRouteSessionHandoff.test.ts
"""
from __future__ import annotations

import asyncio
import json

import pytest

import tina4_python.core.server as server
from tina4_python.auth import get_token
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get, post as route_post, noauth, secured

SECRET = "secure-handoff-secret"


@pytest.fixture(autouse=True)
def _app(monkeypatch, tmp_path):
    Router.clear()
    monkeypatch.setenv("TINA4_SECRET", SECRET)
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "file")
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))

    @noauth()
    @route_post("/api/login")
    async def _login(request, response):
        # Store the token the TEST minted; writing it server-side mints the cookie.
        request.session.set("token", request.body.get("token"))
        return response({"ok": True})

    @secured()
    @route_get("/api/secure")
    async def _secure(request, response):
        return response({
            "user": request.user,
            "session_token": request.session.get("token") if request.session else None,
            "cookie_keys": sorted((request.cookies or {}).keys()),
        })

    yield
    Router.clear()


def _call(method, path, cookie=None, body=b""):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if body:
        headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http", "method": method, "path": path, "query_string": b"",
        "scheme": "http", "headers": headers, "client": ("127.0.0.1", 1),
    }
    return asyncio.run(server.handle(Request.from_scope(scope, body)))


def _set_cookies(resp):
    return [v for k, v in resp._headers if k.lower() == "set-cookie"]


def _cookie_header(set_cookies):
    return "; ".join(c.split(";")[0] for c in set_cookies)


def _body(resp):
    raw = resp.content
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def test_secure_route_session_handoff():
    token = get_token({"user_id": 1, "role": "admin"})

    # 1. Log in: the token lands in the session; the response mints the cookie.
    login = _call("POST", "/api/login", body=json.dumps({"token": token}).encode())
    assert login.status_code == 200, f"login failed: {login.status_code} {login.content!r}"
    cookie = _cookie_header(_set_cookies(login))
    assert cookie, f"login returned no session cookie: {_set_cookies(login)!r}"

    # 2. The router gate really gates: no cookie -> 401, handler never runs.
    denied = _call("GET", "/api/secure")
    assert denied.status_code == 401, f"secure GET without cookie should be 401, got {denied.status_code}"

    # 3. THE #57 assertion: with the cookie, the handler gets principal + session + cookies.
    ok = _call("GET", "/api/secure", cookie=cookie)
    assert ok.status_code == 200, f"secure GET with cookie should be 200, got {ok.status_code} {ok.content!r}"
    data = _body(ok)
    assert isinstance(data["user"], dict) and data["user"], (
        f"request.user must be the validated principal dict, got {data['user']!r}"
    )
    assert data["user"].get("user_id") == 1, f"request.user missing claims: {data['user']!r}"
    assert data["session_token"] == token, "request.session must round-trip the stored token"
    assert data["cookie_keys"], f"request.cookies must be populated in the secured handler, got {data['cookie_keys']!r}"
