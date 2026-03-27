# Tests for POST route protection — verifying auth defaults on route registration.
#
# Tina4 v3 auth convention:
#   - GET routes are public by default
#   - POST/PUT/PATCH/DELETE require auth by default
#   - @noauth() makes a write route public
#   - @secured() makes a GET route require auth
#
# Decorator order (outermost -> innermost):
#   Route decorator (@get, @post, etc.) must be outermost so it sees
#   the _noauth/_secured attribute set by the innermost decorator.
import pytest
from tina4_python.core.router import (
    Router, get, post, put, patch, delete, noauth, secured,
)


@pytest.fixture(autouse=True)
def clear_routes():
    Router.clear()
    yield
    Router.clear()


# ── POST route requires auth by default ──────────────────────────


class TestPostRequiresAuth:

    def test_post_route_auth_required_by_default(self):
        @post("/api/items")
        async def create_item(req, res):
            pass

        route, _ = Router.match("POST", "/api/items")
        assert route is not None
        assert route["auth_required"] is True

    def test_post_route_with_noauth_is_public(self):
        @post("/api/webhook")
        @noauth()
        async def webhook(req, res):
            pass

        route, _ = Router.match("POST", "/api/webhook")
        assert route is not None
        assert route["auth_required"] is False


# ── GET route is public by default ────────────────────────────────


class TestGetIsPublic:

    def test_get_route_public_by_default(self):
        @get("/api/items")
        async def list_items(req, res):
            pass

        route, _ = Router.match("GET", "/api/items")
        assert route is not None
        assert route["auth_required"] is False

    def test_get_route_with_secured_requires_auth(self):
        @get("/api/admin/stats")
        @secured()
        async def admin_stats(req, res):
            pass

        route, _ = Router.match("GET", "/api/admin/stats")
        assert route is not None
        assert route["auth_required"] is True


# ── PUT/PATCH/DELETE also require auth ────────────────────────────


class TestWriteMethodsRequireAuth:

    def test_put_requires_auth(self):
        @put("/api/items/{id}")
        async def update_item(req, res):
            pass

        route, _ = Router.match("PUT", "/api/items/1")
        assert route is not None
        assert route["auth_required"] is True

    def test_patch_requires_auth(self):
        @patch("/api/items/{id}")
        async def patch_item(req, res):
            pass

        route, _ = Router.match("PATCH", "/api/items/1")
        assert route is not None
        assert route["auth_required"] is True

    def test_delete_requires_auth(self):
        @delete("/api/items/{id}")
        async def delete_item(req, res):
            pass

        route, _ = Router.match("DELETE", "/api/items/1")
        assert route is not None
        assert route["auth_required"] is True


# ── @noauth() on PUT/PATCH/DELETE ─────────────────────────────────


class TestNoauthOnWriteMethods:

    def test_put_with_noauth(self):
        @put("/api/public-update")
        @noauth()
        async def public_update(req, res):
            pass

        route, _ = Router.match("PUT", "/api/public-update")
        assert route is not None
        assert route["auth_required"] is False

    def test_patch_with_noauth(self):
        @patch("/api/public-patch")
        @noauth()
        async def public_patch(req, res):
            pass

        route, _ = Router.match("PATCH", "/api/public-patch")
        assert route is not None
        assert route["auth_required"] is False

    def test_delete_with_noauth(self):
        @delete("/api/public-delete")
        @noauth()
        async def public_delete(req, res):
            pass

        route, _ = Router.match("DELETE", "/api/public-delete")
        assert route is not None
        assert route["auth_required"] is False


# ── Explicit auth_required override ───────────────────────────────


class TestExplicitAuthOverride:

    def test_get_with_explicit_auth_required_true(self):
        @get("/api/secret", auth_required=True)
        async def secret_get(req, res):
            pass

        route, _ = Router.match("GET", "/api/secret")
        assert route is not None
        assert route["auth_required"] is True

    def test_post_with_explicit_auth_required_false(self):
        @post("/api/open", auth_required=False)
        async def open_post(req, res):
            pass

        route, _ = Router.match("POST", "/api/open")
        assert route is not None
        assert route["auth_required"] is False


# ── Multiple routes coexist ───────────────────────────────────────


class TestMultipleRoutes:

    def test_get_and_post_on_same_path(self):
        @get("/api/items")
        async def list_items(req, res):
            pass

        @post("/api/items")
        async def create_item(req, res):
            pass

        get_route, _ = Router.match("GET", "/api/items")
        post_route, _ = Router.match("POST", "/api/items")

        assert get_route is not None
        assert post_route is not None
        assert get_route["auth_required"] is False
        assert post_route["auth_required"] is True

    def test_mixed_auth_decorators(self):
        @get("/api/admin/users")
        @secured()
        async def admin_users(req, res):
            pass

        @post("/api/webhook")
        @noauth()
        async def webhook(req, res):
            pass

        @post("/api/users")
        async def create_user(req, res):
            pass

        admin_route, _ = Router.match("GET", "/api/admin/users")
        webhook_route, _ = Router.match("POST", "/api/webhook")
        user_route, _ = Router.match("POST", "/api/users")

        assert admin_route["auth_required"] is True
        assert webhook_route["auth_required"] is False
        assert user_route["auth_required"] is True


# ── Secure-by-default enforcement ────────────────────────────────
#
# These tests verify that auth_required on the route dict means a
# request without proper auth would be rejected at dispatch time.
# We test the route metadata that the server uses to enforce auth.


class TestSecureByDefaultEnforcement:

    def test_post_without_bearer_is_auth_required(self):
        """POST route requires auth by default — no Bearer means 401 at dispatch."""
        @post("/api/protected-post")
        async def protected_post(req, res):
            pass

        route, _ = Router.match("POST", "/api/protected-post")
        assert route is not None
        assert route["auth_required"] is True

    def test_post_route_auth_flag_allows_bearer(self):
        """POST with auth_required=True allows requests that carry a valid Bearer."""
        @post("/api/authed-post")
        async def authed_post(req, res):
            pass

        route, _ = Router.match("POST", "/api/authed-post")
        assert route is not None
        # The route is auth-gated; a valid Bearer would pass at dispatch
        assert route["auth_required"] is True

    def test_post_with_noauth_allows_unauthenticated(self):
        """@noauth() on POST sets auth_required=False — no token needed."""
        @post("/api/public-hook")
        @noauth()
        async def public_hook(req, res):
            pass

        route, _ = Router.match("POST", "/api/public-hook")
        assert route is not None
        assert route["auth_required"] is False

    def test_get_with_secured_requires_auth(self):
        """GET with @secured() sets auth_required=True — no Bearer means 401."""
        @get("/api/locked-get")
        @secured()
        async def locked_get(req, res):
            pass

        route, _ = Router.match("GET", "/api/locked-get")
        assert route is not None
        assert route["auth_required"] is True

    def test_get_without_secured_is_public(self):
        """Plain GET route is public — auth_required=False."""
        @get("/api/open-get")
        async def open_get(req, res):
            pass

        route, _ = Router.match("GET", "/api/open-get")
        assert route is not None
        assert route["auth_required"] is False
