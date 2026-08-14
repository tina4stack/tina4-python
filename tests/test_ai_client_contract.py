"""ADR-0053 app-facing AI client contract over a real HTTP socket."""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tina4_python.ai import (
    Ai,
    AiConfigError,
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

    def _sse(self, events):
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        payload += "data: [DONE]\n\n"
        raw = payload.encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
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


def test_ai_stream_is_ordered_deltas(ai_server, monkeypatch):
    _server, base = ai_server
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-openai")
    assert list(Ai.chat([{"role": "user", "content": "hello"}], stream=True)) == ["hello ", "world"]

    monkeypatch.setenv("TINA4_AI_PROVIDER", "local")
    monkeypatch.delenv("TINA4_AI_KEY", raising=False)
    monkeypatch.setenv("TINA4_AI_MAX_RETRIES", "1")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-partial")
    with pytest.raises(AiParseError):
        list(Ai.chat([{"role": "user", "content": "hello"}], stream=True))
    assert _server.counts["/stream-partial"] == 1
    monkeypatch.setenv("TINA4_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("TINA4_AI_KEY", "hosted-key")
    monkeypatch.setenv("TINA4_AI_URL", base + "/stream-anthropic")
    assert list(Ai.chat([{"role": "user", "content": "hello"}], stream=True)) == ["hello ", "world"]


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
