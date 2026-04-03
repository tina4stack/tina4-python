# Tina4 Request — Parsed HTTP request.
"""
Clean request object with parsed body, params, headers, and cookies.
"""
import json
import os
from urllib.parse import parse_qs, unquote

# Maximum upload size in bytes (default 10 MB). Override via TINA4_MAX_UPLOAD_SIZE env var.
TINA4_MAX_UPLOAD_SIZE = int(os.environ.get("TINA4_MAX_UPLOAD_SIZE", 10_485_760))


class PayloadTooLarge(Exception):
    """Raised when request body exceeds TINA4_MAX_UPLOAD_SIZE."""
    pass


class Request:
    """Parsed HTTP request — everything a route handler needs."""

    __slots__ = (
        "method", "path", "query_string", "params", "query", "headers",
        "body", "raw_body", "cookies", "files", "ip",
        "content_type", "session", "_route_params",
    )

    def __init__(self):
        self.method: str = "GET"
        self.path: str = "/"
        self.query_string: str = ""
        self.params: dict = {}          # Query string + route params merged
        self.query: dict = {}           # Query string params only (separate from route params)
        self.headers: dict = {}         # Lowercase header keys
        self.body: dict | str | None = None  # Parsed body
        self.raw_body: bytes = b""
        self.cookies: dict = {}
        self.files: dict = {}
        self.ip: str = ""
        self.content_type: str = ""
        self.session = None             # Set by session middleware
        self._route_params: dict = {}   # Dynamic route params ({id}, etc.)

    @classmethod
    def from_scope(cls, scope: dict, body: bytes = b"") -> "Request":
        """Build a Request from an ASGI scope + body."""
        req = cls()
        req.method = scope.get("method", "GET")
        req.path = scope.get("path", "/")
        req.query_string = scope.get("query_string", b"").decode()
        req.raw_body = body

        # Parse headers (ASGI sends as list of [name, value] byte pairs)
        for name, value in scope.get("headers", []):
            req.headers[name.decode().lower()] = value.decode()

        req.content_type = req.headers.get("content-type", "")
        req.ip = _extract_ip(scope, req.headers)

        # Check upload size limit
        content_length = int(req.headers.get("content-length", 0) or 0)
        if content_length > TINA4_MAX_UPLOAD_SIZE or len(body) > TINA4_MAX_UPLOAD_SIZE:
            raise PayloadTooLarge(
                f"Request body ({max(content_length, len(body))} bytes) exceeds "
                f"TINA4_MAX_UPLOAD_SIZE ({TINA4_MAX_UPLOAD_SIZE} bytes)"
            )

        # Parse query params
        if req.query_string:
            parsed = parse_qs(req.query_string, keep_blank_values=True)
            req.query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            req.params = dict(req.query)  # params starts as copy of query, route params merge later

        # Parse cookies
        cookie_header = req.headers.get("cookie", "")
        if cookie_header:
            for pair in cookie_header.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    req.cookies[k.strip()] = v.strip()

        # Parse body
        req.body = _parse_body(body, req.content_type)

        # Separate files from body for multipart uploads
        if isinstance(req.body, dict) and "multipart/form-data" in req.content_type:
            files = {}
            fields = {}
            for key, value in req.body.items():
                if isinstance(value, dict) and "filename" in value:
                    # Content stays as raw bytes — no base64 encoding
                    files[key] = value
                else:
                    fields[key] = value
            req.files = files
            req.body = fields

        return req

    def merge_route_params(self):
        """Merge route params into params dict (route params take priority)."""
        if self._route_params:
            self.params.update(self._route_params)

    def param(self, key: str, default=None):
        """Get a route parameter (from URL path). Alias for params[key]."""
        return self.params.get(key, self._route_params.get(key, default))



def _extract_ip(scope: dict, headers: dict) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else ""


def _parse_body(body: bytes, content_type: str) -> dict | str | None:
    """Parse request body based on content type."""
    if not body:
        return None

    if "application/json" in content_type:
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body.decode(errors="replace")

    if "application/x-www-form-urlencoded" in content_type:
        parsed = parse_qs(body.decode(), keep_blank_values=True)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    if "multipart/form-data" in content_type:
        return _parse_multipart(body, content_type)

    # Plain text or unknown
    try:
        return body.decode()
    except UnicodeDecodeError:
        return None


def _parse_multipart(body: bytes, content_type: str) -> dict:
    """Parse multipart/form-data body. Returns dict with fields and files."""
    result = {}

    # Extract boundary
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
            break

    if not boundary:
        return result

    boundary_bytes = f"--{boundary}".encode()
    parts = body.split(boundary_bytes)

    for part in parts[1:]:  # Skip preamble
        if part.strip() == b"--" or part.strip() == b"--\r\n":
            break  # End marker

        # Split headers from content
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue

        header_section = part[:header_end].decode(errors="replace")
        content = part[header_end + 4:].rstrip(b"\r\n")

        # Parse Content-Disposition and Content-Type
        name = None
        filename = None
        file_type = "application/octet-stream"
        for line in header_section.split("\r\n"):
            if "Content-Disposition" in line:
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token[5:].strip('"')
                    elif token.startswith("filename="):
                        filename = token[9:].strip('"')
            elif "Content-Type" in line:
                file_type = line.split(":", 1)[1].strip()

        if not name:
            continue

        if filename:
            result[name] = {
                "filename": filename,
                "type": file_type,
                "content": bytes(content),
                "size": len(content),
            }
        else:
            result[name] = content.decode(errors="replace")

    return result
