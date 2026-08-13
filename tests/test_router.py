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
        pattern, params, _ = _compile_pattern("/api/users")
        assert pattern.match("/api/users")
        assert pattern.match("/api/users/")
        assert params == []

    def test_single_param(self):
        pattern, params, _ = _compile_pattern("/api/users/{id}")
        m = pattern.match("/api/users/42")
        assert m and m.group(1) == "42"
        assert params == ["id"]

    def test_multiple_params(self):
        pattern, params, _ = _compile_pattern("/api/posts/{post_id}/comments/{comment_id}")
        m = pattern.match("/api/posts/5/comments/12")
        assert m and m.group(1) == "5" and m.group(2) == "12"

    def test_int_param(self):
        pattern, _, _ = _compile_pattern("/api/users/{id:int}")
        assert pattern.match("/api/users/42")
        assert not pattern.match("/api/users/abc")

    def test_path_param(self):
        pattern, _, _ = _compile_pattern("/files/{path:path}")
        m = pattern.match("/files/docs/readme.md")
        assert m and m.group(1) == "docs/readme.md"

    def test_no_match_different_path(self):
        pattern, _, _ = _compile_pattern("/api/users")
        assert not pattern.match("/api/products")

    def test_no_match_extra_segments(self):
        pattern, _, _ = _compile_pattern("/api/users")
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
        pattern, params, _ = _compile_pattern("/api/price/{amount:float}")
        m = pattern.match("/api/price/19.99")
        assert m and m.group(1) == "19.99"
        assert params == ["amount"]

    def test_float_param_rejects_alpha(self):
        pattern, _, _ = _compile_pattern("/api/price/{amount:float}")
        assert not pattern.match("/api/price/abc")

    def test_trailing_slash_optional(self):
        pattern, _, _ = _compile_pattern("/api/test")
        assert pattern.match("/api/test")
        assert pattern.match("/api/test/")

    def test_root_path(self):
        pattern, _, _ = _compile_pattern("/")
        assert pattern.match("/")

    def test_uuid_param_matches_valid_uuid(self):
        pattern, params, _ = _compile_pattern("/api/{id:uuid}")
        m = pattern.match("/api/550e8400-e29b-41d4-a716-446655440000")
        assert m is not None
        assert params == ["id"]

    def test_uuid_param_rejects_non_uuid(self):
        pattern, _, _ = _compile_pattern("/api/{id:uuid}")
        assert pattern.match("/api/not-a-uuid") is None
        assert pattern.match("/api/123") is None

    def test_alpha_param_matches_letters_only(self):
        pattern, params, _ = _compile_pattern("/api/{name:alpha}")
        assert pattern.match("/api/alice") is not None
        assert pattern.match("/api/Alice") is not None
        assert params == ["name"]

    def test_alpha_param_rejects_digits(self):
        # fixes tina4-book#125 — developer expectation: :alpha = letters only
        pattern, _, _ = _compile_pattern("/api/{name:alpha}")
        assert pattern.match("/api/alice123") is None
        assert pattern.match("/api/123") is None
        assert pattern.match("/api/alice-bob") is None  # hyphen rejected

    def test_alnum_param_matches_letters_and_digits(self):
        pattern, _, _ = _compile_pattern("/api/{code:alnum}")
        assert pattern.match("/api/abc123") is not None
        assert pattern.match("/api/ABC") is not None
        assert pattern.match("/api/123") is not None

    def test_alnum_param_rejects_punctuation(self):
        pattern, _, _ = _compile_pattern("/api/{code:alnum}")
        assert pattern.match("/api/abc-123") is None
        assert pattern.match("/api/abc.123") is None

    def test_slug_param_matches_urlsafe_slug(self):
        pattern, _, _ = _compile_pattern("/posts/{slug:slug}")
        assert pattern.match("/posts/hello-world") is not None
        assert pattern.match("/posts/post-123") is not None
        assert pattern.match("/posts/a") is not None

    def test_slug_param_rejects_uppercase_and_underscore(self):
        pattern, _, _ = _compile_pattern("/posts/{slug:slug}")
        assert pattern.match("/posts/Hello-World") is None   # uppercase rejected
        assert pattern.match("/posts/hello_world") is None   # underscore rejected
        assert pattern.match("/posts/hello world") is None   # space rejected

    def test_explicit_string_type_matches_default(self):
        """``{name:string}`` should behave identically to ``{name}``."""
        explicit, _, _ = _compile_pattern("/users/{name:string}")
        implicit, _, _ = _compile_pattern("/users/{name}")
        assert explicit.match("/users/alice") is not None
        assert implicit.match("/users/alice") is not None
        assert explicit.match("/users/alice").groups() == implicit.match("/users/alice").groups()

    def test_unknown_type_raises_at_registration(self):
        """Typos like ``:inetger`` or unsupported types like ``:word`` must
        raise at route registration so the developer sees the error at boot —
        not silently fall through to the default matcher (tina4-book#125)."""
        with pytest.raises(ValueError, match="Unknown param type"):
            _compile_pattern("/api/{id:inetger}")
        with pytest.raises(ValueError, match="Unknown param type"):
            _compile_pattern("/api/{name:word}")
        with pytest.raises(ValueError, match="Unknown param type"):
            _compile_pattern("/api/{name:str}")  # the one from #125


class TestTypedParamCoercion:
    """Typed path params arrive coerced to Python scalars (parity with Ruby
    ``cast_param`` in lib/tina4/router.rb). ``{id:int}`` → ``int``,
    ``{price:float}`` → ``float``; every other type and untyped ``{id}`` stay
    ``str``. URL matching is unchanged — coercion happens after the regex,
    when ``Router.match`` builds the params dict, so BOTH ``request.param``
    and the positional handler arg are typed."""

    def test_int_param_is_coerced_to_int(self):
        @get("/coerce/items/{id:int}")
        async def handler(req, res): pass
        route, params = Router.match("GET", "/coerce/items/42")
        assert route is not None
        assert params["id"] == 42
        assert isinstance(params["id"], int)

    def test_integer_alias_is_coerced_to_int(self):
        @get("/coerce/users/{uid:integer}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/users/7")
        assert params["uid"] == 7
        assert isinstance(params["uid"], int)

    def test_float_param_is_coerced_to_float(self):
        @get("/coerce/price/{price:float}")
        async def handler(req, res): pass
        route, params = Router.match("GET", "/coerce/price/19.99")
        assert route is not None
        assert params["price"] == 19.99
        assert isinstance(params["price"], float)

    def test_number_alias_is_coerced_to_float(self):
        @get("/coerce/amount/{amt:number}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/amount/3.5")
        assert params["amt"] == 3.5
        assert isinstance(params["amt"], float)

    def test_untyped_param_stays_str(self):
        @get("/coerce/raw/{id}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/raw/42")
        assert params["id"] == "42"
        assert isinstance(params["id"], str)

    def test_non_castable_types_stay_str(self):
        # slug/alpha/alnum/uuid/path are never coerced — they stay strings
        @get("/coerce/posts/{slug:slug}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/posts/hello-world")
        assert params["slug"] == "hello-world"
        assert isinstance(params["slug"], str)

    def test_non_numeric_path_still_404s(self):
        # URL-matching behaviour is unchanged: {id:int} still only matches
        # digits, so a non-numeric segment yields no route (404 at dispatch).
        @get("/coerce/strict/{id:int}")
        async def handler(req, res): pass
        route, params = Router.match("GET", "/coerce/strict/abc")
        assert route is None
        assert params == {}

    def test_mixed_typed_and_untyped_in_one_route(self):
        @get("/coerce/{category}/{id:int}/{price:float}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/widgets/42/9.5")
        assert params["category"] == "widgets" and isinstance(params["category"], str)
        assert params["id"] == 42 and isinstance(params["id"], int)
        assert params["price"] == 9.5 and isinstance(params["price"], float)

    def test_request_param_sees_coerced_value(self):
        # The coerced value flows through to request.param() too — Router.match
        # feeds request._route_params, which param() reads.
        from tina4_python.core.request import Request

        @get("/coerce/req/{id:int}")
        async def handler(req, res): pass
        _, params = Router.match("GET", "/coerce/req/99")
        req = Request()
        req._route_params = params
        req.attach_route_params()
        assert req.param("id") == 99
        assert isinstance(req.param("id"), int)


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
