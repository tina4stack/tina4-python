"""MCP Streamable HTTP + legacy SSE transport tests.

No mocks: every assertion runs against a real McpServer, real JSON-RPC
messages, and (for the SSE path) a real asyncio.Queue driven by the actual
sse_stream async generator. These lock in the wire contract Claude Code and
other current MCP clients depend on.
"""
import json

import pytest

from tina4_python.mcp import (
    McpServer,
    SUPPORTED_PROTOCOL_VERSIONS,
    LATEST_PROTOCOL_VERSION,
)


def _init_msg(protocol_version="2025-06-18", rid=1):
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": "initialize",
        "params": {"protocolVersion": protocol_version, "capabilities": {}},
    }


class TestProtocolNegotiation:
    def setup_method(self):
        self.server = McpServer("/t-neg", name="Neg")

    def test_echoes_supported_client_version(self):
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            assert self.server.negotiate_protocol_version(version) == version

    def test_falls_back_to_latest_for_unknown_version(self):
        assert self.server.negotiate_protocol_version("1999-01-01") == LATEST_PROTOCOL_VERSION
        assert self.server.negotiate_protocol_version(None) == LATEST_PROTOCOL_VERSION

    def test_initialize_result_carries_negotiated_version(self):
        resp = json.loads(self.server.handle_message(_init_msg("2025-06-18")))
        assert resp["result"]["protocolVersion"] == "2025-06-18"
        # Unknown -> newest we speak.
        resp2 = json.loads(self.server.handle_message(_init_msg("1999-01-01", rid=2)))
        assert resp2["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


class TestSessionLifecycle:
    def setup_method(self):
        self.server = McpServer("/t-sess", name="Sess")

    def test_open_validate_close(self):
        sid = self.server.open_session()
        assert sid and self.server.is_valid_session(sid)
        assert self.server.close_session(sid) is True
        assert not self.server.is_valid_session(sid)
        # Closing an unknown id is a no-op that reports False.
        assert self.server.close_session("nope") is False

    def test_unknown_session_is_invalid(self):
        assert not self.server.is_valid_session("")
        assert not self.server.is_valid_session("deadbeef")


class TestStreamableHttp:
    def setup_method(self):
        self.server = McpServer("/t-http", name="Http")

        def greet(name: str):
            return f"hi {name}"

        self.server.register_tool("greet", greet, "Greet")

    def test_initialize_issues_session_header(self):
        out = self.server.dispatch_http(_init_msg())
        assert out["status"] == 200
        sid = out["headers"].get("Mcp-Session-Id")
        assert sid and self.server.is_valid_session(sid)
        body = json.loads(out["body"])
        assert body["result"]["protocolVersion"] == "2025-06-18"

    def test_unknown_session_rejected_after_init(self):
        # A non-initialize call carrying a session id we never issued -> 404,
        # so the client knows to re-initialize.
        out = self.server.dispatch_http(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
            session_id="never-issued",
        )
        assert out["status"] == 404
        assert json.loads(out["body"])["error"]

    def test_valid_session_allows_tools_list(self):
        init = self.server.dispatch_http(_init_msg())
        sid = init["headers"]["Mcp-Session-Id"]
        out = self.server.dispatch_http(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {}},
            session_id=sid,
        )
        assert out["status"] == 200
        names = [t["name"] for t in json.loads(out["body"])["result"]["tools"]]
        assert "greet" in names

    def test_missing_session_is_lenient(self):
        # A stateless client that never sends the header still works.
        out = self.server.dispatch_http(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
            session_id="",
        )
        assert out["status"] == 200

    def test_tool_call_roundtrip(self):
        out = self.server.dispatch_http({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "greet", "arguments": {"name": "Ada"}},
        })
        assert out["status"] == 200
        content = json.loads(out["body"])["result"]["content"]
        assert content[0]["text"] == "hi Ada"

    def test_notification_yields_202_empty(self):
        out = self.server.dispatch_http({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert out["status"] == 202
        assert out["body"] == ""
        assert "Mcp-Session-Id" not in out["headers"]


class TestLegacySse:
    """The 2024-11-05 HTTP+SSE transport, driven through the real
    sse_stream async generator + real asyncio.Queue."""

    def setup_method(self):
        self.server = McpServer("/t-sse", name="Sse")

        def ping_tool():
            return "pong"

        self.server.register_tool("ping_tool", ping_tool, "Ping")

    @pytest.mark.asyncio
    async def test_stream_delivers_response_on_the_open_connection(self):
        sid = self.server.open_session()
        gen = self.server.sse_stream(sid, f"/t-sse/message?sessionId={sid}", keepalive=5)

        # First frame names the POST endpoint AND registers the queue.
        endpoint_frame = await gen.__anext__()
        assert endpoint_frame.startswith("event: endpoint")
        assert f"sessionId={sid}" in endpoint_frame
        assert sid in self.server._sse_queues

        # A POST to /message feeds the stream and returns 202 (not inline).
        outcome = self.server.dispatch_sse_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, sid
        )
        assert outcome["status"] == 202
        assert outcome["body"] == ""

        # The response arrives as an SSE `message` event on the open stream.
        message_frame = await gen.__anext__()
        assert message_frame.startswith("event: message")
        payload = json.loads(message_frame.split("data: ", 1)[1].strip())
        names = [t["name"] for t in payload["result"]["tools"]]
        assert "ping_tool" in names

        # Closing the client stream tears down the queue + session.
        await gen.aclose()
        assert sid not in self.server._sse_queues
        assert not self.server.is_valid_session(sid)

    def test_message_without_open_stream_falls_back_inline(self):
        # No SSE stream open for this session -> behaves like Streamable HTTP.
        out = self.server.dispatch_sse_message(_init_msg(), session_id="")
        assert out["status"] == 200
        assert out["headers"].get("Mcp-Session-Id")
        assert json.loads(out["body"])["result"]["serverInfo"]["name"] == "Sse"
