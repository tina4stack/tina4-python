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


# ---------------------------------------------------------------------------
# Global Frond template engine registry
# ---------------------------------------------------------------------------
_global_frond = None
_framework_frond = None


def get_frond():
    """Return the global Frond engine, creating a default if needed."""
    global _global_frond
    if _global_frond is None:
        from tina4_python.frond.engine import Frond
        _global_frond = Frond("src/templates")
    return _global_frond


def get_framework_frond():
    """Return the singleton Frond engine for built-in framework templates."""
    global _framework_frond
    framework_dir = Path(__file__).resolve().parent.parent / "templates"
    if _framework_frond is None and framework_dir.is_dir():
        from tina4_python.frond.engine import Frond
        _framework_frond = Frond(str(framework_dir))
    # Sync custom filters/globals from the user engine
    if _framework_frond is not None:
        user_engine = get_frond()
        _framework_frond._filters.update(user_engine._filters)
        _framework_frond._globals.update(user_engine._globals)
    return _framework_frond


def set_frond(engine):
    """Register a pre-configured Frond engine for response.render().

    Call this at startup after registering custom filters and globals:

        from tina4_python.frond import Frond
        from tina4_python.core.response import set_frond

        engine = Frond("src/templates")
        engine.add_filter("money", my_money_filter)
        engine.add_global("APP_VERSION", "1.0")
        set_frond(engine)
    """
    global _global_frond
    _global_frond = engine


class Response:
    """HTTP response builder with compression and ETag support."""

    __slots__ = (
        "status_code", "content", "content_type",
        "_headers", "_cookies", "_is_streaming", "_stream_source",
    )

    def __init__(self):
        self.status_code: int = 200
        self.content: bytes = b""
        self.content_type: str = "text/html; charset=utf-8"
        self._headers: list[tuple[str, str]] = []
        self._cookies: list[str] = []
        self._is_streaming: bool = False
        self._stream_source = None

    def __call__(self, data=None, status_code: int = 200, content_type: str = None,
                 headers: dict | None = None) -> "Response":
        """Smart callable — auto-detects content type from data.

        Usage:
            return response({"key": "value"})                       # JSON
            return response({"ok": True}, HTTP_CREATED)              # JSON with status
            return response("<h1>Hello</h1>")                        # HTML
            return response("plain text", HTTP_OK)                   # Plain text
            return response(data, HTTP_OK, APPLICATION_JSON)         # Explicit
            return response(data, headers={"X-Tenant": "acme"})      # One-shot headers
        """
        self.status_code = status_code

        # Optional one-shot headers — equivalent to chaining .header(k, v)
        # for each entry, but lets call sites stay on a single expression.
        if headers:
            for k, v in headers.items():
                self._headers.append((k, v))

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

    def add_header(self, name: str, value: str) -> "Response":
        """Add a response header (chainable). Alias for header()."""
        return self.header(name, value)

    def cookie(self, name: str, value: str, options=None, *,
               path: str = None, max_age: int = None, http_only: bool = None,
               secure: bool = None, same_site: str = None) -> "Response":
        """Set a cookie (chainable). Two equivalent forms:

            # Kwarg form (original)
            response.cookie("session", token, max_age=3600, http_only=True)

            # Dict-options form (when config comes from a settings object)
            COOKIE_OPTS = {"max_age": 3600, "http_only": True, "secure": True}
            response.cookie("session", token, COOKIE_OPTS)

        When ``options`` is a dict, its values become the defaults; any
        explicit kwarg passed afterwards overrides individual entries.
        """
        # Defaults
        _path = "/"
        _max_age = 3600
        _http_only = True
        _secure = False
        _same_site = "Lax"

        # Dict-options form
        if isinstance(options, dict):
            _path      = options.get("path", _path)
            _max_age   = options.get("max_age", _max_age)
            _http_only = options.get("http_only", _http_only)
            _secure    = options.get("secure", _secure)
            _same_site = options.get("same_site", _same_site)

        # Explicit kwargs win over dict
        if path      is not None: _path = path
        if max_age   is not None: _max_age = max_age
        if http_only is not None: _http_only = http_only
        if secure    is not None: _secure = secure
        if same_site is not None: _same_site = same_site

        parts = [f"{name}={value}", f"Path={_path}", f"Max-Age={_max_age}",
                 f"SameSite={_same_site}"]
        if _http_only:
            parts.append("HttpOnly")
        if _secure:
            parts.append("Secure")
        self._cookies.append("; ".join(parts))
        return self

    def stream(self, source, content_type: str = "text/event-stream") -> "Response":
        """Stream response from an async generator or sync iterable.

        Usage (SSE):
            @get("/events")
            async def events(request, response):
                async def generate():
                    for i in range(5):
                        yield f"data: message {i}\\n\\n"
                        await asyncio.sleep(1)
                return response.stream(generate())

        Usage (custom content type):
            return response.stream(generate(), "application/octet-stream")
        """
        self._is_streaming = True
        self._stream_source = source
        self.content_type = content_type
        if content_type == "text/event-stream":
            self._headers.append(("Cache-Control", "no-cache"))
            self._headers.append(("Connection", "keep-alive"))
            self._headers.append(("X-Accel-Buffering", "no"))
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

    def error(self, code: str, message: str, status_code: int = 400) -> "Response":
        """Standard error response envelope.

        Usage:
            return response.error("VALIDATION_FAILED", "Email is required", 400)
        """
        return self.json(error_response(code, message, status_code), status_code)

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

    def render(self, template: str, data: dict = None, status_code: int = None) -> "Response":
        """Render a Frond/Twig template with data.

        Uses the global Frond engine (registered via set_frond()) so that
        custom filters and globals are available in all templates.
        Falls back to framework templates if not found in user dir.

        The optional ``status_code`` lets error-page handlers render the
        page and set the response status in one call::

            return response.render("errors/404.twig", {}, 404)
            return response.render("errors/500.twig", {"err": str(e)}, 500)
        """
        engine = get_frond()

        # Try user templates first (the global engine's directory)
        try:
            html = engine.render(template, data or {})
            rendered = self.html(html)
            if status_code is not None:
                rendered.status_code = status_code
            return rendered
        except FileNotFoundError:
            pass
        except Exception as e:
            return self.html(f"<pre>Template error: {e}</pre>", 500)

        # Fallback: framework templates (singleton, filters/globals synced)
        fw_engine = get_framework_frond()
        if fw_engine is not None:
            try:
                html = fw_engine.render(template, data or {})
                rendered = self.html(html)
                if status_code is not None:
                    rendered.status_code = status_code
                return rendered
            except FileNotFoundError:
                pass
            except Exception as e:
                return self.html(f"<pre>Template error: {e}</pre>", 500)

        return self.html(f"<pre>Template not found: {template}</pre>", 404)

    def send(self, data=None, status_code: int = None, content_type: str = None) -> "Response":
        """Finalize and return the response — matches PHP/Ruby/Node API."""
        if data is not None:
            if isinstance(data, (dict, list)):
                return self.__call__(data, status_code or 200)
            if isinstance(data, str):
                if content_type:
                    self.content_type = content_type
                self.content = data.encode()
                if status_code:
                    self.status_code = status_code
                return self
        return self

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


def error_response(code: str, message: str, status: int = 400) -> dict:
    """Build a standard error response envelope.

    Usage:
        return response(error_response("VALIDATION_FAILED", "Email is required", 400), 400)
    """
    return {
        "error": True,
        "code": code,
        "message": message,
        "status": status,
    }


def _is_compressible(content_type: str) -> bool:
    """Check if content type benefits from compression."""
    compressible = (
        "text/", "application/json", "application/xml",
        "application/javascript", "image/svg",
    )
    return any(ct in content_type for ct in compressible)
