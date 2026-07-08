"""Chat control-plane regression suite for tina4_python.realtime (feature "chat").

No mocks: the WebSocketManager + rooms, the ORM models, the SQLite database, and
the HTTP dispatch (via the in-process TestClient) are all REAL. Only the terminal
socket write is observed, so we can assert exactly which peer each event reached.
"""
import json
import tempfile

import pytest

from tina4_python import realtime
from tina4_python.core.router import Router
from tina4_python.websocket import WebSocketConnection, WebSocketManager
from tina4_python.database import Database
from tina4_python.orm import bind_database
from tina4_python.auth import get_token
from tina4_python.test_client import TestClient


@pytest.fixture
def chat(monkeypatch):
    """A real SQLite-backed workspace with one public channel and two members.

    Members: user "1" (owner) and "2" (member). User "9" is NOT a member.
    """
    monkeypatch.setenv("TINA4_SECRET", "realtime-chat-test-secret")
    db = Database("sqlite:///" + tempfile.mktemp(suffix=".db"))
    bind_database(db)
    from tina4_python.realtime.models import (
        CHAT_MODELS, Workspace, Channel, ChannelMember,
    )
    for model in CHAT_MODELS:
        model.create_table()
    ws = Workspace(name="Acme", created_at="2026-07-08T00:00:00"); ws.save()
    ch = Channel(workspace_id=ws.id, name="general", kind="public",
                 created_at="2026-07-08T00:00:00"); ch.save()
    ChannelMember(channel_id=ch.id, user_id="1", role="owner").save()
    ChannelMember(channel_id=ch.id, user_id="2", role="member").save()
    realtime(features=["calls", "chat"])
    return {"db": db, "workspace": ws, "channel": ch}


def _find_ws(path):
    routes = [r for r in Router.get_web_socket_routes() if r["path"] == path]
    assert routes, f"no WS route registered at {path}"
    return routes[-1]["handler"]


def _make_conn(mgr, channel_id, user_id):
    conn = WebSocketConnection(None, None, f"/ws/chat/{channel_id}", {},
                               {"channel": str(channel_id)})
    conn.auth = {"user_id": user_id}
    conn.sent = []
    conn.close_called = False

    async def _capture(msg):
        conn.sent.append(msg)

    async def _close(code=1000, reason=""):
        conn.close_called = True
        conn._closed = True

    conn.send = _capture
    conn.close = _close
    mgr.add(conn)
    return conn


def _events(conn):
    return [json.loads(m) for m in conn.sent]


# ── WebSocket control plane ─────────────────────────────────────────

class TestChatWebSocket:
    async def test_presence_roster_and_join_announce(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        await handler(a, "open", None)
        # A alone: gets its own roster
        assert _events(a) == [{"type": "presence", "event": "roster", "users": ["1"]}]

        b = _make_conn(mgr, cid, 2)
        await handler(b, "open", None)
        # B sees both in the roster; A is told B joined
        assert _events(b)[0] == {"type": "presence", "event": "roster",
                                 "users": ["1", "2"]}
        assert _events(a)[-1] == {"type": "presence", "event": "join", "user_id": "2"}

    async def test_message_persists_and_fans_out_including_sender(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        b = _make_conn(mgr, cid, 2)
        await handler(a, "open", None)
        await handler(b, "open", None)
        a.sent.clear(); b.sent.clear()

        await handler(a, "message", json.dumps({"type": "message", "body": "hello"}))

        # Delivered to BOTH (the sender's optimistic message gets its server id).
        for conn in (a, b):
            evs = _events(conn)
            assert len(evs) == 1
            assert evs[0]["type"] == "message"
            assert evs[0]["message"]["body"] == "hello"
            assert evs[0]["message"]["user_id"] == "1"
            assert evs[0]["message"]["id"] is not None

        # Real row landed in the real database.
        from tina4_python.realtime.models import Message
        rows = Message.where("channel_id = ?", [cid])
        assert len(rows) == 1 and rows[0].body == "hello"

    async def test_typing_excludes_sender(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        b = _make_conn(mgr, cid, 2)
        await handler(a, "open", None)
        await handler(b, "open", None)
        a.sent.clear(); b.sent.clear()

        await handler(a, "message", json.dumps({"type": "typing"}))
        assert _events(b) == [{"type": "typing", "user_id": "1"}]
        assert a.sent == []          # never echoed to the typist

    async def test_read_receipt_advances_cursor_and_broadcasts(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        b = _make_conn(mgr, cid, 2)
        await handler(a, "open", None)
        await handler(b, "open", None)
        a.sent.clear(); b.sent.clear()

        await handler(a, "message", json.dumps({"type": "read"}))
        ev = _events(b)[-1]
        assert ev["type"] == "read" and ev["user_id"] == "1" and ev["at"]

        from tina4_python.realtime.models import ChannelMember
        member = ChannelMember.where("channel_id = ? AND user_id = ?", [cid, "1"], limit=1)[0]
        assert member.last_read_at is not None

    async def test_non_member_is_rejected_and_closed(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        outsider = _make_conn(mgr, cid, 9)   # user 9 is not a member
        await handler(outsider, "open", None)
        assert _events(outsider) == [{"type": "error",
                                      "error": "not a member of this channel"}]
        assert outsider.close_called is True

    async def test_message_reauthorized_every_frame(self, chat):
        """Membership revoked mid-session: the next message is dropped."""
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        b = _make_conn(mgr, cid, 2)
        await handler(a, "open", None)
        await handler(b, "open", None)
        a.sent.clear(); b.sent.clear()

        # Revoke A's membership after the socket is already open.
        from tina4_python.realtime.models import ChannelMember
        ChannelMember.where("channel_id = ? AND user_id = ?", [cid, "1"], limit=1)[0].delete()

        await handler(a, "message", json.dumps({"type": "message", "body": "sneaky"}))
        assert b.sent == []          # not delivered
        from tina4_python.realtime.models import Message
        assert Message.where("channel_id = ?", [cid]) == [] or \
            all(m.body != "sneaky" for m in Message.where("channel_id = ?", [cid]))

    async def test_close_announces_leave(self, chat):
        handler = _find_ws("/ws/chat/{channel}")
        mgr = WebSocketManager()
        cid = chat["channel"].id
        a = _make_conn(mgr, cid, 1)
        b = _make_conn(mgr, cid, 2)
        await handler(a, "open", None)
        await handler(b, "open", None)
        a.sent.clear(); b.sent.clear()

        await handler(a, "close", None)
        assert _events(b)[-1] == {"type": "presence", "event": "leave", "user_id": "1"}


# ── History endpoint (real HTTP dispatch + real auth) ───────────────

class TestChatHistory:
    def _seed_messages(self, cid, n):
        from tina4_python.realtime.models import Message
        for i in range(1, n + 1):
            Message(channel_id=cid, user_id="1", body=f"m{i}",
                    created_at=f"2026-07-08T00:{i:02d}:00").save()

    def test_member_gets_newest_first_and_before_cursor_pages(self, chat):
        cid = chat["channel"].id
        self._seed_messages(cid, 5)
        token = get_token({"user_id": 1})
        client = TestClient()
        hdrs = {"Authorization": f"Bearer {token}"}

        res = client.get(f"/api/channels/{cid}/messages?limit=3", headers=hdrs)
        assert res.status == 200
        rows = res.json()
        assert [r["body"] for r in rows] == ["m5", "m4", "m3"]   # newest-first

        cursor = rows[-1]["id"]
        res2 = client.get(f"/api/channels/{cid}/messages?before={cursor}&limit=3",
                          headers=hdrs)
        assert [r["body"] for r in res2.json()] == ["m2", "m1"]

    def test_non_member_is_forbidden(self, chat):
        cid = chat["channel"].id
        self._seed_messages(cid, 2)
        token = get_token({"user_id": 9})   # not a member
        res = TestClient().get(f"/api/channels/{cid}/messages",
                               headers={"Authorization": f"Bearer {token}"})
        assert res.status == 403


# ── Mount wiring ────────────────────────────────────────────────────

class TestChatMount:
    def test_chat_feature_registers_paths(self, chat):
        paths = realtime(prefix="/t-chat", features=["calls", "chat"])
        assert paths["chat"] == "/t-chat/ws/chat"
        assert paths["messages"] == "/t-chat/api/channels"
        _find_ws("/t-chat/ws/chat/{channel}")

    def test_config_advertises_chat(self, chat):
        realtime(prefix="/t-cfg", features=["calls", "chat"])
        res = TestClient().get("/t-cfg/api/rtc/config")
        body = res.json()
        assert body["chat"] == "/t-cfg/ws/chat/{channel}"
        assert body["messages"] == "/t-cfg/api/channels/{id}/messages"
        assert "iceServers" in body
