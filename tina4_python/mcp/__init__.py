# Tina4 MCP Server — Model Context Protocol for AI tool integration.
"""
Built-in MCP server for dev tools + developer API for custom MCP servers.

Usage (developer):

    from tina4_python.mcp import McpServer, mcp_tool, mcp_resource

    mcp = McpServer("/my-mcp", name="My App Tools")

    @mcp_tool("lookup_invoice", description="Find invoice by number")
    def lookup_invoice(invoice_no: str):
        return db.fetch_one("SELECT * FROM invoices WHERE invoice_no = ?", [invoice_no])

    @mcp_resource("app://schema", description="Database schema")
    def get_schema():
        return db.get_tables()

Built-in dev tools auto-register when TINA4_DEBUG=true and running on localhost.
"""
import os
import json
import inspect
import socket
from pathlib import Path

from .protocol import (
    encode_response, encode_error, encode_notification,
    decode_request,
    PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
    INVALID_PARAMS, INTERNAL_ERROR,
)

# Type hint → JSON Schema type mapping (reuse Swagger pattern)
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _schema_from_signature(func) -> dict:
    """Extract JSON Schema input schema from function type hints."""
    sig = inspect.signature(func)
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue
        annotation = param.annotation
        prop = {"type": _TYPE_MAP.get(annotation, "string")}

        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default

        properties[name] = prop

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _is_localhost() -> bool:
    """Check if the server is running on localhost."""
    host = os.environ.get("HOST_NAME", "localhost:7145").split(":")[0]
    return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "")


class McpServer:
    """MCP server that registers tools and resources on a given HTTP path.

    Args:
        path: HTTP path to serve the MCP endpoint (e.g. "/my-mcp").
        name: Human-readable server name.
        version: Server version string.
    """

    # Class-level registry of all MCP server instances
    _instances: list = []

    def __init__(self, path: str, name: str = "Tina4 MCP", version: str = "1.0.0"):
        self.path = path.rstrip("/")
        self.name = name
        self.version = version
        self._tools: dict[str, dict] = {}
        self._resources: dict[str, dict] = {}
        self._initialized = False
        McpServer._instances.append(self)

    def register_tool(self, name: str, handler, description: str = "", schema: dict | None = None):
        """Register a tool callable."""
        if schema is None:
            schema = _schema_from_signature(handler)
        self._tools[name] = {
            "name": name,
            "description": description or (handler.__doc__ or "").strip(),
            "inputSchema": schema,
            "handler": handler,
        }

    def register_resource(self, uri: str, handler, description: str = "", mime_type: str = "application/json"):
        """Register a resource URI."""
        self._resources[uri] = {
            "uri": uri,
            "name": description or uri,
            "description": description or (handler.__doc__ or "").strip(),
            "mimeType": mime_type,
            "handler": handler,
        }

    def handle_message(self, raw_data: str | dict) -> str:
        """Process an incoming JSON-RPC message and return the response."""
        try:
            method, params, request_id = decode_request(raw_data)
        except ValueError as e:
            return encode_error(None, PARSE_ERROR, str(e))

        handler = {
            "initialize": self._handle_initialize,
            "notifications/initialized": self._handle_initialized,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "ping": self._handle_ping,
        }.get(method)

        if handler is None:
            return encode_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        try:
            result = handler(params)
            if request_id is None:
                return ""  # Notification — no response
            return encode_response(request_id, result)
        except Exception as e:
            return encode_error(request_id, INTERNAL_ERROR, str(e))

    def _handle_initialize(self, params: dict) -> dict:
        """Handle initialize request — return server capabilities."""
        self._initialized = True
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
        }

    def _handle_initialized(self, params: dict):
        """Handle initialized notification."""
        pass

    def _handle_ping(self, params: dict) -> dict:
        return {}

    def _handle_tools_list(self, params: dict) -> dict:
        """Return list of registered tools."""
        tools = []
        for t in self._tools.values():
            tools.append({
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            })
        return {"tools": tools}

    def _handle_tools_call(self, params: dict) -> dict:
        """Invoke a tool by name."""
        tool_name = params.get("name")
        if not tool_name:
            raise ValueError("Missing tool name")

        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        arguments = params.get("arguments", {})
        handler = tool["handler"]

        # Call the handler with the provided arguments
        result = handler(**arguments)

        # Format result as MCP content
        if isinstance(result, str):
            content = [{"type": "text", "text": result}]
        elif isinstance(result, dict) or isinstance(result, list):
            content = [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]
        else:
            content = [{"type": "text", "text": str(result)}]

        return {"content": content}

    def _handle_resources_list(self, params: dict) -> dict:
        """Return list of registered resources."""
        resources = []
        for r in self._resources.values():
            resources.append({
                "uri": r["uri"],
                "name": r["name"],
                "description": r["description"],
                "mimeType": r["mimeType"],
            })
        return {"resources": resources}

    def _handle_resources_read(self, params: dict) -> dict:
        """Read a resource by URI."""
        uri = params.get("uri")
        if not uri:
            raise ValueError("Missing resource URI")

        resource = self._resources.get(uri)
        if not resource:
            raise ValueError(f"Unknown resource: {uri}")

        result = resource["handler"]()

        if isinstance(result, str):
            text = result
        elif isinstance(result, (dict, list)):
            text = json.dumps(result, default=str, indent=2)
        else:
            text = str(result)

        return {
            "contents": [{
                "uri": uri,
                "mimeType": resource["mimeType"],
                "text": text,
            }]
        }

    def register_routes(self, router_module):
        """Register HTTP routes for this MCP server on the Tina4 router.

        Registers:
            POST {path}/message — JSON-RPC message endpoint
            GET {path}/sse — SSE endpoint for streaming
        """
        server = self
        msg_path = f"{self.path}/message"
        sse_path = f"{self.path}/sse"

        @router_module.post(msg_path)
        @router_module.noauth()
        async def mcp_message(request, response):
            body = request.body
            if isinstance(body, dict):
                raw = body
            else:
                raw = body if isinstance(body, str) else str(body)
            result = server.handle_message(raw)
            if not result:
                return response("", 204)
            return response(json.loads(result))

        @router_module.get(sse_path)
        @router_module.noauth()
        async def mcp_sse(request, response):
            # SSE endpoint — send initial endpoint message
            endpoint_url = f"{request.url.rsplit('/sse', 1)[0]}/message"
            sse_data = f"event: endpoint\ndata: {endpoint_url}\n\n"
            from tina4_python.core.response import Response as Resp
            r = Resp()
            r.status_code = 200
            r.content_type = "text/event-stream"
            r.content = sse_data.encode()
            r._headers = [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-cache"),
                (b"connection", b"keep-alive"),
            ]
            return r

    def write_claude_config(self, port: int = 7145):
        """Write/update .claude/settings.json with this MCP server config."""
        config_dir = Path(".claude")
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "settings.json"

        config = {}
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        if "mcpServers" not in config:
            config["mcpServers"] = {}

        server_key = self.name.lower().replace(" ", "-")
        config["mcpServers"][server_key] = {
            "url": f"http://localhost:{port}{self.path}/sse"
        }

        config_file.write_text(json.dumps(config, indent=2) + "\n")


# ── Decorator API ──────────────────────────────────────────────

# Default server instance — tools/resources registered via decorators
# attach to this instance. Developers can create their own McpServer.
_default_server: McpServer | None = None


def _get_default_server() -> McpServer:
    global _default_server
    if _default_server is None:
        _default_server = McpServer("/__dev/mcp", name="Tina4 Dev Tools")
    return _default_server


def mcp_tool(name: str = "", description: str = "", server: McpServer | None = None):
    """Decorator to register a function or method as an MCP tool.

    Usage:
        @mcp_tool("lookup_invoice", description="Find invoice by number")
        def lookup_invoice(invoice_no: str):
            return db.fetch_one("SELECT * FROM invoices WHERE invoice_no = ?", [invoice_no])

        # On a class method
        class Service:
            @mcp_tool("get_report")
            def report(self, month: str):
                return generate_report(month)
    """
    def decorator(func):
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip()
        target = server or _get_default_server()
        target.register_tool(tool_name, func, tool_desc)
        func._mcp_tool_name = tool_name
        return func
    return decorator


def mcp_resource(uri: str, description: str = "", mime_type: str = "application/json", server: McpServer | None = None):
    """Decorator to register a function as an MCP resource.

    Usage:
        @mcp_resource("app://tables", description="Database tables")
        def list_tables():
            return db.get_tables()
    """
    def decorator(func):
        target = server or _get_default_server()
        target.register_resource(uri, func, description, mime_type)
        func._mcp_resource_uri = uri
        return func
    return decorator
