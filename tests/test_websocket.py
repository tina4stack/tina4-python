# Tests for tina4_python.websocket
import asyncio
import struct
import pytest
from tina4_python.websocket import (
    compute_accept_key, parse_http_headers, build_frame, read_frame,
    WebSocketConnection, WebSocketManager, WebSocketServer,
    OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG,
    CLOSE_NORMAL, CLOSE_PROTOCOL_ERROR, MAGIC_STRING,
)


# ── Unit Tests ────────────────────────────────────────────────


class TestAcceptKey:
    def test_rfc_example(self):
        # RFC 6455 Section 4.2.2 example
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        assert compute_accept_key(key) == expected

    def test_deterministic(self):
        key = "abc123"
        assert compute_accept_key(key) == compute_accept_key(key)


class TestParseHeaders:
    def test_upgrade_request(self):
        raw = (
            b"GET /ws/chat HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"\r\n"
        )
        headers = parse_http_headers(raw)
        assert headers["_method"] == "GET"
        assert headers["_path"] == "/ws/chat"
        assert headers["upgrade"] == "websocket"
        assert headers["sec-websocket-key"] == "dGhlIHNhbXBsZSBub25jZQ=="
        assert headers["sec-websocket-version"] == "13"


class TestBuildFrame:
    def test_text_frame(self):
        payload = b"Hello"
        frame = build_frame(OP_TEXT, payload)
        assert frame[0] == 0x81  # FIN + TEXT
        assert frame[1] == 5    # payload length
        assert frame[2:] == b"Hello"

    def test_empty_frame(self):
        frame = build_frame(OP_TEXT, b"")
        assert frame[0] == 0x81
        assert frame[1] == 0

    def test_medium_frame(self):
        payload = b"x" * 200
        frame = build_frame(OP_TEXT, payload)
        assert frame[1] == 126  # Extended 16-bit length
        length = struct.unpack(">H", frame[2:4])[0]
        assert length == 200

    def test_large_frame(self):
        payload = b"x" * 70000
        frame = build_frame(OP_BINARY, payload)
        assert frame[1] == 127  # Extended 64-bit length
        length = struct.unpack(">Q", frame[2:10])[0]
        assert length == 70000

    def test_non_fin_frame(self):
        frame = build_frame(OP_TEXT, b"part", fin=False)
        assert frame[0] & 0x80 == 0  # FIN bit not set

    def test_close_frame(self):
        payload = struct.pack(">H", CLOSE_NORMAL) + b"bye"
        frame = build_frame(OP_CLOSE, payload)
        assert frame[0] == 0x88  # FIN + CLOSE

    def test_ping_frame(self):
        frame = build_frame(OP_PING, b"")
        assert frame[0] == 0x89  # FIN + PING

    def test_pong_frame(self):
        frame = build_frame(OP_PONG, b"")
        assert frame[0] == 0x8A  # FIN + PONG


class TestReadFrame:
    @pytest.mark.asyncio
    async def test_unmasked_text(self):
        payload = b"Hello"
        frame = build_frame(OP_TEXT, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert fin is True
        assert opcode == OP_TEXT
        assert data == b"Hello"

    @pytest.mark.asyncio
    async def test_masked_text(self):
        # Build a masked frame manually (client→server)
        payload = b"Hello"
        mask_key = b"\x37\xfa\x21\x3d"
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        frame = bytearray()
        frame.append(0x81)  # FIN + TEXT
        frame.append(0x80 | len(payload))  # MASK bit + length
        frame.extend(mask_key)
        frame.extend(masked)

        reader = asyncio.StreamReader()
        reader.feed_data(bytes(frame))
        fin, opcode, data = await read_frame(reader)
        assert fin is True
        assert opcode == OP_TEXT
        assert data == b"Hello"

    @pytest.mark.asyncio
    async def test_oversized_frame_rejected(self):
        payload = b"x" * 100
        frame = build_frame(OP_TEXT, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        with pytest.raises(ConnectionError, match="Frame too large"):
            await read_frame(reader, max_size=50)


# ── Connection Manager ───────────────────────────────────────


class _MockTransport:
    def __init__(self, ip="127.0.0.1"):
        self._ip = ip

    def get_extra_info(self, key, default=None):
        if key == "peername":
            return (self._ip, 0)
        return default

    def is_closing(self):
        return False


def _mock_transport(ip="127.0.0.1"):
    return _MockTransport(ip)


class TestWebSocketManager:
    def _make_ws(self, path="/"):
        reader = asyncio.StreamReader()
        transport = _mock_transport()
        protocol = type("P", (), {})()
        loop = asyncio.new_event_loop()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        ws = WebSocketConnection(reader, writer, path)
        loop.close()
        return ws

    def test_add_remove(self):
        mgr = WebSocketManager()
        ws = self._make_ws("/chat")
        mgr.add(ws)
        assert mgr.count() == 1
        assert mgr.count_by_path("/chat") == 1
        mgr.remove(ws)
        assert mgr.count() == 0

    def test_get_by_path(self):
        mgr = WebSocketManager()
        ws1 = self._make_ws("/chat")
        ws2 = self._make_ws("/chat")
        ws3 = self._make_ws("/live")
        mgr.add(ws1)
        mgr.add(ws2)
        mgr.add(ws3)
        assert len(mgr.get_by_path("/chat")) == 2
        assert len(mgr.get_by_path("/live")) == 1
        assert len(mgr.get_by_path("/other")) == 0

    def test_get_by_id(self):
        mgr = WebSocketManager()
        ws = self._make_ws()
        mgr.add(ws)
        assert mgr.get(ws.id) is ws
        assert mgr.get("nonexistent") is None

    def test_paths_independent(self):
        mgr = WebSocketManager()
        ws1 = self._make_ws("/a")
        ws2 = self._make_ws("/b")
        mgr.add(ws1)
        mgr.add(ws2)
        assert mgr.count() == 2
        assert mgr.count_by_path("/a") == 1
        assert mgr.count_by_path("/b") == 1

    def test_remove_cleans_path(self):
        mgr = WebSocketManager()
        ws = self._make_ws("/chat")
        mgr.add(ws)
        mgr.remove(ws)
        assert "/chat" not in mgr._paths


class TestWebSocketConnectionProperties:
    def test_connection_id_unique(self):
        reader = asyncio.StreamReader()
        transport = _mock_transport("10.0.0.1")
        protocol = type("P", (), {})()
        loop = asyncio.new_event_loop()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        ws1 = WebSocketConnection(reader, writer, "/test", {"x-custom": "1"}, {"room": "lobby"})
        ws2 = WebSocketConnection(reader, writer, "/test")
        loop.close()
        assert ws1.id != ws2.id
        assert ws1.path == "/test"
        assert ws1.params == {"room": "lobby"}
        assert ws1.ip == "10.0.0.1"

    def test_closed_default(self):
        reader = asyncio.StreamReader()
        transport = _mock_transport()
        protocol = type("P", (), {})()
        loop = asyncio.new_event_loop()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        ws = WebSocketConnection(reader, writer)
        loop.close()
        assert ws.closed is False


class TestWebSocketServer:
    def test_route_registration(self):
        server = WebSocketServer()

        @server.route("/ws/chat")
        async def chat(ws):
            pass

        assert "/ws/chat" in server._handlers
        assert "handler" in server._handlers["/ws/chat"]

    def test_on_connect_registration(self):
        server = WebSocketServer()

        @server.on_connect("/ws/chat")
        async def connected(ws):
            pass

        assert "/ws/chat" in server._handlers
        assert "on_connect" in server._handlers["/ws/chat"]

    def test_on_disconnect_registration(self):
        server = WebSocketServer()

        @server.on_disconnect("/ws/chat")
        async def disconnected(ws):
            pass

        assert "on_disconnect" in server._handlers["/ws/chat"]
