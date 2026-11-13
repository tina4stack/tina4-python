# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Raw TCP service contract — feature 142, ADR-0102.

The executable side of
``tina4-documentation/plan/v3/fixtures/raw_tcp_service_contract.json``. Every
case runs a REAL client socket against a REAL in-process listener — no mocks, no
doubles. Two cases (in-process alongside HTTP, and SIGTERM drain) boot a REAL
framework child server via ``boot_child_server`` so the listener folds into the
genuine accept loop and the genuine shutdown path.

Each test names, in its docstring, the mutation that must turn it red — the proof
it is a gate and not a ghost.
"""
import asyncio
import os
import signal
import time

import pytest

from conftest import free_port, boot_child_server, port_open
from tina4_python import tcp as tcp_module
from tina4_python.tcp import TcpService, tcp_service, tcp


# ── Real-socket helpers (no doubles) ─────────────────────────────────────────

async def _connect(host, port, timeout=2.0):
    return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)


async def _aclose(writer):
    try:
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
    except (OSError, asyncio.TimeoutError):
        pass


async def _wait(predicate, timeout=2.0, interval=0.01):
    """Poll a real condition (a server-side side effect) until true or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _start(svc, host="127.0.0.1"):
    await svc.start(host)
    return svc.bound_port


@pytest.fixture(autouse=True)
def _clean_registry():
    """No global service registration leaks between tests."""
    tcp_module.clear_registry()
    yield
    tcp_module.clear_registry()


# ── Invariant tcp-callbacks-raw-and-line ─────────────────────────────────────

async def test_on_data_delivers_raw_bytes_not_split_on_newlines():
    """on_data sees the raw bytes exactly as received — not newline-split, not
    decoded. Mutation: make _run split on_data on newlines and this joins wrong."""
    received = []
    svc = TcpService(0, "raw", on_data=lambda c, d: received.append(d))
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        writer.write(b"a\nb\nc")
        await writer.drain()
        await _wait(lambda: b"".join(received) == b"a\nb\nc")
        joined = b"".join(received)
        assert joined == b"a\nb\nc", f"raw bytes must arrive intact, got {joined!r}"
        assert b"\n" in joined, "newlines must NOT be stripped by on_data"
        assert all(isinstance(buf, (bytes, bytearray)) for buf in received), \
            "on_data must deliver bytes, never a decoded str"
        await _aclose(writer)
    finally:
        await svc.stop()


async def test_on_line_splits_a_newline_delimited_stream():
    """on_line delivers one line at a time with the terminator stripped, and an
    unterminated tail stays buffered until its newline arrives. Mutation: stop
    stripping \\r, or deliver the tail early, and the asserts fail."""
    lines = []
    svc = TcpService(0, "lines", on_line=lambda c, line: lines.append(line))
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        writer.write(b"a\r\nb\nc")  # 'c' has no terminator yet
        await writer.drain()
        await _wait(lambda: lines == [b"a", b"b"])
        assert lines == [b"a", b"b"], f"terminator must be stripped, got {lines!r}"
        # 'c' must still be buffered — not delivered until its newline arrives.
        writer.write(b"\n")
        await writer.drain()
        await _wait(lambda: lines == [b"a", b"b", b"c"])
        assert lines == [b"a", b"b", b"c"], "the tail delivers only once terminated"
        await _aclose(writer)
    finally:
        await svc.stop()


async def test_on_close_fires_once_when_peer_closes():
    """on_close fires exactly once on peer close and the connection leaves the
    registry. Mutation: fire on_close twice, or never, or skip _remove — red."""
    closes = []
    svc = TcpService(0, "close1", on_close=lambda c: closes.append(c))
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        await _wait(lambda: svc.count() == 1)
        assert svc.count() == 1
        await _aclose(writer)
        await _wait(lambda: len(closes) == 1 and svc.count() == 0)
        assert len(closes) == 1, f"on_close must fire exactly once, fired {len(closes)}"
        assert svc.count() == 0, "a closed connection must leave the registry"
    finally:
        await svc.stop()


# ── Invariant tcp-binary-roundtrip-ack ───────────────────────────────────────

async def test_binary_frame_roundtrips_and_is_acked():
    """A binary frame in, a fixed ACK out on the same socket, bytes exact and in
    order. Mutation: have send() mangle/reorder bytes and the readexactly fails."""
    ack = bytes([0x78, 0x78, 0x05, 0x01])
    frame = bytes([0x78, 0x78, 0x11, 0x0A, 0xFF, 0x00])

    async def on_data(conn, data):
        await conn.send(ack)

    svc = TcpService(0, "ack", on_data=on_data)
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        writer.write(frame)
        await writer.drain()
        got = await asyncio.wait_for(reader.readexactly(len(ack)), timeout=2.0)
        assert got == ack, f"ACK bytes must round-trip exactly, got {got!r}"
        await _aclose(writer)
    finally:
        await svc.stop()


# ── Invariant tcp-identify-registry-push ─────────────────────────────────────

def _login_service(name="reg"):
    """A service whose on_data identifies a connection by a 'LOGIN:<id>' frame,
    exactly as a tracker's login packet would."""
    async def on_data(conn, data):
        if data.startswith(b"LOGIN:"):
            conn.identify(data[len(b"LOGIN:"):].decode())
    return TcpService(0, name, on_data=on_data)


async def test_identify_registers_and_send_to_reaches_that_socket():
    """identify() registers; send_to() reaches that exact socket. Mutation: make
    _register_id a no-op and send_to never arrives."""
    svc = _login_service()
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        writer.write(b"LOGIN:imeiA")
        await writer.drain()
        assert await _wait(lambda: svc.connection("imeiA") is not None), \
            "identify() must register the connection under its id"
        delivered = await svc.send_to("imeiA", b"CMD1")
        assert delivered is True
        got = await asyncio.wait_for(reader.readexactly(4), timeout=2.0)
        assert got == b"CMD1", f"send_to must reach the identified socket, got {got!r}"
        await _aclose(writer)
    finally:
        await svc.stop()


async def test_send_to_is_isolated_to_the_addressed_device():
    """send_to('imeiA') reaches A and NOT B. Mutation: broadcast instead of
    addressing one, and B wrongly receives."""
    svc = _login_service("iso")
    port = await _start(svc)
    try:
        ra, wa = await _connect("127.0.0.1", port)
        rb, wb = await _connect("127.0.0.1", port)
        wa.write(b"LOGIN:imeiA"); await wa.drain()
        wb.write(b"LOGIN:imeiB"); await wb.drain()
        assert await _wait(lambda: svc.connection("imeiA") and svc.connection("imeiB"))
        await svc.send_to("imeiA", b"ONLYA")
        got_a = await asyncio.wait_for(ra.readexactly(5), timeout=2.0)
        assert got_a == b"ONLYA"
        # B must receive NOTHING — a read must time out.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(rb.readexactly(1), timeout=0.4)
        await _aclose(wa)
        await _aclose(wb)
    finally:
        await svc.stop()


async def test_send_to_unknown_id_is_a_noop_not_a_raise():
    """send_to an unknown id returns falsey without raising. Mutation: raise on a
    missing id and this test errors instead of passing."""
    svc = _login_service("ghost")
    await _start(svc)
    try:
        result = await svc.send_to("ghost", b"CMD")
        assert not result, "send_to to an unknown id must be a no-op return"
    finally:
        await svc.stop()


async def test_broadcast_reaches_every_live_connection():
    """broadcast() reaches all three sockets. Mutation: iterate a subset and a
    client misses the message."""
    svc = _login_service("bcast")
    port = await _start(svc)
    writers = []
    try:
        readers = []
        for ident in (b"imei1", b"imei2", b"imei3"):
            r, w = await _connect("127.0.0.1", port)
            w.write(b"LOGIN:" + ident); await w.drain()
            readers.append(r); writers.append(w)
        assert await _wait(lambda: svc.count() == 3)
        delivered = await svc.broadcast(b"PING!")
        assert delivered == 3, f"broadcast must reach all 3, reached {delivered}"
        for r in readers:
            got = await asyncio.wait_for(r.readexactly(5), timeout=2.0)
            assert got == b"PING!"
    finally:
        for w in writers:
            await _aclose(w)
        await svc.stop()


async def test_reidentify_with_the_same_id_supersedes_the_first():
    """A second connection identifying as 'imeiA' supersedes the first — the
    live reconnection wins. Mutation: keep the first registered and send_to
    reaches the stale socket."""
    svc = _login_service("redup")
    port = await _start(svc)
    try:
        r1, w1 = await _connect("127.0.0.1", port)
        w1.write(b"LOGIN:imeiA"); await w1.drain()
        assert await _wait(lambda: svc.connection("imeiA") is not None)
        first = svc.connection("imeiA")

        r2, w2 = await _connect("127.0.0.1", port)
        w2.write(b"LOGIN:imeiA"); await w2.drain()
        assert await _wait(lambda: svc.connection("imeiA") is not first)

        await svc.send_to("imeiA", b"TO2!!")
        got2 = await asyncio.wait_for(r2.readexactly(5), timeout=2.0)
        assert got2 == b"TO2!!", "send_to must reach the live (second) connection"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(r1.readexactly(1), timeout=0.4)
        await _aclose(w1)
        await _aclose(w2)
    finally:
        await svc.stop()


# ── Invariant tcp-connection-object ──────────────────────────────────────────

async def test_remote_addr_is_the_raw_socket_peer():
    """conn.remote_addr is the raw TCP peer, never a forwarded header. Mutation:
    return a header value and the loopback host assert fails."""
    seen = []
    svc = TcpService(0, "peer", on_connect=lambda c: seen.append(c.remote_addr))
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        await _wait(lambda: seen)
        assert seen, "on_connect must have run"
        host = seen[0][0]
        assert host in ("127.0.0.1", "::1", "::ffff:127.0.0.1"), \
            f"remote_addr must be the raw loopback peer, got {seen[0]!r}"
        await _aclose(writer)
    finally:
        await svc.stop()


async def test_context_persists_across_on_data_for_one_connection():
    """conn.context carries state between on_data calls for one connection, and a
    different connection has its own. Mutation: rebuild context per call and the
    accumulated buffer is lost."""
    async def on_data(conn, data):
        conn.context.setdefault("buf", b"")
        conn.context["buf"] += data

    svc = TcpService(0, "ctx", on_data=on_data)
    port = await _start(svc)
    try:
        r1, w1 = await _connect("127.0.0.1", port)
        w1.write(b"AA"); await w1.drain()
        await asyncio.sleep(0.05)
        w1.write(b"BB"); await w1.drain()
        # Find this connection's server-side object and assert its context grew.
        assert await _wait(
            lambda: any(c.context.get("buf") == b"AABB" for c in svc._connections))
        r2, w2 = await _connect("127.0.0.1", port)
        w2.write(b"ZZ"); await w2.drain()
        assert await _wait(
            lambda: any(c.context.get("buf") == b"ZZ" for c in svc._connections))
        bufs = sorted(c.context.get("buf", b"") for c in svc._connections)
        assert bufs == [b"AABB", b"ZZ"], \
            f"each connection must keep its own context, got {bufs!r}"
        await _aclose(w1)
        await _aclose(w2)
    finally:
        await svc.stop()


async def test_close_ends_the_connection_and_fires_on_close():
    """conn.close() closes the socket, fires on_close once, removes the registry
    entry. Mutation: skip _remove in the finally and count stays 1."""
    closed = []
    svc = _login_service("objclose")
    svc.on_close = lambda c: closed.append(c.id)
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        writer.write(b"LOGIN:imeiZ"); await writer.drain()
        assert await _wait(lambda: svc.connection("imeiZ") is not None)
        conn = svc.connection("imeiZ")
        await conn.close()
        # The client must observe EOF (socket really closed).
        tail = await asyncio.wait_for(reader.read(1), timeout=2.0)
        assert tail == b"", "close() must close the client socket"
        await _wait(lambda: closed == ["imeiZ"] and svc.count() == 0)
        assert closed == ["imeiZ"], f"on_close must fire once, got {closed!r}"
        assert svc.connection("imeiZ") is None, "registry entry must be removed"
        await _aclose(writer)
    finally:
        await svc.stop()


# ── Invariant tcp-max-connections-refusal ────────────────────────────────────

async def test_nth_plus_one_connection_is_refused():
    """With max_connections=2 the third connection is refused/closed promptly and
    the two live ones are unaffected. Mutation: drop the limit check and the
    third stays open (count reaches 3)."""
    svc = TcpService(0, "cap", max_connections=2)
    port = await _start(svc)
    writers = []
    try:
        for _ in range(2):
            r, w = await _connect("127.0.0.1", port)
            writers.append(w)
        assert await _wait(lambda: svc.count() == 2)
        r3, w3 = await _connect("127.0.0.1", port)
        writers.append(w3)
        # The refused connection is closed promptly — a read returns EOF.
        tail = await asyncio.wait_for(r3.read(1), timeout=2.0)
        assert tail == b"", "the (N+1)th connection must be refused/closed"
        await asyncio.sleep(0.1)
        assert svc.count() == 2, f"existing connections must be unaffected, count={svc.count()}"
    finally:
        for w in writers:
            await _aclose(w)
        await svc.stop()


# ── Invariant tcp-idle-reaper-default-off ────────────────────────────────────

async def test_idle_timeout_zero_keeps_a_silent_connection_open():
    """idle_timeout=0 (default) never reaps a silent connection. Mutation: start
    a reaper when timeout==0 and the silent connection is closed."""
    svc = TcpService(0, "idle0", idle_timeout=0)
    port = await _start(svc)
    try:
        reader, writer = await _connect("127.0.0.1", port)
        await _wait(lambda: svc.count() == 1)
        assert svc._reaper_task is None, "idle_timeout=0 must start no reaper"
        await asyncio.sleep(0.6)  # longer than any sub-second reap window
        assert svc.count() == 1, "a silent connection must stay open when timeout=0"
        await _aclose(writer)
    finally:
        await svc.stop()


async def test_idle_timeout_positive_reaps_only_the_silent_connection():
    """idle_timeout>0 reaps a silent connection (on_close fires) but spares one
    that keeps sending. Mutation: reap on activity too and the active one dies."""
    closed = []
    svc = TcpService(0, "idlereap", idle_timeout=0.3,
                     on_close=lambda c: closed.append(c))
    port = await _start(svc)
    try:
        r_silent, w_silent = await _connect("127.0.0.1", port)
        r_active, w_active = await _connect("127.0.0.1", port)
        await _wait(lambda: svc.count() == 2)
        # Keep the active one busy across the reap window.
        for _ in range(6):
            w_active.write(b"x"); await w_active.drain()
            await asyncio.sleep(0.1)
        # The silent one must have been reaped; the active one survives.
        assert await _wait(lambda: len(closed) == 1, timeout=2.0), \
            "the silent connection must be reaped"
        tail = await asyncio.wait_for(r_silent.read(1), timeout=2.0)
        assert tail == b"", "the reaped socket must be closed"
        assert svc.connection is not None
        assert any(not c._closed for c in svc._connections) or svc.count() == 1, \
            "the active connection must NOT be reaped"
        await _aclose(w_silent)
        await _aclose(w_active)
    finally:
        await svc.stop()


# ── Invariant tcp-backpressure ───────────────────────────────────────────────

async def test_a_stalled_reader_is_bounded_and_dropped():
    """A client that never reads is bounded to the backlog ceiling and then
    dropped, while other connections keep serving. Mutation: remove the backlog
    check in send() and the send loop never returns False (unbounded)."""
    conns = []

    async def on_connect(conn):
        conns.append(conn)

    async def on_data(conn, data):
        await conn.send(data)  # echo — proves other connections keep serving

    svc = TcpService(0, "bp", on_connect=on_connect, on_data=on_data,
                     max_backlog=65536)
    port = await _start(svc)
    stalled_w = None
    other_w = None
    try:
        # A: connects and NEVER reads.
        r_stall, stalled_w = await _connect("127.0.0.1", port)
        assert await _wait(lambda: len(conns) == 1)
        server_conn = conns[0]

        dropped = False
        for _ in range(200):  # bounded loop — must drop well before this
            ok = await server_conn.send(b"x" * 16384)
            if not ok:
                dropped = True
                break
        assert dropped, "a stalled reader must be dropped, not buffered without end"
        assert server_conn.closed, "the dropped connection must be closed"

        # B: a healthy client still gets served after A was dropped.
        r_ok, other_w = await _connect("127.0.0.1", port)
        other_w.write(b"ping"); await other_w.drain()
        echoed = await asyncio.wait_for(r_ok.readexactly(4), timeout=2.0)
        assert echoed == b"ping", "other connections must keep serving"
    finally:
        if stalled_w is not None:
            await _aclose(stalled_w)
        if other_w is not None:
            await _aclose(other_w)
        await svc.stop()


# ── Invariant tcp-single-owner-bind ──────────────────────────────────────────

async def test_only_one_owner_binds_the_tcp_port():
    """Two services on the same port model two workers: exactly one binds (owner),
    the other skips with no error, and the owner still accepts. Mutation: pass
    reuse_port=True / swallow nothing and the second also binds."""
    port = free_port()
    owner = TcpService(port, "owner")
    second = TcpService(port, "owner")  # the 'other worker'
    try:
        server_a = await owner.start("127.0.0.1")
        assert server_a is not None and owner.is_owner, "the first worker must bind"
        server_b = await second.start("127.0.0.1")
        assert server_b is None, "the second worker must NOT bind the same port"
        assert second.is_owner is False, "only one owner, no bind error raised"
        # The one owner still accepts.
        reader, writer = await _connect("127.0.0.1", port)
        await _aclose(writer)
    finally:
        await owner.stop()
        await second.stop()


# ── Invariant tcp-connection-object / registry — the public tcp() accessor ────

async def test_tcp_service_and_tcp_accessor_share_the_registry():
    """tcp_service() registers a named service reachable via tcp(name); an unknown
    name raises (a programming error), unlike an unknown device id."""
    svc = tcp_service(0, "trackers")
    assert tcp("trackers") is svc, "tcp(name) must return the registered service"
    with pytest.raises(KeyError):
        tcp("nope")
    await svc.stop()


# ── Invariant tcp-listen-accept-in-process (REAL child server) ───────────────

def _write_tcp_app(proj, port):
    """app.py for a real child server: an HTTP /ping route AND a tcp_service on
    port+1 whose on_connect greets the client."""
    (proj / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (proj / "app.py").write_text(
        "import os\n"
        "from tina4_python.core import run\n"
        "from tina4_python.core.router import get\n"
        "from tina4_python.tcp import tcp_service\n"
        "\n"
        "TCP_PORT = int(os.environ['TINA4_TCP_PORT'])\n"
        "\n"
        "@get('/ping')\n"
        "async def ping(request, response):\n"
        "    return response({'ok': True})\n"
        "\n"
        "async def _on_connect(conn):\n"
        "    await conn.send(b'HELLO\\n')\n"
        "\n"
        "async def _on_data(conn, data):\n"
        "    await conn.send(b'ECHO:' + data)\n"
        "\n"
        "tcp_service(port=TCP_PORT, name='trackers', on_connect=_on_connect, on_data=_on_data)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    run()\n"
    )


def _tcp_port_env(extra):
    """Allocate the TCP service port independently of the HTTP port.

    Deriving it as the HTTP port plus one assumed that port was free. On a busy
    runner it sometimes is not: the framework then (correctly) refuses to bind
    it as "already bound by another worker" and the readiness wait times out
    (seen in CI as "child server never became ready"). This takes a real free
    port per boot attempt, never the HTTP port itself, and hands the readiness
    check the same one. Returns (extra_env, ready, state); state["tcp"] holds
    the port the booted server actually listens on.
    """
    state = {}

    def env(http_port):
        tcp = free_port()
        while tcp == http_port:
            tcp = free_port()
        state["tcp"] = tcp
        return {"TINA4_TCP_PORT": str(tcp), **extra}

    def ready(http_port):
        return port_open(http_port) and port_open(state["tcp"])

    return env, ready, state


async def test_listen_accept_in_process_while_http_still_serves(tmp_path):
    """A real framework server: a client connects to the TCP service (on_connect
    fires IN the server process, proven by the greeting it sends) WHILE an HTTP
    request to the same process succeeds. Mutation: don't start TCP services in
    _serve() and the TCP connect never greets."""
    env, ready, tcp = _tcp_port_env({"TINA4_DEFAULT_WEBSERVER": "TRUE"})

    proc, port = boot_child_server(
        tmp_path, _write_tcp_app,
        extra_env=env, ready=ready, new_session=True,
    )
    try:
        # 1. Raw TCP: on_connect greeting proves the listener runs in-process.
        reader, writer = await _connect("127.0.0.1", tcp["tcp"])
        greeting = await asyncio.wait_for(reader.readexactly(6), timeout=3.0)
        assert greeting == b"HELLO\n", f"on_connect must fire in-process, got {greeting!r}"

        # 2. HTTP on the SAME process still serves, concurrently.
        hr, hw = await _connect("127.0.0.1", port)
        hw.write(f"GET /ping HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                 f"Connection: close\r\n\r\n".encode())
        await hw.drain()
        status = await asyncio.wait_for(hr.readline(), timeout=3.0)
        assert b"200" in status, f"HTTP must still serve concurrently, got {status!r}"
        await _aclose(hw)
        await _aclose(writer)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


async def test_service_stop_drains_live_connections_and_fires_on_close():
    """stop() closes every live connection (client sees EOF) and fires on_close —
    the drain mechanism the server's shutdown path calls. Mutation: make drain()
    skip closing connections and the client never sees EOF / on_close never fires."""
    closed = []
    svc = TcpService(0, "drain", on_close=lambda c: closed.append(c))
    port = await _start(svc)
    reader, writer = await _connect("127.0.0.1", port)
    await _wait(lambda: svc.count() == 1)
    await svc.stop(timeout=5)
    tail = await asyncio.wait_for(reader.read(1), timeout=3.0)
    assert tail == b"", "stop() must close the live connection (client sees EOF)"
    await _wait(lambda: len(closed) == 1)
    assert len(closed) == 1, f"on_close must fire during drain, fired {len(closed)}"
    await _aclose(writer)


# ── Invariant tcp-graceful-shutdown-drain (REAL child server + SIGTERM) ──────

async def test_sigterm_drains_live_tcp_connection_and_exits_zero(tmp_path):
    """A real server with a live TCP device connection receives SIGTERM: the
    connection is closed cleanly within the deadline and the process exits 0,
    while HTTP kept serving. Mutation: skip drain_all() on shutdown and the
    client never sees EOF within the deadline (test times out / non-zero exit)."""
    env, ready, tcp = _tcp_port_env({"TINA4_DEFAULT_WEBSERVER": "TRUE",
                                     "TINA4_SHUTDOWN_TIMEOUT": "10"})

    proc, port = boot_child_server(
        tmp_path, _write_tcp_app,
        extra_env=env, ready=ready, new_session=True,
    )
    reader = writer = None
    try:
        reader, writer = await _connect("127.0.0.1", tcp["tcp"])
        greeting = await asyncio.wait_for(reader.readexactly(6), timeout=3.0)
        assert greeting == b"HELLO\n"

        # Signal the whole child process group (new_session=True) so the pytest
        # runner is not signalled.
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

        # The live TCP connection must be closed cleanly (EOF) within the drain.
        tail = await asyncio.wait_for(reader.read(1), timeout=10.0)
        assert tail == b"", "SIGTERM must drain the live TCP connection cleanly"

        # The process exits 0 within the deadline.
        for _ in range(200):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.05)
        assert proc.poll() == 0, f"graceful shutdown must exit 0, got {proc.poll()}"
    finally:
        if writer is not None:
            await _aclose(writer)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
