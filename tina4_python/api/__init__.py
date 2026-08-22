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
import http.client
import secrets
import socket
import mimetypes
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener
from urllib.error import HTTPError, URLError

# Safe: importing the tina4_python.api submodule always fully initializes the
# tina4_python package first, and __version__ is set near the very top of
# tina4_python/__init__.py, well before Api (a LAZY-loaded name) is ever
# touched -- no circular import.
from tina4_python import __version__


# Statuses that warrant an automatic retry when ``max_retries`` > 0: rate-limit
# (429) plus the transient server-side 5xx family. 4xx client errors (401,
# 404, …) are NOT retried — a repeat won't succeed.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Streaming download reads/writes this many bytes per chunk so a multi-megabyte
# body never lands in memory in one piece.
_DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Read chunk size for stream_bytes / stream_lines / stream_sse. The generator
# yields whatever the transport hands back per read; this bounds the buffer.
_STREAM_CHUNK_SIZE = 8 * 1024

# Headers dropped when a redirect crosses to a different origin — a bearer token
# or a session cookie must never be handed to a host you didn't authenticate to.
_STRIP_ON_CROSS_ORIGIN = frozenset({"authorization", "cookie"})


class ApiTimeoutError(TimeoutError):
    """A ``stream_*`` call exceeded TINA4_API_CONNECT_TIMEOUT or TINA4_API_TIMEOUT."""


class ApiStreamError(RuntimeError):
    """A ``stream_*`` call failed at the transport layer (dropped, refused, HTTP error).

    ``status`` is the HTTP status code when the failure is a non-2xx response
    header; ``None`` for a connect/read failure with no HTTP response.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SseEvent:
    """One decoded Server-Sent-Event frame yielded by ``Api.stream_sse``.

    - ``data`` is the concatenated payload of every ``data:`` line in the frame
      (multiple ``data:`` lines join with ``\\n``, per the WHATWG SSE spec).
    - ``event`` / ``id`` are captured verbatim when present, else ``None``.
    - ``retry`` is captured as an ``int`` when the ``retry:`` value parses,
      else ``None``.
    """

    data: str
    event: str | None = None
    id: str | None = None
    retry: int | None = None


def _stream_env_timeout(name: str, default: float) -> float:
    """Read a positive-float timeout from an env var; fall back on garbage."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


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

    # ── streaming primitives (ADR-0060) ────────────────────────────────
    # stream_bytes is the primitive; stream_lines wraps it with UTF-8 +
    # newline framing; stream_sse wraps stream_lines with SSE framing.
    # All three return a Python generator over the response body — no
    # part of the body is ever buffered whole (backpressure = read chunk,
    # yield chunk, wait for the caller to advance).
    #
    # Timeouts: TINA4_API_CONNECT_TIMEOUT bounds establishment,
    # TINA4_API_TIMEOUT bounds total streaming duration. Both raise
    # ``ApiTimeoutError`` when exceeded. Both may be overridden per call.
    # The generator can be closed early (`gen.close()`) — the underlying
    # socket is released in the finally block.
    #
    # These deliberately use ``http.client`` directly rather than urllib:
    # the AI streaming client already speaks this transport, urllib does
    # not expose per-connect / per-read timeout independently, and
    # http.client's ``response.read(n)`` streams cleanly.

    def stream_bytes(self, path: str = "", *, method: str = "GET",
                     body=None, content_type: str = "application/json",
                     extra_headers: dict | None = None,
                     timeout: float | None = None,
                     connect_timeout: float | None = None,
                     params: dict | None = None) -> Iterator[bytes]:
        """Yield the response body in transport-sized chunks.

        The response is NEVER buffered whole; each yield is exactly what
        the socket produced on one ``read`` call. Iteration ends on EOF
        and raises ``ApiStreamError`` on a mid-stream drop / non-2xx.

        Timeouts (both apply, both raise ``ApiTimeoutError`` on expiry):
        - ``connect_timeout`` (or TINA4_API_CONNECT_TIMEOUT, default 10s)
          bounds establishment of the TCP + TLS handshake.
        - ``timeout`` (or TINA4_API_TIMEOUT, default 60s) bounds the total
          time from ``stream_bytes()`` return to the last yielded chunk.
        """
        url = self._url(path)
        if params:
            url += "?" + urlencode(params)
        req = self._build_request(method.upper(), url, body, content_type,
                                  extra_headers)
        return self._stream_iterator(req, timeout=timeout,
                                     connect_timeout=connect_timeout)

    def stream_lines(self, path: str = "", **opts) -> Iterator[str]:
        """Yield one decoded line per element, delimited by ``\\n`` or ``\\r\\n``.

        A trailing line without a final newline is yielded on EOF. An
        incomplete UTF-8 sequence at a chunk boundary is buffered so the
        next chunk completes it — a multibyte codepoint never splits.
        """
        return self._decode_lines(self.stream_bytes(path, **opts))

    def stream_sse(self, path: str = "", **opts) -> Iterator[SseEvent]:
        """Yield one ``SseEvent`` per SSE frame.

        Blank line = event boundary. ``data:`` lines concatenate with
        ``\\n``. ``event:`` / ``id:`` / ``retry:`` fields are captured.
        Lines beginning with ``:`` are comments and are dropped. The
        OpenAI ``data: [DONE]`` sentinel is delivered as an ordinary
        ``SseEvent(data='[DONE]')`` — the caller decides how to treat it
        — and the iterator ends on the next EOF.
        """
        return self._parse_sse(self.stream_lines(path, **opts))

    def _stream_iterator(self, req: Request, *, timeout: float | None,
                         connect_timeout: float | None) -> Iterator[bytes]:
        """Real-socket generator behind stream_bytes.

        Kept apart so a caller-injected transport (``self._transport``)
        can synthesise a stream by wrapping its buffered ``body``. In the
        canonical urllib/http.client path this opens one connection,
        checks the status, yields ``resp.read(chunk_size)`` until empty,
        and closes both the response and the connection on exit — every
        exit path, including ``gen.close()``.
        """
        parsed = urlparse(req.full_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ApiStreamError("stream requires an http or https URL")
        connect_bound = float(connect_timeout) if connect_timeout is not None \
            else _stream_env_timeout("TINA4_API_CONNECT_TIMEOUT", 10.0)
        total_bound = float(timeout) if timeout is not None \
            else _stream_env_timeout("TINA4_API_TIMEOUT", 60.0)
        if connect_bound <= 0:
            raise ApiStreamError("connect_timeout must be greater than zero")
        if total_bound <= 0:
            raise ApiStreamError("timeout must be greater than zero")

        # Transport seam: an injected transport is buffered by contract, so
        # yield its body as a single chunk. This preserves the ergonomics of
        # unit-testing an app that calls stream_* without demanding a real
        # server; framework tests never inject one.
        if self._transport is not None:
            result = self._call_transport(req)
            code = result.get("http_code")
            error = result.get("error")
            if error is not None:
                raise ApiStreamError(str(error))
            if code is None or code < 200 or code >= 300:
                raise ApiStreamError(
                    f"stream failed (HTTP {code})", status=code)
            self._store_cookies(result.get("headers"))
            payload = result.get("body")
            if payload is None:
                return iter(())
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            elif not isinstance(payload, (bytes, bytearray)):
                payload = json.dumps(payload, default=str).encode("utf-8")

            def one_shot():
                if payload:
                    yield bytes(payload)
            return one_shot()

        deadline = time.monotonic() + total_bound
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme == "https":
            context = self._ssl_context or ssl.create_default_context()
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                parsed.hostname, port,
                timeout=min(connect_bound, total_bound), context=context)
        else:
            connection = http.client.HTTPConnection(
                parsed.hostname, port, timeout=min(connect_bound, total_bound))

        response: http.client.HTTPResponse | None = None
        try:
            try:
                connection.connect()
            except (socket.timeout, TimeoutError):
                raise ApiTimeoutError(
                    f"connect timeout after {connect_bound:g}s") from None
            except OSError as exc:
                raise ApiStreamError(f"connect failed: {exc}") from None

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiTimeoutError(f"total timeout after {total_bound:g}s")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)

            path_and_query = parsed.path or "/"
            if parsed.query:
                path_and_query += "?" + parsed.query

            payload = req.data
            headers = {k: v for k, v in req.header_items()}
            try:
                connection.request(req.get_method(), path_and_query,
                                   body=payload, headers=headers)
                response = connection.getresponse()
            except (socket.timeout, TimeoutError):
                raise ApiTimeoutError(
                    f"total timeout after {total_bound:g}s") from None
            except (OSError, http.client.HTTPException) as exc:
                raise ApiStreamError(f"transport failed: {exc}") from None

            self._store_cookies(response.headers)
            status = response.status
            if status < 200 or status >= 300:
                raise ApiStreamError(
                    f"stream failed (HTTP {status})", status=status)

            def chunks():
                assert response is not None
                try:
                    while True:
                        remaining_now = deadline - time.monotonic()
                        if remaining_now <= 0:
                            raise ApiTimeoutError(
                                f"total timeout after {total_bound:g}s")
                        if connection.sock is not None:
                            connection.sock.settimeout(remaining_now)
                        try:
                            # read1(): return as soon as one underlying
                            # syscall yields data. read() would block
                            # accumulating a full _STREAM_CHUNK_SIZE
                            # buffer, defeating streaming backpressure
                            # and the total timeout under slow servers.
                            chunk = response.read1(_STREAM_CHUNK_SIZE)
                        except (socket.timeout, TimeoutError):
                            raise ApiTimeoutError(
                                f"total timeout after {total_bound:g}s") from None
                        except http.client.IncompleteRead as exc:
                            # A chunked-encoding read failed with some
                            # bytes accumulated. Yield those first so
                            # the caller's line/SSE parser sees every
                            # frame that DID arrive, then surface the
                            # drop as an ApiStreamError on the next
                            # read. Without this, the last (possibly
                            # complete) event is discarded silently.
                            if exc.partial:
                                yield exc.partial
                            raise ApiStreamError(
                                f"transport drop: {exc}") from None
                        except (OSError, http.client.HTTPException) as exc:
                            raise ApiStreamError(
                                f"transport drop: {exc}") from None
                        if not chunk:
                            return
                        yield chunk
                finally:
                    try:
                        response.close()
                    except Exception:
                        pass
                    connection.close()

            return chunks()
        except BaseException:
            # Anything raised before we returned the ``chunks()`` generator
            # (bad status, timeout on the request headers, etc.) means the
            # caller never gets the generator, so ``chunks()`` finally-close
            # never runs. Close by hand here.
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            connection.close()
            raise

    @staticmethod
    def _decode_lines(byte_stream: Iterator[bytes]) -> Iterator[str]:
        """UTF-8 line splitter for stream_lines.

        Buffers across chunk boundaries so an incomplete UTF-8 codepoint
        does not raise, and so a line split across two chunks yields as
        one string. Accepts LF (``\\n``) and CRLF (``\\r\\n``); a lone CR
        is treated as ordinary text.
        """
        raw = bytearray()
        try:
            for chunk in byte_stream:
                if not chunk:
                    continue
                raw.extend(chunk)
                # Drain complete lines, keeping any tail that hasn't seen
                # a newline for the next round.
                while True:
                    newline = raw.find(b"\n")
                    if newline == -1:
                        break
                    line = raw[:newline]
                    del raw[:newline + 1]
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    yield line.decode("utf-8", errors="replace")
            if raw:
                yield bytes(raw).decode("utf-8", errors="replace")
        finally:
            # Close the underlying generator if it has one (i.e. our real
            # stream_bytes). The caller may have consumed everything and
            # returned normally, or may have raised and cancelled us; in
            # either case ensure the underlying connection is released.
            close = getattr(byte_stream, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _parse_sse(line_stream: Iterator[str]) -> Iterator[SseEvent]:
        """SSE framer for stream_sse.

        Follows the WHATWG SSE contract: blank line = event boundary,
        multiple ``data:`` lines concatenate with ``\\n``, ``event:`` /
        ``id:`` / ``retry:`` fields captured, ``:`` prefix = comment
        (ignored). The OpenAI ``[DONE]`` sentinel is delivered as an
        ordinary event with data ``"[DONE]"``; the iterator ends on the
        next EOF.
        """
        data_parts: list[str] = []
        event_name: str | None = None
        event_id: str | None = None
        retry_value: int | None = None
        try:
            for line in line_stream:
                if line == "":
                    if data_parts or event_name or event_id or retry_value is not None:
                        yield SseEvent(
                            data="\n".join(data_parts),
                            event=event_name,
                            id=event_id,
                            retry=retry_value,
                        )
                    data_parts, event_name, event_id, retry_value = [], None, None, None
                    continue
                if line.startswith(":"):
                    continue
                if ":" in line:
                    field, _, value = line.partition(":")
                    # SSE says a single leading space after the ":" is a
                    # separator, not part of the value.
                    if value.startswith(" "):
                        value = value[1:]
                else:
                    field, value = line, ""
                if field == "data":
                    data_parts.append(value)
                elif field == "event":
                    event_name = value
                elif field == "id":
                    event_id = value
                elif field == "retry":
                    try:
                        retry_value = int(value)
                    except (TypeError, ValueError):
                        retry_value = None
            # Trailing frame without a terminating blank line still counts
            # (the server may close cleanly right after the last data).
            if data_parts or event_name or event_id or retry_value is not None:
                yield SseEvent(
                    data="\n".join(data_parts),
                    event=event_name,
                    id=event_id,
                    retry=retry_value,
                )
        finally:
            close = getattr(line_stream, "close", None)
            if callable(close):
                close()

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
        # VERSION-DEC-03 (feature 130): every outbound request carries a
        # default ``Tina4/<version>`` User-Agent. ``self._headers`` is merged
        # in AFTER the default, and ``extra_headers`` after that, so a
        # caller-supplied User-Agent (via the constructor's ``headers=``,
        # ``add_headers()``, or a per-call ``extra_headers``) always wins --
        # this is a default, never a clobber.
        headers = {"User-Agent": f"Tina4/{__version__}"}
        headers.update(self._headers)
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


__all__ = ["Api", "SseEvent", "ApiTimeoutError", "ApiStreamError"]
