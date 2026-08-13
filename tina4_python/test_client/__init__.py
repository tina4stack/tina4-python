# Tina4 Test Client — Test routes without starting a server.
"""
In-process test client. Builds a real ASGI scope and dispatches it through the
REAL Tina4 front controller (``tina4_python.core.server.app``) — the same entry
point uvicorn/hypercorn/granian call — then wraps what the app actually sent as
a ``TestResponse``.

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


class TestResponse:
    """Wraps what the ASGI app sent with a clean test-friendly API."""

    __slots__ = ("status", "body", "headers", "content_type", "_header_list")

    def __init__(self, status: int, headers: list[tuple[bytes, bytes]], body: bytes):
        self.status: int = status
        self.body: bytes = body
        # ASGI hands back a LIST of (name, value) pairs, and a real response can
        # legitimately repeat a header (two Set-Cookie, two Vary). `_header_list`
        # preserves every pair in emission order so a duplicate is assertable via
        # get_all(); `headers` stays the back-compat single-value view (last value
        # per name, iteration order — unchanged shape for every existing reader).
        # (TC-HEADER-COLLAPSE, TC-DEC-02 — this used to collapse the list straight
        # into the dict below and the raw pairs were never kept.)
        self._header_list: list[tuple[str, str]] = []
        self.headers: dict = {}
        for name, value in headers:
            key = name.decode().lower() if isinstance(name, (bytes, bytearray)) else str(name).lower()
            val = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
            self._header_list.append((key, val))
            self.headers[key] = val
        self.content_type: str = self.headers.get("content-type", "")

    def get_all(self, name: str) -> list[str]:
        """Every value sent for ``name`` (case-insensitive), in emission order.

        A header sent once returns a one-item list; a header never sent returns
        an empty list. This is the one place a duplicate response header (two
        ``Set-Cookie``, two ``Vary``) is visible — ``headers[name]`` always
        collapses to the LAST value, same as before.
        """
        key = name.lower()
        return [v for k, v in self._header_list if k == key]

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
    """Test the app without opening a socket.

    Builds an ASGI scope and dispatches it through ``core.server.app`` — the
    real front controller. Everything a live request gets, an in-process test
    request gets: global + per-route middleware, the secure-by-default auth
    gate, static files, ``/swagger``, ``/__dev``, ``/__feedback``, CORS
    preflight, the RFC 9110 OPTIONS/405 ``Allow`` responses, HEAD
    body-stripping, session save + cookie, ETag/304, the dev toolbar and the
    500 handler.
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
        """Build an ASGI scope and dispatch it through the REAL front controller.

        This used to call ``Router.match`` directly and invoke the handler
        itself, which made everything the front controller does around route
        matching invisible to tests: global middleware never ran, and static
        files, ``/swagger``, ``/swagger/openapi.json``, the framework's bundled
        assets, ``/__dev``, ``/__feedback``, CORS preflight, the RFC 9110
        OPTIONS/405 ``Allow`` responses and HEAD body-stripping all came back as
        a hand-built 404 ``{"error":"Not found"}`` while the live server served
        them 200. Any test asserting framework-endpoint behaviour through
        TestClient was asserting nothing. (feature-recount D6 — the same shape as
        the #PY2 auth fix: the in-process test client must route through the real
        pipeline, not a re-implementation of it.)
        """

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

        # Build ASGI scope — the same shape the dev server's HTTP bridge and
        # uvicorn build for a real connection.
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": clean_path,
            "raw_path": clean_path.encode(),
            "query_string": query_string.encode(),
            "headers": header_list,
            "client": ("127.0.0.1", 0),
            "server": ("localhost", 7145),
            "root_path": "",
        }

        return self._dispatch(scope, raw_body)

    def _dispatch(self, scope: dict, raw_body: bytes) -> TestResponse:
        """Drive ``core.server.app`` for one request and collect what it sent."""
        from tina4_python.core.server import app

        collected_status: list[int] = []
        collected_headers: list[list] = []
        collected_body = bytearray()

        async def receive():
            return {"type": "http.request", "body": raw_body, "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                collected_status.append(message["status"])
                collected_headers.append(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"") or b""
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                collected_body.extend(chunk)

        self._run(app(scope, receive, send))

        if not collected_status:
            raise RuntimeError(
                f"Tina4 ASGI app sent no response for "
                f"{scope['method']} {scope['path']} — this is a framework bug"
            )

        return TestResponse(collected_status[0], collected_headers[0], bytes(collected_body))

    @staticmethod
    def _run(coro):
        """Run a coroutine to completion from sync code, loop or no loop.

        ``TestClient`` is deliberately synchronous so a test reads as
        ``client.get(...)``. Under an already-running loop (an async test)
        ``asyncio.run`` would raise, so the coroutine is driven on its own loop
        in a worker thread.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is not None and running.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()

        return asyncio.run(coro)
