# Tina4 WebSocket — Zero-dependency RFC 6455 implementation.
"""
Native WebSocket server using asyncio raw sockets.

    from tina4_python.websocket import WebSocketServer, WebSocketConnection, WebSocketManager

Supported:
    - HTTP Upgrade handshake (RFC 6455 Sec-WebSocket-Accept)
    - Frame protocol: text, binary, close, ping, pong
    - Masking / unmasking (client→server)
    - Extended payload lengths (7-bit, 16-bit, 64-bit)
    - Fragmented messages
    - Connection manager with broadcast
    - Per-path routing
"""
import asyncio
import hashlib
import base64
import struct
import json
import os
import uuid
import time
from typing import Callable

MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Opcodes
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# Close codes
CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_UNSUPPORTED = 1003
CLOSE_TOO_LARGE = 1009


def compute_accept_key(key: str) -> str:
    """Compute Sec-WebSocket-Accept from Sec-WebSocket-Key per RFC 6455."""
    digest = hashlib.sha1((key + MAGIC_STRING).encode()).digest()
    return base64.b64encode(digest).decode()


def parse_http_headers(data: bytes) -> dict:
    """Parse HTTP upgrade request headers."""
    lines = data.decode("utf-8", errors="replace").split("\r\n")
    headers = {}
    method_line = lines[0] if lines else ""
    parts = method_line.split(" ")
    if len(parts) >= 2:
        headers["_method"] = parts[0]
        headers["_path"] = parts[1]
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def build_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """Build a WebSocket frame (server→client, never masked)."""
    frame = bytearray()
    first_byte = (0x80 if fin else 0x00) | opcode
    frame.append(first_byte)

    length = len(payload)
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack(">Q", length))

    frame.extend(payload)
    return bytes(frame)


async def read_frame(reader: asyncio.StreamReader, max_size: int = 1048576) -> tuple:
    """Read one WebSocket frame. Returns (fin, opcode, payload).

    Raises ConnectionError on EOF or protocol violation.
    """
    header = await reader.readexactly(2)
    fin = (header[0] >> 7) & 1
    opcode = header[0] & 0x0F
    masked = (header[1] >> 7) & 1
    payload_len = header[1] & 0x7F

    if payload_len == 126:
        payload_len = struct.unpack(">H", await reader.readexactly(2))[0]
    elif payload_len == 127:
        payload_len = struct.unpack(">Q", await reader.readexactly(8))[0]

    if payload_len > max_size:
        raise ConnectionError(f"Frame too large: {payload_len} > {max_size}")

    mask_key = await reader.readexactly(4) if masked else None
    payload = await reader.readexactly(payload_len)

    if mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    return bool(fin), opcode, payload


class WebSocketConnection:
    """Represents a single WebSocket connection."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 path: str = "/", headers: dict = None, params: dict = None):
        self.id = str(uuid.uuid4())[:8]
        self.reader = reader
        self.writer = writer
        self.path = path
        self.headers = headers or {}
        self.params = params or {}
        self.connected_at = time.time()
        self._closed = False
        self._on_message: Callable | None = None
        self._on_close: Callable | None = None
        self._on_error: Callable | None = None
        self._manager: "WebSocketManager | None" = None
        self._fragments: list[bytes] = []
        self._fragment_opcode: int = 0

        try:
            peername = writer.get_extra_info("peername")
            self.ip = peername[0] if peername else "unknown"
        except Exception:
            self.ip = "unknown"

    @property
    def closed(self) -> bool:
        return self._closed

    async def send(self, message: str | bytes):
        """Send a text or binary message."""
        if self._closed:
            return
        if isinstance(message, str):
            self.writer.write(build_frame(OP_TEXT, message.encode("utf-8")))
        else:
            self.writer.write(build_frame(OP_BINARY, message))
        try:
            await self.writer.drain()
        except (ConnectionError, OSError):
            self._closed = True

    async def send_json(self, data):
        """Send data as JSON."""
        await self.send(json.dumps(data))

    async def broadcast(self, message: str | bytes, exclude_self: bool = False):
        """Broadcast to all connections on the same path."""
        if self._manager:
            await self._manager.broadcast(self.path, message,
                                          exclude=self.id if exclude_self else None)

    async def broadcast_to(self, path: str, message: str | bytes):
        """Broadcast to all connections on a different path."""
        if self._manager:
            await self._manager.broadcast(path, message)

    async def ping(self, data: bytes = b""):
        """Send a ping frame."""
        if self._closed:
            return
        self.writer.write(build_frame(OP_PING, data))
        try:
            await self.writer.drain()
        except (ConnectionError, OSError):
            self._closed = True

    async def close(self, code: int = CLOSE_NORMAL, reason: str = ""):
        """Send close frame and close the connection."""
        if self._closed:
            return
        self._closed = True
        payload = struct.pack(">H", code) + reason.encode("utf-8")
        try:
            self.writer.write(build_frame(OP_CLOSE, payload))
            await self.writer.drain()
            self.writer.close()
        except (ConnectionError, OSError):
            pass

    def on(self, event: str, handler: Callable):
        """Register an event handler by name: 'open', 'message', 'close', 'error'.

        Matches PHP/Ruby/Node.js ws.on("event", handler) pattern.
        """
        mapping = {
            "open": "_on_connect",
            "message": "_on_message",
            "close": "_on_close",
            "error": "_on_error",
        }
        attr = mapping.get(event)
        if attr is None:
            raise ValueError(f"Unknown WebSocket event: {event}. Use: open, message, close, error")
        setattr(self, attr, handler)
        return self

    def on_message(self, handler: Callable):
        """Register a message handler (decorator style)."""
        self._on_message = handler

    def on_close(self, handler: Callable):
        """Register a close handler (decorator style)."""
        self._on_close = handler

    def on_error(self, handler: Callable):
        """Register an error handler (decorator style)."""
        self._on_error = handler

    async def _handle_frame(self, fin: bool, opcode: int, payload: bytes):
        """Process a single frame."""
        if opcode == OP_CONTINUATION:
            self._fragments.append(payload)
            if fin:
                full = b"".join(self._fragments)
                self._fragments = []
                if self._fragment_opcode == OP_TEXT:
                    await self._dispatch_message(full.decode("utf-8", errors="replace"))
                else:
                    await self._dispatch_message(full)
            return

        if opcode == OP_CLOSE:
            if not self._closed:
                await self.close()
            return

        if opcode == OP_PING:
            self.writer.write(build_frame(OP_PONG, payload))
            try:
                await self.writer.drain()
            except (ConnectionError, OSError):
                pass
            return

        if opcode == OP_PONG:
            return

        if opcode in (OP_TEXT, OP_BINARY):
            if fin:
                if opcode == OP_TEXT:
                    await self._dispatch_message(payload.decode("utf-8", errors="replace"))
                else:
                    await self._dispatch_message(payload)
            else:
                self._fragment_opcode = opcode
                self._fragments = [payload]
            return

        await self.close(CLOSE_PROTOCOL_ERROR, "Unknown opcode")

    async def _dispatch_message(self, message):
        """Call the message handler."""
        if self._on_message:
            result = self._on_message(message)
            if asyncio.iscoroutine(result):
                await result

    async def _run(self):
        """Main frame loop."""
        max_size = int(os.environ.get("TINA4_WS_MAX_FRAME_SIZE", 1048576))
        try:
            while not self._closed:
                fin, opcode, payload = await read_frame(self.reader, max_size)
                await self._handle_frame(fin, opcode, payload)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self._closed = True
            if self._on_close:
                result = self._on_close()
                if asyncio.iscoroutine(result):
                    await result


class WebSocketManager:
    """Tracks all active WebSocket connections."""

    def __init__(self):
        self._connections: dict[str, WebSocketConnection] = {}
        self._paths: dict[str, set[str]] = {}

    def add(self, ws: WebSocketConnection):
        """Register a connection."""
        ws._manager = self
        self._connections[ws.id] = ws
        if ws.path not in self._paths:
            self._paths[ws.path] = set()
        self._paths[ws.path].add(ws.id)

    def remove(self, ws: WebSocketConnection):
        """Unregister a connection."""
        self._connections.pop(ws.id, None)
        if ws.path in self._paths:
            self._paths[ws.path].discard(ws.id)
            if not self._paths[ws.path]:
                del self._paths[ws.path]

    def get(self, ws_id: str) -> WebSocketConnection | None:
        return self._connections.get(ws_id)

    def get_by_path(self, path: str) -> list[WebSocketConnection]:
        ids = self._paths.get(path, set())
        return [self._connections[i] for i in ids if i in self._connections]

    def count(self) -> int:
        return len(self._connections)

    def count_by_path(self, path: str) -> int:
        return len(self._paths.get(path, set()))

    async def broadcast(self, path: str, message: str | bytes, exclude: str = None):
        """Send message to all connections on a path."""
        for ws in self.get_by_path(path):
            if exclude and ws.id == exclude:
                continue
            await ws.send(message)

    async def broadcast_all(self, message: str | bytes):
        """Send message to ALL connections."""
        for ws in list(self._connections.values()):
            await ws.send(message)

    async def disconnect(self, ws_id: str):
        """Force disconnect a connection."""
        ws = self._connections.get(ws_id)
        if ws:
            await ws.close()
            self.remove(ws)

    async def disconnect_all(self, path: str = None):
        """Force disconnect all connections (optionally filtered by path)."""
        targets = self.get_by_path(path) if path else list(self._connections.values())
        for ws in targets:
            await ws.close()
            self.remove(ws)


class WebSocketServer:
    """Native RFC 6455 WebSocket server using asyncio."""

    def __init__(self, host: str = "0.0.0.0", port: int = 7146):
        self.host = host
        self.port = port
        self.manager = WebSocketManager()
        self._handlers: dict[str, dict[str, Callable]] = {}
        self._server: asyncio.AbstractServer | None = None

    def route(self, path: str):
        """Decorator to register a WebSocket handler for a path."""
        def decorator(func):
            self._handlers[path] = {"handler": func}
            return func
        return decorator

    def on_connect(self, path: str):
        """Decorator for connection events."""
        def decorator(func):
            if path not in self._handlers:
                self._handlers[path] = {}
            self._handlers[path]["on_connect"] = func
            return func
        return decorator

    def on_disconnect(self, path: str):
        """Decorator for disconnection events."""
        def decorator(func):
            if path not in self._handlers:
                self._handlers[path] = {}
            self._handlers[path]["on_disconnect"] = func
            return func
        return decorator

    async def handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """Handle incoming connection — upgrade and enter frame loop."""
        try:
            request_data = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"), timeout=10
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            writer.close()
            return

        headers = parse_http_headers(request_data)
        path = headers.get("_path", "/")

        params = {}
        if "?" in path:
            path, query = path.split("?", 1)
            for pair in query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

        # Validate upgrade
        if headers.get("upgrade", "").lower() != "websocket":
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        ws_version = headers.get("sec-websocket-version", "")
        if ws_version and ws_version != "13":
            writer.write(b"HTTP/1.1 426 Upgrade Required\r\nSec-WebSocket-Version: 13\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        max_conns = int(os.environ.get("TINA4_WS_MAX_CONNECTIONS", 10000))
        if self.manager.count() >= max_conns:
            writer.write(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        # Send upgrade response
        accept = compute_accept_key(ws_key)
        response = (
            f"HTTP/1.1 101 Switching Protocols\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        ws = WebSocketConnection(reader, writer, path, headers, params)
        self.manager.add(ws)

        handler_config = self._handlers.get(path, {})

        on_connect = handler_config.get("on_connect")
        if on_connect:
            result = on_connect(ws)
            if asyncio.iscoroutine(result):
                await result

        handler = handler_config.get("handler")
        try:
            if handler:
                result = handler(ws)
                if asyncio.iscoroutine(result):
                    await result
            else:
                await ws._run()
        except Exception:
            pass
        finally:
            on_disconnect = handler_config.get("on_disconnect")
            if on_disconnect:
                result = on_disconnect(ws)
                if asyncio.iscoroutine(result):
                    await result
            self.manager.remove(ws)
            if not ws._closed:
                ws._closed = True
                try:
                    ws.writer.close()
                except Exception:
                    pass

    async def start(self):
        """Start the WebSocket server."""
        self._server = await asyncio.start_server(
            self.handle_connection, self.host, self.port
        )
        return self._server

    async def stop(self):
        """Stop the server and disconnect all clients."""
        await self.manager.disconnect_all()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def handle_upgrade(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> asyncio.Task:
        """Handle upgrade from an existing HTTP server (integration mode)."""
        return asyncio.create_task(self.handle_connection(reader, writer))


__all__ = [
    "WebSocketServer", "WebSocketConnection", "WebSocketManager",
    "compute_accept_key", "parse_http_headers", "build_frame", "read_frame",
    "OP_TEXT", "OP_BINARY", "OP_CLOSE", "OP_PING", "OP_PONG",
    "CLOSE_NORMAL", "CLOSE_PROTOCOL_ERROR", "CLOSE_TOO_LARGE",
]
