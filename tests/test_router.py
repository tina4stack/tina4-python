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
        routes = Router.all()
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
