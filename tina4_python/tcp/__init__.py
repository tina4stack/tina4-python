# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Raw TCP service — a user-facing, non-HTTP, long-lived binary TCP listener.

Governed by ADR-0102 (feature 142). A Tina4 app exposes its own protocol — a
GPS/GPRS car-tracker gateway (GT06/TK103/Concox/Teltonika) is the driving case —
in the SAME process as its HTTP dashboard, reusing the framework's config,
logging, ORM and queue, without hand-rolling socket lifecycle, limits, idle
reaping and backpressure.

    from tina4_python.tcp import tcp_service, tcp

    svc = tcp_service(port=5023, idle_timeout=0, max_connections=5000)

    @svc.on_data
    async def on_data(conn, data):
        frame = parse(data)                 # the APP frames the raw byte stream
        if frame.is_login:
            conn.identify(frame.imei)       # register under the device id
        await conn.send(ack_for(frame))     # ACK on the same socket

    # from an HTTP route, push a command to one device by its id:
    await tcp("trackers").send_to(imei, build_command("set_interval", 30))

The framework OWNS the socket hard-parts: a listener folded into the running
asyncio accept loop (D1 in-process), the connection lifecycle
(on_connect/on_data/on_close, optional on_line), a uniform connection object, a
name-keyed registry (send_to/connection/broadcast), max_connections refusal, an
idle reaper (default OFF — tracker sockets are long-lived and mostly silent),
graceful-shutdown drain, and write backpressure. The app OWNS protocol framing,
device authentication, and persistence.

Non-goals in v1 (ADR-0102): no CRC/length framing helper beyond on_line, no TLS
termination, no UDP, no replacement for the WebSocket surface.
"""
import asyncio
import errno
import os
import time

from tina4_python.debug import Log

__all__ = [
    "tcp_service",
    "tcp",
    "TcpService",
    "TcpConnection",
    "registered_services",
    "start_all",
    "stop_accepting_all",
    "drain_all",
    "clear_registry",
]

# A stalled reader must never grow server memory without bound: once this many
# bytes are queued for one connection and still unsent, that connection is
# dropped rather than buffered for ever. Overridable per service (explicit arg
# wins, ADR-0041) and, failing that, by TINA4_TCP_MAX_BACKLOG.
DEFAULT_MAX_BACKLOG = 1 << 20  # 1 MiB

# A read is bounded so one connection cannot hand the whole stream to on_data in
# a single unbounded allocation; the app reassembles frames across reads.
_READ_CHUNK = 65536

# Services registered at import time (app.py / src), keyed by name. The server
# loop starts every one of these on boot and drains them on shutdown.
_services: dict[str, "TcpService"] = {}


def _resolve_max_backlog(explicit) -> int:
    """Per-connection outstanding-write ceiling in bytes (explicit arg > env)."""
    if explicit is not None:
        try:
            value = int(explicit)
            return value if value > 0 else DEFAULT_MAX_BACKLOG
        except (TypeError, ValueError):
            return DEFAULT_MAX_BACKLOG
    raw = os.environ.get("TINA4_TCP_MAX_BACKLOG", "").strip()
    if not raw:
        return DEFAULT_MAX_BACKLOG
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_MAX_BACKLOG
    except ValueError:
        Log.warning(
            f"TINA4_TCP_MAX_BACKLOG={raw!r} is not a positive integer — "
            f"using the {DEFAULT_MAX_BACKLOG}-byte default instead"
        )
        return DEFAULT_MAX_BACKLOG


async def _maybe_await(result):
    """Run a callback result: await it when it is a coroutine, else leave it.

    Handlers may be plain functions or coroutines (D2 callback model); the app
    chooses per handler and the framework does not care which.
    """
    if asyncio.iscoroutine(result):
        return await result
    return result


class TcpConnection:
    """One live TCP connection — the uniform connection object (ADR-0102 D5).

    The SAME surface exists in all four frameworks so the primitive ports: raw
    bytes in through the service's callbacks, raw bytes out through ``send``, a
    registry id set by ``identify``, the raw socket peer in ``remote_addr``, and
    a per-connection ``context`` bag for the app's parse buffer and auth state.
    """

    __slots__ = ("reader", "writer", "_service", "_app_id", "context",
                 "_closed", "_close_fired", "_last_activity")

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, service: "TcpService"):
        self.reader = reader
        self.writer = writer
        self._service = service
        # None until the app calls identify() from its login handler.
        self._app_id: str | None = None
        # Per-connection mutable state bag — the app's parse buffer, auth flag,
        # decoded IMEI, anything it must carry between on_data calls.
        self.context: dict = {}
        self._closed = False
        self._close_fired = False
        # Updated on every inbound frame; the idle reaper reads it.
        self._last_activity = time.time()

    @property
    def id(self) -> str | None:
        """The registry id (the IMEI), or None until identify() is called."""
        return self._app_id

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def remote_addr(self):
        """The raw TCP peer address (host, port) — never a forwarded header."""
        try:
            return self.writer.get_extra_info("peername")
        except Exception:
            return None

    def identify(self, app_id) -> "TcpConnection":
        """Register this live connection under an app-chosen id (the IMEI).

        A second connection identifying with the same id SUPERSEDES the first in
        the registry — exactly a device that dropped and reconnected.
        """
        app_id = str(app_id)
        self._app_id = app_id
        self._service._register_id(app_id, self)
        return self

    async def send(self, data) -> bool:
        """Write raw bytes to THIS socket. Returns True when queued, False when
        the connection is closed or dropped for backpressure.

        A stalled reader (never draining) is bounded: once more than the
        service's ``max_backlog`` bytes are outstanding, the connection is
        dropped rather than buffered without end.
        """
        if self._closed:
            return False
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            self.writer.write(data)
            transport = self.writer.transport
            if transport is not None:
                outstanding = transport.get_write_buffer_size()
                if outstanding > self._service.max_backlog:
                    Log.warning(
                        f"tcp_service {self._service.name!r}: dropping a stalled "
                        f"reader — {outstanding} bytes queued exceeds the "
                        f"{self._service.max_backlog}-byte backlog limit"
                    )
                    await self.close()
                    return False
            await self.writer.drain()
            return True
        except (ConnectionError, OSError):
            await self.close()
            return False

    async def close(self) -> None:
        """Close this connection. on_close fires exactly once (from the read
        loop) and the registry entry is removed."""
        if self._closed:
            return
        self._closed = True
        try:
            if not self.writer.is_closing():
                self.writer.close()
        except (ConnectionError, OSError):
            pass


class TcpService:
    """A named raw TCP listener and its connection registry (ADR-0102)."""

    def __init__(self, port: int, name: str = "default", *,
                 on_connect=None, on_data=None, on_close=None, on_line=None,
                 idle_timeout: float = 0, max_connections: int | None = None,
                 max_backlog: int | None = None):
        self.port = int(port)
        self.name = name
        self.on_connect = on_connect
        self.on_data = on_data
        self.on_close = on_close
        self.on_line = on_line
        # Default OFF: tracker sockets are deliberately long-lived and mostly
        # idle between location packets, so a default reaper would kill healthy
        # devices. > 0 closes a connection silent for that many seconds.
        self.idle_timeout = float(idle_timeout or 0)
        self.max_connections = (int(max_connections)
                                if max_connections is not None else None)
        self.max_backlog = _resolve_max_backlog(max_backlog)

        # All live connections (for broadcast, count, drain) and the id->conn
        # registry (for send_to / connection).
        self._connections: set[TcpConnection] = set()
        self._by_id: dict[str, TcpConnection] = {}
        self._server: asyncio.base_events.Server | None = None
        self._owner = False
        self._bound_port: int | None = None
        self._reaper_task: asyncio.Task | None = None

    # ── Decorator / setter registration (D2 callback model) ──────────────────

    def on_connect_handler(self, func):
        self.on_connect = func
        return func

    def on_data_handler(self, func):
        self.on_data = func
        return func

    def on_close_handler(self, func):
        self.on_close = func
        return func

    def on_line_handler(self, func):
        self.on_line = func
        return func

    # Idiomatic decorator aliases: @svc.on_data etc.
    on_connect_decorator = on_connect_handler

    def __repr__(self) -> str:
        return (f"<TcpService name={self.name!r} port={self.port} "
                f"connections={len(self._connections)}>")

    @property
    def bound_port(self) -> int:
        """The port actually bound (resolves an ephemeral port=0 to the real
        one); falls back to the configured port before the listener binds."""
        if self._server is not None and self._server.sockets:
            try:
                return self._server.sockets[0].getsockname()[1]
            except (OSError, IndexError):
                pass
        return self._bound_port if self._bound_port is not None else self.port

    @property
    def is_owner(self) -> bool:
        """True on the one worker that bound the port (single-owner, D1)."""
        return self._owner

    def count(self) -> int:
        return len(self._connections)

    # ── Registry (D4 — server -> device push) ────────────────────────────────

    def _register_id(self, app_id: str, conn: TcpConnection) -> None:
        self._by_id[app_id] = conn  # supersede: the live reconnection wins

    def connection(self, app_id) -> TcpConnection | None:
        """The live connection for an app id, or None if unknown or closed."""
        conn = self._by_id.get(str(app_id))
        if conn is None or conn._closed:
            return None
        return conn

    async def send_to(self, app_id, data) -> bool:
        """Write bytes to exactly the connection identified by ``app_id``.

        A send to an unknown or closed id is a NO-OP that returns False — never
        a raise — so an HTTP route addressing a device that has gone offline
        does not 500.
        """
        conn = self.connection(app_id)
        if conn is None:
            return False
        return await conn.send(data)

    async def broadcast(self, data) -> int:
        """Write bytes to every live connection. Returns how many received it."""
        delivered = 0
        for conn in list(self._connections):
            if await conn.send(data):
                delivered += 1
        return delivered

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0"):
        """Bind the listener on ``host:port`` on the running event loop.

        SO_REUSEPORT is OFF by default, so under a multi-worker HTTP deployment
        exactly ONE worker wins the bind; a worker that finds the port already
        bound skips silently (single-owner, D1) rather than raising.
        """
        if self._server is not None:
            return self._server
        try:
            self._server = await asyncio.start_server(self._handle, host, self.port)
            self._owner = True
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                self._owner = False
                Log.info(
                    f"tcp_service {self.name!r} port {self.port} is already bound "
                    f"by another worker — single-owner, this worker will not bind"
                )
                return None
            raise
        self._bound_port = self.bound_port
        Log.info(f"tcp_service {self.name!r} listening on {host}:{self._bound_port}")
        self._start_idle_reaper()
        return self._server

    def stop_accepting(self) -> None:
        """Stop accepting new connections and cancel the idle reaper. Live
        connections are left to drain."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            self._reaper_task = None
        if self._server is not None and self._owner:
            self._server.close()

    async def drain(self) -> None:
        """Close every live connection (firing on_close) and release the
        listener. Called within the server's shutdown deadline."""
        for conn in list(self._connections):
            await conn.close()
        if self._server is not None and self._owner:
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001 — never fail the exit path
                pass
        self._server = None

    async def stop(self, timeout: float | None = None) -> None:
        """Stop accepting and drain in one call (used by direct callers/tests)."""
        self.stop_accepting()
        if timeout is not None and timeout > 0:
            try:
                async with asyncio.timeout(timeout):
                    await self.drain()
            except TimeoutError:
                Log.warning(
                    f"tcp_service {self.name!r} drain exceeded {timeout:g}s — "
                    f"forcing the remaining connections closed"
                )
        else:
            await self.drain()

    # ── Accept + per-connection read loop ────────────────────────────────────

    async def _handle(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> None:
        # Refuse past the limit BEFORE the connection joins the registry: a
        # device fleet must not exhaust server memory/fds through an unbounded
        # accept backlog.
        if (self.max_connections is not None
                and len(self._connections) >= self.max_connections):
            try:
                writer.close()
            except (ConnectionError, OSError):
                pass
            return

        conn = TcpConnection(reader, writer, self)
        # Raise the transport's high-water mark to the backlog limit so a write
        # only blocks (and is then dropped) at OUR ceiling, not at asyncio's
        # 64KB default — send() owns the drop decision.
        try:
            if writer.transport is not None:
                writer.transport.set_write_buffer_limits(high=self.max_backlog)
        except Exception:  # noqa: BLE001 — a transport without limits still works
            pass
        self._connections.add(conn)
        await self._run(conn)

    async def _run(self, conn: TcpConnection) -> None:
        line_buffer = b""
        try:
            if self.on_connect is not None:
                await _maybe_await(self.on_connect(conn))
            while True:
                try:
                    data = await conn.reader.read(_READ_CHUNK)
                except (ConnectionError, OSError):
                    break
                if not data:
                    break  # peer closed
                conn._last_activity = time.time()

                if self.on_data is not None:
                    # Raw bytes, exactly as received — never newline-split, never
                    # decoded. The app frames the stream itself.
                    await _maybe_await(self.on_data(conn, data))

                if self.on_line is not None:
                    line_buffer += data
                    while b"\n" in line_buffer:
                        line, _, line_buffer = line_buffer.partition(b"\n")
                        await _maybe_await(
                            self.on_line(conn, line.rstrip(b"\r")))

                if conn._closed:
                    break
        except Exception as exc:  # noqa: BLE001 — one bad conn never aborts accept
            Log.error(f"tcp_service {self.name!r} handler error: {exc}")
        finally:
            self._remove(conn)
            conn._closed = True
            if self.on_close is not None and not conn._close_fired:
                conn._close_fired = True
                try:
                    await _maybe_await(self.on_close(conn))
                except Exception as exc:  # noqa: BLE001
                    Log.error(f"tcp_service {self.name!r} on_close error: {exc}")
            try:
                if not conn.writer.is_closing():
                    conn.writer.close()
            except (ConnectionError, OSError):
                pass

    def _remove(self, conn: TcpConnection) -> None:
        self._connections.discard(conn)
        if conn._app_id is not None and self._by_id.get(conn._app_id) is conn:
            # Only remove the id when THIS connection still owns it; a newer
            # connection that superseded it keeps the id.
            del self._by_id[conn._app_id]

    # ── Idle reaper (D1 consumer shape — default OFF) ─────────────────────────

    def _start_idle_reaper(self) -> None:
        if self.idle_timeout <= 0 or self._reaper_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        # Sweep often enough that a silent connection is closed within about one
        # timeout window of going quiet.
        interval = max(0.1, self.idle_timeout / 2.0)
        self._reaper_task = loop.create_task(self._reaper_loop(interval))

    async def _reaper_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._reap_idle()
                except Exception as exc:  # noqa: BLE001 — a sweep never kills the loop
                    Log.error(f"tcp_service {self.name!r} idle reaper sweep failed: {exc}")
        except asyncio.CancelledError:
            raise

    async def _reap_idle(self) -> int:
        now = time.time()
        stale = [c for c in list(self._connections)
                 if (now - c._last_activity) >= self.idle_timeout]
        for conn in stale:
            await conn.close()
        return len(stale)


# ── Public surface ───────────────────────────────────────────────────────────

def tcp_service(port: int, name: str = "default", *,
                on_connect=None, on_data=None, on_close=None, on_line=None,
                idle_timeout: float = 0, max_connections: int | None = None,
                max_backlog: int | None = None) -> TcpService:
    """Register a named raw TCP service; the server binds it on boot (D1).

    Reachable from anywhere in the app by name via ``tcp(name)``. Options are
    read once here (explicit argument wins, ADR-0041); there is no env override
    of a per-service port/idle_timeout/max_connections in v1.
    """
    service = TcpService(
        port, name,
        on_connect=on_connect, on_data=on_data, on_close=on_close,
        on_line=on_line, idle_timeout=idle_timeout,
        max_connections=max_connections, max_backlog=max_backlog,
    )
    _services[name] = service
    return service


def tcp(name: str = "default") -> TcpService:
    """The registry for a named service, for server -> device push from a route.

    Raises KeyError for an unknown service name — that is a programming error,
    unlike a send to an unknown device id, which is a runtime no-op.
    """
    try:
        return _services[name]
    except KeyError:
        known = ", ".join(sorted(_services)) or "(none registered)"
        raise KeyError(
            f"no tcp_service named {name!r} is registered; known services: {known}"
        ) from None


def registered_services() -> list[TcpService]:
    return list(_services.values())


def clear_registry() -> None:
    """Drop every registered service (test isolation; not used in production)."""
    _services.clear()


async def start_all(host: str = "0.0.0.0") -> None:
    """Start every registered service on the running loop (called by the server
    on boot — built-in loop and production ASGI lifespan alike)."""
    for service in registered_services():
        try:
            await service.start(host)
        except Exception as exc:  # noqa: BLE001 — a bad service never stops boot
            Log.error(f"tcp_service {service.name!r} failed to start: {exc}")


def stop_accepting_all() -> None:
    """Stop every service accepting new connections (shutdown step 1)."""
    for service in registered_services():
        try:
            service.stop_accepting()
        except Exception as exc:  # noqa: BLE001
            Log.error(f"tcp_service {service.name!r} stop-accepting failed: {exc}")


async def drain_all() -> None:
    """Drain and release every service's connections (shutdown drain step)."""
    for service in registered_services():
        try:
            await service.drain()
        except Exception as exc:  # noqa: BLE001
            Log.error(f"tcp_service {service.name!r} drain failed: {exc}")
