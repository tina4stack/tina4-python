"""Shared cross-framework conformance for feature 131 (TestClient fidelity).

Plan: tina4-documentation/plan/v3/features/131-test-client.md
Fixture: tina4-documentation/plan/v3/fixtures/test_client_contract.json

TC-DEC-01 (Node-only fix, exercised here as the Python REFERENCE the other
three languages are proven against): Node's TestClient used to RE-IMPLEMENT
dispatch instead of calling the real front controller, so the session stage
never ran and route middleware ran BEFORE the auth gate. Python has always
called the real ``core.server.app`` — this suite is the shared conformance
fixture that pins that fidelity here too, so a regression that made Python's
TestClient skip a stage would be caught the same way it would in Node.

TC-DEC-02: ``TestResponse`` used to collapse the ASGI header LIST into a
last-wins DICT, losing a duplicate response header (two ``Set-Cookie``). Fixed
by keeping the raw list and adding ``get_all(name)``; ``headers[name]`` stays
the back-compat single (last) value.

Four cases, identical names in all four frameworks' own idiom:
  * test_client_response_equals_a_real_socket_request — THE ORACLE. Boots a
    REAL child server (conftest.boot_child_server, the established real-process
    pattern this suite already uses elsewhere) and asserts the in-process
    TestClient response for an identically-defined route equals what the real
    socket gave back (status, body, content-type, a custom marker header).
  * a_secured_route_returns_401_without_running_its_route_middleware — locks
    gate-BEFORE-middleware (ADR-0012): a visible marker proves the route's own
    middleware never ran on a request the gate already rejected.
  * a_session_login_then_authenticated_request_succeeds — locks the session
    stage: a login route sets request.session['token'], the Set-Cookie is
    threaded BY HAND (no cookie jar — TC-NO-COOKIE-JAR is deliberately out of
    scope) into a second request to a @secured() route.
  * duplicate_response_headers_are_all_exposed — two response.cookie() calls
    on one route; get_all('set-cookie') returns BOTH, headers['set-cookie']
    still collapses to the last (back-compat).

NO MOCKS: the oracle is a real child process on a real socket; every other
case drives the real in-process dispatch (core.server.app) through TestClient.
Positive AND negative assertions throughout.
"""
from __future__ import annotations

import http.client
import os
import subprocess

# A real signing secret so get_token()/valid_token_static() agree, set before
# any token is minted (the auth helpers read TINA4_SECRET at call time).
os.environ["TINA4_SECRET"] = "tc131-contract-secret"
os.environ.pop("TINA4_API_KEY", None)

from conftest import boot_child_server

from tina4_python.auth import get_token
from tina4_python.core.router import get, post, noauth, secured, middleware
from tina4_python.test_client import TestClient


# ── case 2: gate-before-middleware marker ───────────────────────────────

_route_middleware_marker = {"ran": False}


class _Tc131MarkerMiddleware:
    """Route-attached middleware that flips a visible marker when it runs."""

    @staticmethod
    def before_marker(request, response):
        _route_middleware_marker["ran"] = True
        return request, response


class TestTestClientContract:
    def setup_method(self, _method):
        # Registered fresh before each test — immune to any suite that clears
        # the route registry between tests (matches test_test_client_auth.py).
        _route_middleware_marker["ran"] = False

        @middleware(_Tc131MarkerMiddleware)
        @post("/tc131-secured-write")
        async def _secured_write(request, response):
            return response({"created": True}, 201)

        @noauth()
        @post("/tc131-login")
        async def _login(request, response):
            token = get_token({"sub": "tc131-user"})
            request.session.set("token", token)
            return response({"logged_in": True})

        @secured()
        @get("/tc131-protected")
        async def _protected(request, response):
            return response({"ok": True})

        @get("/tc131-cookies")
        async def _cookies(request, response):
            response.cookie("tc131_a", "1")
            response.cookie("tc131_b", "2")
            return response({"ok": True})

    # ── the oracle ──────────────────────────────────────────────────────

    def test_client_response_equals_a_real_socket_request(self, tmp_path):
        """The in-process TestClient response equals a real socket response
        for the identically-defined route — the one assertion that catches
        ANY skipped dispatch stage."""

        def write_app(proj, port):
            (proj / "app.py").write_text(
                "from tina4_python import get\n"
                "from tina4_python.core.server import start\n\n"
                "@get('/tc131-oracle')\n"
                "async def oracle(request, response):\n"
                "    response.header('X-Tc131-Marker', 'oracle')\n"
                "    return response({'pipeline': 'ok'})\n\n"
                f"start(port={port}, no_browser=True, no_reload=True)\n"
            )

        proc, port = boot_child_server(tmp_path, write_app)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.request("GET", "/tc131-oracle")
                live = conn.getresponse()
                live_body = live.read()
                live_status = live.status
                live_headers = {k.lower(): v for k, v in live.getheaders()}
            finally:
                conn.close()

            # The live server is the oracle: prove IT answered before trusting
            # the comparison (a shared failure could vacuously "match").
            assert live_status == 200, "the real socket server did not serve /tc131-oracle"
            assert live_headers.get("x-tc131-marker") == "oracle"

            # The IDENTICAL route, registered in THIS process, for TestClient.
            @get("/tc131-oracle")
            async def _oracle(request, response):
                response.header("X-Tc131-Marker", "oracle")
                return response({"pipeline": "ok"})

            test_res = TestClient().get("/tc131-oracle")

            assert test_res.status == live_status
            assert test_res.body == live_body
            assert test_res.headers.get("content-type") == live_headers.get("content-type")
            assert test_res.headers.get("x-tc131-marker") == live_headers.get("x-tc131-marker")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ── gate BEFORE route middleware (ADR-0012) ─────────────────────────

    def test_a_secured_route_returns_401_without_running_its_route_middleware(self):
        assert _route_middleware_marker["ran"] is False, "marker must start unset"

        res = TestClient().post("/tc131-secured-write", json={"name": "Mallory"})

        assert res.status == 401, "a tokenless write to a secured route must 401"
        assert _route_middleware_marker["ran"] is False, (
            "the route's own middleware ran on a request the auth gate should have "
            "rejected first — gate-before-middleware order (ADR-0012) is broken"
        )

        # Positive control: a VALID token lets the request through, and only
        # THEN does the route's own middleware run — proving the marker
        # mechanism itself works (a permanently-false marker would pass the
        # negative assertion above for the wrong reason).
        token = get_token({"sub": "tc131-user"})
        ok = TestClient().post(
            "/tc131-secured-write",
            json={"name": "Alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ok.status == 201
        assert _route_middleware_marker["ran"] is True, "middleware must run for an authorised request"

    # ── the session stage runs (Node's structural gap) ──────────────────

    def test_a_session_login_then_authenticated_request_succeeds(self):
        client = TestClient()

        # Negative first: the protected route is genuinely gated.
        bare = client.get("/tc131-protected")
        assert bare.status == 401, "the session-guarded route must reject an unauthenticated request"

        login_res = client.post("/tc131-login")
        assert login_res.status == 200
        set_cookie = login_res.headers.get("set-cookie")
        assert set_cookie, "login must set a session cookie for the session stage to have run"
        cookie_pair = set_cookie.split(";", 1)[0]

        protected_res = client.get("/tc131-protected", headers={"Cookie": cookie_pair})
        assert protected_res.status == 200, (
            "replaying the session cookie must authenticate the request via the "
            "session-token path — this is structurally unreachable if the session "
            "stage never attaches request.session"
        )
        assert protected_res.json() == {"ok": True}

    # ── duplicate response headers are all exposed (TC-DEC-02) ─────────

    def test_duplicate_response_headers_are_all_exposed(self):
        res = TestClient().get("/tc131-cookies")

        assert res.status == 200
        all_cookies = res.get_all("set-cookie")
        assert len(all_cookies) == 2, f"expected 2 Set-Cookie values, got {all_cookies!r}"
        assert any(c.startswith("tc131_a=1") for c in all_cookies)
        assert any(c.startswith("tc131_b=2") for c in all_cookies)

        # Back-compat: the single accessor still collapses to ONE value (the
        # last one sent), never a list — existing callers are unaffected.
        assert isinstance(res.headers.get("set-cookie"), str)
        assert res.headers["set-cookie"] in all_cookies

        # Negative: a header that was only ever sent once returns a one-item
        # list, not an empty one, and a header never sent returns [].
        assert res.get_all("content-type") == [res.headers["content-type"]]
        assert res.get_all("x-tc131-never-sent") == []
