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


# ── Additional Tests: Accept Key ──────────────────────────────


class TestAcceptKeyExtra:
    def test_different_keys_produce_different_accepts(self):
        key1 = "dGhlIHNhbXBsZSBub25jZQ=="
        key2 = "x3JJHMbDL1EzLkh9GBhXDw=="
        assert compute_accept_key(key1) != compute_accept_key(key2)

    def test_produces_nonempty_base64(self):
        result = compute_accept_key("x3JJHMbDL1EzLkh9GBhXDw==")
        assert len(result) > 0
        assert result.endswith("=")

    def test_empty_key(self):
        result = compute_accept_key("")
        assert len(result) > 0

    def test_magic_string_value(self):
        assert MAGIC_STRING == "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ── Additional Tests: Header Parsing ─────────────────────────


class TestParseHeadersExtra:
    def test_host_header(self):
        raw = (
            b"GET /ws HTTP/1.1\r\n"
            b"Host: localhost:8080\r\n"
            b"\r\n"
        )
        headers = parse_http_headers(raw)
        assert headers["host"] == "localhost:8080"

    def test_missing_path(self):
        raw = b"\r\n"
        headers = parse_http_headers(raw)
        assert "_method" not in headers or "_path" not in headers

    def test_case_insensitive_keys(self):
        raw = (
            b"GET / HTTP/1.1\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
        )
        headers = parse_http_headers(raw)
        assert headers["content-type"] == "application/json"


# ── Additional Tests: Build Frame ────────────────────────────


class TestBuildFrameExtra:
    def test_binary_frame_opcode(self):
        frame = build_frame(OP_BINARY, b"\x00\x01\x02\x03")
        assert frame[0] & 0x0F == OP_BINARY

    def test_continuation_frame_opcode(self):
        from tina4_python.websocket import OP_CONTINUATION
        frame = build_frame(OP_CONTINUATION, b"continuation")
        assert frame[0] & 0x0F == OP_CONTINUATION

    def test_non_fin_with_correct_payload(self):
        frame = build_frame(OP_TEXT, b"partial", fin=False)
        assert frame[0] & 0x80 == 0  # FIN not set
        assert frame[2:] == b"partial"

    def test_fin_frame_has_fin_set(self):
        frame = build_frame(OP_TEXT, b"complete", fin=True)
        assert frame[0] & 0x80 == 0x80

    def test_boundary_125_bytes_small_encoding(self):
        payload = b"x" * 125
        frame = build_frame(OP_TEXT, payload)
        assert frame[1] == 125

    def test_boundary_126_bytes_extended_encoding(self):
        payload = b"x" * 126
        frame = build_frame(OP_TEXT, payload)
        assert frame[1] == 126

    def test_boundary_65535_uses_16bit(self):
        payload = b"x" * 65535
        frame = build_frame(OP_TEXT, payload)
        assert frame[1] == 126

    def test_boundary_65536_uses_64bit(self):
        payload = b"x" * 65536
        frame = build_frame(OP_TEXT, payload)
        assert frame[1] == 127

    def test_ping_with_data(self):
        frame = build_frame(OP_PING, b"ping-payload")
        assert frame[0] == 0x89
        assert frame[2:] == b"ping-payload"

    def test_pong_with_data(self):
        frame = build_frame(OP_PONG, b"pong-data")
        assert frame[0] == 0x8A
        assert frame[2:] == b"pong-data"

    def test_close_with_reason(self):
        reason = "Server shutting down"
        payload = struct.pack(">H", 1001) + reason.encode("utf-8")
        frame = build_frame(OP_CLOSE, payload)
        assert frame[0] == 0x88
        # Verify close code in frame payload
        assert struct.unpack(">H", frame[2:4])[0] == 1001
        assert frame[4:].decode("utf-8") == reason


# ── Additional Tests: Read Frame ─────────────────────────────


class TestReadFrameExtra:
    @pytest.mark.asyncio
    async def test_round_trip_empty(self):
        frame = build_frame(OP_TEXT, b"")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert fin is True
        assert opcode == OP_TEXT
        assert data == b""

    @pytest.mark.asyncio
    async def test_round_trip_single_char(self):
        frame = build_frame(OP_TEXT, b"a")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert data == b"a"

    @pytest.mark.asyncio
    async def test_round_trip_unicode(self):
        payload = "Unicode: \u00e9\u00e8\u00ea".encode("utf-8")
        frame = build_frame(OP_TEXT, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert data.decode("utf-8") == "Unicode: \u00e9\u00e8\u00ea"

    @pytest.mark.asyncio
    async def test_round_trip_medium_payload(self):
        payload = b"B" * 200
        frame = build_frame(OP_TEXT, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert len(data) == 200
        assert data[0] == 0x42
        assert data[199] == 0x42
        assert fin is True
        assert opcode == OP_TEXT

    @pytest.mark.asyncio
    async def test_round_trip_binary(self):
        payload = bytes(range(256))
        frame = build_frame(OP_BINARY, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_BINARY
        assert data == payload

    @pytest.mark.asyncio
    async def test_close_frame_round_trip(self):
        close_payload = struct.pack(">H", CLOSE_NORMAL)
        frame = build_frame(OP_CLOSE, close_payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_CLOSE
        assert struct.unpack(">H", data[:2])[0] == 1000

    @pytest.mark.asyncio
    async def test_close_with_reason_round_trip(self):
        reason = "Server shutting down"
        close_payload = struct.pack(">H", 1001) + reason.encode("utf-8")
        frame = build_frame(OP_CLOSE, close_payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_CLOSE
        assert struct.unpack(">H", data[:2])[0] == 1001
        assert data[2:].decode("utf-8") == reason

    @pytest.mark.asyncio
    async def test_ping_round_trip(self):
        frame = build_frame(OP_PING, b"ping-payload")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_PING
        assert data == b"ping-payload"

    @pytest.mark.asyncio
    async def test_pong_round_trip(self):
        frame = build_frame(OP_PONG, b"pong-data")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_PONG
        assert data == b"pong-data"

    @pytest.mark.asyncio
    async def test_non_fin_frame_read(self):
        frame = build_frame(OP_TEXT, b"partial", fin=False)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert fin is False
        assert data == b"partial"

    @pytest.mark.asyncio
    async def test_empty_ping_round_trip(self):
        frame = build_frame(OP_PING, b"")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        fin, opcode, data = await read_frame(reader)
        assert opcode == OP_PING
        assert data == b""


# ── Additional Tests: Constants ──────────────────────────────


class TestConstants:
    def test_op_text(self):
        assert OP_TEXT == 0x1

    def test_op_binary(self):
        assert OP_BINARY == 0x2

    def test_op_close(self):
        assert OP_CLOSE == 0x8

    def test_op_ping(self):
        assert OP_PING == 0x9

    def test_op_pong(self):
        assert OP_PONG == 0xA

    def test_close_normal(self):
        assert CLOSE_NORMAL == 1000

    def test_close_protocol_error(self):
        assert CLOSE_PROTOCOL_ERROR == 1002

    def test_close_going_away(self):
        from tina4_python.websocket import CLOSE_GOING_AWAY
        assert CLOSE_GOING_AWAY == 1001

    def test_close_unsupported(self):
        from tina4_python.websocket import CLOSE_UNSUPPORTED
        assert CLOSE_UNSUPPORTED == 1003

    def test_close_too_large(self):
        from tina4_python.websocket import CLOSE_TOO_LARGE
        assert CLOSE_TOO_LARGE == 1009

    def test_op_continuation(self):
        from tina4_python.websocket import OP_CONTINUATION
        assert OP_CONTINUATION == 0x0


# ── Additional Tests: Close Codes ────────────────────────────


class TestCloseCodes:
    @pytest.mark.asyncio
    async def test_close_1000_round_trip(self):
        payload = struct.pack(">H", 1000)
        frame = build_frame(OP_CLOSE, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        _, _, data = await read_frame(reader)
        assert struct.unpack(">H", data[:2])[0] == 1000

    @pytest.mark.asyncio
    async def test_close_1001_round_trip(self):
        payload = struct.pack(">H", 1001)
        frame = build_frame(OP_CLOSE, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        _, _, data = await read_frame(reader)
        assert struct.unpack(">H", data[:2])[0] == 1001

    @pytest.mark.asyncio
    async def test_close_1002_round_trip(self):
        payload = struct.pack(">H", 1002)
        frame = build_frame(OP_CLOSE, payload)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        _, _, data = await read_frame(reader)
        assert struct.unpack(">H", data[:2])[0] == 1002


# ── Additional Tests: WebSocket Connection ───────────────────


class TestWebSocketConnectionExtra:
    def _make_ws(self, path="/", ip="127.0.0.1", headers=None, params=None):
        reader = asyncio.StreamReader()
        transport = _MockTransport(ip)
        protocol = type("P", (), {})()
        loop = asyncio.new_event_loop()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        ws = WebSocketConnection(reader, writer, path, headers, params)
        loop.close()
        return ws

    def test_default_path(self):
        ws = self._make_ws()
        assert ws.path == "/"

    def test_default_headers(self):
        ws = self._make_ws()
        assert ws.headers == {}

    def test_default_params(self):
        ws = self._make_ws()
        assert ws.params == {}

    def test_connected_at_set(self):
        import time
        before = time.time()
        ws = self._make_ws()
        assert ws.connected_at >= before
        assert ws.connected_at <= time.time()

    def test_on_message_handler(self):
        ws = self._make_ws()
        handler = lambda msg: None
        ws.on_message(handler)
        assert ws._on_message is handler

    def test_on_close_handler(self):
        ws = self._make_ws()
        handler = lambda: None
        ws.on_close(handler)
        assert ws._on_close is handler

    def test_on_error_handler(self):
        ws = self._make_ws()
        handler = lambda err: None
        ws.on_error(handler)
        assert ws._on_error is handler

    def test_manager_set_on_add(self):
        mgr = WebSocketManager()
        ws = self._make_ws("/test")
        mgr.add(ws)
        assert ws._manager is mgr


# ── Additional Tests: WebSocket Manager ──────────────────────


class TestWebSocketManagerExtra:
    def _make_ws(self, path="/"):
        reader = asyncio.StreamReader()
        transport = _MockTransport()
        protocol = type("P", (), {})()
        loop = asyncio.new_event_loop()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        ws = WebSocketConnection(reader, writer, path)
        loop.close()
        return ws

    def test_remove_nonexistent(self):
        mgr = WebSocketManager()
        ws = self._make_ws()
        mgr.remove(ws)  # Should not raise
        assert mgr.count() == 0

    def test_count_by_path_empty(self):
        mgr = WebSocketManager()
        assert mgr.count_by_path("/nowhere") == 0

    def test_get_by_path_empty(self):
        mgr = WebSocketManager()
        assert mgr.get_by_path("/nowhere") == []

    def test_multiple_paths_multiple_connections(self):
        mgr = WebSocketManager()
        for _ in range(3):
            mgr.add(self._make_ws("/chat"))
        for _ in range(2):
            mgr.add(self._make_ws("/live"))
        assert mgr.count() == 5
        assert mgr.count_by_path("/chat") == 3
        assert mgr.count_by_path("/live") == 2


# ── Additional Tests: WebSocket Server ───────────────────────


class TestWebSocketServerExtra:
    def test_default_host_port(self):
        server = WebSocketServer()
        assert server.host == "0.0.0.0"
        assert server.port == 7146

    def test_custom_host_port(self):
        server = WebSocketServer(host="127.0.0.1", port=9000)
        assert server.host == "127.0.0.1"
        assert server.port == 9000

    def test_initial_manager_empty(self):
        server = WebSocketServer()
        assert server.manager.count() == 0

    def test_route_returns_handler(self):
        server = WebSocketServer()

        @server.route("/ws/test")
        async def handler(ws):
            pass

        assert handler is not None

    def test_on_connect_creates_path_entry(self):
        server = WebSocketServer()

        @server.on_connect("/ws/new")
        async def on_connect(ws):
            pass

        assert "/ws/new" in server._handlers

    def test_multiple_routes(self):
        server = WebSocketServer()

        @server.route("/ws/a")
        async def handler_a(ws):
            pass

        @server.route("/ws/b")
        async def handler_b(ws):
            pass

        assert "/ws/a" in server._handlers
        assert "/ws/b" in server._handlers

    def test_on_disconnect_without_prior_route(self):
        server = WebSocketServer()

        @server.on_disconnect("/ws/orphan")
        async def on_disconnect(ws):
            pass

        assert "/ws/orphan" in server._handlers
        assert "on_disconnect" in server._handlers["/ws/orphan"]
