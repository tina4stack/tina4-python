#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import asyncio
import base64
import json
import os
import re
import mimetypes
from urllib.parse import unquote_plus, urlparse, parse_qsl
import tina4_python
from tina4_python.Constant import (
    LOOKUP_HTTP_CODE,
    HTTP_REDIRECT,
    HTTP_REDIRECT_OTHER,
    HTTP_REDIRECT_MOVED,
    HTTP_OK,
    HTTP_SERVER_ERROR,
    TINA4_GET
)
from tina4_python.Session import Session
from tina4_python.Router import Router
from tina4_python.Debug import Debug
from tina4_python.Template import Template


def is_int(v: str) -> bool:
    """
    Utility to check if a string can be converted to an integer.

    Args:
        v (str): Value to test.

    Returns:
        bool: True if convertible to int, False otherwise.
    """
    try:
        int(v)
        return True
    except ValueError:
        return False


class Webserver:
    """
    Lightweight, async-native HTTP server for Tina4 Python.

    Implements a minimal but fully functional web server using ``asyncio.start_server``.
    Features include:

    - Static file serving from ``src/public/``
    - Full request parsing (headers, query strings, cookies)
    - Support for:
        - ``application/x-www-form-urlencoded``
        - ``application/json``
        - ``multipart/form-data`` (with file uploads → base64 encoded)
        - ``text/plain``
    - Session management via :class:`tina4_python.Session.Session`
    - Automatic CORS headers
    - Built-in routing via :class:`tina4_python.Router.Router`
    - Graceful error handling with customizable 500 page
    - ASGI-like response capability (for WebSocket or advanced use)

    The server is deliberately simple and fast — ideal for micro-services,
    APIs, and full-stack Tina4 applications.
    """

    # ------------------------------------------------------------------
    # Construction & configuration
    # ------------------------------------------------------------------
    def __init__(self, host_name: str = "0.0.0.0", port: int = 8000):
        """
        Initialise the web server.

        Args:
            host_name (str): Interface to bind (default: all interfaces).
            port (int): Port to listen on (default: 8000).
        """
        self.host_name = host_name
        self.port = port

        # Request state (populated per connection)
        self.method: str | None = None
        self.path: str | None = None
        self.request_raw: bytes | None = None
        self.content_raw: bytes | None = None
        self.headers: dict | None = None
        self.lowercase_headers: dict | None = None
        self.cookies: dict = {}
        self.session: Session | None = None
        self.request : dict | None = None

        # Response helpers
        self.response_protocol = "HTTP/1.1"

        # Core components
        self.router_handler: Router = Router()  # will be replaced by Tina4.initialize()
        self.server: asyncio.Server | None = None
        self.running = False

    # ------------------------------------------------------------------
    # Low-level request parsing helpers
    # ------------------------------------------------------------------
    async def get_content_length(self) -> int:
        """
        Return the request body length from the ``Content-Length`` header.

        Returns:
            int: Body length in bytes (0 if header missing).
        """
        return int(self.lowercase_headers.get("content-length", 0))

    async def get_content_body(self, content_length: int) -> tuple[dict | str | bytes, dict]:
        """
        Parse the request body according to ``Content-Type``.

        Supported types:
            - application/x-www-form-urlencoded → dict
            - application/json                 → dict (or raw string on error)
            - text/plain                       → str
            - multipart/form-data              → (fields dict, files dict)
            - everything else                  → base64-encoded raw data

        Files are returned as base64 strings inside the ``files`` dict
        (compatible with Tina4's PHP heritage).

        Returns:
            tuple: (parsed_body, parsed_files)
        """
        content = self.content_raw or b""

        # No body
        if content_length == 0 or not content:
            return {}, {}

        ctype = self.lowercase_headers.get("content-type", "")

        # ------------------------------------------------------------------
        # application/x-www-form-urlencoded
        # ------------------------------------------------------------------
        if ctype.startswith("application/x-www-form-urlencoded"):
            body = {}
            for pair in content.decode("utf-8").split("&"):
                if "=" not in pair:
                    continue
                key, _, value = pair.partition("=")
                body[key] = unquote_plus(value)
            return body, {}

        # ------------------------------------------------------------------
        # application/json
        # ------------------------------------------------------------------
        if ctype.startswith("application/json"):
            try:
                return json.loads(content), {}
            except json.JSONDecodeError:
                return content.decode("utf-8", errors="replace"), {}

        # ------------------------------------------------------------------
        # text/plain
        # ------------------------------------------------------------------
        if ctype.startswith("text/plain"):
            return content.decode("utf-8", errors="replace"), {}

        # ------------------------------------------------------------------
        # multipart/form-data
        # ------------------------------------------------------------------
        if ctype.startswith("multipart/form-data"):
            boundary_line = ctype.split("boundary=", 1)[-1]
            boundary = f"--{boundary_line}".encode()
            parts = content.split(boundary)[1:-1]  # drop prologue/epilogue

            fields: dict = {}
            files: dict = {}

            for part in parts:
                if b"\r\n\r\n" not in part:
                    continue
                header_block, body = part.split(b"\r\n\r\n", 1)
                headers = header_block.decode("utf-8", errors="replace")

                # Extract disposition
                disposition_match = re.search(r'name="([^"]+)"', headers)
                filename_match = re.search(r'filename="([^"]*)"', headers)
                ctype_match = re.search(r"Content-Type: ([^\r\n]+)", headers)

                name = disposition_match.group(1) if disposition_match else "unknown"
                filename = filename_match.group(1) if filename_match else None
                mime = ctype_match.group(1).strip() if ctype_match else "application/octet-stream"

                # Remove trailing boundary markers
                body = body.split(b"\r\n--")[0].rstrip(b"\r\n")

                if filename is None:
                    # Regular field
                    value = unquote_plus(body.decode("utf-8", errors="replace"))
                    fields[name] = value
                else:
                    # File upload
                    encoded = base64.b64encode(body).decode().replace("\n", "")
                    file_entry = {
                        "file_name": filename,
                        "content_type": mime,
                        "content": encoded,
                    }
                    if name in files:
                        if not isinstance(files[name], list):
                            files[name] = [files[name]]
                        files[name].append(file_entry)
                    else:
                        files[name] = file_entry

            return fields, files

        if ctype in ("text/xml", "application/xml", "application/soap+xml"):
            return content, {}
        # ------------------------------------------------------------------
        # Fallback – raw base64
        # ------------------------------------------------------------------
        return {"data": base64.b64encode(content).decode().replace("\n", "")}, {}

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------
    @staticmethod
    def send_header(header: str, value: str, headers_list: list):
        """
        Append a raw ``header: value`` line to the response header list.

        Args:
            header (str): Header name.
            value (str): Header value.
            headers_list (list): Mutable list collecting header lines.
        """
        headers_list.append(f"{header}: {value}")

    async def send_basic_headers(self, headers_list: list):
        """
        Add permissive CORS and keep-alive headers (used for most responses).

        Args:
            headers_list (list): List to which headers are appended.
        """
        self.send_header("Access-Control-Allow-Origin", "*", headers_list)
        self.send_header(
            "Access-Control-Allow-Headers",
            "Origin, X-Requested-With, Content-Type, Accept, Authorization",
            headers_list,
        )
        self.send_header("Access-Control-Allow-Credentials", "true", headers_list)
        self.send_header("Connection", "Keep-Alive", headers_list)
        self.send_header("Keep-Alive", "timeout=5, max=30", headers_list)
        self.send_header("Timing-Allow-Origin", "*", headers_list)

    @staticmethod
    async def get_headers(header_lines: list, protocol: str, status_code: int) -> bytes:
        """
        Convert collected header lines into final HTTP response header bytes.

        Args:
            header_lines (list): List of ``"Header: value"`` strings.
            protocol (str): e.g. ``"HTTP/1.1"``.
            status_code (int): Numeric HTTP status.

        Returns:
            bytes: Complete header block terminated by ``\\r\\n\\r\\n``.
        """
        status_text = LOOKUP_HTTP_CODE.get(status_code, "Unknown")
        result = f"{protocol} {status_code} {status_text}\r\n"
        for line in header_lines:
            result += f"{line}\r\n"
        result += "\r\n"
        return result.encode()

    # ------------------------------------------------------------------
    # Core request → response flow
    # ------------------------------------------------------------------
    async def get_response(self, method: str, scope ,reader: asyncio.StreamReader, writer: asyncio.StreamWriter, asgi_response: bool = False):
        """
        Main request dispatcher.

        - Handles OPTIONS pre-flight
        - Parses query string with nested/array support (e.g. ``user[name]=john``)
        - Builds the unified ``request`` object used throughout Tina4
        - Calls the router
        - Serialises the :class:`tina4_python.Response` object

        Args:
            method (str): HTTP method.
            reader (asyncio.StreamReader): Reader for direct response (ASGI mode).
            writer (asyncio.StreamWriter): Writer for direct response (ASGI mode).
            asgi_response (bool): If True, returns raw response object instead of bytes.

        Returns:
            bytes | tuple: Final HTTP response or (response_object, header_lines).
            :param scope:
            :param method:
            :param asgi_response:
            :param writer:
            :param reader:
        """
        # ------------------------------------------------------------------
        # OPTIONS → CORS pre-flight
        # ------------------------------------------------------------------
        if method == "OPTIONS":
            headers = []
            self.send_header("Access-Control-Allow-Origin", "*", headers)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS", headers)
            self.send_header(
                "Access-Control-Allow-Headers",
                "Origin, X-Requested-With, Content-Type, Accept, Authorization",
                headers,
            )
            self.send_header("Access-Control-Allow-Credentials", "true", headers)

            headers_bytes = await self.get_headers(headers, self.response_protocol, HTTP_OK)
            return headers_bytes if not asgi_response else (None, headers)

        # ------------------------------------------------------------------
        # Query string parsing with nested support
        # ------------------------------------------------------------------
        params = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))
        # Advanced nested parsing (user[0][name]=john → dict/list structure)
        for key, value in list(params.items()):
            matches = re.finditer(r"(\w+|\d+)", key)
            keys = [m.group(0) for m in matches]
            if len(keys) > 1:
                current = params
                for i, k in enumerate(keys):
                    is_last = i == len(keys) - 1
                    if not is_int(k):
                        if k not in current:
                            current[k] = {} if not is_last and keys[i + 1].isdigit() else value if is_last else []
                        current = current[k]
                    else:
                        idx = int(k)
                        if not isinstance(current, list):
                            current = current[list(current.keys())[-1]] if current else []
                        while len(current) <= idx:
                            current.append({})
                        if is_last:
                            current[idx] = value
                        else:
                            current = current[idx]

        # ------------------------------------------------------------------
        # Body parsing (POST, PUT, PATCH, etc.)
        # ------------------------------------------------------------------
        content_length = await self.get_content_length()
        if method != TINA4_GET:
            body, files = await self.get_content_body(content_length)
        else:
            body, files = None, None

        # ------------------------------------------------------------------
        # Unified request object (exposed globally for convenience)
        # ------------------------------------------------------------------
        request = {
            "params": params,
            "body": body,
            "files": files,
            "raw_data": self.request,
            "url": self.path,
            "session": self.session,
            "headers": self.lowercase_headers,
            "raw_request": self.request_raw,
            "raw_content": self.content_raw,
            "asgi_scope": scope,
            "asgi_reader": reader,
            "asgi_writer": writer,
            "asgi_response": asgi_response,
        }
        tina4_python.tina4_current_request = request

        # ------------------------------------------------------------------
        # Route resolution
        # ------------------------------------------------------------------
        response = await self.router_handler.resolve(
            method, self.path, request, self.lowercase_headers, self.session
        )

        # ------------------------------------------------------------------
        # Header assembly
        # ------------------------------------------------------------------
        headers = []

        if response.http_code not in (HTTP_REDIRECT, HTTP_REDIRECT_OTHER, HTTP_REDIRECT_MOVED):
            self.send_header("Content-Type", response.content_type or "text/html", headers)
            await self.send_basic_headers(headers)

            # Preserve session cookie
            session_name = os.getenv("TINA4_SESSION", "PY_SESS")
            if session_name in self.cookies:
                self.send_header("Set-Cookie", f"{session_name}={self.cookies[session_name]}", headers)

        # Custom headers from route
        for name, value in response.headers.items():
            self.send_header(name, str(value), headers)

        if asgi_response:
            return response, headers

        header_bytes = await self.get_headers(headers, self.response_protocol, response.http_code)

        if isinstance(response.content, (bytes, bytearray)):
            return header_bytes + response.content
        return header_bytes + response.content.encode("utf-8")

    # ------------------------------------------------------------------
    # Raw data reception
    # ------------------------------------------------------------------
    async def get_data(self, reader: asyncio.StreamReader) -> tuple:
        """
        Read the initial request line + headers + body (if Content-Length present).

        Returns:
            tuple: (request_line, headers_dict, lowercase_headers, body_text, full_raw, body_raw)
        """
        # Read until header/body separator
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            head = await reader.read(1024)

        # Parse request line & headers
        text = head.decode("utf-8", errors="replace")
        lines = text.split("\r\n")
        request_line = lines[0]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

        lowercase_headers = {k.lower(): v for k, v in headers.items()}

        # Read body if Content-Length present
        body_raw = b""
        if "content-length" in lowercase_headers:
            length = int(lowercase_headers["content-length"])
            while len(body_raw) < length:
                chunk = await reader.read(length - len(body_raw))
                if not chunk:
                    break
                body_raw += chunk

        full_raw = head + body_raw
        return request_line, headers, lowercase_headers, body_raw.decode("utf-8", errors="replace"), full_raw, body_raw

    # ------------------------------------------------------------------
    # Client connection handler
    # ------------------------------------------------------------------
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Entry point for each incoming connection.

        Handles static files, sessions, routing, errors, and WebSockets.
        """
        try:
            (
                request_line,
                headers,
                lowercase_headers,
                _,
                request_raw,
                content_raw,
            ) = await self.get_data(reader)

            if not request_line.strip():
                return  # Empty keep-alive probe

            self.request_raw = request_raw
            self.content_raw = content_raw
            self.headers = headers
            self.lowercase_headers = lowercase_headers

            parts = request_line.split(" ")
            self.method = parts[0].upper()
            self.path = parts[1]

            # ------------------------------------------------------------------
            # Fast static file serving (GET only, no WebSocket)
            # ------------------------------------------------------------------
            request_handled = False
            if self.method == "GET" and "sec-websocket-key" not in lowercase_headers:
                clean_url = Router.clean_url(self.path)
                file_path = os.path.join(tina4_python.root_path, "src", "public", clean_url.lstrip("/"))
                file_path = os.path.abspath(file_path)

                # Security: prevent directory traversal
                if os.path.commonpath([file_path, os.path.abspath(os.path.join(tina4_python.root_path, "src", "public"))]) == os.path.abspath(os.path.join(tina4_python.root_path, "src", "public")):
                    if os.path.isfile(file_path):
                        mime_type, _ = mimetypes.guess_type(file_path)
                        mime_type = mime_type or "application/octet-stream"

                        with open(file_path, "rb") as f:
                            content = f.read()

                        headers = []
                        self.send_header("Content-Type", mime_type, headers)
                        await self.send_basic_headers(headers)
                        header_bytes = await self.get_headers(headers, self.response_protocol, HTTP_OK)
                        writer.write(header_bytes + content)
                        await writer.drain()
                        writer.close()
                        request_handled = True

            if request_handled:
                return

            # ------------------------------------------------------------------
            # Cookie & session initialisation
            # ------------------------------------------------------------------
            self.cookies = {}
            if "cookie" in lowercase_headers:
                for part in lowercase_headers["cookie"].split(";"):
                    if "=" in part:
                        name, val = part.strip().split("=", 1)
                        self.cookies[name] = val

            session_name = os.getenv("TINA4_SESSION", "PY_SESS")
            session_folder = os.getenv("TINA4_SESSION_FOLDER", os.path.join(tina4_python.root_path, "sessions"))
            self.session = Session(session_name, session_folder)

            if session_name in self.cookies:
                self.session.load(self.cookies[session_name])
            else:
                self.cookies[session_name] = self.session.start()

            # ------------------------------------------------------------------
            # Route or WebSocket
            # ------------------------------------------------------------------
            if "sec-websocket-key" in lowercase_headers:
                await self.get_response(self.method, reader, writer)
            else:
                response_bytes = await self.get_response(self.method, reader, writer)
                if response_bytes:
                    writer.write(response_bytes)
                    await writer.drain()
                writer.close()

        except Exception as exc:  # Global safety net
            error_msg = tina4_python.global_exception_handler(exc)
            Debug.error(f"Unhandled exception: {exc}")

            headers = []
            await self.send_basic_headers(headers)
            header_bytes = await self.get_headers(headers, self.response_protocol, HTTP_SERVER_ERROR)

            accept = self.lowercase_headers.get("accept", "")
            if "application/json" in accept or "application/json" in self.lowercase_headers.get("content-type", ""):
                payload = json.dumps({"error": "500 - Internal Server Error", "message": error_msg})
                writer.write(header_bytes + payload.encode())
            else:
                html = Template.render_twig_template(
                    "errors/500.twig",
                    {"server": {"url": self.path or "/"}, "error_message": error_msg},
                )
                writer.write(header_bytes + html.encode())

            await writer.drain()
            writer.close()

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------
    async def run_server(self):
        """
        Start the asyncio server. Called internally by :meth:`serve_forever`.
        """
        self.server = await asyncio.start_server(self.handle_client, self.host_name, self.port)
        addr = self.server.sockets[0].getsockname()
        if addr[0] == "0.0.0.0" or addr[0] == "127.0.0.1" or addr[0] == "::1":
            hostname = "localhost"
        else:
            hostname = addr[0]
        Debug.info(f"Tina4 Python server running on http://{hostname}:{addr[1]}")
        await self.server.serve_forever()

    async def serve_forever(self):
        """
        Public method to start the server (used by Tina4's ``initialize()``).
        """
        await self.run_server()

    def server_close(self):
        """
        Gracefully shut down the server (currently a placeholder).
        """
        if self.server:
            self.server.close()
            self.running = False