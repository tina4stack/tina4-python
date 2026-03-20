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
import base64
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError


class Api:
    """HTTP client using urllib — zero external dependencies."""

    def __init__(self, base_url: str = "", auth_header: str = "",
                 ignore_ssl: bool = False, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        self._headers: dict[str, str] = {}
        self._ssl_context = None
        if ignore_ssl:
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
        """Generic request method."""
        return self._request(method.upper(), self._url(path), body, content_type)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

    def _request(self, method: str, url: str, body=None,
                 content_type: str = "application/json") -> dict:
        """Execute HTTP request. Returns standardized result dict."""
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

        req = Request(url, data=data, headers=headers, method=method)

        try:
            resp = urlopen(req, timeout=self.timeout, context=self._ssl_context)
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
