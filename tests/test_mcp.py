# Tests for tina4_python.mcp
import pytest
import json
import os
from pathlib import Path


class TestJsonRpcProtocol:
    """JSON-RPC 2.0 codec tests."""

    def test_encode_response(self):
        from tina4_python.mcp.protocol import encode_response
        raw = encode_response(1, {"tools": []})
        msg = json.loads(raw)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 1
        assert msg["result"] == {"tools": []}

    def test_encode_error(self):
        from tina4_python.mcp.protocol import encode_error, METHOD_NOT_FOUND
        raw = encode_error(2, METHOD_NOT_FOUND, "Not found")
        msg = json.loads(raw)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 2
        assert msg["error"]["code"] == -32601
        assert msg["error"]["message"] == "Not found"

    def test_decode_request(self):
        from tina4_python.mcp.protocol import decode_request
        method, params, rid = decode_request(json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {},
        }))
        assert method == "tools/list"
        assert params == {}
        assert rid == 3

    def test_decode_notification(self):
        from tina4_python.mcp.protocol import decode_request
        method, params, rid = decode_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        assert method == "notifications/initialized"
        assert rid is None

    def test_invalid_request(self):
        from tina4_python.mcp.protocol import decode_request
        with pytest.raises(ValueError, match="Invalid JSON"):
            decode_request("not json")

    def test_missing_method(self):
        from tina4_python.mcp.protocol import decode_request
        with pytest.raises(ValueError, match="method"):
            decode_request({"jsonrpc": "2.0", "id": 1})

    def test_missing_jsonrpc(self):
        from tina4_python.mcp.protocol import decode_request
        with pytest.raises(ValueError, match="jsonrpc"):
            decode_request({"method": "test", "id": 1})


class TestMcpServer:
    """McpServer core functionality."""

    def setup_method(self):
        from tina4_python.mcp import McpServer
        self.server = McpServer("/test-mcp", name="Test Server", version="0.1.0")

    def test_initialize_handshake(self):
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1.0"}},
        }))
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "Test Server"
        assert "tools" in resp["result"]["capabilities"]

    def test_ping(self):
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "ping", "params": {},
        }))
        assert resp["result"] == {}

    def test_method_not_found(self):
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {},
        }))
        assert resp["error"]["code"] == -32601

    def test_notification_no_response(self):
        resp = self.server.handle_message({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert resp == ""


class TestToolRegistration:
    """Tool registration and invocation."""

    def setup_method(self):
        from tina4_python.mcp import McpServer
        self.server = McpServer("/test-tools", name="Tool Test")

    def test_register_tool(self):
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        self.server.register_tool("greet", greet, "Greet someone")
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        }))
        tools = resp["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "greet"
        assert tools[0]["inputSchema"]["properties"]["name"]["type"] == "string"
        assert "name" in tools[0]["inputSchema"]["required"]

    def test_call_tool(self):
        def add(a: int, b: int) -> int:
            return a + b

        self.server.register_tool("add", add, "Add two numbers")
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 3, "b": 5}},
        }))
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "8" in content[0]["text"]

    def test_unknown_tool(self):
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "missing", "arguments": {}},
        }))
        assert resp["error"]["code"] == -32603

    def test_type_hint_to_schema(self):
        from tina4_python.mcp import _schema_from_signature

        def example(name: str, count: int = 5, active: bool = True):
            pass

        schema = _schema_from_signature(example)
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["count"]["default"] == 5
        assert schema["properties"]["active"]["type"] == "boolean"
        assert schema["required"] == ["name"]

    def test_class_method_tool(self):
        class MyService:
            def report(self, month: str, year: int) -> str:
                return f"Report for {month} {year}"

        svc = MyService()
        self.server.register_tool("report", svc.report, "Generate report")

        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "report", "arguments": {"month": "March", "year": 2026}},
        }))
        assert "March 2026" in resp["result"]["content"][0]["text"]


class TestResourceRegistration:
    """Resource registration and reading."""

    def setup_method(self):
        from tina4_python.mcp import McpServer
        self.server = McpServer("/test-resources", name="Resource Test")

    def test_register_resource(self):
        def get_tables():
            return ["users", "products"]

        self.server.register_resource("app://tables", get_tables, "Database tables")
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {},
        }))
        resources = resp["result"]["resources"]
        assert len(resources) == 1
        assert resources[0]["uri"] == "app://tables"

    def test_read_resource(self):
        def get_info():
            return {"version": "1.0", "name": "Test App"}

        self.server.register_resource("app://info", get_info, "App info")
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "resources/read",
            "params": {"uri": "app://info"},
        }))
        contents = resp["result"]["contents"]
        assert len(contents) == 1
        data = json.loads(contents[0]["text"])
        assert data["version"] == "1.0"

    def test_unknown_resource(self):
        resp = json.loads(self.server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "resources/read",
            "params": {"uri": "app://missing"},
        }))
        assert resp["error"]["code"] == -32603


class TestDecoratorApi:
    """@mcp_tool and @mcp_resource decorators."""

    def test_mcp_tool_decorator(self):
        from tina4_python.mcp import McpServer, mcp_tool

        server = McpServer("/test-decorator", name="Decorator Test")

        @mcp_tool("hello", description="Say hello", server=server)
        def hello(name: str) -> str:
            return f"Hello, {name}!"

        assert hello._mcp_tool_name == "hello"
        resp = json.loads(server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "hello", "arguments": {"name": "World"}},
        }))
        assert "Hello, World!" in resp["result"]["content"][0]["text"]

    def test_mcp_resource_decorator(self):
        from tina4_python.mcp import McpServer, mcp_resource

        server = McpServer("/test-decorator2", name="Decorator Test 2")

        @mcp_resource("test://data", description="Test data", server=server)
        def get_data():
            return [1, 2, 3]

        assert get_data._mcp_resource_uri == "test://data"


class TestSecurity:
    """Security constraints."""

    def test_localhost_detection(self):
        from tina4_python.mcp import _is_localhost
        old = os.environ.get("HOST_NAME")
        try:
            os.environ["HOST_NAME"] = "localhost:7145"
            assert _is_localhost() is True
            os.environ["HOST_NAME"] = "127.0.0.1:7145"
            assert _is_localhost() is True
            os.environ["HOST_NAME"] = "0.0.0.0:7145"
            assert _is_localhost() is True
            os.environ["HOST_NAME"] = "myserver.example.com:7145"
            assert _is_localhost() is False
        finally:
            if old is not None:
                os.environ["HOST_NAME"] = old
            elif "HOST_NAME" in os.environ:
                del os.environ["HOST_NAME"]

    def test_file_sandbox(self, tmp_path):
        from tina4_python.mcp.tools import register_dev_tools
        from tina4_python.mcp import McpServer

        server = McpServer("/test-sandbox", name="Sandbox Test")
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            register_dev_tools(server)
            # Try to read a file outside project dir
            resp = json.loads(server.handle_message({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "file_read", "arguments": {"path": "../../../etc/passwd"}},
            }))
            # Should error — path escapes project directory
            assert "error" in resp, f"Expected error response, got: {resp}"
            assert "escapes" in resp["error"]["message"].lower() or "path" in resp["error"]["message"].lower()
        finally:
            os.chdir(old_cwd)

    def test_file_write_sandbox(self, tmp_path):
        from tina4_python.mcp.tools import register_dev_tools
        from tina4_python.mcp import McpServer

        server = McpServer("/test-sandbox2", name="Sandbox Test 2")
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            register_dev_tools(server)
            resp = json.loads(server.handle_message({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "file_write", "arguments": {"path": "../../evil.txt", "content": "hacked"}},
            }))
            # Should error — path escapes project directory
            assert "error" in resp, f"Expected error response, got: {resp}"
        finally:
            os.chdir(old_cwd)
