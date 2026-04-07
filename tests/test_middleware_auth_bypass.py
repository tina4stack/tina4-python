# Tests for middleware-skips-auth behaviour.
#
# When a route has custom middleware, the built-in Bearer token auth gate
# is skipped — the developer's middleware handles auth. This allows
# OAuth cookie-based sessions and other non-Bearer auth patterns.
#
# Use @secured() to explicitly re-enable the built-in gate on routes
# that have middleware.
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


# ── Write routes with middleware skip built-in auth ──────────────


class TestMiddlewareSkipsBuiltinAuth:

    def test_post_with_middleware_skips_auth(self):
        """POST route with custom middleware should NOT require built-in auth."""
        @middleware(DummyAuthMiddleware)
        @post("/api/tasks")
        async def create_task(req, res):
            pass

        route, _ = Router.match("POST", "/api/tasks")
        assert route is not None
        assert route["auth_required"] is False

    def test_put_with_middleware_skips_auth(self):
        """PUT route with custom middleware should NOT require built-in auth."""
        @middleware(DummyAuthMiddleware)
        @put("/api/tasks/{id}")
        async def update_task(req, res):
            pass

        route, _ = Router.match("PUT", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is False

    def test_patch_with_middleware_skips_auth(self):
        """PATCH route with custom middleware should NOT require built-in auth."""
        @middleware(DummyAuthMiddleware)
        @patch("/api/tasks/{id}")
        async def patch_task(req, res):
            pass

        route, _ = Router.match("PATCH", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is False

    def test_delete_with_middleware_skips_auth(self):
        """DELETE route with custom middleware should NOT require built-in auth."""
        @middleware(DummyAuthMiddleware)
        @delete("/api/tasks/{id}")
        async def delete_task(req, res):
            pass

        route, _ = Router.match("DELETE", "/api/tasks/1")
        assert route is not None
        assert route["auth_required"] is False


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
