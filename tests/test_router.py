# Tests for tina4_python.core.router (v3)
import pytest
from tina4_python.core.router import Router, get, post, put, patch, delete, _compile_pattern


@pytest.fixture(autouse=True)
def clear_routes():
    Router.clear()
    yield
    Router.clear()


class TestPatternCompilation:

    def test_exact_match(self):
        pattern, params = _compile_pattern("/api/users")
        assert pattern.match("/api/users")
        assert pattern.match("/api/users/")
        assert params == []

    def test_single_param(self):
        pattern, params = _compile_pattern("/api/users/{id}")
        m = pattern.match("/api/users/42")
        assert m and m.group(1) == "42"
        assert params == ["id"]

    def test_multiple_params(self):
        pattern, params = _compile_pattern("/api/posts/{post_id}/comments/{comment_id}")
        m = pattern.match("/api/posts/5/comments/12")
        assert m and m.group(1) == "5" and m.group(2) == "12"

    def test_int_param(self):
        pattern, _ = _compile_pattern("/api/users/{id:int}")
        assert pattern.match("/api/users/42")
        assert not pattern.match("/api/users/abc")

    def test_path_param(self):
        pattern, _ = _compile_pattern("/files/{path:path}")
        m = pattern.match("/files/docs/readme.md")
        assert m and m.group(1) == "docs/readme.md"

    def test_no_match_different_path(self):
        pattern, _ = _compile_pattern("/api/users")
        assert not pattern.match("/api/products")

    def test_no_match_extra_segments(self):
        pattern, _ = _compile_pattern("/api/users")
        assert not pattern.match("/api/users/extra")


class TestRouterRegistration:

    def test_register_get(self):
        @get("/api/test")
        async def handler(req, res): pass
        routes = Router.get_routes()
        assert any(r["path"] == "/api/test" and r["method"] == "GET" for r in routes)

    def test_register_post(self):
        @post("/api/test")
        async def handler(req, res): pass
        route, _ = Router.match("POST", "/api/test")
        assert route is not None

    def test_register_put_with_params(self):
        @put("/api/test/{id}")
        async def handler(req, res): pass
        route, params = Router.match("PUT", "/api/test/42")
        assert route is not None
        assert params["id"] == "42"

    def test_register_delete(self):
        @delete("/api/test/{id}")
        async def handler(req, res): pass
        route, _ = Router.match("DELETE", "/api/test/1")
        assert route is not None

    def test_match_correct_method(self):
        @get("/api/data")
        async def get_handler(req, res): pass
        @post("/api/data")
        async def post_handler(req, res): pass
        route_get, _ = Router.match("GET", "/api/data")
        route_post, _ = Router.match("POST", "/api/data")
        assert route_get["handler"] is get_handler
        assert route_post["handler"] is post_handler

    def test_no_match_returns_none(self):
        route, params = Router.match("GET", "/nonexistent")
        assert route is None
        assert params == {}

    def test_wrong_method_no_match(self):
        @get("/api/only-get")
        async def handler(req, res): pass
        route, _ = Router.match("POST", "/api/only-get")
        assert route is None

    def test_register_patch(self):
        @patch("/api/test/{id}")
        async def handler(req, res): pass
        route, params = Router.match("PATCH", "/api/test/7")
        assert route is not None
        assert params["id"] == "7"

    def test_all_returns_routes(self):
        @get("/one")
        async def h1(req, res): pass
        @post("/two")
        async def h2(req, res): pass
        routes = Router.get_routes()
        assert len(routes) == 2
        paths = [r["path"] for r in routes]
        assert "/one" in paths
        assert "/two" in paths

    def test_clear_removes_all(self):
        @get("/will-be-cleared")
        async def handler(req, res): pass
        assert len(Router.get_routes()) > 0
        Router.clear()
        assert len(Router.get_routes()) == 0


class TestAnyMethod:

    def test_any_matches_get(self):
        from tina4_python.core.router import any_method
        @any_method("/wildcard")
        async def handler(req, res): pass
        route, _ = Router.match("GET", "/wildcard")
        assert route is not None

    def test_any_matches_post(self):
        from tina4_python.core.router import any_method
        @any_method("/wildcard2")
        async def handler(req, res): pass
        route, _ = Router.match("POST", "/wildcard2")
        assert route is not None

    def test_any_matches_delete(self):
        from tina4_python.core.router import any_method
        @any_method("/wildcard3")
        async def handler(req, res): pass
        route, _ = Router.match("DELETE", "/wildcard3")
        assert route is not None

    def test_any_matches_put(self):
        from tina4_python.core.router import any_method
        @any_method("/wildcard4")
        async def handler(req, res): pass
        route, _ = Router.match("PUT", "/wildcard4")
        assert route is not None

    def test_any_matches_patch(self):
        from tina4_python.core.router import any_method
        @any_method("/wildcard5")
        async def handler(req, res): pass
        route, _ = Router.match("PATCH", "/wildcard5")
        assert route is not None


class TestPatternEdgeCases:

    def test_float_param(self):
        pattern, params = _compile_pattern("/api/price/{amount:float}")
        m = pattern.match("/api/price/19.99")
        assert m and m.group(1) == "19.99"
        assert params == ["amount"]

    def test_float_param_rejects_alpha(self):
        pattern, _ = _compile_pattern("/api/price/{amount:float}")
        assert not pattern.match("/api/price/abc")

    def test_trailing_slash_optional(self):
        pattern, _ = _compile_pattern("/api/test")
        assert pattern.match("/api/test")
        assert pattern.match("/api/test/")

    def test_root_path(self):
        pattern, _ = _compile_pattern("/")
        assert pattern.match("/")

    def test_unknown_type_hint_treated_as_segment(self):
        pattern, params = _compile_pattern("/api/{id:uuid}")
        m = pattern.match("/api/550e8400-e29b-41d4-a716-446655440000")
        assert m is not None
        assert params == ["id"]


class TestAuthDecorators:

    def test_get_is_public_by_default(self):
        @get("/public-get")
        async def handler(req, res): pass
        route, _ = Router.match("GET", "/public-get")
        assert route["auth_required"] is False

    def test_post_requires_auth_by_default(self):
        @post("/secure-post")
        async def handler(req, res): pass
        route, _ = Router.match("POST", "/secure-post")
        assert route["auth_required"] is True

    def test_put_requires_auth_by_default(self):
        @put("/secure-put")
        async def handler(req, res): pass
        route, _ = Router.match("PUT", "/secure-put")
        assert route["auth_required"] is True

    def test_delete_requires_auth_by_default(self):
        @delete("/secure-delete")
        async def handler(req, res): pass
        route, _ = Router.match("DELETE", "/secure-delete")
        assert route["auth_required"] is True

    def test_noauth_makes_post_public(self):
        from tina4_python.core.router import noauth
        @post("/public-post")
        @noauth()
        async def handler(req, res): pass
        route, _ = Router.match("POST", "/public-post")
        assert route["auth_required"] is False

    def test_secured_makes_get_protected(self):
        from tina4_python.core.router import secured
        @get("/protected-get")
        @secured()
        async def handler(req, res): pass
        route, _ = Router.match("GET", "/protected-get")
        assert route["auth_required"] is True


class TestMiddlewareAndCaching:

    def test_middleware_decorator(self):
        from tina4_python.core.router import middleware as mw_decorator

        class MyMiddleware:
            pass

        @mw_decorator(MyMiddleware)
        @get("/mw-test")
        async def handler(req, res): pass
        route, _ = Router.match("GET", "/mw-test")
        assert MyMiddleware in route["handler"]._middleware

    def test_cached_decorator(self):
        from tina4_python.core.router import cached

        @cached(max_age=120)
        @get("/cached-test")
        async def handler(req, res): pass
        assert handler._cached is True
        assert handler._cache_max_age == 120
