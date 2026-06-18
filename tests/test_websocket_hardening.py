# Tests for the WebSocket + SSE hardening sweep:
#   - Backplane relay across simulated instances (thread→loop bridge + origin guard)
#   - Broadcast resilience (one dead client never aborts delivery; it is pruned)
#   - SSE streaming error handling (generator raises / client disconnect)
#   - origin_allowed() allow-list semantics
#   - bytes round-trip through the backplane envelope (base64)
#
# Everything here is engine-agnostic: no real Redis, NATS, or sockets. A tiny
# in-memory FakeBackplane proves the relay path end-to-end.
import asyncio
import base64
import json

import pytest

from tina4_python.websocket import WebSocketManager, origin_allowed
from tina4_python.websocket.backplane import WebSocketBackplane


# ── Fakes ─────────────────────────────────────────────────────


class FakeConnection:
    """Minimal stand-in for WebSocketConnection — records what was sent and can
    be told to raise on send (to exercise broadcast resilience / pruning)."""

    def __init__(self, conn_id, raise_on_send=False):
        self.id = conn_id
        self.path = "/"
        self._closed = False
        self._rooms = set()
        self._last_activity = 0.0
        self._manager = None
        self.sent = []
        self.raise_on_send = raise_on_send

    async def send(self, message):
        if self.raise_on_send:
            raise ConnectionError(f"simulated broken pipe on {self.id}")
        self.sent.append(message)

    async def close(self, code=1000, reason=""):
        self._closed = True


class FakeBackplane(WebSocketBackplane):
    """In-memory pub/sub backplane. ``publish`` synchronously fans the raw
    message out to every subscribed callback — exactly what a real backplane
    does, minus the network and background thread. Because the manager's
    callback runs ``run_coroutine_threadsafe`` against the captured loop, the
    relay still goes through the real thread→loop bridge."""

    def __init__(self):
        self._subs = {}

    def publish(self, channel, message):
        for cb in self._subs.get(channel, []):
            cb(message)

    def subscribe(self, channel, callback):
        self._subs.setdefault(channel, []).append(callback)

    def unsubscribe(self, channel):
        self._subs.pop(channel, None)

    def close(self):
        self._subs.clear()


def _wire_backplane(manager, backplane):
    """Attach a fake backplane to a manager the way _ensure_backplane would,
    capturing the running loop for the thread→loop relay bridge."""
    manager._backplane = backplane
    manager._backplane_started = True
    manager._backplane_loop = asyncio.get_running_loop()
    backplane.subscribe(manager._backplane_channel, manager._on_backplane_message)


# ── Backplane relay + origin guard ────────────────────────────


class TestBackplaneRelay:
    async def test_remote_message_relayed_to_local_connections(self):
        """A broadcast from instance A is relayed to instance B's local conns."""
        backplane = FakeBackplane()

        # Instance A (the publisher) and instance B (the relayer) share the bus.
        mgr_a = WebSocketManager()
        mgr_b = WebSocketManager()
        _wire_backplane(mgr_a, backplane)
        _wire_backplane(mgr_b, backplane)

        # B has a local connection that should receive A's broadcast.
        conn_b = FakeConnection("b1")
        mgr_b.add(conn_b)

        # A broadcasts to all — delivers locally (A has none) then publishes.
        await mgr_a.broadcast_all("hello-cluster")

        # The relay schedules a coroutine on B's loop; let it run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert conn_b.sent == ["hello-cluster"]

    async def test_origin_guard_drops_own_echo(self):
        """A message tagged with the manager's own instance id is NOT
        re-delivered (it was already delivered locally on broadcast)."""
        backplane = FakeBackplane()
        mgr = WebSocketManager()
        _wire_backplane(mgr, backplane)

        conn = FakeConnection("c1")
        mgr.add(conn)

        # Hand-craft an envelope whose src == this manager's instance id.
        echo = json.dumps({
            "src": mgr._instance_id,
            "kind": "all",
            "exclude": None,
            "room": None,
            "path": None,
            "text": "echo-should-be-dropped",
        })
        mgr._on_backplane_message(echo)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # Origin guard: the connection must NOT have received the echo.
        assert conn.sent == []

    async def test_real_broadcast_no_double_delivery(self):
        """End-to-end: a single broadcast on A is delivered once on A (locally)
        and once on B (via relay) — A does not re-deliver its own echo."""
        backplane = FakeBackplane()
        mgr_a = WebSocketManager()
        mgr_b = WebSocketManager()
        _wire_backplane(mgr_a, backplane)
        _wire_backplane(mgr_b, backplane)

        conn_a = FakeConnection("a1")
        conn_b = FakeConnection("b1")
        mgr_a.add(conn_a)
        mgr_b.add(conn_b)

        await mgr_a.broadcast_all("ping")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # Exactly once each — the origin guard prevents A from re-delivering.
        assert conn_a.sent == ["ping"]
        assert conn_b.sent == ["ping"]

    async def test_room_relay_targets_only_room_members(self):
        backplane = FakeBackplane()
        mgr_a = WebSocketManager()
        mgr_b = WebSocketManager()
        _wire_backplane(mgr_a, backplane)
        _wire_backplane(mgr_b, backplane)

        in_room = FakeConnection("b_in")
        out_room = FakeConnection("b_out")
        mgr_b.add(in_room)
        mgr_b.add(out_room)
        mgr_b._join_room("b_in", "lobby")

        await mgr_a.broadcast_to_room("lobby", "room-msg")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert in_room.sent == ["room-msg"]
        assert out_room.sent == []

    async def test_bytes_round_trip_through_envelope(self):
        """Binary payloads survive the JSON envelope via base64."""
        backplane = FakeBackplane()
        mgr_a = WebSocketManager()
        mgr_b = WebSocketManager()
        _wire_backplane(mgr_a, backplane)
        _wire_backplane(mgr_b, backplane)

        conn_b = FakeConnection("b1")
        mgr_b.add(conn_b)

        payload = b"\x00\x01\x02\xfffoo"
        await mgr_a.broadcast_all(payload)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert conn_b.sent == [payload]
        assert isinstance(conn_b.sent[0], bytes)

    def test_publish_encodes_bytes_as_b64(self):
        """The envelope stores bytes under 'b64' and str under 'text'."""
        backplane = FakeBackplane()
        captured = []
        backplane.subscribe("tina4:ws", lambda raw: captured.append(json.loads(raw)))

        mgr = WebSocketManager()
        mgr._backplane = backplane
        mgr._backplane_started = True

        mgr._publish("all", b"\x10\x20")
        mgr._publish("all", "plain text")

        assert "b64" in captured[0]
        assert base64.b64decode(captured[0]["b64"]) == b"\x10\x20"
        assert captured[1]["text"] == "plain text"
        assert captured[0]["src"] == mgr._instance_id

    def test_publish_is_noop_without_backplane(self):
        """No backplane configured → _publish does nothing and never raises."""
        mgr = WebSocketManager()
        # Should not raise even though no backplane is wired.
        mgr._publish("all", "noop")

    async def test_publish_failure_does_not_crash_broadcast(self):
        """A flaky message bus must never undo a local broadcast."""

        class ExplodingBackplane(FakeBackplane):
            def publish(self, channel, message):
                raise RuntimeError("bus down")

        mgr = WebSocketManager()
        mgr._backplane = ExplodingBackplane()
        mgr._backplane_started = True

        conn = FakeConnection("c1")
        mgr.add(conn)
        # broadcast_all delivers locally then publishes; publish raises but is
        # caught — local delivery still happened.
        await mgr.broadcast_all("survive")
        assert conn.sent == ["survive"]

    async def test_backplane_init_failure_degrades_to_local_only(self, monkeypatch):
        """If wiring the backplane blows up (e.g. Redis unreachable at startup),
        the manager logs and falls back to LOCAL-only delivery — a broadcast
        still reaches local connections and never raises. (Distinct from a
        publish-time failure: this is the _ensure_backplane construction path.)"""
        def _boom(*a, **k):
            raise RuntimeError("backplane unreachable at startup")
        # _ensure_backplane does `from ...backplane import create_backplane`,
        # so patch it where it is looked up.
        monkeypatch.setattr(
            "tina4_python.websocket.backplane.create_backplane", _boom
        )
        mgr = WebSocketManager()
        conn = FakeConnection("c1")
        mgr.add(conn)
        # Must NOT raise even though backplane construction throws.
        await mgr.broadcast("hello")
        assert mgr._backplane is None          # degraded to local-only
        assert mgr._backplane_started is True  # attempted exactly once
        assert conn.sent == ["hello"]          # local delivery still happened


# ── Broadcast resilience ──────────────────────────────────────


class TestBroadcastResilience:
    async def test_dead_connection_does_not_abort_delivery_and_is_pruned(self):
        mgr = WebSocketManager()
        good1 = FakeConnection("g1")
        bad = FakeConnection("bad", raise_on_send=True)
        good2 = FakeConnection("g2")
        mgr.add(good1)
        mgr.add(bad)
        mgr.add(good2)

        await mgr.broadcast_all("payload")

        # Both healthy connections received the message despite the bad one.
        assert good1.sent == ["payload"]
        assert good2.sent == ["payload"]
        # The dead connection was pruned from the manager.
        assert mgr.get("bad") is None
        assert mgr.count() == 2

    async def test_dead_connection_pruned_on_path_broadcast(self):
        mgr = WebSocketManager()
        good = FakeConnection("g")
        bad = FakeConnection("bad", raise_on_send=True)
        good.path = "/chat"
        bad.path = "/chat"
        mgr.add(good)
        mgr.add(bad)

        await mgr.broadcast("hi", path="/chat")

        assert good.sent == ["hi"]
        assert mgr.get("bad") is None


# ── SSE / streaming hardening ─────────────────────────────────


class TestSSEHardening:
    async def _run_stream(self, source):
        """Drive the streaming branch of the ASGI app() with a captured send.
        Returns (sent_messages, raised_exception_or_None)."""
        from tina4_python.core.response import Response

        response = Response()
        response.stream(source)

        scope = {"type": "http", "path": "/sse", "headers": [], "method": "GET", "query_string": b""}
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        # We only need the streaming branch; patch handle() to return our response.
        import tina4_python.core.server as server

        async def fake_handle(_request):
            return response

        original_handle = server.handle
        server.handle = fake_handle
        raised = None
        try:
            await server.app(scope, receive, send)
        except BaseException as exc:  # capture CancelledError too
            raised = exc
        finally:
            server.handle = original_handle
        return sent, raised

    async def test_generator_raising_mid_stream_does_not_crash(self):
        """A generator that raises mid-stream is handled cleanly and the final
        empty-body terminator is still sent (worker not crashed)."""

        async def boom():
            yield "data: one\n\n"
            raise ValueError("generator blew up")

        sent, raised = await self._run_stream(boom())

        assert raised is None  # no crash propagated to the worker
        bodies = [m for m in sent if m["type"] == "http.response.body"]
        # First chunk delivered, then the terminating empty body.
        assert bodies[0]["body"] == b"data: one\n\n"
        assert bodies[-1] == {"type": "http.response.body", "body": b"", "more_body": False}

    async def test_client_disconnect_cancels_generator_and_reraises(self):
        """asyncio.CancelledError (client gone) closes the source via aclose()
        and is re-raised — cancellation is never swallowed."""
        closed = {"aclose": False}

        class HangingSource:
            """Async-iterable stand-in for a streaming generator that gets
            cancelled mid-stream. Exposes a settable ``aclose`` so we can assert
            the server attempts best-effort cleanup."""

            def __init__(self):
                self._first = True

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._first:
                    self._first = False
                    return "data: start\n\n"
                # Simulate the client disconnecting while awaiting the next chunk.
                raise asyncio.CancelledError()

            async def aclose(self):
                closed["aclose"] = True

        sent, raised = await self._run_stream(HangingSource())

        assert isinstance(raised, asyncio.CancelledError)
        assert closed["aclose"] is True
        # The first chunk was delivered before the disconnect.
        bodies = [m for m in sent if m["type"] == "http.response.body"]
        assert bodies[0]["body"] == b"data: start\n\n"


# ── origin_allowed() ──────────────────────────────────────────


class TestOriginAllowed:
    def test_empty_env_allows_all(self, monkeypatch):
        monkeypatch.delenv("TINA4_WS_ALLOWED_ORIGINS", raising=False)
        assert origin_allowed({"origin": "https://anything.example"}) is True
        assert origin_allowed({}) is True

    def test_blank_env_allows_all(self, monkeypatch):
        monkeypatch.setenv("TINA4_WS_ALLOWED_ORIGINS", "   ")
        assert origin_allowed({"origin": "https://anything.example"}) is True

    def test_listed_origin_allowed(self, monkeypatch):
        monkeypatch.setenv(
            "TINA4_WS_ALLOWED_ORIGINS",
            "https://app.example.com, https://admin.example.com",
        )
        assert origin_allowed({"origin": "https://app.example.com"}) is True
        assert origin_allowed({"origin": "https://admin.example.com"}) is True

    def test_mismatched_origin_rejected(self, monkeypatch):
        monkeypatch.setenv("TINA4_WS_ALLOWED_ORIGINS", "https://app.example.com")
        assert origin_allowed({"origin": "https://evil.example.com"}) is False

    def test_missing_origin_rejected_when_allowlist_active(self, monkeypatch):
        monkeypatch.setenv("TINA4_WS_ALLOWED_ORIGINS", "https://app.example.com")
        assert origin_allowed({}) is False

    def test_case_insensitive_header_key(self, monkeypatch):
        monkeypatch.setenv("TINA4_WS_ALLOWED_ORIGINS", "https://app.example.com")
        assert origin_allowed({"Origin": "https://app.example.com"}) is True


# ── Idle reaper ───────────────────────────────────────────────


class TestIdleReaper:
    async def test_reap_idle_disabled_is_noop(self):
        mgr = WebSocketManager()
        conn = FakeConnection("c1")
        mgr.add(conn)
        assert await mgr.reap_idle(0) == 0
        assert mgr.count() == 1

    async def test_reap_idle_closes_stale_connections(self):
        import time

        mgr = WebSocketManager()
        fresh = FakeConnection("fresh")
        stale = FakeConnection("stale")
        fresh._last_activity = time.time()
        stale._last_activity = time.time() - 1000  # long idle
        mgr.add(fresh)
        mgr.add(stale)

        reaped = await mgr.reap_idle(30)

        assert reaped == 1
        assert mgr.get("stale") is None
        assert stale._closed is True
        assert mgr.get("fresh") is not None
