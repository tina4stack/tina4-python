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
import secrets
import time
from pathlib import Path

from .protocol import (
    encode_response, encode_error, encode_notification,
    decode_request,
    PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
    INVALID_PARAMS, INTERNAL_ERROR,
)

# MCP protocol versions this server can speak, newest first. The 2025-*
# versions are the Streamable HTTP era; 2024-11-05 is the legacy HTTP+SSE
# transport we still accept for older clients (Claude Desktop et al.).
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# Re-export protocol helpers as public API (parity with PHP/Ruby/Node)
__all__ = [
    "McpServer", "mcp_tool", "mcp_resource",
    "encode_response", "encode_error", "encode_notification", "decode_request",
    "is_localhost", "is_loopback", "is_enabled", "is_request_allowed",
    "resolve_port", "register",
]

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


def is_localhost() -> bool:
    """Whether the CONFIGURED host name looks local. Informational only —
    kept for back-compat. This is NOT the security gate: it reads the
    configured TINA4_HOST_NAME, not the real caller, so it must never be
    used to authorise a request. Use `is_request_allowed(remote_ip, ...)`
    with the raw socket peer instead."""
    host = os.environ.get("TINA4_HOST_NAME", "localhost:7145").split(":")[0]
    return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "")


# Private alias kept for internal use
_is_localhost = is_localhost


def _is_truthy(val) -> bool:
    return str(val or "").strip().lower() in ("true", "1", "yes", "on")


def is_loopback(ip: str) -> bool:
    """True when `ip` is a loopback / local peer address.

    `ip` MUST be the raw socket peer (e.g. request.remote_ip), never a
    value derived from X-Forwarded-For (which the client controls and can
    spoof to 127.0.0.1). An empty string means there is no TCP peer
    (in-process call or the built-in dev server) and is treated as local —
    a genuine remote TCP client always has a non-empty address.

    NOTE: 0.0.0.0 is a *bind* address, never a *client* address, so it is
    deliberately NOT loopback here (the old is_localhost() bug treated the
    0.0.0.0 default bind as "localhost" and so let remote callers through).
    """
    if not ip:
        return True
    ip = ip.strip().lower()
    if ip.startswith("::ffff:"):   # IPv4-mapped IPv6
        ip = ip[7:]
    return ip in ("::1", "localhost") or ip.startswith("127.")


def is_enabled() -> bool:
    """Whether the built-in MCP dev tools are turned on at all (capability).

    This is the transport/mount gate only:
        1. TINA4_MCP env var — explicit on/off override (any host).
        2. else TINA4_DEBUG=true — on for development.
        3. otherwise off.

    It deliberately does NOT decide localhost-vs-remote — that is a
    PER-REQUEST decision made by `is_request_allowed()` against the real
    socket peer, because the MCP tools expose powerful operations (DB
    query/execute, file read/write) and must never auto-expose to a remote
    caller. (v3.13.40: previously is_enabled() gated on is_localhost(),
    which read the configured host name instead of the caller — a remote
    box bound to 0.0.0.0 with TINA4_DEBUG passed the "localhost" check.)
    """
    explicit = os.environ.get("TINA4_MCP")
    if explicit is not None and explicit != "":
        return _is_truthy(explicit)
    return _is_truthy(os.environ.get("TINA4_DEBUG"))


def is_request_allowed(remote_ip: str, has_valid_token: bool = False) -> bool:
    """Per-request authorisation for the MCP endpoint — the real security gate.

    - The capability must be on (`is_enabled()`), else deny.
    - A loopback caller (`is_loopback(remote_ip)`) is always allowed (the
      normal local dev / Claude Desktop case).
    - A non-loopback (remote) caller is allowed ONLY when BOTH
      `TINA4_MCP_REMOTE` is truthy AND a valid token was supplied
      (`has_valid_token`). A bare `TINA4_MCP_REMOTE=true` is no longer
      enough — remote access to file_write / database_execute now requires
      a token (TINA4_MCP_TOKEN, falling back to TINA4_API_KEY).

    `remote_ip` MUST be the raw socket peer (request.remote_ip).
    """
    if not is_enabled():
        return False
    if is_loopback(remote_ip):
        return True
    return _is_truthy(os.environ.get("TINA4_MCP_REMOTE")) and bool(has_valid_token)


def resolve_port(framework_port: int = 7145) -> int:
    """Resolve the MCP server port.

    Honours TINA4_MCP_PORT. Default is `framework_port + 2000` so the
    MCP endpoint never collides with either the main server (default
    7145) or the AI test port (default framework_port + 1000).
    """
    raw = os.environ.get("TINA4_MCP_PORT", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return framework_port + 2000


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
        # Streamable HTTP session ids issued at initialize time, mapped to
        # their creation timestamp. Transport layers echo the id back in the
        # Mcp-Session-Id header; a request bearing an unknown id gets a 404 so
        # the client knows to re-initialize.
        self._sessions: dict[str, float] = {}
        # Open legacy HTTP+SSE streams keyed by session id. The GET /sse
        # handler registers an asyncio.Queue here; the POST /message handler
        # pushes each JSON-RPC response onto it so it streams back on the open
        # connection (the 2024-11-05 transport). Empty for Streamable HTTP.
        self._sse_queues: dict = {}
        McpServer._instances.append(self)

    # ── Session lifecycle (Streamable HTTP + legacy SSE correlation) ──

    def open_session(self) -> str:
        """Mint a new session id and remember it. Called on `initialize`."""
        sid = secrets.token_hex(16)
        self._sessions[sid] = time.time()
        return sid

    def is_valid_session(self, session_id: str) -> bool:
        """True when `session_id` was issued by this server and still open."""
        return bool(session_id) and session_id in self._sessions

    def close_session(self, session_id: str) -> bool:
        """Forget a session (client DELETE or SSE stream close). Returns
        True when a live session was actually removed."""
        return self._sessions.pop(session_id, None) is not None

    def negotiate_protocol_version(self, requested: str | None) -> str:
        """Pick the protocol version to run on. Echo the client's requested
        version when we support it (proper negotiation), else fall back to the
        newest version we speak so an unversioned/old client still connects."""
        if requested in SUPPORTED_PROTOCOL_VERSIONS:
            return requested
        return LATEST_PROTOCOL_VERSION

    def _peek_method(self, raw_data) -> str | None:
        """Read the JSON-RPC `method` from a raw request without dispatching.
        Used by the transport to spot `initialize` (mint a session) before it
        hands the message to handle_message()."""
        try:
            obj = raw_data if isinstance(raw_data, dict) else json.loads(raw_data or "{}")
        except (ValueError, TypeError):
            return None
        return obj.get("method") if isinstance(obj, dict) else None

    def dispatch_http(self, raw_data, session_id: str = "") -> dict:
        """Transport-agnostic Streamable HTTP POST handler.

        Every language's transport calls this so the wire behaviour stays
        identical:
          - `initialize` mints a session id, returned in the Mcp-Session-Id
            response header.
          - a non-initialize request carrying an unknown session id is a 404
            (JSON-RPC error) so the client knows to re-initialize.
          - a notification / response-only POST (no id) yields 202 with an
            empty body.
          - anything else returns 200 with the JSON-RPC response as
            application/json, which the MCP Streamable HTTP spec permits for a
            POST that resolves to a single response.

        Returns {"status": int, "headers": {name: value}, "body": str}.
        """
        is_init = self._peek_method(raw_data) == "initialize"
        if not is_init and session_id and not self.is_valid_session(session_id):
            return {
                "status": 404,
                "headers": {},
                "body": encode_error(None, INVALID_REQUEST, "session not found"),
            }
        body = self.handle_message(raw_data)
        headers: dict[str, str] = {}
        if is_init:
            headers["Mcp-Session-Id"] = self.open_session()
        if not body:
            return {"status": 202, "headers": headers, "body": ""}
        return {"status": 200, "headers": headers, "body": body}

    def dispatch_sse_message(self, raw_data, session_id: str = "") -> dict:
        """Legacy HTTP+SSE POST /message handler.

        When a live SSE stream is open for `session_id`, run the message and
        push the JSON-RPC response down that stream (returning 202 here, per
        the 2024-11-05 transport). With no open stream this degrades to an
        inline Streamable HTTP response, so the same /message path serves both
        a legacy SSE client and a plain POST client.
        """
        queue = self._sse_queues.get(session_id) if session_id else None
        if queue is None:
            return self.dispatch_http(raw_data, session_id)
        body = self.handle_message(raw_data)
        if body:
            queue.put_nowait(body)
        return {"status": 202, "headers": {}, "body": ""}

    async def sse_stream(self, session_id: str, endpoint_url: str, keepalive: float = 15.0):
        """Async generator of SSE frames for the legacy HTTP+SSE transport.

        Emits the `endpoint` event first (telling the client where to POST),
        then each queued JSON-RPC response as it arrives, with periodic
        keep-alive comment frames so proxies do not close an idle connection.
        Registers the per-session queue up front and tears it down (plus the
        session) when the client disconnects and the generator is closed.
        """
        import asyncio
        queue: asyncio.Queue = asyncio.Queue()
        self._sse_queues[session_id] = queue
        try:
            yield f"event: endpoint\ndata: {endpoint_url}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=keepalive)
                    yield f"event: message\ndata: {message}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self._sse_queues.pop(session_id, None)
            self.close_session(session_id)

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
        """Handle initialize request — negotiate the protocol version and
        return server capabilities. We echo the client's requested version
        when we support it and otherwise offer our newest, so both a current
        Streamable HTTP client and a legacy 2024-11-05 client connect."""
        self._initialized = True
        requested = (params or {}).get("protocolVersion")
        return {
            "protocolVersion": self.negotiate_protocol_version(requested),
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

        Mounts both supported transports on `path`:
            POST {path}          — Streamable HTTP (the current transport)
            POST {path}/message  — legacy HTTP+SSE message sink (+ inline fallback)
            GET  {path}/sse      — legacy HTTP+SSE stream (persistent)

        A Streamable HTTP client (Claude Code `--transport http`) POSTs to
        `{path}` and reads the JSON-RPC response inline, with an Mcp-Session-Id
        header issued on initialize. A legacy SSE client (Claude Desktop,
        `--transport sse`) GETs `{path}/sse`, receives the endpoint event, and
        its responses stream back on that connection.
        """
        server = self

        def _session_header(request) -> str:
            headers = getattr(request, "headers", None) or {}
            return headers.get("mcp-session-id", "") or ""

        def _apply(response, outcome):
            for name, value in outcome["headers"].items():
                response.header(name, value)
            body = outcome["body"]
            if not body:
                return response("", outcome["status"])
            return response(json.loads(body), outcome["status"])

        @router_module.post(self.path)
        @router_module.noauth()
        async def mcp_streamable(request, response):
            outcome = server.dispatch_http(request.body, _session_header(request))
            return _apply(response, outcome)

        @router_module.post(f"{self.path}/message")
        @router_module.noauth()
        async def mcp_message(request, response):
            params = getattr(request, "params", None) or {}
            session_id = params.get("sessionId") or _session_header(request)
            outcome = server.dispatch_sse_message(request.body, session_id)
            return _apply(response, outcome)

        @router_module.get(f"{self.path}/sse")
        @router_module.noauth()
        async def mcp_sse(request, response):
            session_id = server.open_session()
            base = getattr(request, "path", self.path).rsplit("/sse", 1)[0]
            endpoint_url = f"{base}/message?sessionId={session_id}"
            return response.stream(server.sse_stream(session_id, endpoint_url))

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
            "type": "http",
            "url": f"http://localhost:{port}{self.path}",
        }

        config_file.write_text(json.dumps(config, indent=2) + "\n")


# ── Decorator API ──────────────────────────────────────────────

# Default server instance — tools/resources registered via decorators
# attach to this instance. Developers can create their own McpServer.
_default_server: McpServer | None = None


def _get_default_server() -> McpServer:
    """Return the singleton default McpServer, creating + populating
    it on first use.

    First-call side effect: the 24-tool built-in dev toolkit (file
    I/O, plan_*, docs_*, project_overview, etc.) is registered on the
    server. Without this call the server exists but its `_tools` dict
    stays empty — any GET /mcp/tools request then returns [] and
    dev-admin has nothing to work with. Registration is idempotent
    (tool names are dict keys) so repeated calls are safe.
    """
    global _default_server
    if _default_server is None:
        _default_server = McpServer("/__dev/mcp", name="Tina4 Dev Tools")
        try:
            from .tools import register_dev_tools
            register_dev_tools(_default_server)
        except Exception as exc:
            # Don't let a bad tool module prevent the server from
            # existing — the REST shim should still return an empty
            # list rather than crashing the request.
            import sys
            print(f"[mcp] dev tool registration failed: {exc}", file=sys.stderr)
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


def register(server: McpServer) -> None:
    """Register all built-in dev tools on the given McpServer instance.

    Only active when TINA4_DEBUG=true and running on localhost (or TINA4_MCP_REMOTE=true).
    """
    from .tools import register_dev_tools
    register_dev_tools(server)
