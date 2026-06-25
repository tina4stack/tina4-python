"""Tests for middleware behaviour reported in tina4-book#141.

Covers PY-10-01 (function-based middleware now runs), PY-10-02
(@middleware no longer disables auth_required), and PY-10-03
(request.headers is case-insensitive). Same contract is mirrored in
tina4-php, tina4-ruby, tina4-nodejs.
"""
import asyncio

import pytest

from tina4_python.core.request import CaseInsensitiveDict, Request
from tina4_python.core.response import Response
from tina4_python.core.router import (
    Router, get, post, middleware, noauth, secured,
)
from tina4_python.core.server import (
    _invoke_handler_with_middleware,
    _is_function_middleware,
    _run_before_middleware,
)


# ────────────────────────────────────────────────────────────────────
# PY-10-02 — @middleware must NOT disable auth_required
# ────────────────────────────────────────────────────────────────────


class TestMiddlewareDoesNotDisableAuth:
    def setup_method(self):
        Router.clear()

    def test_post_route_with_middleware_still_requires_auth(self):
        """Reporter's exact scenario — adding custom middleware to a write
        route must leave the framework's built-in Bearer-token gate in place.

        Before the fix, applying @middleware() flipped auth_required=False
        silently, opening an admin endpoint to unauthenticated callers."""
        class NoopMw:
            @staticmethod
            def before_log(req, resp):
                return req, resp

        @middleware(NoopMw)
        @post("/admin/api-keys")
        async def create_key(req, resp):
            return resp.json({"created": True})

        route = create_key._route_ref._route
        assert route["auth_required"] is True, \
            "@middleware() must not disable the default auth gate on write routes"

    def test_noauth_above_middleware_still_opens_route(self):
        """@noauth() is the documented way to open a write route. It must
        keep working when @middleware() is also applied."""
        class NoopMw:
            @staticmethod
            def before_log(req, resp):
                return req, resp

        @noauth()
        @middleware(NoopMw)
        @post("/api/webhook")
        async def webhook(req, resp):
            return resp.json({"ok": True})

        route = webhook._route_ref._route
        assert route["auth_required"] is False

    def test_secured_above_middleware_locks_get_route(self):
        """@secured() is the documented way to lock a read route. Still works
        when @middleware() is applied."""
        class NoopMw:
            @staticmethod
            def before_log(req, resp):
                return req, resp

        @secured()
        @middleware(NoopMw)
        @get("/api/admin/stats")
        async def admin_stats(req, resp):
            return resp.json({"secret": True})

        route = admin_stats._route_ref._route
        assert route["auth_required"] is True


# ────────────────────────────────────────────────────────────────────
# PY-10-03 — request.headers case-insensitive lookup
# ────────────────────────────────────────────────────────────────────


class TestCaseInsensitiveHeaders:
    def test_mixed_case_lookup(self):
        d = CaseInsensitiveDict()
        d["content-type"] = "application/json"
        # Every casing returns the value:
        assert d["Content-Type"] == "application/json"
        assert d["CONTENT-TYPE"] == "application/json"
        assert d.get("Content-type") == "application/json"
        assert d.get("content-type") == "application/json"

    def test_mixed_case_write_normalises_storage(self):
        d = CaseInsensitiveDict()
        d["X-API-Key"] = "secret123"
        # Stored as the lowercase form internally.
        assert "x-api-key" in d
        assert "X-API-Key" in d  # also reports membership via lookup norm
        assert d.get("x-api-key") == "secret123"

    def test_in_operator_case_insensitive(self):
        d = CaseInsensitiveDict({"Authorization": "Bearer abc"})
        assert "Authorization" in d
        assert "authorization" in d
        assert "AUTHORIZATION" in d
        assert "X-Missing" not in d

    def test_request_headers_use_case_insensitive_dict(self):
        """The 6 examples in chapter 10 used mixed case and silently broke.
        Now they work. Reporter's exact scenario."""
        scope = {
            "method": "POST",
            "path": "/api/widgets",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-api-key", b"key-abc-123"),
                (b"authorization", b"Bearer token-xyz"),
                (b"user-agent", b"Mozilla/5.0"),
            ],
            "scheme": "http",
        }
        req = Request.from_scope(scope, body=b"")
        # Every chapter-10 lookup pattern returns the value:
        assert req.headers.get("Content-Type") == "application/json"
        assert req.headers.get("content-type") == "application/json"
        assert req.headers.get("X-API-Key") == "key-abc-123"
        assert req.headers.get("Authorization") == "Bearer token-xyz"
        assert req.headers.get("User-Agent") == "Mozilla/5.0"

    def test_get_returns_default_for_missing_key(self):
        d = CaseInsensitiveDict({"foo": "bar"})
        assert d.get("X-Missing", "fallback") == "fallback"

    def test_delete_is_case_insensitive(self):
        d = CaseInsensitiveDict({"Content-Type": "text/html"})
        del d["content-TYPE"]
        assert "Content-Type" not in d

    def test_pop_is_case_insensitive(self):
        d = CaseInsensitiveDict({"Content-Type": "text/html"})
        assert d.pop("CONTENT-TYPE") == "text/html"
        assert "content-type" not in d


# ────────────────────────────────────────────────────────────────────
# PY-10-01 — function-based middleware now runs
# ────────────────────────────────────────────────────────────────────


class TestFunctionMiddleware:
    def setup_method(self):
        Router.clear()

    def test_function_middleware_is_recognised(self):
        async def my_mw(req, resp, next_handler):
            return await next_handler(req, resp)

        class ClassMw:
            @staticmethod
            def before_x(req, resp):
                return req, resp

        assert _is_function_middleware(my_mw) is True
        assert _is_function_middleware(ClassMw) is False
        # A 2-arg callable is NOT function-style (it would be a legacy
        # before-only style — currently unsupported).
        async def two_arg(req, resp):
            return req, resp
        assert _is_function_middleware(two_arg) is False

    def test_function_middleware_body_runs(self):
        """Before the fix, the body of an `async def(req, resp, next_handler)`
        never executed because the dispatcher walked dir() looking for
        before_* attrs and found none. Now it runs."""
        trace = []

        async def fn_mw(req, resp, next_handler):
            trace.append("before")
            result = await next_handler(req, resp)
            trace.append("after")
            return result

        async def handler(req, resp):
            trace.append("handler")
            return resp.json({"ok": True})

        route = {
            "handler": handler,
            "middleware": [fn_mw],
        }

        req = _make_request()
        resp = Response()

        async def run():
            return await _invoke_handler_with_middleware(req, resp, route, {})

        asyncio.run(run())

        assert trace == ["before", "handler", "after"], \
            f"function middleware must wrap the handler; got {trace}"

    def test_function_middleware_chain_order(self):
        """Multiple function middlewares form a Russian-doll chain — first
        declared is outermost."""
        trace = []

        async def outer(req, resp, next_handler):
            trace.append("outer.before")
            result = await next_handler(req, resp)
            trace.append("outer.after")
            return result

        async def inner(req, resp, next_handler):
            trace.append("inner.before")
            result = await next_handler(req, resp)
            trace.append("inner.after")
            return result

        async def handler(req, resp):
            trace.append("handler")
            return resp.json({"ok": True})

        route = {"handler": handler, "middleware": [outer, inner]}
        req = _make_request()
        resp = Response()

        async def run():
            return await _invoke_handler_with_middleware(req, resp, route, {})

        asyncio.run(run())

        assert trace == [
            "outer.before",
            "inner.before",
            "handler",
            "inner.after",
            "outer.after",
        ], f"middleware chain order broken: {trace}"

    def test_function_middleware_can_short_circuit(self):
        """A function middleware that does NOT call next_handler must
        short-circuit the chain — the handler does not run."""
        trace = []

        async def gate(req, resp, next_handler):
            trace.append("gate")
            return resp.json({"blocked": True}, 403)
            # Note: no next_handler call

        async def handler(req, resp):
            trace.append("handler-should-not-run")
            return resp.json({"ok": True})

        route = {"handler": handler, "middleware": [gate]}
        req = _make_request()
        resp = Response()

        async def run():
            return await _invoke_handler_with_middleware(req, resp, route, {})

        asyncio.run(run())

        assert trace == ["gate"], \
            f"short-circuit failed; handler ran: {trace}"

    def test_class_middleware_unchanged_by_function_dispatch(self):
        """Existing class-based middleware with before_*/after_* methods
        must still run via the class dispatcher."""
        trace = []

        class ClassMw:
            @staticmethod
            def before_log(req, resp):
                trace.append("class.before_log")
                return req, resp

            @staticmethod
            def after_log(req, resp):
                trace.append("class.after_log")
                return req, resp

        req = _make_request()
        resp = Response()
        route = {"handler": None, "middleware": [ClassMw]}

        # _run_before_middleware should still dispatch the before_log method:
        _, _, _ = _run_before_middleware(req, resp, route)
        assert "class.before_log" in trace

    def test_function_middleware_skipped_by_class_dispatcher(self):
        """A function-style middleware must NOT trigger the class
        dispatcher — otherwise dir() would scan its dunders and might
        accidentally match (defensive guard)."""
        async def fn_mw(req, resp, next_handler):
            return await next_handler(req, resp)

        req = _make_request()
        resp = Response()
        route = {"handler": None, "middleware": [fn_mw]}

        # Should not raise — function mw is silently skipped.
        out_req, out_resp, skip = _run_before_middleware(req, resp, route)
        assert skip is False


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────


def _make_request() -> Request:
    """Build a minimal Request without hitting the network."""
    scope = {
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
    }
    return Request.from_scope(scope, body=b"")


# ────────────────────────────────────────────────────────────────────
# #55 — global middleware (Middleware.use / Router.use) must be dispatched
# ────────────────────────────────────────────────────────────────────

from tina4_python.core.middleware import Middleware  # noqa: E402
from tina4_python.core.server import _run_after_middleware  # noqa: E402


class TestGlobalMiddlewareDispatched:
    """Global middleware registered via ``Middleware.use`` / ``Router.use`` must
    run on every route. Before #55 the dispatcher only iterated
    ``route['middleware']`` and never consulted the global registry, so global
    middleware silently never ran. Mirrors PHP/Ruby/Node, which already dispatch
    globals."""

    def setup_method(self):
        Middleware.reset()
        Router.clear()

    def teardown_method(self):
        Middleware.reset()
        Router.clear()

    def test_middleware_use_global_runs_before_and_after(self):
        fired = {"before": False, "after": False}

        class GlobalMarker:
            @staticmethod
            def before_mark(req, resp):
                fired["before"] = True
                return req, resp

            @staticmethod
            def after_mark(req, resp):
                fired["after"] = True
                return req, resp

        Middleware.use(GlobalMarker)
        route = {"middleware": []}
        req, resp = Request(), Response()
        req, resp, _skip = _run_before_middleware(req, resp, route)
        req, resp = _run_after_middleware(req, resp, route)

        assert fired["before"] is True, "global before_* middleware did not run"
        assert fired["after"] is True, "global after_* middleware did not run"

    def test_router_use_registers_into_the_dispatched_registry(self):
        # Router.use must land in the SAME registry the dispatcher reads
        # (it used to write a private Router._global_middleware nothing read).
        calls = {"n": 0}

        class GlobalViaRouter:
            @staticmethod
            def before_count(req, resp):
                calls["n"] += 1
                return req, resp

        Router.use(GlobalViaRouter)
        assert GlobalViaRouter in Middleware.get_global(), \
            "Router.use did not register into the Middleware global registry"

        route = {"middleware": []}
        req, resp = Request(), Response()
        _run_before_middleware(req, resp, route)
        assert calls["n"] == 1, "global middleware registered via Router.use did not run"

    def test_global_not_double_run_when_also_route_level(self):
        calls = {"n": 0}

        class Once:
            @staticmethod
            def before_once(req, resp):
                calls["n"] += 1
                return req, resp

        Middleware.use(Once)
        route = {"middleware": [Once]}  # same class also attached at route level
        req, resp = Request(), Response()
        _run_before_middleware(req, resp, route)
        assert calls["n"] == 1, "middleware that is both global and route-level ran twice (dedupe failed)"
