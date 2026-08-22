"""ADR-0053 app-facing AI client contract over a real HTTP socket."""

import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tina4_python.ai import (
    Ai,
    AiConfigError,
    AiEvent,
    AiHTTPError,
    AiParseError,
    AiTimeoutError,
    ChatResponse,
)


class _ContractHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def _body(self):
        size = int(self.headers.get("content-length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def _json(self, status, body, headers=None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _sse(self, events, *, done_sentinel: bool = True):
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        if done_sentinel:
            payload += "data: [DONE]\n\n"
        raw = payload.encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse_raw(self, raw_text: str, *, close_mid: bool = False):
        raw = raw_text.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        if not close_mid:
            self.send_header("content-length", str(len(raw)))
        else:
            # Advertise more content than we send, then drop the socket.
            self.send_header("content-length", str(len(raw) + 200))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = self._body()
        self.server.requests.append({
            "path": self.path,
            "body": body,
            "authorization": self.headers.get("authorization"),
            "x_api_key": self.headers.get("x-api-key"),
        })
        self.server.counts[self.path] = self.server.counts.get(self.path, 0) + 1

        if self.path == "/openai":
            return self._json(200, {
                "model": body.get("model", "fixture-model"),
                "choices": [{"message": {"content": "hello world"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })
        if self.path == "/anthropic":
            return self._json(200, {
                "model": body.get("model", "fixture-model"),
                "content": [{"type": "text", "text": "hello world"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            })
        if self.path == "/embeddings":
            inputs = body.get("input")
            items = inputs if isinstance(inputs, list) else [inputs]
            return self._json(200, {
                "model": body.get("model", "embed-model"),
                "data": [{"index": i, "embedding": [float(i), 0.25, 0.5]} for i, _ in enumerate(items)],
            })
        if self.path == "/stream-openai":
            return self._sse([
                {"choices": [{"delta": {"content": "hello "}}]},
                {"choices": [{"delta": {"content": "world"}, "finish_reason": "stop"}]},
            ])
        if self.path == "/stream-anthropic":
            return self._sse([
                {"type": "message_start", "message": {}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello "}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}},
                {"type": "message_stop"},
            ])
        if self.path == "/stream-partial":
            payload = 'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'.encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/stream-openai-tools":
            # OpenAI-shape tool call: id, name, and arguments arrive in
            # fragments that concatenate to valid JSON.
            return self._sse([
                {"choices": [{"delta": {"content": "let me check "}}]},
                {"choices": [{"delta": {"tool_calls": [{
                    "index": 0, "id": "call_x1", "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"cit'}
                }]}}]},
                {"choices": [{"delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"arguments": 'y":"Cape Town"}'}
                }]}}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ])
        if self.path == "/stream-anthropic-tools":
            return self._sse([
                {"type": "message_start", "message": {}},
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "tool_use",
                                   "id": "toolu_x1", "name": "get_weather",
                                   "input": {}}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": '{"cit'}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta",
                           "partial_json": 'y":"Cape Town"}'}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ], done_sentinel=False)
        if self.path == "/stream-openai-agent":
            # ADR-0061 agent-loop round-trip against an OpenAI-style
            # provider. Turn 1 (no role='tool' message in history):
            # stream a tool_call event. Turn 2 (has a role='tool'
            # message): stream a text_delta answer that uses the
            # returned tool result.
            has_tool_result = any(
                msg.get("role") == "tool" for msg in body.get("messages", [])
            )
            if not has_tool_result:
                return self._sse([
                    {"choices": [{"delta": {"tool_calls": [{
                        "index": 0, "id": "call_agent1", "type": "function",
                        "function": {"name": "get_weather",
                                     "arguments": '{"cit'}
                    }]}}]},
                    {"choices": [{"delta": {"tool_calls": [{
                        "index": 0,
                        "function": {"arguments": 'y":"Cape Town"}'}
                    }]}}]},
                    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
                ])
            # Turn 2 - echo the tool result content into the answer so
            # the test can prove the loop actually round-tripped it.
            tool_msg = next(
                (m for m in body["messages"] if m.get("role") == "tool"), {})
            answer = f"The weather is {tool_msg.get('content', '')}."
            return self._sse([
                {"choices": [{"delta": {"content": answer}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ])
        if self.path == "/stream-anthropic-agent":
            # ADR-0061 agent-loop round-trip against Anthropic. Turn 1
            # (no tool_result content parts): stream a tool_use block.
            # Turn 2 (has tool_result parts on a user turn): stream a
            # text_delta answer.
            def _has_tool_result(messages):
                for msg in messages:
                    content = msg.get("content")
                    if isinstance(content, list):
                        for part in content:
                            if (isinstance(part, dict)
                                    and part.get("type") == "tool_result"):
                                return True
                return False

            if not _has_tool_result(body.get("messages", [])):
                return self._sse([
                    {"type": "message_start", "message": {}},
                    {"type": "content_block_start", "index": 0,
                     "content_block": {"type": "tool_use",
                                       "id": "toolu_agent1",
                                       "name": "get_weather",
                                       "input": {}}},
                    {"type": "content_block_delta", "index": 0,
                     "delta": {"type": "input_json_delta",
                               "partial_json": '{"cit'}},
                    {"type": "content_block_delta", "index": 0,
                     "delta": {"type": "input_json_delta",
                               "partial_json": 'y":"Cape Town"}'}},
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta",
                     "delta": {"stop_reason": "tool_use"}},
                    {"type": "message_stop"},
                ], done_sentinel=False)
            # Turn 2 - pull the tool_result content and echo it into a
            # text_delta so the test can prove the loop round-tripped.
            tool_content = ""
            for msg in body["messages"]:
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if (isinstance(part, dict)
                                and part.get("type") == "tool_result"):
                            tool_content = part.get("content", "")
                            break
                if tool_content:
                    break
            answer = f"The weather is {tool_content}."
            return self._sse([
                {"type": "message_start", "message": {}},
                {"type": "content_block_delta",
                 "delta": {"type": "text_delta", "text": answer}},
                {"type": "message_delta",
                 "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ], done_sentinel=False)
        if self.path == "/stream-drop":
            # See the ai_drop_server fixture: this route is unused now,
            # but kept as a defensive fallback if a test still points at
            # this URL. It returns a normal short SSE with a done event.
            return self._sse([
                {"choices": [{"delta": {"content": "hi "}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ])
        if self.path == "/stream-flaky":
            # Fails with 503 on first call, streams successfully on retry.
            if self.server.counts[self.path] == 1:
                return self._json(503, {"error": "please retry"})
            return self._sse([
                {"choices": [{"delta": {"content": "recovered"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ])
        if self.path == "/retry":
            if self.server.counts[self.path] == 1:
                return self._json(429, {"error": "later"}, {"retry-after": "0"})
            return self._json(200, {
                "model": "retry-model",
                "choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}],
                "usage": {},
            })
        if self.path == "/always500":
            return self._json(500, {"error": "provider-secret-body"})
        if self.path == "/bad400":
            return self._json(400, {"error": "permanent"})
        if self.path == "/slow":
            time.sleep(0.25)
            return self._json(200, {"choices": [{"message": {"content": "late"}}]})
        if self.path == "/malformed":
            return self._json(200, {"choices": []})
        return self._json(404, {"error": "missing"})


@pytest.fixture()
def ai_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ContractHandler)
    server.requests = []
    server.counts = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def ai_drop_server():
    """A raw-socket HTTP server that streams one SSE event and then RSTs
    the connection. Used for the ADR-0060 mid-stream failure cases; the
    ``BaseHTTPRequestHandler`` teardown cannot reliably close its own
    socket mid-response without confusing the framework's own finish()
    path, so this drops down to a plain socket."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    port = listener.getsockname()[1]
    stopped = threading.Event()
    hits = {"count": 0}

    def one_shot(payload: bytes, drain_before_close: float):
        try:
            client, _addr = listener.accept()
        except (TimeoutError, OSError):
            return
        hits["count"] += 1
        try:
            client.settimeout(2.0)
            request_buf = b""
            while b"\r\n\r\n" not in request_buf:
                got = client.recv(4096)
                if not got:
                    break
                request_buf += got
            headers, _, tail = request_buf.partition(b"\r\n\r\n")
            length = 0
            for line in headers.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    try:
                        length = int(line.split(b":", 1)[1].strip())
                    except ValueError:
                        pass
                    break
            already = len(tail)
            while already < length:
                got = client.recv(min(4096, length - already))
                if not got:
                    break
                already += len(got)
            client.sendall(payload)
            # Give the client's kernel buffer time to receive the data
            # before we tear the socket down.
            time.sleep(drain_before_close)
            # SHUT_WR then close: the client's next read returns EOF
            # after consuming what we sent. http.client, seeing that its
            # content-length promise isn't met, raises IncompleteRead —
            # which surfaces as an ApiStreamError, i.e. the ADR-0060
            # mid-stream failure path.
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def serve(payload: bytes, drain_before_close: float = 0.1):
        thread = threading.Thread(
            target=one_shot, args=(payload, drain_before_close), daemon=True)
        thread.start()
        return thread

    try:
        yield port, serve, hits
    finally:
        stopped.set()
        listener.close()


@pytest.fixture()
def ai_stall_server():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.05)
    stopped = threading.Event()
    clients = []

    def accept_connections():
        while not stopped.is_set():
            try:
                client, _address = listener.accept()
                clients.append(client)
            except TimeoutError:
                continue
            except OSError:
                break

    thread = threading.Thread(target=accept_connections, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stopped.set()
        listener.close()
        for client in clients:
            client.close()
        thread.join(timeout=2)


@pytest.fixture(autouse=True)
def clean_ai_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TINA4_AI_") or key == "TINA4_EMBED_URL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TINA4_AI_MODEL", "env-model")
    monkeypatch.setenv("TINA4_AI_TIMEOUT", "2")
    monkeypatch.setenv("TINA4_AI_CONNECT_TIMEOUT", "1")
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "0")


def test_ai_public_surface(ai_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    assert isinstance(Ai.chat([{"role": "user", "content": "hello"}]), ChatResponse)
    assert Ai.complete("hello") == "hello world"
    monkeypatch.setenv("TINA4_EMBED_URL", base + "/embeddings")
    assert Ai.embed("hello") == [0.0, 0.25, 0.5]
    assert not hasattr(Ai, "ask")
    assert not hasattr(Ai, "ask_json")
    assert not hasattr(Ai, "vision")
    assert not hasattr(Ai, "image")


def test_ai_chat_response_normalized(ai_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    response = Ai.chat([{"role": "user", "content": "hello"}], model="call-model")
    assert response.text == "hello world"
    assert response.model == "call-model"
    assert response.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert response.finish_reason == "stop"
    assert response.raw["choices"][0]["message"]["content"] == "hello world"

    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    response = Ai.chat([{"role": "user", "content": "hello"}])
    assert response.text == "hello world"
    assert response.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert response.finish_reason == "end_turn"


def test_ai_complete_is_single_turn_text(ai_server, monkeypatch):
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    assert Ai.complete("only this") == "hello world"
    assert server.requests[-1]["body"]["messages"] == [{"role": "user", "content": "only this"}]


def test_ai_embedding_cardinality(ai_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_EMBED_URL", base + "/embeddings")
    assert Ai.embed("one") == [0.0, 0.25, 0.5]
    assert Ai.embed(["one", "two"]) == [[0.0, 0.25, 0.5], [1.0, 0.25, 0.5]]


def test_ai_stream_text_deltas_order(ai_server, monkeypatch):
    """ai-stream-text-deltas-order: text_delta events arrive in wire order,
    followed by exactly one done event."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-openai")
    events = list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    types = [e.type for e in events]
    texts = [e.text for e in events if e.type == "text_delta"]
    assert types == ["text_delta", "text_delta", "done"]
    assert texts == ["hello ", "world"]
    assert events[-1].finish_reason == "stop"

    # Anthropic: same shape.
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-anthropic")
    events = list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    types = [e.type for e in events]
    texts = [e.text for e in events if e.type == "text_delta"]
    assert types == ["text_delta", "text_delta", "done"]
    assert texts == ["hello ", "world"]


def test_ai_stream_tool_call_aggregated_openai(ai_server, monkeypatch):
    """ai-stream-tool-call-aggregated-openai: OpenAI tool_call arg fragments
    are buffered and emitted as one tool_call event with parsed args."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-openai-tools")
    events = list(Ai.chat([{"role": "user", "content": "weather?"}], stream=True))
    types = [e.type for e in events]
    assert types == ["text_delta", "tool_call", "done"]
    text_ev = events[0]
    tool_ev = events[1]
    done_ev = events[2]
    assert text_ev.text == "let me check "
    assert tool_ev.id == "call_x1"
    assert tool_ev.name == "get_weather"
    assert tool_ev.args == {"city": "Cape Town"}
    assert done_ev.finish_reason == "tool_calls"


def test_ai_stream_tool_call_aggregated_anthropic(ai_server, monkeypatch):
    """ai-stream-tool-call-aggregated-anthropic: Anthropic tool_use blocks
    accumulate input_json_delta fragments and emit at content_block_stop."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-anthropic-tools")
    events = list(Ai.chat([{"role": "user", "content": "weather?"}], stream=True))
    types = [e.type for e in events]
    assert types == ["tool_call", "done"]
    tool_ev = events[0]
    done_ev = events[1]
    assert tool_ev.id == "toolu_x1"
    assert tool_ev.name == "get_weather"
    assert tool_ev.args == {"city": "Cape Town"}
    assert done_ev.finish_reason == "tool_use"


def test_ai_stream_done_fires_once(ai_server, monkeypatch):
    """ai-stream-done-fires-once: exactly one done event, always the last."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-openai")
    events = list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    done_events = [e for e in events if e.type == "done"]
    assert len(done_events) == 1
    assert events[-1].type == "done"


def _partial_chunked_response(body: bytes) -> bytes:
    """Build a chunked-encoding response that sends ``body`` as one
    complete chunk and then advertises a second chunk it never sends —
    the client's read of the second chunk will fail (IncompleteRead)."""
    first_chunk = f"{len(body):x}\r\n".encode() + body + b"\r\n"
    # Advertise a 256-byte chunk header — we send NONE of its 256 bytes,
    # then the server closes the socket → IncompleteRead.
    truncated_next = b"100\r\n"
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"content-type: text/event-stream\r\n"
        b"transfer-encoding: chunked\r\n\r\n"
    ) + first_chunk + truncated_next


def test_ai_stream_error_instead_of_done_on_midstream_failure(ai_drop_server, monkeypatch):
    """ai-stream-error-instead-of-done-on-midstream-failure: a mid-stream
    drop yields one error event and ends; no done fires."""
    port, serve, _hits = ai_drop_server
    body = b'data: {"choices":[{"delta":{"content":"hi "}}]}\n\n'
    serve(_partial_chunked_response(body))
    monkeypatch.setenv("TINA4_AI_URL", f"http://127.0.0.1:{port}/stream")
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "0")
    events = list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    types = [e.type for e in events]
    assert "text_delta" in types
    assert "error" in types
    assert "done" not in types
    assert events[-1].type == "error"


def test_ai_stream_no_retry_after_first_event(ai_drop_server, monkeypatch):
    """ai-stream-no-retry-after-first-event: once one event is yielded, the
    client never re-opens the stream. Verified by ensuring only one
    request lands on the fixture server (max_retries=3, would attempt
    again if the guard were absent)."""
    port, serve, hits = ai_drop_server
    body = b'data: {"choices":[{"delta":{"content":"hi "}}]}\n\n'
    serve(_partial_chunked_response(body))
    monkeypatch.setenv("TINA4_AI_URL", f"http://127.0.0.1:{port}/stream")
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "3")
    list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    assert hits["count"] == 1


def test_ai_stream_pre_first_event_retries(ai_server, monkeypatch):
    """Pre-first-event failures may retry (contract inverse of the above)."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-flaky")
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "1")
    events = list(Ai.chat([{"role": "user", "content": "hi"}], stream=True))
    types = [e.type for e in events]
    assert "text_delta" in types
    assert types[-1] == "done"
    assert server.counts["/stream-flaky"] == 2


def test_ai_multimodal_text_part(ai_server, monkeypatch):
    """ai-multimodal-text-part: list content with a single text part is accepted."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    response = Ai.chat([{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
    assert isinstance(response, ChatResponse)
    body = server.requests[-1]["body"]
    assert body["messages"][0]["content"] == [{"type": "text", "text": "hi"}]


def test_ai_multimodal_image_data_uri(ai_server, monkeypatch):
    """ai-multimodal-image-data-uri: image part with data: URI is accepted."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    parts = [
        {"type": "text", "text": "describe:"},
        {"type": "image", "source": data_uri},
    ]
    Ai.chat([{"role": "user", "content": parts}])
    body = server.requests[-1]["body"]
    content = body["messages"][0]["content"]
    # OpenAI shape: image_url + {url}
    assert content[0] == {"type": "text", "text": "describe:"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == data_uri


def test_ai_multimodal_image_url(ai_server, monkeypatch):
    """ai-multimodal-image-url: image part with https URL is accepted."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    parts = [
        {"type": "text", "text": "look:"},
        {"type": "image", "source": "https://example.com/photo.jpg"},
    ]
    Ai.chat([{"role": "user", "content": parts}])
    body = server.requests[-1]["body"]
    content = body["messages"][0]["content"]
    assert content[1]["image_url"]["url"] == "https://example.com/photo.jpg"


def test_ai_multimodal_malformed_part_fails_config(ai_server, monkeypatch):
    """ai-multimodal-malformed-part-fails-config: bad parts raise AiConfigError
    before any request is sent."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    # Missing 'text' on a text part
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": [{"type": "text"}]}])
    # Missing 'source' on an image part
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": [{"type": "image"}]}])
    # Unknown part type
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": [{"type": "audio", "url": "x"}]}])
    # Empty parts list
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": []}])
    # source not http(s)/data:
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": [
            {"type": "image", "source": "ftp://foo/bar.png"}]}])
    # No request should have escaped.
    assert server.requests == []


def test_ai_multimodal_openai_body_shape(ai_server, monkeypatch):
    """ai-multimodal-openai-body-shape: OpenAI/local providers get image_url shape."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    parts = [{"type": "image", "source": "https://x/y.png"}]
    Ai.chat([{"role": "user", "content": parts}])
    content = server.requests[-1]["body"]["messages"][0]["content"]
    assert content == [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}]


def test_ai_multimodal_anthropic_body_shape(ai_server, monkeypatch):
    """ai-multimodal-anthropic-body-shape: Anthropic gets base64 or URL block."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    # data: URI -> base64 block
    data_uri = "data:image/png;base64,ABCDEF=="
    Ai.chat([{"role": "user", "content": [{"type": "image", "source": data_uri}]}])
    content = server.requests[-1]["body"]["messages"][0]["content"]
    assert content == [{
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "ABCDEF=="},
    }]
    # https:// URL -> url block
    Ai.chat([{"role": "user", "content": [
        {"type": "image", "source": "https://x/y.png"}]}])
    content = server.requests[-1]["body"]["messages"][0]["content"]
    assert content == [{
        "type": "image",
        "source": {"type": "url", "url": "https://x/y.png"},
    }]


def test_ai_configuration_precedence(ai_server, monkeypatch):
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    monkeypatch.setenv("TINA4_AI_MODEL", "env-model")
    Ai.chat([{"role": "user", "content": "hello"}], model="call-model", temperature=0.2, max_tokens=9)
    assert server.requests[-1]["body"]["model"] == "call-model"
    assert server.requests[-1]["body"]["temperature"] == 0.2
    assert server.requests[-1]["body"]["max_tokens"] == 9


def test_ai_hosted_key_fails_closed_and_redacted(ai_server, monkeypatch):
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "openai")
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "private prompt"}])
    assert server.requests == []

    key = "super-secret-key"
    monkeypatch.setenv("TINA4_AI_KEY", key)
    monkeypatch.setenv("TINA4_AI_URL", base + "/always500")
    with pytest.raises(AiHTTPError) as exc:
        Ai.chat([{"role": "user", "content": "private prompt"}])
    message = str(exc.value)
    assert key not in message
    assert "private prompt" not in message
    assert "provider-secret-body" not in message


def test_ai_retries_only_safe_transients(ai_server, monkeypatch):
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "1")
    monkeypatch.setenv("TINA4_AI_URL", base + "/retry")
    assert Ai.complete("hello") == "recovered"
    assert server.counts["/retry"] == 2
    monkeypatch.setenv("TINA4_AI_URL", base + "/bad400")
    with pytest.raises(AiHTTPError):
        Ai.complete("hello")
    assert server.counts["/bad400"] == 1


def test_ai_timeouts_are_distinct_and_bounded(ai_server, ai_stall_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/slow")
    start = time.monotonic()
    with pytest.raises(AiTimeoutError, match="total"):
        Ai.chat([{"role": "user", "content": "hello"}], timeout=0.05)
    assert time.monotonic() - start < 0.5

    monkeypatch.setenv("TINA4_AI_URL", f"https://127.0.0.1:{ai_stall_server}/stall")
    monkeypatch.setenv("TINA4_AI_CONNECT_TIMEOUT", "0.05")
    start = time.monotonic()
    with pytest.raises(AiTimeoutError, match="connection"):
        Ai.chat([{"role": "user", "content": "hello"}], timeout=1)
    assert time.monotonic() - start < 0.5
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hello"}], timeout=0)


def test_ai_zero_runtime_dependencies_real_socket(ai_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/malformed")
    with pytest.raises(AiParseError):
        Ai.chat([{"role": "user", "content": "hello"}])


# ─────────────────────────────────────────────────────────────────────
# ADR-0061 — tool declaration outbound, tool_choice, tool_result shape
# and the full agent-loop round trip. All hit real fixture endpoints.
# ─────────────────────────────────────────────────────────────────────


_TOOL_WEATHER = {
    "name": "get_weather",
    "description": "Get the weather for a city",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def test_ai_tools_openai_body_shape(ai_server, monkeypatch):
    """ai-tools-openai-body-shape: OpenAI/local gets tools wrapped in
    {type: 'function', function: {name, description, parameters}}."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    Ai.chat([{"role": "user", "content": "hi"}], tools=[_TOOL_WEATHER])
    body = server.requests[-1]["body"]
    assert body["tools"] == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": _TOOL_WEATHER["parameters"],
        },
    }]


def test_ai_tools_anthropic_body_shape(ai_server, monkeypatch):
    """ai-tools-anthropic-body-shape: Anthropic gets {name, description,
    input_schema} (parameters renamed to input_schema)."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}], tools=[_TOOL_WEATHER])
    body = server.requests[-1]["body"]
    assert body["tools"] == [{
        "name": "get_weather",
        "description": "Get the weather for a city",
        "input_schema": _TOOL_WEATHER["parameters"],
    }]
    # parameters key must NOT appear on the anthropic wire body.
    assert "parameters" not in body["tools"][0]


def test_ai_tools_parameters_passthrough_jsonschema(ai_server, monkeypatch):
    """ai-tools-parameters-passthrough-jsonschema: the parameters object
    is passed through verbatim as JSON Schema (nothing renamed inside)."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    complex_schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "minLength": 1},
            "units": {"type": "string", "enum": ["c", "f"], "default": "c"},
            "nested": {"type": "object", "additionalProperties": True},
        },
        "required": ["city"],
        "additionalProperties": False,
    }
    tool = {"name": "get_weather", "description": "d", "parameters": complex_schema}
    Ai.chat([{"role": "user", "content": "hi"}], tools=[tool])
    body = server.requests[-1]["body"]
    assert body["tools"][0]["function"]["parameters"] == complex_schema

    # Same on Anthropic under input_schema.
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}], tools=[tool])
    body = server.requests[-1]["body"]
    assert body["tools"][0]["input_schema"] == complex_schema


def test_ai_tool_choice_auto(ai_server, monkeypatch):
    """ai-tool-choice-auto: 'auto' -> OpenAI 'auto' / Anthropic {type:'auto'}."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="auto")
    assert server.requests[-1]["body"]["tool_choice"] == "auto"

    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="auto")
    assert server.requests[-1]["body"]["tool_choice"] == {"type": "auto"}


def test_ai_tool_choice_none(ai_server, monkeypatch):
    """ai-tool-choice-none: 'none' -> OpenAI 'none' / Anthropic omits tools."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="none")
    body = server.requests[-1]["body"]
    assert body["tool_choice"] == "none"
    # tools still declared on OpenAI when tool_choice='none'.
    assert body["tools"][0]["function"]["name"] == "get_weather"

    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="none")
    body = server.requests[-1]["body"]
    # Anthropic has no 'none' mode - tools field is omitted entirely.
    assert "tools" not in body
    assert "tool_choice" not in body


def test_ai_tool_choice_required(ai_server, monkeypatch):
    """ai-tool-choice-required: 'required' -> OpenAI 'required' / Anthropic
    {type:'any'}."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="required")
    assert server.requests[-1]["body"]["tool_choice"] == "required"

    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice="required")
    assert server.requests[-1]["body"]["tool_choice"] == {"type": "any"}


def test_ai_tool_choice_named(ai_server, monkeypatch):
    """ai-tool-choice-named: {name:'x'} -> OpenAI {type:'function', function:
    {name:'x'}} / Anthropic {type:'tool', name:'x'}."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice={"name": "get_weather"})
    assert server.requests[-1]["body"]["tool_choice"] == {
        "type": "function", "function": {"name": "get_weather"},
    }

    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    Ai.chat([{"role": "user", "content": "hi"}],
            tools=[_TOOL_WEATHER], tool_choice={"name": "get_weather"})
    assert server.requests[-1]["body"]["tool_choice"] == {
        "type": "tool", "name": "get_weather",
    }


def test_ai_tool_result_openai_form_passthrough(ai_server, monkeypatch):
    """ai-tool-result-openai-form-passthrough: OpenAI-form tool result on
    an OpenAI provider passes through as {role:'tool', tool_call_id,
    content}."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_x1", "type": "function",
                         "function": {"name": "get_weather",
                                      "arguments": '{"city":"Cape Town"}'}}]},
        {"role": "tool", "tool_call_id": "call_x1", "content": "22C sunny"},
    ]
    Ai.chat(messages)
    body = server.requests[-1]["body"]
    tool_msg = body["messages"][-1]
    assert tool_msg == {
        "role": "tool", "tool_call_id": "call_x1", "content": "22C sunny",
    }


def test_ai_tool_result_anthropic_form_passthrough(ai_server, monkeypatch):
    """ai-tool-result-anthropic-form-passthrough: Anthropic-form tool
    result on an Anthropic provider passes through as user turn with
    a tool_result content block."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_x1", "name": "get_weather",
             "input": {"city": "Cape Town"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_x1",
             "content": "22C sunny"}]},
    ]
    Ai.chat(messages)
    body = server.requests[-1]["body"]
    tool_result_msg = body["messages"][-1]
    assert tool_result_msg == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_x1",
                     "content": "22C sunny"}],
    }


def test_ai_tool_result_openai_to_anthropic_translation(ai_server, monkeypatch):
    """ai-tool-result-openai-to-anthropic-translation: OpenAI-form input
    (role='tool') on an Anthropic provider becomes a user turn with a
    tool_result content block."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/anthropic")
    messages = [
        {"role": "user", "content": "weather?"},
        # OpenAI-form assistant tool_calls - translated to tool_use parts.
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_x1", "type": "function",
                         "function": {"name": "get_weather",
                                      "arguments": '{"city":"Cape Town"}'}}]},
        # OpenAI-form tool result - translated to user + tool_result part.
        {"role": "tool", "tool_call_id": "call_x1", "content": "22C sunny"},
    ]
    Ai.chat(messages)
    body = server.requests[-1]["body"]
    # No role='tool' message on the wire; it became a user turn.
    assert all(m.get("role") != "tool" for m in body["messages"])
    assert body["messages"][-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_x1",
                     "content": "22C sunny"}],
    }
    # The assistant tool_calls turn was folded into tool_use content parts.
    assistant_msg = body["messages"][-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == [{
        "type": "tool_use", "id": "call_x1", "name": "get_weather",
        "input": {"city": "Cape Town"},
    }]
    assert "tool_calls" not in assistant_msg


def test_ai_tool_result_anthropic_to_openai_translation(ai_server, monkeypatch):
    """ai-tool-result-anthropic-to-openai-translation: Anthropic-form
    input (user turn with tool_result parts) on an OpenAI provider
    becomes a role='tool' message."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    messages = [
        {"role": "user", "content": "weather?"},
        # Anthropic-form assistant with tool_use - translated to tool_calls.
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_x1", "name": "get_weather",
             "input": {"city": "Cape Town"}}]},
        # Anthropic-form tool result - translated to role='tool'.
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_x1",
             "content": "22C sunny"}]},
    ]
    Ai.chat(messages)
    body = server.requests[-1]["body"]
    tool_msg = body["messages"][-1]
    assert tool_msg == {
        "role": "tool", "tool_call_id": "toolu_x1", "content": "22C sunny",
    }
    # The assistant tool_use turn was folded into OpenAI tool_calls.
    assistant_msg = body["messages"][-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] is None
    assert assistant_msg["tool_calls"] == [{
        "id": "toolu_x1", "type": "function",
        "function": {"name": "get_weather",
                     "arguments": '{"city": "Cape Town"}'},
    }]


def test_ai_tool_result_malformed_fails_config(ai_server, monkeypatch):
    """ai-tool-result-message-shape (negative): malformed tool-result
    parts raise AiConfigError before wire."""
    server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    # role='tool' missing tool_call_id.
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "tool", "content": "22C sunny"}])
    # role='tool' with non-string content.
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "tool", "tool_call_id": "x", "content": 123}])
    # Anthropic-form tool_result part missing tool_use_id.
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": [
            {"type": "tool_result", "content": "22C sunny"}]}])
    # tool_use part missing name.
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "assistant", "content": [
            {"type": "tool_use", "id": "x", "input": {}}]}])
    # No request should have escaped.
    assert server.requests == []


def test_ai_tool_choice_invalid_fails_config(ai_server, monkeypatch):
    """Malformed tool_choice values raise AiConfigError before wire."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}], tool_choice="always")
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}], tool_choice={"foo": "x"})
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}], tool_choice=42)


def test_ai_tools_invalid_fails_config(ai_server, monkeypatch):
    """Malformed tools raise AiConfigError before wire."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/openai")
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}], tools=[])
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}], tools=[{"description": "d"}])
    with pytest.raises(AiConfigError):
        Ai.chat([{"role": "user", "content": "hi"}],
                tools=[{"name": "x", "parameters": "not-a-schema"}])


def test_ai_agent_loop_openai_round_trip(ai_server, monkeypatch):
    """ai-agent-loop-openai-round-trip: end-to-end round trip against
    the OpenAI-style fixture - send tools, receive tool_call, execute,
    send tool_result, receive text_delta and done."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-openai-agent")

    messages = [{"role": "user", "content": "weather in Cape Town?"}]
    events = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))

    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    call = tool_events[0]
    assert call.name == "get_weather"
    assert call.args == {"city": "Cape Town"}
    assert events[-1].type == "done"
    assert events[-1].finish_reason == "tool_calls"

    # Caller runs the tool locally.
    tool_output = "22C sunny"
    messages.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": call.id, "type": "function",
            "function": {"name": call.name,
                         "arguments": json.dumps(call.args)},
        }],
    })
    messages.append({
        "role": "tool", "tool_call_id": call.id, "content": tool_output,
    })

    # Second turn - fresh Ai.chat call with the augmented history.
    events2 = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))
    text = "".join(e.text or "" for e in events2 if e.type == "text_delta")
    assert tool_output in text
    assert events2[-1].type == "done"
    assert events2[-1].finish_reason == "stop"


def test_ai_agent_loop_anthropic_round_trip(ai_server, monkeypatch):
    """ai-agent-loop-anthropic-round-trip: same round trip on the
    Anthropic-style fixture with provider-neutral caller code (this
    test happens to use Anthropic-form messages to prove that form
    passes through untouched)."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-anthropic-agent")

    messages = [{"role": "user", "content": "weather in Cape Town?"}]
    events = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))

    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    call = tool_events[0]
    assert call.name == "get_weather"
    assert call.args == {"city": "Cape Town"}
    assert events[-1].type == "done"
    assert events[-1].finish_reason == "tool_use"

    tool_output = "22C sunny"
    messages.append({
        "role": "assistant", "content": [{
            "type": "tool_use", "id": call.id, "name": call.name,
            "input": call.args,
        }],
    })
    messages.append({
        "role": "user", "content": [{
            "type": "tool_result", "tool_use_id": call.id,
            "content": tool_output,
        }],
    })

    events2 = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))
    text = "".join(e.text or "" for e in events2 if e.type == "text_delta")
    assert tool_output in text
    assert events2[-1].type == "done"
    assert events2[-1].finish_reason == "end_turn"


def test_ai_agent_loop_provider_neutral_caller_code(ai_server, monkeypatch):
    """The same caller code (OpenAI-form messages) drives an Anthropic
    round trip via the client's normalisation. Proves the ADR-0061
    provider-neutral promise beyond the two round-trip cases above."""
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-anthropic-agent")

    messages = [{"role": "user", "content": "weather in Cape Town?"}]
    events = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))
    call = next(e for e in events if e.type == "tool_call")

    tool_output = "22C sunny"
    # OpenAI-form assistant + tool messages - normalised on the wire.
    messages.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": call.id, "type": "function",
            "function": {"name": call.name,
                         "arguments": json.dumps(call.args)},
        }],
    })
    messages.append({
        "role": "tool", "tool_call_id": call.id, "content": tool_output,
    })

    events2 = list(Ai.chat(messages, tools=[_TOOL_WEATHER], stream=True))
    text = "".join(e.text or "" for e in events2 if e.type == "text_delta")
    assert tool_output in text
    assert events2[-1].type == "done"
