"""Feature 7 - middleware pipeline characterisation.

Pins the CURRENT behaviour of the middleware pipeline mechanism so a change to
it is visible rather than silent: how hooks are discovered, what order they run
in, what short-circuits the handler, and what happens when a hook throws.

The case names are IDENTICAL in all four frameworks so the suites can be read
side by side:

  tina4-php/tests/MiddlewarePipelineCharacterisationTest.php
  tina4-ruby/spec/middleware_pipeline_characterisation_spec.rb
  tina4-nodejs/test/middlewarePipelineCharacterisation.test.ts

NOT a mock anywhere: real middleware classes, real Request/Response objects,
and the real front controller (``TestClient`` dispatches through
``core.server.app``). Nothing stands in for a collaborator.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("TINA4_SECRET", "feature7-characterisation-secret")

import pytest

from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.router import get, middleware
from tina4_python.core.server import (
    _run_after_middleware,
    _run_before_middleware,
)
from tina4_python.test_client import TestClient


# The shared trace every hook appends to. A list, not a spy: the hooks are real
# middleware methods and the list is their real side effect.
TRACE: list[str] = []

# Every Response object a hook handed back, in order. Also a real side effect,
# so a test can assert the pipeline adopted THAT object and not a copy.
HANDED_BACK: list[Response] = []


def fresh_pair() -> tuple[Request, Response]:
    """A real Request/Response pair, built the way the dispatcher builds them."""
    request = Request()
    request.method = "GET"
    request.path = "/characterisation"
    return request, Response()


class OrderedHooks:
    """Two before hooks and two after hooks, declared out of alphabetical order.

    ``before_zulu`` is declared FIRST and ``before_alpha`` second, so definition
    order and alphabetical order disagree and the test can tell them apart.
    """

    @staticmethod
    def before_zulu(request, response):
        TRACE.append("before_zulu")
        return request, response

    @staticmethod
    def before_alpha(request, response):
        TRACE.append("before_alpha")
        return request, response

    @staticmethod
    def after_zulu(request, response):
        TRACE.append("after_zulu")
        return request, response

    @staticmethod
    def after_alpha(request, response):
        TRACE.append("after_alpha")
        return request, response


class FirstRegistered:
    @staticmethod
    def before_first(request, response):
        TRACE.append("before_first")
        return request, response


class SecondRegistered:
    @staticmethod
    def before_second(request, response):
        TRACE.append("before_second")
        return request, response


class DenyReturningPair:
    """Sets 403 and returns the (request, response) pair - the documented form."""

    @staticmethod
    def before_deny(request, response):
        TRACE.append("before_deny")
        response.status(403).json({"error": "denied"})
        return request, response


class DenyReturningNothing:
    """Sets 403 on the response but returns nothing.

    Rails short-circuits on response STATE, not on what the filter returned, so
    this is a shape real middleware takes. This case is the one that measured
    differently across the four.
    """

    @staticmethod
    def before_deny(request, response):
        TRACE.append("before_deny")
        response.status(403).json({"error": "denied"})


class AfterOnDeny:
    @staticmethod
    def after_mark(request, response):
        TRACE.append("after_mark")
        return request, response


class ThrowingBefore:
    @staticmethod
    def before_boom(request, response):
        TRACE.append("before_boom")
        raise RuntimeError("before hook exploded")


class ThrowingAfterThenAnother:
    @staticmethod
    def after_boom(request, response):
        TRACE.append("after_boom")
        raise RuntimeError("after hook exploded")

    @staticmethod
    def after_survivor(request, response):
        TRACE.append("after_survivor")
        return request, response


class BaseHooks:
    @staticmethod
    def before_base(request, response):
        TRACE.append("before_base")
        return request, response


class SubclassHooks(BaseHooks):
    @staticmethod
    def before_sub(request, response):
        TRACE.append("before_sub")
        return request, response


class RouteScoped:
    @staticmethod
    def before_route(request, response):
        TRACE.append("before_route")
        return request, response

    @staticmethod
    def after_route(request, response):
        TRACE.append("after_route")
        return request, response


class ReturnsResponseObject:
    """Hands back a BRAND NEW Response - the object itself is the answer.

    A fresh object (not the one it was passed) so a test can assert by IDENTITY
    that the pipeline adopted the hook's object, which no response-state rule
    could ever do.
    """

    @staticmethod
    def before_replace(request, response):
        TRACE.append("before_replace")
        replacement = Response().status(401).json({"error": "replaced"})
        HANDED_BACK.append(replacement)
        return replacement


class ReturnsRedirectResponse:
    """Returns a 302 Response - the case the >= 400 state rule cannot express."""

    @staticmethod
    def before_redirect(request, response):
        TRACE.append("before_redirect")
        return response.redirect("/login")


class ReturnsFalse:
    """Returns False and leaves the response untouched (still default/empty)."""

    @staticmethod
    def before_deny(request, response):
        TRACE.append("before_deny")
        return False


class ReturnsNothing:
    """Returns None and touches nothing - the chain must simply continue."""

    @staticmethod
    def before_pass(request, response):
        TRACE.append("before_pass")


class TrailingHook:
    """Registered AFTER the hook under test. Its silence proves short-circuit.

    ``Middleware.run_before`` returns no skip flag - it just returns early - so
    the only honest way to observe a short-circuit at the orchestrator is a
    later hook that never ran.
    """

    @staticmethod
    def before_trailing(request, response):
        TRACE.append("before_trailing")
        return request, response

    @staticmethod
    def after_trailing(request, response):
        TRACE.append("after_trailing")
        return request, response


@pytest.fixture(autouse=True)
def _reset():
    TRACE.clear()
    HANDED_BACK.clear()
    Middleware.reset()
    yield
    Middleware.reset()
    HANDED_BACK.clear()
    TRACE.clear()


class TestMiddlewarePipelineCharacterisation:
    # ---------------------------------------------------------------- global

    def test_global_class_middleware_runs_its_before_hook(self):
        """global class middleware runs its before hook"""
        Middleware.use(OrderedHooks)

        @get("/f7/global-before")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        assert TestClient().get("/f7/global-before").status == 200
        assert "before_zulu" in TRACE

    def test_global_class_middleware_runs_its_after_hook(self):
        """global class middleware runs its after hook"""
        Middleware.use(OrderedHooks)

        @get("/f7/global-after")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        TestClient().get("/f7/global-after")
        assert "after_zulu" in TRACE
        assert TRACE.index("handler") < TRACE.index("after_zulu")

    def test_hooks_within_one_class_run_in_definition_order(self):
        """hooks within one class run in definition order"""
        request, response = fresh_pair()
        Middleware.run_before([OrderedHooks], request, response)
        assert TRACE == ["before_zulu", "before_alpha"], (
            "definition order, never alphabetical"
        )

    def test_classes_run_in_registration_order(self):
        """classes run in registration order"""
        request, response = fresh_pair()
        Middleware.run_before([FirstRegistered, SecondRegistered], request, response)
        assert TRACE == ["before_first", "before_second"]

    # -------------------------------------------------------- short-circuit

    def test_a_before_hook_that_returns_a_4xx_pair_skips_the_handler(self):
        """a before hook that returns a 4xx pair skips the handler"""
        request, response = fresh_pair()
        _, _, skip = _run_before_middleware(
            request, response,
            {"middleware": [DenyReturningPair], "handler": None},
            include_globals=False,
        )
        assert skip is True
        assert response.status_code == 403

    def test_a_before_hook_that_sets_4xx_and_returns_nothing_skips_the_handler(self):
        """a before hook that sets 4xx and returns nothing skips the handler"""
        # The RETAINED LEGACY COMPAT path: short-circuit on response STATE
        # (Rails-style), even though the hook returned None. It stays because
        # real middleware takes this shape - but it is NOT the main mechanism,
        # because it cannot express a 3xx (see the redirect case below).
        request, response = fresh_pair()
        _, _, skip = _run_before_middleware(
            request, response,
            {"middleware": [DenyReturningNothing], "handler": None},
            include_globals=False,
        )
        assert skip is True, (
            "a hook that sets 4xx must stop the handler regardless of what it returned"
        )
        assert response.status_code == 403

    def test_after_hooks_still_run_when_a_before_hook_short_circuits(self):
        """after hooks still run when a before hook short circuits"""
        request, response = fresh_pair()
        route = {"middleware": [DenyReturningPair, AfterOnDeny], "handler": None}
        _, _, skip = _run_before_middleware(request, response, route, include_globals=False)
        assert skip is True
        _run_after_middleware(request, response, route, include_globals=False)
        assert "after_mark" in TRACE

    # --------------------------------------------------------------- throws

    def test_a_throwing_before_hook_becomes_a_clean_500(self):
        """a throwing before hook becomes a clean 500"""
        request, response = fresh_pair()
        _, resp, skip = _run_before_middleware(
            request, response,
            {"middleware": [ThrowingBefore], "handler": None},
            include_globals=False,
        )
        assert skip is True
        assert resp.status_code == 500

    def test_a_throwing_after_hook_does_not_stop_the_remaining_after_hooks(self):
        """a throwing after hook does not stop the remaining after hooks"""
        request, response = fresh_pair()
        _run_after_middleware(
            request, response,
            {"middleware": [ThrowingAfterThenAnother], "handler": None},
            include_globals=False,
        )
        assert TRACE == ["after_boom", "after_survivor"]

    # ---------------------------------------------------------- inheritance

    def test_hook_discovery_includes_hooks_inherited_from_a_base_class(self):
        """hook discovery includes hooks inherited from a base class"""
        names = Middleware._discover_methods(SubclassHooks, "before_")
        assert "before_base" in names, "an inherited hook must still be discovered"
        assert "before_sub" in names

    def test_inherited_before_hooks_run_before_the_subclass_own_hooks(self):
        """inherited before hooks run before the subclass own hooks"""
        names = Middleware._discover_methods(SubclassHooks, "before_")
        assert names.index("before_base") < names.index("before_sub")

    # --------------------------------------------------------- route-scoped

    def test_route_class_middleware_runs_its_before_hook(self):
        """route class middleware runs its before hook"""
        request, response = fresh_pair()
        _run_before_middleware(
            request, response,
            {"middleware": [RouteScoped], "handler": None},
            include_globals=False,
        )
        assert "before_route" in TRACE

    def test_route_class_middleware_runs_its_after_hook(self):
        """route class middleware runs its after hook"""
        request, response = fresh_pair()
        _run_after_middleware(
            request, response,
            {"middleware": [RouteScoped], "handler": None},
            include_globals=False,
        )
        assert "after_route" in TRACE

    # ------------------------------------------------- return-value contract

    def test_a_before_hook_that_returns_a_response_object_short_circuits(self):
        """a before hook that returns a response object short circuits"""
        request, response = fresh_pair()
        _, resp, skip = _run_before_middleware(
            request, response,
            {"middleware": [ReturnsResponseObject, TrailingHook], "handler": None},
            include_globals=False,
        )
        assert skip is True, "a returned Response IS the response - the handler must not run"
        assert resp is HANDED_BACK[0], (
            "the pipeline must adopt the hook's OWN object, not copy its status"
        )
        assert resp.status_code == 401
        assert "before_trailing" not in TRACE, "later middleware must not run"

        @middleware(ReturnsResponseObject)
        @get("/f7/returns-response")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        sent = TestClient().get("/f7/returns-response")
        assert sent.status == 401
        assert sent.json() == {"error": "replaced"}
        assert "handler" not in TRACE

    def test_a_before_hook_that_returns_a_redirect_response_short_circuits(self):
        """a before hook that returns a redirect response short circuits"""
        # LOAD-BEARING. 302 is below 400, so the legacy response-state rule
        # CANNOT express it. Only the Response-object rule can, which is exactly
        # why that rule is primary and the state rule is legacy compat.
        request, response = fresh_pair()
        _, resp, skip = _run_before_middleware(
            request, response,
            {"middleware": [ReturnsRedirectResponse, TrailingHook], "handler": None},
            include_globals=False,
        )
        assert skip is True, "a 302 Response must short-circuit - the >= 400 rule cannot"
        assert resp.status_code == 302
        assert "before_trailing" not in TRACE

        @middleware(ReturnsRedirectResponse)
        @get("/f7/returns-redirect")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        sent = TestClient().get("/f7/returns-redirect")
        assert sent.status == 302
        assert sent.headers["location"] == "/login"
        assert "handler" not in TRACE

    def test_a_before_hook_that_returns_false_short_circuits_with_403(self):
        """a before hook that returns false short circuits with 403"""
        request, response = fresh_pair()
        _, resp, skip = _run_before_middleware(
            request, response,
            {"middleware": [ReturnsFalse, TrailingHook], "handler": None},
            include_globals=False,
        )
        assert skip is True, "False means stop"
        assert resp.status_code == 403, (
            "False on an untouched response means Forbidden, not 200 and not a crash"
        )
        assert "before_trailing" not in TRACE

        @middleware(ReturnsFalse)
        @get("/f7/returns-false")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        sent = TestClient().get("/f7/returns-false")
        assert sent.status == 403
        assert "handler" not in TRACE

    def test_a_before_hook_that_returns_nothing_continues_to_the_handler(self):
        """a before hook that returns nothing continues to the handler"""
        request, response = fresh_pair()
        _, resp, skip = _run_before_middleware(
            request, response,
            {"middleware": [ReturnsNothing, TrailingHook], "handler": None},
            include_globals=False,
        )
        assert skip is False, "None means carry on"
        assert resp.status_code == 200
        assert TRACE == ["before_pass", "before_trailing"]

        @middleware(ReturnsNothing)
        @get("/f7/returns-nothing")
        async def _handler(request, response):
            TRACE.append("handler")
            return response({"ok": True})

        sent = TestClient().get("/f7/returns-nothing")
        assert sent.status == 200
        assert "handler" in TRACE


class TestMiddlewarePipelineOrchestrator:
    """The SAME contract at the OTHER public entry point.

    ``Middleware.run_before`` / ``Middleware.run_after`` are public API - an app
    can call them directly, and the frameworks' own docs show exactly that - so
    the return-value table and the throwing-hook rule must hold here identically
    to the dispatcher. Two entry points, one contract.

    The orchestrator returns no skip flag (it just returns early), so the honest
    observable for a short-circuit is ``TrailingHook`` never running.
    """

    def test_a_throwing_before_hook_becomes_a_clean_500(self):
        """a throwing before hook becomes a clean 500"""
        request, response = fresh_pair()
        _, resp = Middleware.run_before(
            [ThrowingBefore, TrailingHook], request, response
        )
        assert resp.status_code == 500, "a raising hook must never escape the orchestrator"
        assert json.loads(resp.content) == {"error": "Internal Server Error", "status": 500}
        assert "before_trailing" not in TRACE, "a throwing before hook short-circuits"

    def test_a_throwing_after_hook_does_not_stop_the_remaining_after_hooks(self):
        """a throwing after hook does not stop the remaining after hooks"""
        request, response = fresh_pair()
        _, resp = Middleware.run_after(
            [ThrowingAfterThenAnother], request, response
        )
        assert TRACE == ["after_boom", "after_survivor"]
        assert resp.status_code == 500

    def test_a_before_hook_that_returns_a_response_object_short_circuits(self):
        """a before hook that returns a response object short circuits"""
        request, response = fresh_pair()
        _, resp = Middleware.run_before(
            [ReturnsResponseObject, TrailingHook], request, response
        )
        assert resp is HANDED_BACK[0], (
            "the orchestrator must adopt the hook's OWN Response object"
        )
        assert resp.status_code == 401
        assert "before_trailing" not in TRACE

    def test_a_before_hook_that_returns_a_redirect_response_short_circuits(self):
        """a before hook that returns a redirect response short circuits"""
        # Same load-bearing case at the orchestrator: 302 < 400, so nothing but
        # the Response-object rule can stop the chain here.
        request, response = fresh_pair()
        _, resp = Middleware.run_before(
            [ReturnsRedirectResponse, TrailingHook], request, response
        )
        assert resp.status_code == 302
        assert "before_trailing" not in TRACE, "a 302 Response must stop the chain"

    def test_a_before_hook_that_returns_false_short_circuits_with_403(self):
        """a before hook that returns false short circuits with 403"""
        request, response = fresh_pair()
        _, resp = Middleware.run_before(
            [ReturnsFalse, TrailingHook], request, response
        )
        assert resp.status_code == 403
        assert "before_trailing" not in TRACE

    def test_a_before_hook_that_returns_nothing_continues_to_the_handler(self):
        """a before hook that returns nothing continues to the handler"""
        request, response = fresh_pair()
        _, resp = Middleware.run_before(
            [ReturnsNothing, TrailingHook], request, response
        )
        assert resp.status_code == 200
        assert TRACE == ["before_pass", "before_trailing"]
