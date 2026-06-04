# Tests for the @middleware() decorator's effect on auth_required.
#
# **Behaviour changed in v3.13.4** (tina4-book#141 PY-10-02): adding
# @middleware() to a write route NO longer silently disables the built-in
# Bearer-token gate. Middleware is purely additive. Use @noauth() to open
# a write route and @secured() to lock a read route — those decorators
# stay the only documented way to flip auth_required.
#
# Before the fix, applying @middleware() to a POST/PUT/PATCH/DELETE route
# silently flipped auth_required from True to False, creating an
# undocumented bypass that Chapter 10's "secure-by-default" promise
# silently violated.
import pytest
from tina4_python.core.router import (
    Router, get, post, put, patch, delete, noauth, secured, middleware,
)


class DummyAuthMiddleware:
    """Stub middleware that represents a custom OAuth/cookie auth handler."""
    @staticmethod
    def before_auth(request, response):
        return request, response


@pytest.fixture(autouse=True)
def clear_routes():
    Router.clear()
    yield
    Router.clear()


# ── Write routes with middleware STILL require auth (v3.13.4) ────


class TestMiddlewareDoesNotSkipBuiltinAuth:
    """Regression for tina4-book#141 PY-10-02 — @middleware() must NOT
    silently disable the framework's built-in Bearer-token gate."""

    def test_post_with_middleware_still_requires_auth(self):
        @middleware(DummyAuthMiddleware)
        @post("/api/tasks")
        async def create_task(req, res):
            pass

        route, _ = Router.match("POST", "/api/tasks")
        assert route is not None
        assert route["auth_required"] is True, \
            "@middleware() must not disable the default auth gate (PY-10-02)"

    def test_put_with_middleware_still_requires_auth(self):
        @middleware(DummyAuthMiddleware)
        @put("/api/tasks/{id}")
        async def update_task(req, res):
            pass

        route, _ = Router.match("PUT", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is True

    def test_patch_with_middleware_still_requires_auth(self):
        @middleware(DummyAuthMiddleware)
        @patch("/api/tasks/{id}")
        async def patch_task(req, res):
            pass

        route, _ = Router.match("PATCH", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is True

    def test_delete_with_middleware_still_requires_auth(self):
        @middleware(DummyAuthMiddleware)
        @delete("/api/tasks/{id}")
        async def delete_task(req, res):
            pass

        route, _ = Router.match("DELETE", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is True


# ── Write routes WITHOUT middleware still require auth ───────────


class TestBareWriteRoutesStillRequireAuth:

    def test_post_without_middleware_requires_auth(self):
        """POST route with no middleware should still require built-in auth."""
        @post("/api/items")
        async def create_item(req, res):
            pass

        route, _ = Router.match("POST", "/api/items")
        assert route is not None
        assert route["auth_required"] is True

    def test_put_without_middleware_requires_auth(self):
        @put("/api/items/{id}")
        async def update_item(req, res):
            pass

        route, _ = Router.match("PUT", "/api/items/1")
        assert route is not None
        assert route["auth_required"] is True


# ── @secured() re-enables auth even with middleware ──────────────


class TestSecuredOverridesMiddlewareBypass:

    def test_post_with_middleware_and_secured_requires_auth(self):
        """@secured() should re-enable built-in auth even when middleware is present."""
        @middleware(DummyAuthMiddleware)
        @post("/api/admin/tasks")
        @secured()
        async def admin_create(req, res):
            pass

        route, _ = Router.match("POST", "/api/admin/tasks")
        assert route is not None
        assert route["auth_required"] is True


# ── @noauth() still works on bare routes ─────────────────────────


class TestNoauthStillWorks:

    def test_post_with_noauth_is_public(self):
        """@noauth() on a bare POST route should remain public."""
        @post("/api/webhook")
        @noauth()
        async def webhook(req, res):
            pass

        route, _ = Router.match("POST", "/api/webhook")
        assert route is not None
        assert route["auth_required"] is False


# ── GET routes unaffected ────────────────────────────────────────


class TestGetRoutesUnaffected:

    def test_get_with_middleware_stays_public(self):
        """GET route with middleware should remain public (no change)."""
        @middleware(DummyAuthMiddleware)
        @get("/api/tasks")
        async def list_tasks(req, res):
            pass

        route, _ = Router.match("GET", "/api/tasks")
        assert route is not None
        assert route["auth_required"] is False

    def test_get_with_middleware_and_secured_requires_auth(self):
        """GET route with middleware and @secured() should require auth."""
        @middleware(DummyAuthMiddleware)
        @get("/api/admin/stats")
        @secured()
        async def admin_stats(req, res):
            pass

        route, _ = Router.match("GET", "/api/admin/stats")
        assert route is not None
        assert route["auth_required"] is True
