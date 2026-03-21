# Tina4 Response — Clean response builder.
"""
Fluent response API. Every route handler receives a response object.

Smart callable — the framework figures out the content type:

    return response({"users": []})                    # Auto-JSON, 200
    return response({"created": True}, HTTP_CREATED)  # JSON with status
    return response("<h1>Hello</h1>")                 # Auto-HTML
    return response("Not found", HTTP_NOT_FOUND)      # Text with status

Explicit methods for special cases:

    return response.redirect("/login")
    return response.render("page.html", {"title": "Home"})
    return response.file("report.pdf")
"""
import json
import gzip
import hashlib
import mimetypes
from pathlib import Path


class Response:
    """HTTP response builder with compression and ETag support."""

    __slots__ = (
        "status_code", "content", "content_type",
        "_headers", "_cookies",
    )

    def __init__(self):
        self.status_code: int = 200
        self.content: bytes = b""
        self.content_type: str = "text/html; charset=utf-8"
        self._headers: list[tuple[str, str]] = []
        self._cookies: list[str] = []

    def __call__(self, data=None, status_code: int = 200, content_type: str = None) -> "Response":
        """Smart callable — auto-detects content type from data.

        Usage:
            return response({"key": "value"})              # JSON
            return response({"ok": True}, HTTP_CREATED)     # JSON with status
            return response("<h1>Hello</h1>")               # HTML
            return response("plain text", HTTP_OK)          # Plain text
            return response(data, HTTP_OK, APPLICATION_JSON)  # Explicit
        """
        self.status_code = status_code

        if content_type:
            # Explicit content type provided
            self.content_type = content_type
            if isinstance(data, (dict, list)):
                self.content = json.dumps(data, default=str, separators=(",", ":")).encode()
            elif isinstance(data, str):
                self.content = data.encode()
            elif isinstance(data, bytes):
                self.content = data
            elif data is None:
                self.content = b""
            else:
                self.content = str(data).encode()
        elif isinstance(data, (dict, list)):
            # Auto-detect JSON
            self.content_type = "application/json"
            self.content = json.dumps(data, default=str, separators=(",", ":")).encode()
        elif isinstance(data, str):
            stripped = data.strip()
            if stripped.startswith("<") and stripped.endswith(">"):
                # Looks like HTML
                self.content_type = "text/html; charset=utf-8"
            else:
                self.content_type = "text/plain; charset=utf-8"
            self.content = data.encode()
        elif isinstance(data, bytes):
            self.content_type = "application/octet-stream"
            self.content = data
        elif data is None:
            self.content = b""
        else:
            self.content_type = "text/plain; charset=utf-8"
            self.content = str(data).encode()

        return self

    def status(self, code: int) -> "Response":
        """Set status code (chainable)."""
        self.status_code = code
        return self

    def header(self, name: str, value: str) -> "Response":
        """Add a response header (chainable)."""
        self._headers.append((name, value))
        return self

    def cookie(self, name: str, value: str, path: str = "/",
               max_age: int = 3600, http_only: bool = True,
               secure: bool = False, same_site: str = "Lax") -> "Response":
        """Set a cookie (chainable)."""
        parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}",
                 f"SameSite={same_site}"]
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        self._cookies.append("; ".join(parts))
        return self

    def json(self, data, status_code: int = None) -> "Response":
        """JSON response."""
        if status_code:
            self.status_code = status_code
        self.content_type = "application/json"
        self.content = json.dumps(data, default=str, separators=(",", ":")).encode()
        return self

    def html(self, content: str, status_code: int = None) -> "Response":
        """HTML response."""
        if status_code:
            self.status_code = status_code
        self.content_type = "text/html; charset=utf-8"
        self.content = content.encode() if isinstance(content, str) else content
        return self

    def text(self, content: str, status_code: int = None) -> "Response":
        """Plain text response."""
        if status_code:
            self.status_code = status_code
        self.content_type = "text/plain; charset=utf-8"
        self.content = content.encode() if isinstance(content, str) else content
        return self

    def xml(self, content: str, status_code: int = None) -> "Response":
        """XML response."""
        if status_code:
            self.status_code = status_code
        self.content_type = "application/xml; charset=utf-8"
        self.content = content.encode() if isinstance(content, str) else content
        return self

    def redirect(self, url: str, status_code: int = 302) -> "Response":
        """HTTP redirect."""
        self.status_code = status_code
        self.content = b""
        self._headers.append(("location", url))
        return self

    def file(self, file_path: str, download_name: str = None) -> "Response":
        """Serve a file with auto-detected content type."""
        path = Path(file_path)
        if not path.is_file():
            self.status_code = 404
            self.content = b"File not found"
            self.content_type = "text/plain"
            return self

        mime, _ = mimetypes.guess_type(str(path))
        self.content_type = mime or "application/octet-stream"
        self.content = path.read_bytes()

        if download_name:
            self._headers.append(
                ("content-disposition", f'attachment; filename="{download_name}"')
            )
        return self

    def render(self, template: str, data: dict = None) -> "Response":
        """Render a Frond/Twig template with data."""
        from tina4_python.frond.engine import Frond
        from pathlib import Path

        # Search for templates in user dir first, then framework dir
        template_dirs = []
        user_dir = Path("src/templates")
        if user_dir.is_dir():
            template_dirs.append(str(user_dir))
        framework_dir = Path(__file__).resolve().parent.parent / "templates"
        if framework_dir.is_dir():
            template_dirs.append(str(framework_dir))

        for tdir in template_dirs:
            if (Path(tdir) / template).exists():
                try:
                    frond = Frond(tdir)
                    html = frond.render(template, data or {})
                    return self.html(html)
                except Exception as e:
                    return self.html(f"<pre>Template error: {e}</pre>", 500)

        return self.html(f"<pre>Template not found: {template}</pre>", 404)

    def build_headers(self, accept_encoding: str = "") -> list[tuple[bytes, bytes]]:
        """Build final ASGI headers with compression and ETag."""
        # Compress if applicable
        should_compress = (
            len(self.content) > 1024
            and "gzip" in accept_encoding
            and _is_compressible(self.content_type)
        )

        if should_compress:
            self.content = gzip.compress(self.content, compresslevel=6)
            self._headers.append(("content-encoding", "gzip"))
            self._headers.append(("vary", "Accept-Encoding"))

        # ETag
        if self.content and self.status_code == 200:
            etag = hashlib.md5(self.content).hexdigest()[:16]
            self._headers.append(("etag", f'"{etag}"'))

        # Build ASGI header list
        headers = [
            (b"content-type", self.content_type.encode()),
            (b"content-length", str(len(self.content)).encode()),
        ]

        for name, value in self._headers:
            headers.append((name.encode(), value.encode()))

        for cookie_str in self._cookies:
            headers.append((b"set-cookie", cookie_str.encode()))

        return headers


def _is_compressible(content_type: str) -> bool:
    """Check if content type benefits from compression."""
    compressible = (
        "text/", "application/json", "application/xml",
        "application/javascript", "image/svg",
    )
    return any(ct in content_type for ct in compressible)
