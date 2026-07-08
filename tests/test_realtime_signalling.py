"""Slice 1 (calls plane) regression suite for tina4_python.realtime.

No mocks: the WebSocketManager, its rooms, and the broadcast fan-out are the REAL
framework objects. Only the terminal socket write (`connection.send`) is observed,
so we assert exactly which peer the relay delivered to.
"""
import base64
import hashlib
import hmac
import json
import time

from tina4_python import realtime
from tina4_python.realtime import ice_servers, MeshBackend, RtcMediaBackend
from tina4_python.core.router import Router
from tina4_python.websocket import WebSocketConnection, WebSocketManager


def _find_ws(path):
    routes = [r for r in Router.get_web_socket_routes() if r["path"] == path]
    assert routes, f"no WS route registered at {path}"
    return routes[-1]["handler"]


def _make_conn(mgr, room):
    conn = WebSocketConnection(None, None, f"/ws/rtc/{room}", {}, {"room": room})
    conn.sent = []

    async def _capture(msg):
        conn.sent.append(msg)

    conn.send = _capture           # observe the socket sink; everything else is real
    mgr.add(conn)                  # real registration (sets _manager, tracks id)
    return conn


# ── ICE config (STUN + ephemeral TURN) ──────────────────────────────

class TestIceServers:
    def test_stun_only_by_default(self, monkeypatch):
        for k in ("TINA4_RTC_STUN_URLS", "TINA4_RTC_TURN_URL", "TINA4_RTC_TURN_SECRET"):
            monkeypatch.delenv(k, raising=False)
        servers = ice_servers()
        assert len(servers) == 1
        assert servers[0]["urls"] == ["stun:stun.l.google.com:19302"]
        assert "credential" not in servers[0]

    def test_ephemeral_turn_credential_is_valid_hmac(self, monkeypatch):
        monkeypatch.setenv("TINA4_RTC_TURN_URL", "turn:turn.example.com:3478")
        monkeypatch.setenv("TINA4_RTC_TURN_SECRET", "s3cr3t")
        monkeypatch.setenv("TINA4_RTC_TURN_TTL", "3600")
        turn = ice_servers()[-1]
        assert turn["urls"] == ["turn:turn.example.com:3478"]
        # username is a future expiry epoch (coturn use-auth-secret scheme)
        assert int(turn["username"]) > int(time.time())
        expected = base64.b64encode(
            hmac.new(b"s3cr3t", turn["username"].encode(), hashlib.sha1).digest()
        ).decode()
        assert turn["credential"] == expected


# ── Mount: configurable paths, self-describing config ───────────────

class TestRealtimeMount:
    def test_registers_config_and_signalling_under_prefix(self):
        paths = realtime(prefix="/t-mount")
        assert paths["config"] == "/t-mount/api/rtc/config"
        assert paths["signalling"] == "/t-mount/ws/rtc"
        assert paths["backend"] == "mesh"
        _find_ws("/t-mount/ws/rtc/{room}")

    def test_prefix_defaults_to_root(self):
        paths = realtime()
        assert paths["config"] == "/api/rtc/config"
        assert paths["signalling"] == "/ws/rtc"

    def test_mesh_backend_mints_no_join_token(self):
        assert MeshBackend().mint_join("room", "alice") is None
        assert isinstance(MeshBackend(), RtcMediaBackend)


# ── Signalling relay (the real WS manager fan-out) ──────────────────

class TestSignallingRelay:
    async def test_relays_to_peers_not_sender_and_room_isolated(self):
        realtime(prefix="/t-relay")
        handler = _find_ws("/t-relay/ws/rtc/{room}")

        mgr = WebSocketManager()
        a = _make_conn(mgr, "demo")
        b = _make_conn(mgr, "demo")
        c = _make_conn(mgr, "other")
        for conn in (a, b, c):
            await handler(conn, "open", None)

        offer = json.dumps({"type": "offer", "from": a.id, "to": b.id, "sdp": "v=0..."})
        await handler(a, "message", offer)

        assert b.sent == [offer], "the other peer in the room receives the offer"
        assert a.sent == [], "the sender is never echoed its own signal (exclude_self)"
        assert c.sent == [], "a peer in a different room receives nothing (isolation)"
