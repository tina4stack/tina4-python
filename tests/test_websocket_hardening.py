# Tests for the WebSocket + SSE hardening sweep:
#   - Backplane relay across two manager instances (thread->loop bridge + origin guard)
#   - Broadcast resilience (one dead client never aborts delivery; it is pruned)
#   - SSE streaming error handling (generator raises / client disconnect)
#   - origin_allowed() allow-list semantics
#   - bytes round-trip through the backplane envelope (base64)
#
# The backplane is the REAL RedisBackplane on a REAL Redis (TINA4_TEST_REDIS_URL):
# two WebSocketManager instances, each with its own backplane connection, as two
# server processes would have. Messages cross the network, arrive on redis-py's
# listener thread and hop onto the event loop through the real bridge. Each test
# uses its own channel, so parallel runs never see each other's traffic. (An
# in-memory FakeBackplane used to stand in here: it fanned out synchronously on
# the caller's thread, so the listener thread, the envelope on the wire and the
# subscription timing were never exercised.)
import asyncio
import base64
import json
import os
import socket
import threading
import uuid
from types import SimpleNamespace

import pytest

from tina4_python.websocket import WebSocketManager, origin_allowed
from tina4_python.websocket.backplane import RedisBackplane

REDIS_URL = os.environ.get("TINA4_TEST_REDIS_URL", "")

# The backplane's listener is a background thread. An exception there (a read
# on a socket closed under it) is a real defect, not noise: fail the test.
pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")


# ── Test connection ───────────────────────────────────────────


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


# ── Real Redis bus ────────────────────────────────────────────


def _closed_port() -> int:
    """A real TCP port on 127.0.0.1 that nothing listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def redis_bus():
    """A private channel on the real Redis, plus a factory for backplanes that
    are all closed when the test ends."""
    if not REDIS_URL:
        pytest.skip("redis not set: export TINA4_TEST_REDIS_URL (e.g. redis://localhost:6379)")
    redis = pytest.importorskip("redis", reason="redis client not installed (uv sync --extra test)")
    probe = redis.Redis.from_url(REDIS_URL)
    try:
        probe.ping()
    except Exception as exc:
        probe.close()
        pytest.skip(f"redis not reachable at {REDIS_URL}: {exc}")
    opened = []

    def make_backplane(url=REDIS_URL):
        backplane = RedisBackplane(url=url)
        opened.append(backplane)
        return backplane

    yield SimpleNamespace(channel=f"tina4:ws:test:{uuid.uuid4().hex}", probe=probe, make=make_backplane)
    for backplane in opened:
        try:
            backplane.close()
        except Exception:
            pass
    probe.close()


def _wire_backplane(manager, bus):
    """Give `manager` its own real backplane on the test channel, the way
    _ensure_backplane wires one (loop captured for the thread->loop bridge)."""
    manager._backplane_channel = bus.channel
    manager._backplane = bus.make()
    manager._backplane_started = True
    manager._backplane_loop = asyncio.get_running_loop()
    manager._backplane.subscribe(bus.channel, manager._on_backplane_message)


async def _until_subscribed(bus, count):
    """Wait until Redis itself reports `count` subscribers on the channel, so a
    publish cannot race a subscription that is still in flight."""
    for _ in range(500):
        if dict(bus.probe.pubsub_numsub(bus.channel)).get(bus.channel.encode(), 0) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Redis never reported {count} subscriber(s) on {bus.channel}")


async def _until(predicate, what):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


async def _two_wired_managers(bus):
    manager_a, manager_b = WebSocketManager(), WebSocketManager()
    _wire_backplane(manager_a, bus)
    _wire_backplane(manager_b, bus)
    await _until_subscribed(bus, 2)
    return manager_a, manager_b


# ── Backplane relay + origin guard ────────────────────────────


class TestBackplaneRelay:
    async def test_remote_message_relayed_to_local_connections(self, redis_bus):
        """A broadcast from instance A is relayed to instance B's local conns."""
        mgr_a, mgr_b = await _two_wired_managers(redis_bus)
        conn_b = FakeConnection("b1")
        mgr_b.add(conn_b)

        # A broadcasts to all: delivers locally (A has none) then publishes.
        await mgr_a.broadcast_all("hello-cluster")

        await _until(lambda: conn_b.sent, "B to receive A's broadcast over Redis")
        assert conn_b.sent == ["hello-cluster"]

    async def test_origin_guard_drops_own_echo(self, redis_bus):
        """An envelope tagged with the manager's own instance id arrives over
        the real channel and is NOT re-delivered."""
        mgr = WebSocketManager()
        _wire_backplane(mgr, redis_bus)
        await _until_subscribed(redis_bus, 1)
        conn = FakeConnection("c1")
        mgr.add(conn)

        def envelope(source, text):
            return json.dumps({"src": source, "kind": "all", "exclude": None,
                               "room": None, "path": None, "text": text})

        publisher = redis_bus.make()
        publisher.publish(redis_bus.channel, envelope(mgr._instance_id, "echo-should-be-dropped"))
        # A foreign envelope published AFTER it: once it is delivered, the echo
        # (earlier on the same ordered channel) has certainly been processed.
        publisher.publish(redis_bus.channel, envelope("another-instance", "sentinel"))

        await _until(lambda: conn.sent, "the sentinel")
        assert conn.sent == ["sentinel"]

    async def test_real_broadcast_no_double_delivery(self, redis_bus):
        """A broadcast on A is delivered once on A (locally) and once on B (via
        the relay) - A does not re-deliver its own echo."""
        mgr_a, mgr_b = await _two_wired_managers(redis_bus)
        conn_a = FakeConnection("a1")
        conn_b = FakeConnection("b1")
        mgr_a.add(conn_a)
        mgr_b.add(conn_b)

        await mgr_a.broadcast_all("ping")
        await _until(lambda: conn_b.sent, "B to receive ping")
        # B answers; when A has B's reply, A has also processed its own echo of
        # "ping" (it arrived earlier on A's ordered subscription).
        await mgr_b.broadcast_all("pong")
        await _until(lambda: len(conn_a.sent) >= 2, "A to receive pong")

        assert conn_a.sent == ["ping", "pong"]
        assert conn_b.sent == ["ping", "pong"]

    async def test_room_relay_targets_only_room_members(self, redis_bus):
        mgr_a, mgr_b = await _two_wired_managers(redis_bus)
        in_room = FakeConnection("b_in")
        out_room = FakeConnection("b_out")
        mgr_b.add(in_room)
        mgr_b.add(out_room)
        mgr_b._join_room("b_in", "lobby")

        await mgr_a.broadcast_to_room("lobby", "room-msg")
        await mgr_a.broadcast_all("everyone")
        await _until(lambda: out_room.sent, "the broadcast to everyone")

        assert in_room.sent == ["room-msg", "everyone"]
        assert out_room.sent == ["everyone"]

    async def test_bytes_round_trip_through_envelope(self, redis_bus):
        """Binary payloads survive the JSON envelope via base64."""
        mgr_a, mgr_b = await _two_wired_managers(redis_bus)
        conn_b = FakeConnection("b1")
        mgr_b.add(conn_b)

        payload = b"\x00\x01\x02\xfffoo"
        await mgr_a.broadcast_all(payload)
        await _until(lambda: conn_b.sent, "the binary payload")

        assert conn_b.sent == [payload]
        assert isinstance(conn_b.sent[0], bytes)

    async def test_publish_encodes_bytes_as_b64(self, redis_bus):
        """The envelope on the wire stores bytes under 'b64' and str under 'text'."""
        captured = []
        listener = redis_bus.make()
        listener.subscribe(redis_bus.channel, lambda raw: captured.append(json.loads(raw)))
        await _until_subscribed(redis_bus, 1)

        mgr = WebSocketManager()
        mgr._backplane_channel = redis_bus.channel
        mgr._backplane = redis_bus.make()
        mgr._backplane_started = True

        mgr._publish("all", b"\x10\x20")
        mgr._publish("all", "plain text")
        await _until(lambda: len(captured) >= 2, "both envelopes")

        assert "b64" in captured[0]
        assert base64.b64decode(captured[0]["b64"]) == b"\x10\x20"
        assert captured[1]["text"] == "plain text"
        assert captured[0]["src"] == mgr._instance_id

    async def test_one_backplane_serves_two_channels_and_closes_cleanly(self, redis_bus):
        """Two subscriptions on ONE backplane both deliver, and close() stops
        the listener before closing its socket (no thread exception)."""
        backplane = redis_bus.make()
        second_channel = redis_bus.channel + ":second"
        received = []
        backplane.subscribe(redis_bus.channel, lambda raw: received.append(("first", raw)))
        backplane.subscribe(second_channel, lambda raw: received.append(("second", raw)))
        await _until_subscribed(redis_bus, 1)
        await _until(lambda: dict(redis_bus.probe.pubsub_numsub(second_channel)).get(second_channel.encode(), 0) >= 1,
                     "the second subscription")

        redis_bus.probe.publish(redis_bus.channel, "one")
        redis_bus.probe.publish(second_channel, "two")
        await _until(lambda: len(received) >= 2, "both channels")
        assert sorted(received) == [("first", "one"), ("second", "two")]

        def live_listeners():
            # redis-py's worker threads carry the PubSub they read from.
            return [thread for thread in threading.enumerate()
                    if getattr(thread, "pubsub", None) is backplane._pubsub and thread.is_alive()]

        # Exactly one reader for the one pub/sub socket, however many channels.
        assert len(live_listeners()) == 1
        backplane.close()
        # close() returns only once that reader is gone - never with a thread
        # still reading the socket it is about to close.
        assert live_listeners() == []

    def test_publish_is_noop_without_backplane(self):
        """No backplane configured → _publish does nothing and never raises."""
        mgr = WebSocketManager()
        # Should not raise even though no backplane is wired.
        mgr._publish("all", "noop")

    async def test_publish_failure_does_not_crash_broadcast(self, redis_bus):
        """A message bus that is down must never undo a local broadcast: a real
        RedisBackplane pointed at a closed port raises on publish."""
        mgr = WebSocketManager()
        mgr._backplane = redis_bus.make(url=f"redis://127.0.0.1:{_closed_port()}")
        mgr._backplane_started = True
        with pytest.raises(Exception):
            mgr._backplane.publish("probe", "the bus really is down")

        conn = FakeConnection("c1")
        mgr.add(conn)
        # broadcast_all delivers locally then publishes; publish raises but is
        # caught — local delivery still happened.
        await mgr.broadcast_all("survive")
        assert conn.sent == ["survive"]

    async def test_backplane_init_failure_degrades_to_local_only(self, monkeypatch):
        """If wiring the backplane blows up (Redis unreachable at startup: a real
        closed port), the manager logs and falls back to LOCAL-only delivery - a
        broadcast still reaches local connections and never raises. (Distinct
        from a publish-time failure: this is the _ensure_backplane path.)"""
        pytest.importorskip("redis", reason="redis client not installed (uv sync --extra test)")
        monkeypatch.setenv("TINA4_WS_BACKPLANE", "redis")
        monkeypatch.setenv("TINA4_WS_BACKPLANE_URL", f"redis://127.0.0.1:{_closed_port()}")
        mgr = WebSocketManager()
        conn = FakeConnection("c1")
        mgr.add(conn)
        # Must NOT raise even though the backplane cannot subscribe.
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
