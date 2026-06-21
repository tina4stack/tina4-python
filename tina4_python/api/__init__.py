# Tina4 API Client — HTTP client using Python stdlib only.
"""
Make HTTP requests without requests/httpx/aiohttp.

    from tina4_python.api import Api

    api = Api("https://api.example.com")
    result = api.get("/users")
    result = api.post("/users", {"name": "Alice"})
"""
import json
import ssl
import time
import base64
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener
from urllib.error import HTTPError, URLError


# Statuses that warrant an automatic retry when ``max_retries`` > 0: rate-limit
# (429) plus the transient server-side 5xx family. 4xx client errors (401,
# 404, …) are NOT retried — a repeat won't succeed.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _same_origin(url_a: str, url_b: str) -> bool:
    """True when two URLs share scheme + host + (effective) port."""
    a, b = urlparse(url_a), urlparse(url_b)
    default = {"http": 80, "https": 443}
    pa = a.port if a.port is not None else default.get(a.scheme)
    pb = b.port if b.port is not None else default.get(b.scheme)
    return (a.scheme, a.hostname, pa) == (b.scheme, b.hostname, pb)


class _AuthStripRedirectHandler(HTTPRedirectHandler):
    """Follow redirects, but drop the Authorization header on a cross-origin hop.

    Plain urllib forwards the Authorization header to ANY redirect target,
    including a different host — so an ``api.get("/login")`` that 302s to
    ``https://attacker.example/`` would hand the bearer token to the attacker.
    Stripping it when the target origin (scheme/host/port) differs matches
    requests/httpx and closes that leak, while same-origin redirects keep auth.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None and not _same_origin(req.full_url, newurl):
            new_req.headers = {
                k: v for k, v in new_req.headers.items() if k.lower() != "authorization"
            }
            new_req.unredirected_hdrs = {
                k: v for k, v in getattr(new_req, "unredirected_hdrs", {}).items()
                if k.lower() != "authorization"
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
                 retry_backoff: float = 0.5):
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
        """
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = retry_backoff
        self._headers: dict[str, str] = {}
        self._ssl_context = None
        self._opener_cache = None

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

    def send(self, method: str, path: str = "", body=None,
             content_type: str = "application/json") -> dict:
        """Generic request method — pick HTTP verb at call time.

        Renamed from ``send_request`` in 3.13.0 for parity with the
        documentation and conciseness (``api.send("PATCH", ...)`` reads
        cleaner than ``api.send_request("PATCH", ...)``).
        """
        return self._request(method.upper(), self._url(path), body, content_type)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

    def _opener(self):
        """Build (once) an opener that follows redirects but strips the
        Authorization header on a cross-origin hop, honouring the SSL context."""
        if self._opener_cache is None:
            handlers = [_AuthStripRedirectHandler()]
            if self._ssl_context is not None:
                handlers.append(HTTPSHandler(context=self._ssl_context))
            self._opener_cache = build_opener(*handlers)
        return self._opener_cache

    def _build_request(self, method: str, url: str, body, content_type: str) -> Request:
        headers = dict(self._headers)
        if self.auth_header:
            headers["Authorization"] = self.auth_header

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

        return Request(url, data=data, headers=headers, method=method)

    def _request(self, method: str, url: str, body=None,
                 content_type: str = "application/json") -> dict:
        """Execute the request with opt-in retry/backoff. Returns a result dict.

        With ``max_retries`` > 0, a transport failure (``http_code`` None) or a
        retryable status (429/5xx) is retried up to ``max_retries`` times with
        exponential backoff; any other outcome (2xx, 4xx, 3xx) returns at once.
        """
        req = self._build_request(method, url, body, content_type)
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

    def _attempt(self, req: Request) -> dict:
        """A single HTTP attempt. Returns the standardized result dict."""
        try:
            resp = _open(req, self.timeout, self._opener())
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


__all__ = ["Api"]
