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


def origin_allowed(headers: dict) -> bool:
    """Return True if the request's ``Origin`` is permitted to upgrade.

    Controlled by ``TINA4_WS_ALLOWED_ORIGINS`` (comma-separated list of exact
    origins, e.g. ``https://app.example.com,https://admin.example.com``).

    Empty/unset = allow ALL origins (current behaviour, no breakage). When set,
    only requests whose ``Origin`` header exactly matches a listed value are
    allowed; a missing ``Origin`` header is rejected once the allow-list is
    active. Header lookup is case-insensitive on the key."""
    raw = os.environ.get("TINA4_WS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return True  # No allow-list configured — permit everything.
    allowed = {o.strip() for o in raw.split(",") if o.strip()}
    if not allowed:
        return True
    # Headers may arrive with either exact or lowercased keys depending on the
    # upgrade path; check both.
    origin = headers.get("origin") or headers.get("Origin")
    return origin in allowed


def ws_token(headers: dict, query_string: str = "", subprotocol: str = "") -> "str | None":
    """Extract a bearer token from a WS upgrade handshake.

    Order: the ``Authorization: Bearer`` header (set by server/CLI/mobile
    clients), then the ``Sec-WebSocket-Protocol`` subprotocol in the form
    ``"bearer, <token>"`` (the only way a *browser* can pass a token, since
    ``new WebSocket()`` cannot set headers), then a ``?token=`` query param.
    Returns the token string or ``None``."""
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    proto = subprotocol or headers.get("sec-websocket-protocol") or headers.get("Sec-WebSocket-Protocol") or ""
    parts = [p.strip() for p in proto.split(",") if p.strip()]
    if len(parts) >= 2 and parts[0].lower() == "bearer":
        return parts[1] or None
    if query_string:
        from urllib.parse import parse_qs
        tok = parse_qs(query_string).get("token", [None])[0]
        if tok:
            return tok
    return None


def ws_authorized(route: dict, headers: dict, query_string: str = "", subprotocol: str = "") -> "tuple[dict | None, bool]":
    """Per-route WebSocket authentication, checked on the upgrade.

    A route is secured when ``route["auth_required"]`` is truthy (set by
    ``@secured()`` on the WS handler). Public routes (the default) always pass.
    A secured route needs a valid JWT via the Authorization header, the
    ``bearer`` subprotocol, or ``?token=``. Returns ``(payload, ok)`` — the
    verified token payload (or ``None``) and whether the upgrade may proceed."""
    if not route.get("auth_required"):
        return None, True
    from tina4_python.auth import Auth
    token = ws_token(headers, query_string, subprotocol)
    if not token:
        return None, False
    payload = Auth.valid_token_static(token)
    return payload, payload is not None


def _parse_http_headers(data: bytes) -> dict:
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


async def _read_frame(reader: asyncio.StreamReader, max_size: int = 1048576) -> tuple:
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
        self.auth = None   # verified JWT payload on a @secured WS route, else None
        self.connected_at = time.time()
        # Updated on every inbound frame; the idle reaper closes connections
        # that have been silent longer than TINA4_WS_IDLE_TIMEOUT (opt-in).
        self._last_activity = time.time()
        self._closed = False
        self._on_message: Callable | None = None
        self._on_close: Callable | None = None
        self._on_error: Callable | None = None
        self._manager: "WebSocketManager | None" = None
        self._fragments: list[bytes] = []
        self._fragment_opcode: int = 0
        self._rooms: set[str] = set()

        try:
            peername = writer.get_extra_info("peername")
            self.ip = peername[0] if peername else "unknown"
        except Exception:
            self.ip = "unknown"

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def connection_count(self) -> int:
        """Total open connections on this connection's manager.

        Convenience so chat-room / presence code can ask the connection
        directly rather than reaching back to the manager::

            async def on_message(conn, msg):
                await conn.send(f"There are {conn.connection_count} users here")

        Returns 1 (just this connection) when not attached to a manager.
        """
        if self._manager is None:
            return 1
        return self._manager.count()

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
            await self._manager.broadcast(message,
                                          exclude=self.id if exclude_self else None,
                                          path=self.path)

    async def broadcast_to(self, path: str, message: str | bytes):
        """Broadcast to all connections on a different path."""
        if self._manager:
            await self._manager.broadcast(message, path=path)

    # ── Rooms ──────────────────────────────────────────────────

    @property
    def rooms(self) -> set[str]:
        """Return the set of room names this connection has joined."""
        return self._rooms

    def join_room(self, room_name: str) -> None:
        """Join a named room."""
        self._rooms.add(room_name)
        if self._manager:
            self._manager._join_room(self.id, room_name)

    def leave_room(self, room_name: str) -> None:
        """Leave a named room."""
        self._rooms.discard(room_name)
        if self._manager:
            self._manager._leave_room(self.id, room_name)

    async def broadcast_to_room(self, room_name: str, message: str | bytes,
                                 exclude_self: bool = False) -> None:
        """Broadcast a message to all connections in a room."""
        if self._manager:
            exclude = self.id if exclude_self else None
            await self._manager.broadcast_to_room(room_name, message, exclude=exclude)

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
                fin, opcode, payload = await _read_frame(self.reader, max_size)
                self._last_activity = time.time()  # mark activity for idle reaper
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
        self._rooms: dict[str, set[str]] = {}  # room_name → set of connection IDs
        # ── Backplane (multi-instance scaling) ──────────────────────
        # Lazily wired on first broadcast (see _ensure_backplane). Each
        # instance owns a stable id so it can ignore its own echoes coming
        # back over the shared pub/sub channel (the origin guard).
        self._backplane = None
        self._backplane_loop = None
        self._backplane_started = False
        self._instance_id = uuid.uuid4().hex[:16]
        self._backplane_channel = "tina4:ws"

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
        # Remove from all rooms
        for room_name in list(ws._rooms):
            self._leave_room(ws.id, room_name)
        ws._rooms.clear()

    def get(self, ws_id: str) -> WebSocketConnection | None:
        return self._connections.get(ws_id)

    def get_by_path(self, path: str) -> list[WebSocketConnection]:
        ids = self._paths.get(path, set())
        return [self._connections[i] for i in ids if i in self._connections]

    def count(self) -> int:
        return len(self._connections)

    def count_by_path(self, path: str) -> int:
        return len(self._paths.get(path, set()))

    async def _safe_send(self, ws: WebSocketConnection, message: str | bytes) -> bool:
        """Send to ONE connection without letting a single dead client abort a
        broadcast loop. Returns True if delivered, False if the connection looks
        dead (the caller then prunes it). A failed send is logged, never silent."""
        try:
            await ws.send(message)
            return not ws._closed
        except Exception as exc:  # broken pipe, write error, etc.
            from tina4_python.debug import Log
            Log.warning(f"WebSocket send to {ws.id} failed, pruning: {exc}")
            return False

    # ── Backplane (multi-instance scaling) ──────────────────────
    #
    # When TINA4_WS_BACKPLANE is configured, every broadcast is ALSO published
    # to a shared pub/sub channel so sibling server instances can relay it to
    # their own local connections. The flow is:
    #
    #     instance A: broadcast() → deliver locally → _publish() → channel
    #                                                                  │
    #     instance B: backplane bg-thread → _on_backplane_message() ──┘
    #                   │ (origin guard drops A's own echoes by src id)
    #                   └→ run_coroutine_threadsafe(_relay_local, loop)
    #                        → deliver to B's LOCAL connections only (no re-publish)
    #
    # The backplane callback runs in a *background thread* owned by the
    # backplane (Redis pubsub thread / NATS loop thread), so it must hop back
    # onto the server's asyncio event loop before touching connections — hence
    # the captured _backplane_loop + run_coroutine_threadsafe bridge.

    def _ensure_backplane(self):
        """Lazily wire the configured backplane. Idempotent and best-effort —
        a failure here logs and leaves the manager in local-only mode; it must
        NEVER crash a broadcast."""
        if self._backplane_started:
            return
        # Set immediately so we only ever attempt the wiring once, even if it
        # fails (no retry storm on every broadcast).
        self._backplane_started = True
        from tina4_python.debug import Log
        try:
            from tina4_python.websocket.backplane import create_backplane
            backplane = create_backplane()
            if backplane is None:
                return  # No backplane configured — stay local-only.
            self._backplane = backplane
            try:
                self._backplane_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._backplane_loop = None
            self._backplane.subscribe(self._backplane_channel, self._on_backplane_message)
            Log.info(
                f"WebSocket backplane active (instance {self._instance_id}, "
                f"channel '{self._backplane_channel}')"
            )
        except Exception as exc:
            self._backplane = None
            Log.error(f"WebSocket backplane wiring failed, continuing local-only: {exc}")

    def _on_backplane_message(self, raw):
        """Receive a raw envelope from the backplane. Runs in the backplane's
        BACKGROUND THREAD — must hop onto the event loop to touch connections."""
        try:
            env = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(env, dict):
            return
        # Origin guard: ignore our own broadcasts echoed back over the channel.
        # We already delivered them locally; relaying again would double-send.
        if env.get("src") == self._instance_id:
            return
        if self._backplane_loop is not None:
            asyncio.run_coroutine_threadsafe(self._relay_local(env), self._backplane_loop)

    @staticmethod
    def _decode_envelope_message(env: dict):
        """Reconstruct the original str/bytes WS message from a backplane
        envelope. JSON can't carry bytes, so str → {"text": ...} and
        bytes → {"b64": base64(...)}."""
        if "text" in env:
            return env["text"]
        if "b64" in env:
            return base64.b64decode(env["b64"])
        return None

    async def _relay_local(self, env: dict):
        """Deliver a remote-originated envelope to LOCAL connections only.

        NEVER re-publishes (that would loop the message around the cluster).
        Dispatches by ``kind``: room / path / all."""
        message = self._decode_envelope_message(env)
        if message is None:
            return
        kind = env.get("kind")
        exclude = env.get("exclude")
        if kind == "room":
            room = env.get("room")
            targets = self.get_room_connections(room) if room else []
        elif kind == "path":
            path = env.get("path")
            targets = self.get_by_path(path) if path else []
        else:  # "all" (and anything unknown) → every local connection
            targets = list(self._connections.values())
        dead = [ws for ws in targets
                if not (exclude and ws.id == exclude)
                and not await self._safe_send(ws, message)]
        for ws in dead:
            self.remove(ws)

    def _publish(self, kind: str, message: str | bytes, room: str = None,
                 path: str = None, exclude: str = None):
        """Publish a broadcast to the shared channel for sibling instances.

        No-op when no backplane is configured. Best-effort — a publish failure
        logs and is swallowed so the local broadcast that already happened is
        never undone by a flaky message bus."""
        if not self._backplane:
            return
        from tina4_python.debug import Log
        envelope = {
            "src": self._instance_id,
            "kind": kind,
            "exclude": exclude,
            "room": room,
            "path": path,
        }
        # JSON can't carry bytes — encode str as text, bytes as base64.
        if isinstance(message, (bytes, bytearray)):
            envelope["b64"] = base64.b64encode(bytes(message)).decode()
        else:
            envelope["text"] = message
        try:
            self._backplane.publish(self._backplane_channel, json.dumps(envelope))
        except Exception as exc:
            Log.warning(f"WebSocket backplane publish failed: {exc}")

    async def broadcast(self, message: str | bytes, exclude: str = None, path: str = None):
        """Send message to all connections, optionally filtered by path.

        One dead/slow connection never aborts delivery to the rest — failed
        sends are logged and the dead connection is pruned afterwards. When a
        backplane is configured the message is also published to sibling
        instances."""
        self._ensure_backplane()
        targets = self.get_by_path(path) if path else list(self._connections.values())
        dead = [ws for ws in targets
                if not (exclude and ws.id == exclude)
                and not await self._safe_send(ws, message)]
        for ws in dead:
            self.remove(ws)
        self._publish("path" if path else "all", message, path=path, exclude=exclude)

    async def broadcast_all(self, message: str | bytes):
        """Send message to ALL connections (resilient to dead clients).

        Also fans out to sibling instances over the backplane when configured."""
        self._ensure_backplane()
        dead = [ws for ws in list(self._connections.values())
                if not await self._safe_send(ws, message)]
        for ws in dead:
            self.remove(ws)
        self._publish("all", message)

    async def send_to(self, client_id: str, message: str | bytes):
        """Send a message to a specific client by ID.

        Local-only: a connection lives on exactly one instance, so there is
        nothing to fan out over the backplane."""
        ws = self._connections.get(client_id)
        if ws and not await self._safe_send(ws, message):
            self.remove(ws)

    async def close(self, client_id: str, code: int = 1000, reason: str = ""):
        """Close a specific client connection by ID."""
        ws = self._connections.get(client_id)
        if ws:
            await ws.close(code, reason)
            self.remove(ws)

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

    async def reap_idle(self, timeout: float) -> int:
        """Close connections whose last inbound frame is older than *timeout*
        seconds. Returns the number reaped. ``timeout <= 0`` is a no-op (the
        reaper is opt-in via TINA4_WS_IDLE_TIMEOUT). Connections without a
        ``_last_activity`` attribute (e.g. some ASGI wrappers) are skipped."""
        if timeout <= 0:
            return 0
        now = time.time()
        stale = [
            ws for ws in list(self._connections.values())
            if (now - getattr(ws, "_last_activity", now)) > timeout
        ]
        for ws in stale:
            await ws.close(CLOSE_GOING_AWAY, "idle timeout")
            self.remove(ws)
        if stale:
            from tina4_python.debug import Log
            Log.info(f"WebSocket idle reaper closed {len(stale)} connection(s)")
        return len(stale)

    # ── Rooms ──────────────────────────────────────────────────

    def _join_room(self, ws_id: str, room_name: str) -> None:
        """Internal: add connection ID to a room."""
        if room_name not in self._rooms:
            self._rooms[room_name] = set()
        self._rooms[room_name].add(ws_id)

    def _leave_room(self, ws_id: str, room_name: str) -> None:
        """Internal: remove connection ID from a room."""
        if room_name in self._rooms:
            self._rooms[room_name].discard(ws_id)

    def room_count(self, room_name: str) -> int:
        """Return the number of connections in a room."""
        return len(self._rooms.get(room_name, set()))

    def get_room_connections(self, room_name: str) -> list["WebSocketConnection"]:
        """Return the list of WebSocketConnection objects in a room."""
        ids = self._rooms.get(room_name, set())
        return [self._connections[i] for i in ids if i in self._connections]

    def get_client_rooms(self, client_id: str) -> list[str]:
        """Return the list of room names a specific client belongs to.

        Mirrors PHP's ``getClientRooms()`` and the per-connection ``conn.rooms``
        property — useful when you have a client ID but not the connection
        object itself.
        """
        return [room for room, members in self._rooms.items() if client_id in members]

    async def broadcast_to_room(self, room_name: str, message: str | bytes,
                                 exclude: str = None) -> None:
        """Send message to all connections in a room (resilient to dead clients).

        Also fans out to sibling instances over the backplane when configured —
        a room can span instances, so each one delivers to its own members."""
        self._ensure_backplane()
        dead = [ws for ws in self.get_room_connections(room_name)
                if not (exclude and ws.id == exclude)
                and not await self._safe_send(ws, message)]
        for ws in dead:
            self.remove(ws)
        self._publish("room", message, room=room_name, exclude=exclude)


class WebSocketServer:
    """Native RFC 6455 WebSocket server using asyncio."""

    def __init__(self, host: str = "0.0.0.0", port: int = 7146):
        self.host = host
        self.port = port
        self.manager = WebSocketManager()
        self._handlers: dict[str, dict[str, Callable]] = {}
        self._server: asyncio.AbstractServer | None = None
        self._reaper_task: asyncio.Task | None = None

    def route(self, path: str, handler: Callable | None = None):
        """Register a WebSocket handler for a path.

        Can be used either as a decorator (``@server.route("/chat")``) or
        called directly with a handler (``server.route("/chat", chat_handler)``)
        for parity with PHP/Ruby/Node.

        Registers both on this server instance (standalone mode) and on the
        main Router (integrated mode) so routes work either way.

        The handler uses WebSocketServer style: ``async def handler(conn)``
        with ``@conn.on_message`` / ``@conn.on_close`` decorators.
        This is automatically adapted to the Router's ``(conn, event, data)``
        style for integrated mode.
        """
        def decorator(func):
            self._handlers[path] = {"handler": func}

            # Adapt to Router's (conn, event, data) style
            async def _router_adapter(conn, event, data):
                if event == "open":
                    result = func(conn)
                    if asyncio.iscoroutine(result):
                        await result
                elif event == "message":
                    if conn._on_message:
                        result = conn._on_message(data)
                        if asyncio.iscoroutine(result):
                            await result
                elif event == "close":
                    if conn._on_close:
                        result = conn._on_close()
                        if asyncio.iscoroutine(result):
                            await result

            from tina4_python.core.router import Router
            Router.websocket(path, _router_adapter)
            return func

        if handler is not None:
            return decorator(handler)
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

        headers = _parse_http_headers(request_data)
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

        # Origin allow-list (opt-in via TINA4_WS_ALLOWED_ORIGINS). Unset = allow
        # all, so this never breaks an existing deployment.
        if not origin_allowed(headers):
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
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
        """Start the WebSocket server (and the idle reaper if configured)."""
        self._server = await asyncio.start_server(
            self.handle_connection, self.host, self.port
        )
        self._start_idle_reaper()
        return self._server

    def _start_idle_reaper(self):
        """Spin up the idle-connection reaper task when TINA4_WS_IDLE_TIMEOUT is
        a positive number of seconds. Opt-in and non-breaking — unset/0 means no
        reaper task is created at all (current behaviour)."""
        try:
            timeout = float(os.environ.get("TINA4_WS_IDLE_TIMEOUT", "0") or "0")
        except (TypeError, ValueError):
            timeout = 0.0
        if timeout <= 0 or self._reaper_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        # Sweep at a fraction of the timeout (min 1s) so an idle conn is closed
        # within roughly one timeout window of going silent.
        interval = max(1.0, timeout / 2.0)
        self._reaper_task = loop.create_task(self._idle_reaper_loop(timeout, interval))

    async def _idle_reaper_loop(self, timeout: float, interval: float):
        """Periodically reap idle connections until cancelled."""
        from tina4_python.debug import Log
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.manager.reap_idle(timeout)
                except Exception as exc:  # never let a sweep kill the loop
                    Log.error(f"WebSocket idle reaper sweep failed: {exc}")
        except asyncio.CancelledError:
            raise

    async def stop(self):
        """Stop the server, cancel the reaper, and disconnect all clients."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reaper_task = None
        await self.manager.disconnect_all()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def get_clients(self) -> dict:
        """Return a dict of all connected WebSocketConnection objects keyed by ID."""
        return dict(self.manager._connections)

    def _handle_upgrade(self, reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> asyncio.Task:
        """Handle upgrade from an existing HTTP server (integration mode)."""
        return asyncio.create_task(self.handle_connection(reader, writer))


__all__ = [
    "WebSocketServer", "WebSocketConnection", "WebSocketManager",
    "compute_accept_key", "build_frame", "origin_allowed",
    "OP_TEXT", "OP_BINARY", "OP_CLOSE", "OP_PING", "OP_PONG",
    "CLOSE_NORMAL", "CLOSE_GOING_AWAY", "CLOSE_PROTOCOL_ERROR", "CLOSE_TOO_LARGE",
]
