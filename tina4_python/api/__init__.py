# Tina4 API Client — HTTP client using Python stdlib only.
"""
Make HTTP requests without requests/httpx/aiohttp.

    from tina4_python.api import Api

    api = Api("https://api.example.com")
    result = api.get("/users")
    result = api.post("/users", {"name": "Alice"})

Multipart upload (from disk or in-memory bytes), streaming download,
an injectable transport seam (for USERS to unit-test their own code),
and an opt-in per-client cookie jar are all built on the same zero-dependency
urllib core.
"""
import os
import json
import ssl
import time
import base64
import secrets
import mimetypes
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener
from urllib.error import HTTPError, URLError


# Statuses that warrant an automatic retry when ``max_retries`` > 0: rate-limit
# (429) plus the transient server-side 5xx family. 4xx client errors (401,
# 404, …) are NOT retried — a repeat won't succeed.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Streaming download reads/writes this many bytes per chunk so a multi-megabyte
# body never lands in memory in one piece.
_DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Headers dropped when a redirect crosses to a different origin — a bearer token
# or a session cookie must never be handed to a host you didn't authenticate to.
_STRIP_ON_CROSS_ORIGIN = frozenset({"authorization", "cookie"})


def _same_origin(url_a: str, url_b: str) -> bool:
    """True when two URLs share scheme + host + (effective) port."""
    a, b = urlparse(url_a), urlparse(url_b)
    default = {"http": 80, "https": 443}
    pa = a.port if a.port is not None else default.get(a.scheme)
    pb = b.port if b.port is not None else default.get(b.scheme)
    return (a.scheme, a.hostname, pa) == (b.scheme, b.hostname, pb)


class _AuthStripRedirectHandler(HTTPRedirectHandler):
    """Follow redirects, but drop the Authorization (and Cookie) header on a
    cross-origin hop.

    Plain urllib forwards the Authorization header to ANY redirect target,
    including a different host — so an ``api.get("/login")`` that 302s to
    ``https://attacker.example/`` would hand the bearer token to the attacker.
    Stripping it when the target origin (scheme/host/port) differs matches
    requests/httpx and closes that leak, while same-origin redirects keep auth.
    The cookie jar's ``Cookie`` header is stripped on the same rule for the
    identical reason.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and not _same_origin(req.full_url, newurl):
            new_req.headers = {
                k: v for k, v in new_req.headers.items()
                if k.lower() not in _STRIP_ON_CROSS_ORIGIN
            }
            new_req.unredirected_hdrs = {
                k: v for k, v in getattr(new_req, "unredirected_hdrs", {}).items()
                if k.lower() not in _STRIP_ON_CROSS_ORIGIN
            }
        return new_req


def _open(req, timeout, opener):
    """The single network-call indirection point (keeps the call site easy to
    patch in tests). ``req`` stays the first positional arg on purpose."""
    return opener.open(req, timeout=timeout)


class Api:
    """HTTP client using urllib — zero external dependencies."""

    def __init__(self, base_url: str = "", auth_header: str = "",
                 ignore_ssl: bool = False, timeout: int = 30,
                 bearer_token: str | None = None,
                 username: str | None = None,
                 password: str | None = None,
                 headers: dict[str, str] | None = None,
                 verify_ssl: bool | None = None,
                 max_retries: int = 0,
                 retry_backoff: float = 0.5,
                 transport=None,
                 cookies: bool = False):
        """HTTP client.

        Constructor accepts ergonomic kwargs the documentation has long
        described — every modern Python HTTP library (requests, httpx)
        accepts these directly rather than requiring post-construction
        setter calls.

            api = Api("https://api.example.com", bearer_token="sk-...")
            api = Api("https://api.example.com", username="u", password="p")
            api = Api("https://api.example.com", headers={"X-Tenant": "acme"})
            api = Api("https://self-signed.local", verify_ssl=False)

        The setter-based API (``set_bearer_token``, ``set_basic_auth``,
        ``add_headers``) continues to work; pick whichever reads better.

        ``verify_ssl`` is the docs-friendly inverse of ``ignore_ssl`` —
        ``verify_ssl=False`` is equivalent to ``ignore_ssl=True``. If
        both are supplied, ``ignore_ssl`` wins (legacy precedence).

        ``max_retries`` (default 0 = off) enables automatic retry with
        exponential backoff (``retry_backoff`` seconds base, doubling each
        attempt) on a transport error or a retryable status (429/5xx). A
        retried non-idempotent request (POST/…) may be re-sent — retries are
        opt-in for that reason.

        ``transport`` (default None = the real urllib network path) is an
        injectable seam so that USERS can unit-test their own code without a
        live server. When supplied it must be a callable with the signature
        ``transport(method, url, headers, body, timeout)`` returning the same
        result dict every verb returns: ``{"http_code", "body", "headers",
        "error"}``. It fully REPLACES the network call.

        NOTE: Tina4's own test suite must NEVER inject a fake/canned transport
        — the no-mock rule stands, so framework tests always exercise the real
        network path against a real local server. The seam exists purely so
        *application* developers can test code that calls an ``Api`` instance.

        ``cookies`` (default False = off, zero behaviour change) turns on a
        per-client, in-memory cookie jar: ``Set-Cookie`` headers on responses
        are parsed and the accumulated ``Cookie`` header is sent on subsequent
        requests. The jar is not persisted and is scoped to this instance.
        """
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = retry_backoff
        self._headers: dict[str, str] = {}
        self._ssl_context = None
        self._opener_cache = None
        self._transport = transport
        self._cookies_enabled = bool(cookies)
        self._cookies: dict[str, str] = {}

        # ── kwarg sugar ────────────────────────────────────────────────
        # Bearer token wins over basic auth if both are passed.
        if bearer_token is not None:
            self.set_bearer_token(bearer_token)
        elif username is not None and password is not None:
            self.set_basic_auth(username, password)

        if headers:
            self._headers.update(headers)

        # ignore_ssl is the existing flag; verify_ssl=False is the same thing
        # expressed positively. Honour ignore_ssl when both are set.
        if ignore_ssl or (verify_ssl is False):
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE

    def add_headers(self, headers: dict[str, str]):
        """Add custom headers to all requests."""
        self._headers.update(headers)


    def set_basic_auth(self, username: str, password: str):
        """Set Basic authentication."""
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.auth_header = f"Basic {creds}"

    def set_bearer_token(self, token: str):
        """Set Bearer token authentication."""
        self.auth_header = f"Bearer {token}"

    def get(self, path: str = "", params: dict = None) -> dict:
        """HTTP GET request."""
        url = self._url(path)
        if params:
            url += "?" + urlencode(params)
        return self._request("GET", url)

    def post(self, path: str = "", body=None, content_type: str = "application/json") -> dict:
        """HTTP POST request."""
        return self._request("POST", self._url(path), body, content_type)

    def put(self, path: str = "", body=None, content_type: str = "application/json") -> dict:
        """HTTP PUT request."""
        return self._request("PUT", self._url(path), body, content_type)

    def patch(self, path: str = "", body=None, content_type: str = "application/json") -> dict:
        """HTTP PATCH request."""
        return self._request("PATCH", self._url(path), body, content_type)

    def delete(self, path: str = "", body=None) -> dict:
        """HTTP DELETE request."""
        return self._request("DELETE", self._url(path), body)

    def send_request(self, method: str, path: str = "", body=None,
                     content_type: str = "application/json") -> dict:
        """Generic request method — pick the HTTP verb at call time.

        ``send_request`` is the name all four frameworks share (PHP
        ``sendRequest``, Ruby ``send_request``, Node ``sendRequest``). The
        3.13.0 Python-only rename to ``send`` was reverted: ``send`` can never
        be the shared name because Ruby's ``send`` is ``Object#send``, the
        metaprogramming primitive, so a Ruby class cannot expose an HTTP
        ``send`` without shadowing it. One concept, one name, everywhere.
        """
        return self._request(method.upper(), self._url(path), body, content_type)

    def upload(self, path: str = "", file_path: str | None = None,
               field_name: str = "file", extra_fields: dict | None = None,
               headers: dict[str, str] | None = None,
               file_bytes: bytes | None = None,
               filename: str | None = None) -> dict:
        """POST a ``multipart/form-data`` body — a file plus optional text fields.

        Two ways to supply the file, so a caller never needs a temp file:

        - ``file_path`` — a file on disk. ``filename`` defaults to its basename.
        - ``file_bytes`` + ``filename`` — an in-memory payload (bytes/str).

        ``field_name`` is the form field the file is sent under (default
        ``"file"``). ``extra_fields`` (dict) become additional text parts.
        ``headers`` (dict) are extra per-call headers merged onto the request.
        The part's ``Content-Type`` is guessed from the filename via
        ``mimetypes`` (falling back to ``application/octet-stream``).

        Returns the standard result dict ``{"http_code", "body", "headers",
        "error"}``. A missing file or no source given returns a clean error
        dict (``http_code`` None, ``error`` set) — it does NOT raise.

            api.upload("/avatars", file_path="/tmp/me.png")
            api.upload("/avatars", file_bytes=raw, filename="me.png",
                       extra_fields={"user_id": "42"})
        """
        if file_bytes is not None:
            content = (file_bytes if isinstance(file_bytes, (bytes, bytearray))
                       else str(file_bytes).encode("utf-8"))
            upload_name = filename or "upload.bin"
        elif file_path:
            if not os.path.isfile(file_path):
                return {"http_code": None, "body": None, "headers": {},
                        "error": f"file not found: {file_path}"}
            try:
                with open(file_path, "rb") as file_handle:
                    content = file_handle.read()
            except OSError as read_error:
                return {"http_code": None, "body": None, "headers": {},
                        "error": str(read_error)}
            upload_name = filename or os.path.basename(file_path)
        else:
            return {"http_code": None, "body": None, "headers": {},
                    "error": "upload requires file_path or file_bytes"}

        part_content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
        boundary = "----Tina4Boundary" + secrets.token_hex(16)
        body = self._build_multipart_body(
            boundary, field_name, upload_name, bytes(content),
            part_content_type, extra_fields)
        content_type = f"multipart/form-data; boundary={boundary}"
        return self._request("POST", self._url(path), body, content_type,
                             extra_headers=headers)

    def download(self, path: str = "", dest_path: str | None = None,
                 params: dict | None = None) -> dict:
        """Stream a GET response body to ``dest_path`` in chunks.

        The body is written to disk ``_DOWNLOAD_CHUNK_SIZE`` bytes at a time
        instead of being buffered whole in memory — safe for large payloads.
        Uses the same opener as every other verb (redirect following, the
        cross-origin auth strip, and the SSL context all apply).

        Returns ``{"http_code", "headers", "error", "path"}`` — there is no
        ``"body"`` key (it went to disk). ``path`` is ``dest_path`` on success
        and ``None`` on any error (missing dest, HTTP error status, or a
        transport failure), and the destination file is not written on error.
        """
        if not dest_path:
            return {"http_code": None, "headers": {},
                    "error": "download requires dest_path", "path": None}

        url = self._url(path)
        if params:
            url += "?" + urlencode(params)
        req = self._build_request("GET", url, None, "application/json")

        # An injected transport can't stream (it returns a buffered result), so
        # write its body out; only the real urllib path streams chunk-by-chunk.
        if self._transport is not None:
            result = self._call_transport(req)
            self._store_cookies(result["headers"])
            code = result["http_code"]
            if result["error"] is None and code is not None and 200 <= code < 300:
                data = result["body"]
                if isinstance(data, str):
                    data = data.encode("utf-8")
                elif not isinstance(data, (bytes, bytearray)):
                    data = json.dumps(data, default=str).encode("utf-8")
                try:
                    with open(dest_path, "wb") as out_file:
                        out_file.write(data)
                except OSError as write_error:
                    return {"http_code": code, "headers": result["headers"],
                            "error": str(write_error), "path": None}
                return {"http_code": code, "headers": result["headers"],
                        "error": None, "path": dest_path}
            return {"http_code": code, "headers": result["headers"],
                    "error": result["error"] or f"download failed (HTTP {code})",
                    "path": None}

        try:
            resp = _open(req, self.timeout, self._opener())
            self._store_cookies(resp.headers)
            with open(dest_path, "wb") as out_file:
                while True:
                    chunk = resp.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
            return {"http_code": resp.status, "headers": dict(resp.headers),
                    "error": None, "path": dest_path}
        except HTTPError as http_error:
            return {"http_code": http_error.code,
                    "headers": dict(http_error.headers) if http_error.headers else {},
                    "error": str(http_error), "path": None}
        except URLError as url_error:
            return {"http_code": None, "headers": {},
                    "error": str(url_error.reason), "path": None}
        except Exception as exc:
            return {"http_code": None, "headers": {}, "error": str(exc), "path": None}

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

    def _opener(self):
        """Build (once) an opener that follows redirects but strips the
        Authorization/Cookie header on a cross-origin hop, honouring the SSL
        context."""
        if self._opener_cache is None:
            handlers = [_AuthStripRedirectHandler()]
            if self._ssl_context is not None:
                handlers.append(HTTPSHandler(context=self._ssl_context))
            self._opener_cache = build_opener(*handlers)
        return self._opener_cache

    @staticmethod
    def _build_multipart_body(boundary: str, field_name: str, filename: str,
                              file_content: bytes, content_type: str,
                              extra_fields: dict | None) -> bytes:
        """Assemble a ``multipart/form-data`` body as raw bytes.

        Text fields come first, then the file part, then the closing delimiter
        — matching the canonical Ruby ``build_multipart_body`` shape so every
        framework produces a byte-identical layout.
        """
        crlf = b"\r\n"
        delimiter = ("--" + boundary).encode("utf-8")
        chunks: list[bytes] = []
        for key, value in (extra_fields or {}).items():
            chunks.append(delimiter + crlf)
            chunks.append(f'Content-Disposition: form-data; name="{key}"'.encode("utf-8")
                          + crlf + crlf)
            chunks.append(str(value).encode("utf-8") + crlf)
        chunks.append(delimiter + crlf)
        disposition = f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'
        chunks.append(disposition.encode("utf-8") + crlf)
        chunks.append(f"Content-Type: {content_type}".encode("utf-8") + crlf + crlf)
        chunks.append(file_content + crlf)
        chunks.append(delimiter + b"--" + crlf)
        return b"".join(chunks)

    def _build_request(self, method: str, url: str, body, content_type: str,
                       extra_headers: dict | None = None) -> Request:
        headers = dict(self._headers)
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        # Cookie jar: attach the accumulated Cookie header when enabled.
        if self._cookies_enabled:
            cookie_header = self._cookie_header()
            if cookie_header:
                headers["Cookie"] = cookie_header

        data = None
        if body is not None:
            if content_type == "application/json" and isinstance(body, (dict, list)):
                data = json.dumps(body, default=str).encode("utf-8")
                headers["Content-Type"] = "application/json"
            elif isinstance(body, str):
                data = body.encode("utf-8")
                headers["Content-Type"] = content_type
            elif isinstance(body, bytes):
                data = body
                headers["Content-Type"] = content_type

        if extra_headers:
            headers.update(extra_headers)

        return Request(url, data=data, headers=headers, method=method)

    def _request(self, method: str, url: str, body=None,
                 content_type: str = "application/json",
                 extra_headers: dict | None = None) -> dict:
        """Execute the request with opt-in retry/backoff. Returns a result dict.

        With ``max_retries`` > 0, a transport failure (``http_code`` None) or a
        retryable status (429/5xx) is retried up to ``max_retries`` times with
        exponential backoff; any other outcome (2xx, 4xx, 3xx) returns at once.
        """
        req = self._build_request(method, url, body, content_type, extra_headers)
        attempts = self.max_retries + 1
        result = None
        for attempt in range(attempts):
            result = self._attempt(req)
            code = result.get("http_code")
            retryable = code is None or code in _RETRY_STATUSES
            if not retryable or attempt == attempts - 1:
                return result
            time.sleep(self.retry_backoff * (2 ** attempt))
        return result

    def _call_transport(self, req: Request) -> dict:
        """Invoke a user-injected transport and normalize its result dict.

        The transport fully replaces the network call; it is called with the
        request as ``(method, url, headers, body, timeout)``.
        """
        try:
            result = self._transport(
                req.get_method(),
                req.full_url,
                dict(req.header_items()),
                req.data,
                self.timeout,
            )
        except Exception as exc:
            return {"http_code": None, "body": None, "headers": {}, "error": str(exc)}
        return {
            "http_code": result.get("http_code"),
            "body": result.get("body"),
            "headers": result.get("headers") or {},
            "error": result.get("error"),
        }

    def _attempt(self, req: Request) -> dict:
        """A single HTTP attempt. Returns the standardized result dict."""
        if self._transport is not None:
            result = self._call_transport(req)
            self._store_cookies(result["headers"])
            return result
        try:
            resp = _open(req, self.timeout, self._opener())
            self._store_cookies(resp.headers)
            raw = resp.read().decode("utf-8", errors="replace")
            resp_headers = dict(resp.headers)
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                parsed = raw

            return {
                "http_code": resp.status,
                "body": parsed,
                "headers": resp_headers,
                "error": None,
            }
        except HTTPError as e:
            self._store_cookies(e.headers)
            raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                parsed = raw
            return {
                "http_code": e.code,
                "body": parsed,
                "headers": dict(e.headers) if e.headers else {},
                "error": str(e),
            }
        except URLError as e:
            return {
                "http_code": None,
                "body": None,
                "headers": {},
                "error": str(e.reason),
            }
        except Exception as e:
            return {
                "http_code": None,
                "body": None,
                "headers": {},
                "error": str(e),
            }

    # ── cookie jar (opt-in, in-memory, per-client) ─────────────────────────
    def _cookie_header(self) -> str | None:
        """The accumulated ``Cookie`` request header, or None when empty."""
        if not self._cookies:
            return None
        return "; ".join(f"{name}={value}" for name, value in self._cookies.items())

    def _store_cookies(self, headers) -> None:
        """Parse ``Set-Cookie`` response headers into the jar (when enabled).

        Only the leading ``name=value`` pair of each ``Set-Cookie`` header is
        kept (attributes like Path/HttpOnly/Expires are ignored); a later value
        for the same name overwrites an earlier one. ``headers`` may be an
        ``http.client.HTTPMessage`` (real path — supports multiple
        ``Set-Cookie`` via ``get_all``) or a plain dict (transport seam).
        """
        if not self._cookies_enabled or headers is None:
            return
        raw_values: list[str] = []
        if hasattr(headers, "get_all"):
            raw_values = headers.get_all("Set-Cookie") or []
        elif isinstance(headers, dict):
            for key, value in headers.items():
                if key.lower() == "set-cookie" and value:
                    raw_values.append(value)
        for raw in raw_values:
            first_pair = raw.split(";", 1)[0].strip()
            if "=" in first_pair:
                name, _, value = first_pair.partition("=")
                name = name.strip()
                if name:
                    self._cookies[name] = value.strip()


__all__ = ["Api"]
