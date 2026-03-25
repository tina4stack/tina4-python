# Tina4 Test Client — Test routes without starting a server.
"""
Simple test client that creates mock requests, matches routes,
executes handlers, and returns a TestResponse.

Usage::

    from tina4_python.test_client import TestClient

    client = TestClient()

    response = client.get("/api/users")
    assert response.status == 200
    assert response.json()["users"] is not None

    response = client.post("/api/users", json={"name": "Alice"})
    assert response.status == 201

    response = client.get("/api/users/1", headers={"Authorization": "Bearer token123"})
"""
import json as _json
import asyncio
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.router import Router


class TestResponse:
    """Wraps a Response object with a clean test-friendly API."""

    __slots__ = ("status", "body", "headers", "content_type")

    def __init__(self, response: Response):
        self.status: int = response.status_code
        self.body: bytes = response.content
        self.content_type: str = response.content_type
        self.headers: dict = {}
        for name, value in response._headers:
            self.headers[name.lower()] = value

    def json(self) -> dict | list | None:
        """Parse body as JSON."""
        if not self.body:
            return None
        return _json.loads(self.body.decode())

    def text(self) -> str:
        """Return body as a string."""
        return self.body.decode(errors="replace")

    def __repr__(self) -> str:
        return f"<TestResponse status={self.status} content_type={self.content_type!r}>"


class TestClient:
    """Test routes directly without starting a server.

    Creates a mock Request, finds the matching route via Router.match(),
    executes the handler, and returns a TestResponse.
    """

    def get(self, path: str, *, headers: dict | None = None) -> TestResponse:
        """Send a GET request to the given path."""
        return self._request("GET", path, headers=headers)

    def post(self, path: str, *, json: dict | list | None = None,
             body: str | bytes | None = None, headers: dict | None = None) -> TestResponse:
        """Send a POST request to the given path."""
        return self._request("POST", path, json=json, body=body, headers=headers)

    def put(self, path: str, *, json: dict | list | None = None,
            body: str | bytes | None = None, headers: dict | None = None) -> TestResponse:
        """Send a PUT request to the given path."""
        return self._request("PUT", path, json=json, body=body, headers=headers)

    def patch(self, path: str, *, json: dict | list | None = None,
              body: str | bytes | None = None, headers: dict | None = None) -> TestResponse:
        """Send a PATCH request to the given path."""
        return self._request("PATCH", path, json=json, body=body, headers=headers)

    def delete(self, path: str, *, headers: dict | None = None) -> TestResponse:
        """Send a DELETE request to the given path."""
        return self._request("DELETE", path, headers=headers)

    def _request(self, method: str, path: str, *,
                 json: dict | list | None = None,
                 body: str | bytes | None = None,
                 headers: dict | None = None) -> TestResponse:
        """Build a mock request, match the route, execute the handler."""

        # Build raw body bytes
        raw_body = b""
        content_type = ""

        if json is not None:
            raw_body = _json.dumps(json).encode()
            content_type = "application/json"
        elif body is not None:
            if isinstance(body, str):
                raw_body = body.encode()
            else:
                raw_body = body

        # Build ASGI-style headers
        header_list: list[tuple[bytes, bytes]] = []
        if headers:
            for k, v in headers.items():
                header_list.append((k.lower().encode(), v.encode()))

        if content_type and not any(h[0] == b"content-type" for h in header_list):
            header_list.append((b"content-type", content_type.encode()))

        if raw_body and not any(h[0] == b"content-length" for h in header_list):
            header_list.append((b"content-length", str(len(raw_body)).encode()))

        # Split path and query string
        query_string = ""
        clean_path = path
        if "?" in path:
            clean_path, query_string = path.split("?", 1)

        # Build ASGI scope
        scope = {
            "type": "http",
            "method": method,
            "path": clean_path,
            "query_string": query_string.encode(),
            "headers": header_list,
            "client": ("127.0.0.1", 0),
        }

        # Create Request from scope
        request = Request.from_scope(scope, raw_body)

        # Match route
        route, params = Router.match(method, clean_path)

        if route is None:
            # No route found — return 404
            resp = Response()
            resp.status_code = 404
            resp.content = b'{"error":"Not found"}'
            resp.content_type = "application/json"
            return TestResponse(resp)

        # Inject route params
        request._route_params = params
        request.merge_route_params()

        # Create response callable
        response = Response()

        # Execute handler (sync or async)
        handler = route["handler"]
        result = handler(request, response)

        # If handler is async, run it in an event loop
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in an async context — create a task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, result).result()
            else:
                result = asyncio.run(result)

        # The handler should have returned the response via response(...)
        # If the handler returned a Response, use that
        if isinstance(result, Response):
            return TestResponse(result)

        return TestResponse(response)
