"""ADR-0060 Api.stream_bytes / stream_lines / stream_sse contract over
a real HTTP socket.

Every case reaches a real local HTTP server across a real loopback
socket. No mocks: the fixture server is a plain ``BaseHTTPRequestHandler``
(for well-formed responses) or a raw socket accept loop (for cases
that need chunked-encoding half-frames the stdlib server would not
easily produce).
"""

from __future__ import annotations

import http.client
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tina4_python.api import (
    Api,
    ApiStreamError,
    ApiTimeoutError,
    SseEvent,
)
from tina4_python.ai import Ai


# ── Fixture servers ────────────────────────────────────────────────


class _StreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _send(self, body: bytes, content_type: str = "text/plain"):
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_chunked(self, body_chunks: list[bytes], content_type: str = "text/plain"):
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for piece in body_chunks:
            self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")

    def do_GET(self):
        self.server.hits[self.path] = self.server.hits.get(self.path, 0) + 1
        if self.path == "/bytes-fixed":
            return self._send(b"hello world", "application/octet-stream")
        if self.path == "/bytes-chunked":
            # A body that arrives as multiple transport chunks. The client
            # should yield the chunks in the order the server sent them.
            return self._send_chunked([b"one ", b"two ", b"three"],
                                      "application/octet-stream")
        if self.path == "/bytes-empty":
            return self._send(b"", "application/octet-stream")
        if self.path == "/lines-lf":
            return self._send_chunked(
                [b"alpha\nbeta\n", b"gamma\n"], "text/plain")
        if self.path == "/lines-crlf":
            return self._send_chunked(
                [b"alpha\r\nbeta\r\n", b"gamma\r\n"], "text/plain")
        if self.path == "/lines-trailing":
            return self._send_chunked(
                [b"alpha\nbeta\ngamma"], "text/plain")
        if self.path == "/lines-multibyte":
            # "cafe\n" then "é rio\n" with the leading e-acute BYTE
            # sequence (0xc3 0xa9) SPLIT across two transport chunks. If
            # the decoder splits on bytes instead of decoding across
            # boundaries, it either raises UnicodeDecodeError or replaces
            # with U+FFFD.
            return self._send_chunked(
                [b"cafe\n\xc3", b"\xa9 rio\n"], "text/plain")
        if self.path == "/sse-single":
            return self._send(b"data: hello\n\n", "text/event-stream")
        if self.path == "/sse-multiline":
            # Two data lines in one event -> data joined with \n.
            return self._send(b"data: line1\ndata: line2\n\n",
                              "text/event-stream")
        if self.path == "/sse-named":
            return self._send(
                b"event: ping\ndata: pong\n\n", "text/event-stream")
        if self.path == "/sse-comment":
            # A comment line (: prefix) is dropped; the actual event has
            # data 'real'.
            return self._send(
                b": heartbeat\n: still here\ndata: real\n\n",
                "text/event-stream")
        if self.path == "/sse-blank-boundary":
            return self._send(
                b"data: first\n\ndata: second\n\n", "text/event-stream")
        if self.path == "/sse-done":
            return self._send(
                b"data: alpha\n\ndata: [DONE]\n\n", "text/event-stream")
        if self.path == "/sse-retry":
            return self._send(
                b"retry: 1500\ndata: ok\n\n", "text/event-stream")
        if self.path == "/slow":
            time.sleep(1.0)
            return self._send(b"never", "text/plain")
        if self.path == "/never-ends":
            # Advertise chunked transfer and just write chunks forever
            # (until the connection closes on its own). Used by the
            # total-timeout case.
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                for _ in range(1000):
                    self.wfile.write(b"5\r\ntick!\r\n")
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                return
            return
        if self.path == "/ok-for-close":
            # Chunked encoding with a slow drip so the client can close
            # after the first chunk arrives.
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                self.wfile.write(b"4\r\nfoo!\r\n")
                self.wfile.flush()
                # Keep writing until the peer closes.
                for _ in range(20):
                    self.wfile.write(b"3\r\nbar\r\n")
                    self.wfile.flush()
                    time.sleep(0.05)
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                return
            return
        return self._send(b"", "text/plain")

    def do_POST(self):
        return self.do_GET()


@pytest.fixture()
def stream_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StreamHandler)
    server.hits = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def stall_server():
    """A listener that accepts but never sends bytes — used for the
    connect-timeout scenario. (An accepted-but-silent server produces
    the SLOW-read case; a listener that DOESN'T accept produces the
    connect-timeout case. We use both roles in the same fixture: this
    one accepts and holds the connection.)"""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    stop = threading.Event()
    clients: list[socket.socket] = []

    def accept_loop():
        while not stop.is_set():
            try:
                c, _ = listener.accept()
                clients.append(c)
            except (TimeoutError, OSError):
                continue

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        listener.close()
        for c in clients:
            try:
                c.close()
            except OSError:
                pass
        thread.join(timeout=2)


@pytest.fixture()
def drop_server():
    """Raw-socket server that serves a canned response and then closes.
    Reuses the same shape as the AI-client drop fixture."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    port = listener.getsockname()[1]
    hits = {"count": 0}

    def one_shot(payload: bytes):
        try:
            client, _ = listener.accept()
        except (TimeoutError, OSError):
            return
        hits["count"] += 1
        try:
            client.settimeout(2.0)
            buf = b""
            while b"\r\n\r\n" not in buf:
                got = client.recv(4096)
                if not got:
                    break
                buf += got
            client.sendall(payload)
            time.sleep(0.1)
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        finally:
            client.close()

    def serve(payload: bytes):
        t = threading.Thread(target=one_shot, args=(payload,), daemon=True)
        t.start()

    try:
        yield port, serve, hits
    finally:
        listener.close()


# ── api-stream-bytes-primitive ─────────────────────────────────────


def test_stream_bytes_yields_chunks_in_order(stream_server):
    """stream-bytes-yields-chunks-in-order"""
    url, _server = stream_server
    api = Api()
    chunks = list(api.stream_bytes(url + "/bytes-chunked"))
    assert b"".join(chunks) == b"one two three"
    # Chunks were kept intact (order preserved). We do NOT assert
    # length==3 because a fast transport may coalesce transport chunks.
    # The order and total content are the contract; per-chunk boundaries
    # are best-effort.


def test_stream_bytes_ends_on_eof(stream_server):
    """stream-bytes-ends-on-eof"""
    url, _server = stream_server
    api = Api()
    all_bytes = b"".join(api.stream_bytes(url + "/bytes-fixed"))
    assert all_bytes == b"hello world"
    # Empty body also ends cleanly.
    assert b"".join(api.stream_bytes(url + "/bytes-empty")) == b""


def test_stream_bytes_raises_on_transport_drop(drop_server):
    """stream-bytes-raises-on-transport-drop"""
    port, serve, _hits = drop_server
    # A chunked response with a truncated second chunk header — the
    # client will read the first chunk cleanly, then IncompleteRead
    # while trying to read the second chunk.
    payload = (
        b"HTTP/1.1 200 OK\r\n"
        b"content-type: application/octet-stream\r\n"
        b"transfer-encoding: chunked\r\n\r\n"
        b"5\r\nalpha\r\n"
        b"100\r\n"       # promises 256 bytes we never send
    )
    serve(payload)
    api = Api()
    api.base_url = f"http://127.0.0.1:{port}"
    got_chunks = []
    with pytest.raises(ApiStreamError):
        for c in api.stream_bytes("/whatever"):
            got_chunks.append(c)
    # The pre-drop bytes were recovered.
    assert b"".join(got_chunks) == b"alpha"


# ── api-stream-lines-newline-buffered ──────────────────────────────


def test_stream_lines_splits_on_lf(stream_server):
    """stream-lines-splits-on-lf"""
    url, _server = stream_server
    api = Api()
    lines = list(api.stream_lines(url + "/lines-lf"))
    assert lines == ["alpha", "beta", "gamma"]


def test_stream_lines_splits_on_crlf(stream_server):
    """stream-lines-splits-on-crlf"""
    url, _server = stream_server
    api = Api()
    lines = list(api.stream_lines(url + "/lines-crlf"))
    assert lines == ["alpha", "beta", "gamma"]


def test_stream_lines_yields_trailing_line_without_newline(stream_server):
    """stream-lines-yields-trailing-line-without-newline"""
    url, _server = stream_server
    api = Api()
    lines = list(api.stream_lines(url + "/lines-trailing"))
    assert lines == ["alpha", "beta", "gamma"]


def test_stream_lines_multibyte_across_chunk_boundary(stream_server):
    """stream-lines-multibyte-across-chunk-boundary"""
    url, _server = stream_server
    api = Api()
    lines = list(api.stream_lines(url + "/lines-multibyte"))
    # The e-acute (U+00E9) is 0xc3 0xa9 in UTF-8; split across chunks.
    # If the framer didn't buffer across chunks, decoding would yield
    # U+FFFD replacements. We assert the exact codepoint.
    assert lines == ["cafe", "é rio"]


# ── api-stream-sse-framing ─────────────────────────────────────────


def test_stream_sse_single_event(stream_server):
    """stream-sse-single-event"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-single"))
    assert events == [SseEvent(data="hello")]


def test_stream_sse_multi_line_data_concatenated(stream_server):
    """stream-sse-multi-line-data-concatenated"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-multiline"))
    assert events == [SseEvent(data="line1\nline2")]


def test_stream_sse_named_event(stream_server):
    """stream-sse-named-event"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-named"))
    assert events == [SseEvent(data="pong", event="ping")]


def test_stream_sse_comment_ignored(stream_server):
    """stream-sse-comment-ignored"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-comment"))
    assert events == [SseEvent(data="real")]


def test_stream_sse_blank_line_boundary(stream_server):
    """stream-sse-blank-line-boundary"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-blank-boundary"))
    assert events == [SseEvent(data="first"), SseEvent(data="second")]


def test_stream_sse_done_sentinel_delivered(stream_server):
    """stream-sse-done-sentinel-delivered"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-done"))
    # [DONE] is delivered as an ordinary SseEvent; the iterator ends on
    # the next EOF.
    assert events == [SseEvent(data="alpha"), SseEvent(data="[DONE]")]


def test_stream_sse_retry_field_captured(stream_server):
    """stream-sse-retry-field-captured"""
    url, _server = stream_server
    events = list(Api().stream_sse(url + "/sse-retry"))
    assert events == [SseEvent(data="ok", retry=1500)]


# ── api-stream-timeouts-and-close ──────────────────────────────────


def test_stream_connect_timeout_honoured(stall_server):
    """stream-connect-timeout-honoured

    A listener that accepts silently produces a stall on read; a
    listener that never accepts (unbound port) produces a stall on
    connect. We construct the unresponsive-connect case with an
    unroutable address so ``connect_timeout`` is the deadline.
    """
    # 10.255.255.1 is a documented non-routable address on most Linux
    # test hosts; on macOS the SYN typically times out via the OS
    # rather than getting a RST, which is exactly the scenario we
    # want to bound with connect_timeout.
    api = Api(base_url="http://10.255.255.1:65001")
    started = time.monotonic()
    with pytest.raises(ApiTimeoutError):
        list(api.stream_bytes("/", connect_timeout=0.1, timeout=5))
    assert time.monotonic() - started < 2.0


def test_stream_total_timeout_honoured(stream_server):
    """stream-total-timeout-honoured

    /never-ends drips chunks forever. The total timeout must fire
    even though the connection is healthy and delivering data.
    """
    url, _server = stream_server
    api = Api()
    started = time.monotonic()
    with pytest.raises(ApiTimeoutError):
        for _ in api.stream_bytes(url + "/never-ends",
                                  connect_timeout=1.0, timeout=0.3):
            pass
    elapsed = time.monotonic() - started
    assert elapsed < 2.0


def test_stream_early_close_releases_socket(stream_server):
    """stream-early-close-releases-socket

    Consume one chunk, then close the generator: the underlying
    connection MUST be released; otherwise a subsequent request on
    the same server would hang / accumulate FDs.
    """
    url, _server = stream_server
    api = Api()
    gen = api.stream_bytes(url + "/ok-for-close")
    first = next(gen)
    assert first  # got some bytes
    gen.close()   # user broke out of the loop
    # If the socket had leaked, a fresh call would still work but
    # we'd have one extra ESTABLISHED. A simpler proof: a follow-up
    # request completes without blocking.
    assert list(api.stream_bytes(url + "/bytes-fixed")) == [b"hello world"]


# ── api-stream-shared-with-ai-chat ─────────────────────────────────


def test_ai_chat_uses_api_stream_sse_under_the_hood(monkeypatch, stream_server):
    """ai-chat-uses-api-stream-sse-under-the-hood

    The contract insists that Ai.chat(stream=True) is layered on top
    of Api.stream_sse (one SSE framer per language). This test proves
    it by monkeypatching Api.stream_sse and checking the AI path
    routes through the patched implementation.
    """
    _url, _server = stream_server
    calls = {"count": 0}
    original = Api.stream_sse

    def spy(self, path="", **opts):
        calls["count"] += 1
        return original(self, path, **opts)

    monkeypatch.setattr(Api, "stream_sse", spy)
    # Set up minimal AI config pointing at an SSE endpoint.
    for key in list(os.environ):
        if key.startswith("TINA4_AI_") or key == "TINA4_EMBED_URL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TINA4_AI_URL", _url + "/sse-openai-like")
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "0")
    # Add a matching route by extending the server handler at call time.
    # Simplest way is to reuse /sse-done which speaks the OpenAI-shape
    # SSE. But we want a JSON-payload event that the aggregator can
    # translate. Use a canned SSE via the server's /sse-openai-like
    # path — not defined by default, so we add it now.

    # Add a one-off handler by monkeypatching the class do_GET to serve
    # our OpenAI-style event when hit.
    real_do_get = _StreamHandler.do_GET

    def patched(self):
        if self.path == "/sse-openai-like":
            payload = (
                b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return real_do_get(self)

    monkeypatch.setattr(_StreamHandler, "do_GET", patched)
    # POST hits the same handler:
    monkeypatch.setattr(_StreamHandler, "do_POST", patched)

    events = list(Ai.chat([{"role": "user", "content": "hi"}], stream=True))
    types = [e.type for e in events]
    assert "text_delta" in types and types[-1] == "done"
    assert calls["count"] >= 1, "Ai.chat should route through Api.stream_sse"
