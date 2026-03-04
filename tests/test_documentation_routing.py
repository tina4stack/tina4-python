# tests/test_documentation_routing.py
"""
Self-contained routing test suite for Tina4 Python.

All routes are defined inline — no running server or src/ routes required.
Tests exercise the Router.resolve() pipeline directly.
"""

import json
import pytest
from urllib.parse import urlparse, parse_qs
import tina4_python
from tina4_python import Constant
from tina4_python.Router import Router, get, post, put, delete, middleware, secured, noauth


# ------------------------------------------------------------------
# Fixture: reset routes before/after each test
# ------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_routes():
    saved = dict(tina4_python.tina4_routes)
    tina4_python.tina4_routes = {}
    _register_all_routes()
    yield
    tina4_python.tina4_routes = saved


def _make_request(params=None, body=None, raw_content=None):
    """Build a minimal request dict for Router.resolve()."""
    return {
        "params": params or {},
        "body": body or {},
        "files": {},
        "raw_data": None,
        "raw_request": None,
        "raw_content": raw_content,
        "asgi_scope": None,
        "asgi_reader": None,
        "asgi_writer": None,
        "asgi_response": None,
    }


# ------------------------------------------------------------------
# Route definitions (inline — the whole point of this test)
# ------------------------------------------------------------------

class AuthMiddleware:
    @staticmethod
    def before_auth(request, response):
        if not request.headers.get("authorization"):
            response.content = "Unauthorized"
            response.http_code = Constant.HTTP_UNAUTHORIZED
        return request, response

    @staticmethod
    def after_header(request, response):
        response.headers["X-Custom"] = "Processed"
        return request, response


class RunSomething:
    @staticmethod
    def before_something(request, response):
        response.content += "Before"
        return request, response

    @staticmethod
    def after_something(request, response):
        response.content += "After"
        return request, response

    @staticmethod
    def before_and_after_something(request, response):
        response.content += "[Before / After Something]"
        return request, response


def _register_all_routes():
    """Register all test routes. Called by the fixture before each test."""

    @get("/hello")
    async def get_hello(request, response):
        return response("Hello, Tina4 Python!")

    @noauth()
    @post("/submit")
    async def post_submit(request, response):
        name = request.body.get("name", "")
        age = request.body.get("age", "")
        return response(f"Name: {name}, Age: {age}")

    @get("/users")
    async def get_users(request, response):
        return response({"users": ["Alice", "Bob"]})

    @noauth()
    @post("/users")
    async def post_users(request, response):
        name = request.body.get("name", "Unknown")
        return response({"created": name})

    @noauth()
    @put("/users/{id}")
    async def put_user(id, request, response):
        name = request.body.get("name", "")
        return response(f"Updated user {id}: {name}")

    @noauth()
    @delete("/users/{id}")
    async def delete_user(id, request, response):
        return response(f"Deleted user {id}")

    @get("/users/{user_id}/posts/{post_id}")
    async def get_user_posts(user_id, post_id, request, response):
        return response(f"User {user_id}, Post {post_id}")

    @get("/search")
    async def get_search(request, response):
        q = request.params.get("q", "")
        page = request.params.get("page", "1")
        return response(f"Search: {q}, Page: {page}")

    @get("/admin/dashboard")
    async def get_admin_dashboard(request, response):
        return response("Admin Dashboard")

    @middleware(AuthMiddleware)
    @get("/protected")
    async def get_protected(request, response):
        return response("Secure data")

    @get("/divide/{n}")
    async def get_divide(n, request, response):
        try:
            n_val = int(n)
        except ValueError:
            return response("Invalid number", Constant.HTTP_BAD_REQUEST)
        if n_val == 0:
            return response("Cannot divide by zero", Constant.HTTP_BAD_REQUEST)
        return response(f"Result: {100 / n_val}")

    @get("/async-db")
    async def get_async_db(request, response):
        return response([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])

    @get("/api/health")
    async def get_health(request, response):
        return response({"status": "ok"})

    @secured()
    @get("/profile")
    async def get_profile(request, response):
        return response("User profile data")

    @middleware(RunSomething)
    @get("/middleware")
    async def get_middleware(request, response):
        return response("Route")


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------
async def resolve(method, path, headers=None, body=None, params=None):
    """Shorthand for Router.resolve with sensible defaults.

    Parses query string from *path* into request.params automatically
    (mimicking what the webserver layer does before calling the router).
    """
    hdrs = headers or {}
    parsed = urlparse(path)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    merged_params = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
    if params:
        merged_params.update(params)
    req = _make_request(params=merged_params, body=body)
    session = {}
    return await Router.resolve(method, path, req, hdrs, session)


# ------------------------------------------------------------------
# 1. Basic GET Route
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_basic_get_route():
    r = await resolve(Constant.TINA4_GET, "/hello")
    assert r.http_code == Constant.HTTP_OK
    assert "Hello, Tina4 Python!" in str(r.content)


# ------------------------------------------------------------------
# 2. POST Route with body parsing
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_post_route_with_body():
    token = tina4_python.tina4_auth.get_token({"url": "/submit"})
    r = await resolve(
        Constant.TINA4_POST, "/submit",
        headers={"authorization": f"Bearer {token}"},
        body={"name": "Alice", "age": 30},
    )
    assert r.http_code == Constant.HTTP_OK
    assert "Alice" in str(r.content)
    assert "30" in str(r.content)


# ------------------------------------------------------------------
# 3. All HTTP Methods
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_users():
    r = await resolve(Constant.TINA4_GET, "/users")
    assert r.http_code == Constant.HTTP_OK
    data = json.loads(r.content) if isinstance(r.content, str) else r.content
    assert isinstance(data["users"], list)
    assert "Alice" in data["users"]


@pytest.mark.asyncio
async def test_post_create_user():
    token = tina4_python.tina4_auth.get_token({"url": "/users"})
    r = await resolve(
        Constant.TINA4_POST, "/users",
        body={"name": "Charlie", "formToken": token},
    )
    assert r.http_code == Constant.HTTP_OK
    data = json.loads(r.content) if isinstance(r.content, str) else r.content
    assert data["created"] == "Charlie"


@pytest.mark.asyncio
async def test_put_update_user():
    token = tina4_python.tina4_auth.get_token({"url": "/users/123"})
    r = await resolve(
        Constant.TINA4_PUT, "/users/123",
        headers={"authorization": f"Bearer {token}"},
        body={"name": "David"},
    )
    assert r.http_code == Constant.HTTP_OK
    assert "David" in str(r.content)
    assert "123" in str(r.content)


@pytest.mark.asyncio
async def test_delete_user():
    token = tina4_python.tina4_auth.get_token({"url": "/users/999"})
    r = await resolve(
        Constant.TINA4_DELETE, "/users/999",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.http_code == Constant.HTTP_OK
    assert "999" in str(r.content)


# ------------------------------------------------------------------
# 4. Path Parameters
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_path_parameters():
    r = await resolve(Constant.TINA4_GET, "/users/42/posts/7")
    assert r.http_code == Constant.HTTP_OK
    assert "42" in str(r.content)
    assert "7" in str(r.content)


# ------------------------------------------------------------------
# 5. Query Parameters via request.params
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_query_parameters():
    r = await resolve(Constant.TINA4_GET, "/search?q=tina4&page=2")
    assert r.http_code == Constant.HTTP_OK
    assert "tina4" in str(r.content)
    assert "2" in str(r.content)


# ------------------------------------------------------------------
# 6. Route Groups / Namespaces
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_route_with_prefix():
    r = await resolve(Constant.TINA4_GET, "/admin/dashboard")
    assert r.http_code == Constant.HTTP_OK
    assert "Admin Dashboard" in str(r.content)


# ------------------------------------------------------------------
# 7. Middleware – before_route & after_route
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_middleware_auth_blocked():
    r = await resolve(Constant.TINA4_GET, "/protected")
    assert r.http_code == Constant.HTTP_UNAUTHORIZED
    assert "Unauthorized" in str(r.content)


@pytest.mark.asyncio
async def test_middleware_auth_passed():
    token = tina4_python.tina4_auth.get_token({"url": "/protected"})
    r = await resolve(
        Constant.TINA4_GET, "/protected",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.http_code == Constant.HTTP_OK
    assert "Secure data" in str(r.content)


@pytest.mark.asyncio
async def test_middleware_adds_header():
    token = tina4_python.tina4_auth.get_token({"url": "/protected"})
    r = await resolve(
        Constant.TINA4_GET, "/protected",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.headers.get("X-Custom") == "Processed"


# ------------------------------------------------------------------
# 8. Error Handling in Routes
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_divide_by_zero():
    r = await resolve(Constant.TINA4_GET, "/divide/0")
    assert r.http_code == Constant.HTTP_BAD_REQUEST
    assert "Cannot divide by zero" in str(r.content)


@pytest.mark.asyncio
async def test_invalid_number():
    r = await resolve(Constant.TINA4_GET, "/divide/abc")
    assert r.http_code == Constant.HTTP_BAD_REQUEST
    assert "Invalid number" in str(r.content)


# ------------------------------------------------------------------
# 9. Async Handlers
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_db_route():
    r = await resolve(Constant.TINA4_GET, "/async-db")
    assert r.http_code == Constant.HTTP_OK
    data = json.loads(r.content) if isinstance(r.content, str) else r.content
    assert isinstance(data, list)


# ------------------------------------------------------------------
# 10. Response Types
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_response_string():
    r = await resolve(Constant.TINA4_GET, "/hello")
    assert r.content_type == Constant.TEXT_HTML


@pytest.mark.asyncio
async def test_response_json_auto():
    r = await resolve(Constant.TINA4_GET, "/api/health")
    assert r.content_type == Constant.APPLICATION_JSON
    data = json.loads(r.content) if isinstance(r.content, str) else r.content
    assert data["status"] == "ok"


# ------------------------------------------------------------------
# 11. @secured() decorator
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secured_route_without_token():
    r = await resolve(Constant.TINA4_GET, "/profile")
    assert r.http_code in (Constant.HTTP_UNAUTHORIZED, Constant.HTTP_FORBIDDEN)


@pytest.mark.asyncio
async def test_secured_route_with_token():
    token = tina4_python.tina4_auth.get_token({"url": "/profile"})
    r = await resolve(
        Constant.TINA4_GET, "/profile",
        headers={"authorization": f"Bearer {token}"},
    )
    assert r.http_code == Constant.HTTP_OK
    assert "user" in str(r.content).lower()


# ------------------------------------------------------------------
# 12. 404 Handler
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_404_not_found():
    r = await resolve(Constant.TINA4_GET, "/this-does-not-exist-404")
    assert r.http_code == Constant.HTTP_NOT_FOUND


# ------------------------------------------------------------------
# 13. Middleware lifecycle
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_middleware_responses():
    r = await resolve(Constant.TINA4_GET, "/middleware")
    assert r.http_code == Constant.HTTP_OK
    # Pre-route middleware mutates mw_response, but the handler creates a fresh
    # Response.  Post-route any+after hooks then mutate the handler result.
    assert "Route[Before / After Something]After" in str(r.content)
