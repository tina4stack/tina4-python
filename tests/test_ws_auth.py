"""Per-route WebSocket authentication (v3.13.39).

A @secured() WebSocket route enforces a valid JWT on the upgrade handshake —
via the Authorization header (server/CLI clients), the "bearer" subprotocol
(browsers, which can't set headers on new WebSocket()), or a ?token= query
param. Public by default (mirrors GET), so existing WS routes are unaffected.
"""
import pytest

from tina4_python.websocket import ws_token, ws_authorized
from tina4_python.auth import get_token
from tina4_python.core.router import Router, websocket, secured


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("TINA4_SECRET", "test-ws-secret-0123456789abcdef0123456789")
    yield


class TestWsToken:
    def test_authorization_header(self):
        assert ws_token({"authorization": "Bearer abc.def.ghi"}) == "abc.def.ghi"

    def test_authorization_header_case_insensitive_scheme(self):
        assert ws_token({"authorization": "bearer abc.def.ghi"}) == "abc.def.ghi"

    def test_bearer_subprotocol(self):
        assert ws_token({}, subprotocol="bearer, abc.def.ghi") == "abc.def.ghi"

    def test_query_param(self):
        assert ws_token({}, query_string="token=abc.def.ghi&x=1") == "abc.def.ghi"

    def test_none_when_absent(self):
        assert ws_token({}) is None

    def test_header_wins_over_query(self):
        assert ws_token({"authorization": "Bearer H"}, query_string="token=Q") == "H"


class TestWsAuthorized:
    def test_public_route_always_ok(self):
        payload, ok = ws_authorized({"auth_required": False}, {})
        assert ok is True and payload is None

    def test_route_without_flag_is_public(self):
        payload, ok = ws_authorized({}, {})
        assert ok is True and payload is None

    def test_secured_valid_token_header(self):
        tok = get_token({"user_id": 7})
        payload, ok = ws_authorized({"auth_required": True}, {"authorization": f"Bearer {tok}"})
        assert ok is True and payload["user_id"] == 7

    def test_secured_valid_token_subprotocol(self):
        tok = get_token({"user_id": 9})
        payload, ok = ws_authorized({"auth_required": True}, {}, subprotocol=f"bearer, {tok}")
        assert ok is True and payload["user_id"] == 9

    def test_secured_valid_token_query(self):
        tok = get_token({"user_id": 11})
        payload, ok = ws_authorized({"auth_required": True}, {}, query_string=f"token={tok}")
        assert ok is True and payload["user_id"] == 11

    def test_secured_missing_token_rejected(self):
        payload, ok = ws_authorized({"auth_required": True}, {})
        assert ok is False and payload is None

    def test_secured_invalid_token_rejected(self):
        payload, ok = ws_authorized({"auth_required": True}, {"authorization": "Bearer not.a.jwt"})
        assert ok is False and payload is None


class TestSecuredWsRoute:
    def test_plain_ws_route_is_public(self):
        @websocket("/ws/auth-plain")
        async def h(connection, event, data):
            pass
        route, _ = Router.match_ws("/ws/auth-plain")
        assert route["auth_required"] is False

    def test_secured_decorator_above_websocket(self):
        # @secured() on top, @websocket() below — websocket registers first,
        # secured() flips the flag via the back-ref.
        @secured()
        @websocket("/ws/auth-above")
        async def h(connection, event, data):
            pass
        route, _ = Router.match_ws("/ws/auth-above")
        assert route["auth_required"] is True

    def test_secured_decorator_below_websocket(self):
        # @websocket() on top, @secured() below — secured() sets _secured first,
        # websocket() reads it at registration.
        @websocket("/ws/auth-below")
        @secured()
        async def h(connection, event, data):
            pass
        route, _ = Router.match_ws("/ws/auth-below")
        assert route["auth_required"] is True


class TestNativeServerUpgrade:
    """Real socket-pair integration for the built-in webserver's WS upgrade.

    Regression for the gap the realtime chat demo surfaced: the native
    (TINA4_DEFAULT_WEBSERVER) upgrade path imported ws_authorized but never
    called it — so a @secured WS route was unauthenticated, conn.auth was never
    set, and the `bearer` subprotocol was not echoed (which makes a browser fail
    the handshake). No mocks: a real socketpair carries the real handshake.
    """

    @staticmethod
    async def _drive(headers, path, captured=None):
        import asyncio
        import socket
        from tina4_python.core import server as srv

        s_srv, s_cli = socket.socketpair()
        for s in (s_srv, s_cli):
            s.setblocking(False)
        sr, sw = await asyncio.open_connection(sock=s_srv)
        cr, cw = await asyncio.open_connection(sock=s_cli)

        task = asyncio.create_task(
            srv._handle_dev_websocket(sr, sw, headers, path, ""))
        await asyncio.sleep(0.1)
        try:
            data = await asyncio.wait_for(cr.read(4096), timeout=0.5)
        except asyncio.TimeoutError:
            data = b""
        cw.close()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except Exception:
            task.cancel()
        return data.decode("utf-8", errors="replace")

    def _register(self, path, secured_flag, captured):
        async def handler(connection, event, data):
            if event == "open":
                captured["auth"] = connection.auth
        if secured_flag:
            handler._secured = True
        Router.websocket(path, handler)

    async def test_secured_rejects_without_token(self):
        captured = {}
        self._register("/ws/native-secure-a", True, captured)
        resp = await self._drive(
            {"upgrade": "websocket", "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ=="},
            "/ws/native-secure-a", captured)
        assert "401" in resp
        assert "101" not in resp
        assert "auth" not in captured        # open handler never ran

    async def test_secured_accepts_bearer_and_echoes_subprotocol(self):
        captured = {}
        self._register("/ws/native-secure-b", True, captured)
        token = get_token({"user_id": 42})
        resp = await self._drive({
            "upgrade": "websocket",
            "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
            "sec-websocket-protocol": f"bearer, {token}",
        }, "/ws/native-secure-b", captured)
        assert "101 Switching Protocols" in resp
        assert "sec-websocket-protocol: bearer" in resp.lower()   # echoed for the browser
        assert captured.get("auth", {}).get("user_id") == 42       # conn.auth populated

    async def test_public_route_upgrades_without_token(self):
        captured = {}
        self._register("/ws/native-public", False, captured)
        resp = await self._drive(
            {"upgrade": "websocket", "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ=="},
            "/ws/native-public", captured)
        assert "101 Switching Protocols" in resp
        assert captured.get("auth") is None                        # public → no payload
