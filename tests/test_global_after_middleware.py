# A global middleware's after_* hooks MUST run, for BOTH phases.
"""
REGRESSION. The after pass used to cover only the POST-match group, so a
``pre_match`` middleware's after_* never ran on a successful request - measured
0 runs in 5 requests. An acquire/release pair leaked one slot per request,
unbounded; a timer started in before_* was never stopped; an access log saw the
request and never the response.

It also inverted: the pre-match after_* DID run when the pre-match pass
short-circuited, so it fired on the error path and not the happy one. A smoke
test on a 401 would have shown it "working".

Splitting the BEFORE pass by dependency (ADR-0012) says nothing about the after
pass: an after hook adds headers or logging and needs no route metadata either
way. Django unwinds its single MIDDLEWARE list in reverse, Laravel runs the
response phase for global, group AND route middleware, Rails runs every
declared after_action.

NO MOCKS: real routes through the real dispatcher.

Same case names in all four:
  tina4-php/tests/GlobalAfterMiddlewareTest.php
  tina4-nodejs/test/globalAfterMiddleware.test.ts
  tina4-ruby/spec/global_after_middleware_spec.rb
"""
import asyncio

import pytest

from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get
from tina4_python.core.server import handle


class PreMatchAfter:
    """Acquire in before, release in after - the pair that leaked."""

    pre_match = True
    in_flight = 0
    runs = 0

    @staticmethod
    def before_acquire(request, response):
        PreMatchAfter.in_flight += 1
        return request, response

    @staticmethod
    def after_release(request, response):
        PreMatchAfter.in_flight -= 1
        PreMatchAfter.runs += 1
        return request, response


class PostMatchAfter:
    runs = 0

    @staticmethod
    def after_count(request, response):
        PostMatchAfter.runs += 1
        return request, response


@pytest.fixture(autouse=True)
def _reset():
    Router.clear()
    Middleware._global_middleware = []
    PreMatchAfter.in_flight = PreMatchAfter.runs = 0
    PostMatchAfter.runs = 0
    yield
    Router.clear()
    Middleware._global_middleware = []


def _call(method, path):
    scope = {"type": "http", "method": method, "path": path, "query_string": b"",
             "headers": [], "client": ("127.0.0.1", 1)}
    return asyncio.run(handle(Request.from_scope(scope, b"")))


def _hello():
    @route_get("/hello")
    async def _h(request, response):
        return response("ok")


def test_a_global_after_hook_runs_on_a_matched_route():
    """POSITIVE: the post-match group, which always worked."""
    Middleware.use(PostMatchAfter)
    _hello()

    assert _call("GET", "/hello").status_code == 200
    assert PostMatchAfter.runs == 1


def test_a_pre_match_middlewares_after_hook_also_runs():
    """POSITIVE: the case that was broken."""
    Middleware.use(PreMatchAfter)
    _hello()

    _call("GET", "/hello")
    assert PreMatchAfter.runs == 1, (
        "a pre-match middleware was excluded from the after pass - the ADR-0012 "
        "split applies to the BEFORE pass only"
    )


def test_an_acquire_release_pair_stays_balanced():
    """
    The implication, asserted directly: a before/after pair must not leak.

    This is what made the bug serious rather than cosmetic - the imbalance grew
    by one per request, without bound, and nothing errored.
    """
    Middleware.use(PreMatchAfter)
    _hello()

    for _ in range(5):
        _call("GET", "/hello")

    assert PreMatchAfter.runs == 5
    assert PreMatchAfter.in_flight == 0, (
        f"acquire/release leaked {PreMatchAfter.in_flight} slots over 5 requests"
    )


def test_a_global_after_hook_does_not_run_on_an_unmatched_path():
    """NEGATIVE: the after pass belongs to the matched-route path."""
    Middleware.use(PostMatchAfter)

    assert _call("GET", "/no/such/route").status_code == 404
    assert PostMatchAfter.runs == 0
