"""Parity Group B — signature expansions on Api, Model.find, route decorators,
swagger decorators, Response.render/cookie/__call__.

These pin the docs-friendly kwargs/overloads introduced in 3.13.0.
"""
from __future__ import annotations

import pytest


# ─── Api(__init__) ergonomic kwargs ───────────────────────────────────────


class TestApiKwargs:
    def test_bearer_token_kwarg(self):
        from tina4_python.api import Api
        api = Api("https://x.example", bearer_token="sk-test123")
        assert api.auth_header == "Bearer sk-test123"

    def test_username_password_kwargs(self):
        from tina4_python.api import Api
        api = Api("https://x.example", username="u", password="p")
        assert api.auth_header.startswith("Basic ")

    def test_headers_kwarg(self):
        from tina4_python.api import Api
        api = Api("https://x.example", headers={"X-Tenant": "acme"})
        assert api._headers["X-Tenant"] == "acme"

    def test_verify_ssl_false_disables_verification(self):
        from tina4_python.api import Api
        api = Api("https://x.example", verify_ssl=False)
        assert api._ssl_context is not None

    def test_ignore_ssl_still_works(self):
        from tina4_python.api import Api
        api = Api("https://x.example", ignore_ssl=True)
        assert api._ssl_context is not None

    def test_bearer_overrides_basic_when_both_passed(self):
        from tina4_python.api import Api
        api = Api("https://x.example", bearer_token="tok", username="u", password="p")
        assert api.auth_header.startswith("Bearer ")

    def test_no_kwargs_keeps_legacy_default(self):
        from tina4_python.api import Api
        api = Api("https://x.example")
        assert api.auth_header == ""
        assert api._headers == {}
        assert api._ssl_context is None


# ─── Model.find(pk) int overload ──────────────────────────────────────────


def _make_user_model():
    """Build a fresh User ORM model with in-memory SQLite."""
    from tina4_python.database import Database
    from tina4_python.orm import ORM, IntegerField, StringField, orm_bind

    db = Database("sqlite:///:memory:")
    orm_bind(db)

    class TestUser(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()
        email = StringField()

    TestUser().create_table()
    return TestUser, db


class TestModelFindOverload:
    def test_find_with_int_routes_to_find_by_id(self):
        TestUser, db = _make_user_model()
        try:
            u = TestUser({"name": "Alice", "email": "a@x"})
            u.save()
            loaded = TestUser.find(u.id)
            assert loaded is not None
            assert loaded.name == "Alice"
        finally:
            db.close()

    def test_find_with_int_returns_none_when_missing(self):
        TestUser, db = _make_user_model()
        try:
            assert TestUser.find(99999) is None
        finally:
            db.close()

    def test_find_with_dict_returns_list(self):
        TestUser, db = _make_user_model()
        try:
            TestUser({"name": "Alice", "email": "a@x"}).save()
            TestUser({"name": "Bob", "email": "b@x"}).save()
            users = TestUser.find({"name": "Alice"})
            assert isinstance(users, list)
            assert len(users) == 1
            assert users[0].name == "Alice"
        finally:
            db.close()

    def test_find_no_args_returns_all(self):
        TestUser, db = _make_user_model()
        try:
            TestUser({"name": "Alice", "email": "a@x"}).save()
            TestUser({"name": "Bob", "email": "b@x"}).save()
            all_users = TestUser.find()
            assert isinstance(all_users, list)
            assert len(all_users) == 2
        finally:
            db.close()

    def test_bool_is_not_treated_as_pk(self):
        """isinstance(True, int) is True in Python — explicitly exclude bools.

        We want find(True) to NOT be a PK lookup. Because bool isn't a valid
        filter dict either, we expect a TypeError-ish failure rather than
        silently treating True as the PK value 1. The important contract is
        just that bools don't get coerced into PK lookups.
        """
        TestUser, db = _make_user_model()
        try:
            TestUser({"name": "Alice", "email": "a@x"}).save()
            try:
                result = TestUser.find(True)
                # If it returned at all, must NOT be the row with id=1
                # (which would mean bool was treated as PK=1)
                assert result is None or (isinstance(result, list) and len(result) == 0)
            except (AttributeError, TypeError):
                # Acceptable — bool as filter is malformed input
                pass
        finally:
            db.close()


# ─── @description(summary, detail=, params=, query=) ──────────────────────


class TestDescriptionExpanded:
    def test_single_string_form_works(self):
        from tina4_python.swagger import description

        @description("Short summary")
        def handler(req, resp):
            return resp({"ok": True})

        assert handler._swagger_description == "Short summary"

    def test_expanded_form_with_detail_and_params(self):
        from tina4_python.swagger import description

        @description(
            "Create user",
            detail="Validates email + password strength.",
            params={"id": "URL path — user id"},
            query={"include_inactive": "bool"},
        )
        def handler(req, resp):
            return resp({})

        assert handler._swagger_description == "Create user"
        assert handler._swagger_detail == "Validates email + password strength."
        assert handler._swagger_params == {"id": "URL path — user id"}
        assert handler._swagger_query == {"include_inactive": "bool"}


# ─── @tags(str | list) ────────────────────────────────────────────────────


class TestTagsAcceptsBoth:
    def test_list_form_works(self):
        from tina4_python.swagger import tags

        @tags(["users", "admin"])
        def handler(req, resp):
            return resp({})

        assert handler._swagger_tags == ["users", "admin"]

    def test_string_form_works(self):
        from tina4_python.swagger import tags

        @tags("users")
        def handler(req, resp):
            return resp({})

        assert handler._swagger_tags == ["users"]


# ─── @example_response with status code ───────────────────────────────────


class TestExampleResponseStatus:
    def test_two_arg_form_status_first(self):
        from tina4_python.swagger import example_response

        @example_response(201, {"id": 1, "name": "Alice"})
        def handler(req, resp):
            return resp({})

        assert handler._swagger_example_responses[201] == {"id": 1, "name": "Alice"}

    def test_one_arg_form_defaults_to_200(self):
        from tina4_python.swagger import example_response

        @example_response({"id": 1})
        def handler(req, resp):
            return resp({})

        assert handler._swagger_example_responses[200] == {"id": 1}

    def test_multiple_decorators_accumulate(self):
        from tina4_python.swagger import example_response

        @example_response(200, {"ok": True})
        @example_response(404, {"error": "not found"})
        def handler(req, resp):
            return resp({})

        assert 200 in handler._swagger_example_responses
        assert 404 in handler._swagger_example_responses
        assert handler._swagger_example_responses[404] == {"error": "not found"}


# ─── Response.render(template, data, status_code) ─────────────────────────


def _make_response():
    from tina4_python.core.response import Response
    return Response()


class TestResponseRenderStatusCode:
    def test_render_with_status_code_arg(self, tmp_path, monkeypatch):
        from tina4_python.frond import Frond
        from tina4_python.core.response import set_frond, Response

        # Set up a Frond engine with a temp template dir
        (tmp_path / "404.twig").write_text("<h1>Not Found</h1>")
        engine = Frond(template_dir=str(tmp_path))
        set_frond(engine)

        response = Response()
        result = response.render("404.twig", {}, 404)
        assert result.status_code == 404
        assert b"Not Found" in result.content


# ─── Response.cookie() dict-options form ──────────────────────────────────


class TestResponseCookieDictOptions:
    def test_kwarg_form_still_works(self):
        r = _make_response()
        r.cookie("session", "tok", max_age=7200, http_only=True)
        assert any("session=tok" in c for c in r._cookies)
        assert any("Max-Age=7200" in c for c in r._cookies)
        assert any("HttpOnly" in c for c in r._cookies)

    def test_dict_options_form(self):
        r = _make_response()
        r.cookie("session", "tok", {"max_age": 600, "secure": True, "http_only": False})
        cookie = r._cookies[0]
        assert "session=tok" in cookie
        assert "Max-Age=600" in cookie
        assert "Secure" in cookie
        assert "HttpOnly" not in cookie

    def test_explicit_kwarg_overrides_dict(self):
        r = _make_response()
        r.cookie("session", "tok", {"max_age": 600}, max_age=999)
        assert any("Max-Age=999" in c for c in r._cookies)


# ─── Response(headers={...}) one-shot kwargs ──────────────────────────────


class TestResponseCallableHeaders:
    def test_headers_kwarg_adds_response_headers(self):
        r = _make_response()
        r({"ok": True}, headers={"X-Tenant": "acme", "X-Trace-Id": "abc123"})
        assert ("X-Tenant", "acme") in r._headers
        assert ("X-Trace-Id", "abc123") in r._headers

    def test_omitted_headers_no_op(self):
        r = _make_response()
        r({"ok": True})
        assert r._headers == []


# ─── @get(path, description=, middleware=[...]) kwargs ────────────────────


class TestRouteDecoratorKwargs:
    def test_description_kwarg_sets_swagger_attr(self):
        from tina4_python.core.router import get, Router

        # Use a unique path to avoid colliding with the global router
        @get("/test-parity-b-description", description="Test endpoint")
        async def handler(req, resp):
            return resp({})

        assert handler._swagger_description == "Test endpoint"

    def test_middleware_kwarg_string_form(self):
        from tina4_python.core.router import get

        @get("/test-parity-b-mw-string", middleware=["ResponseCache"])
        async def handler(req, resp):
            return resp({})

        # The middleware list should have been resolved to the class/instance
        assert len(handler._middleware) == 1

    def test_middleware_kwarg_with_arg(self):
        from tina4_python.core.router import get

        @get("/test-parity-b-mw-string-arg", middleware=["ResponseCache:120"])
        async def handler(req, resp):
            return resp({})

        # Instantiated form
        assert len(handler._middleware) == 1

    def test_middleware_kwarg_unknown_name_raises(self):
        from tina4_python.core.router import get

        with pytest.raises(ValueError, match="Unknown middleware"):
            @get("/test-parity-b-mw-unknown", middleware=["NonexistentMW"])
            async def handler(req, resp):
                return resp({})

    def test_class_form_still_works(self):
        from tina4_python.core.router import get
        from tina4_python.cache import ResponseCache

        @get("/test-parity-b-mw-class", middleware=[ResponseCache])
        async def handler(req, resp):
            return resp({})

        assert handler._middleware == [ResponseCache]
