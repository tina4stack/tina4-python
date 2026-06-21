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
