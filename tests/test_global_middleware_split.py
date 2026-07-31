# Global middleware runs in TWO passes, split by what it depends on.
"""
The two groups need opposite things and cannot share a position:

  PRE-match  - must survive a short-circuit, needs no route metadata.
               CORS lives here. A browser shown a 401 with no CORS headers
               reports a CORS error, so the real status never reaches the
               developer debugging it.
  POST-match - reads the matched route's metadata. CSRF lives here, because it
               must honour a route marked @noauth: core/middleware.py reads
               ``request._handler`` / ``_noauth``, which is only assigned once
               a route has matched. PHP shipped exactly that bypass as DEAD
               CODE once, because the metadata was not set yet.

Moving the whole pass before matching would therefore have BROKEN CSRF here.
That is why the pass is split rather than moved.

Opt in with ``pre_match = True``; the default is unchanged, so no existing
middleware moves.

NO MOCKS: real routes through the real dispatcher.

Same case names in all four:
  tina4-ruby/spec/global_middleware_split_spec.rb
  tina4-php/tests/GlobalMiddlewareSplitTest.php
  tina4-nodejs/test/globalMiddlewareSplit.test.ts
"""
import asyncio

import pytest

from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get, post as route_post
from tina4_python.core.server import handle


class PreMatchStamp:
    """Stamps a header the way CORS would, before any route is looked up."""

    pre_match = True

    @staticmethod
    def before_stamp(request, response):
        response.add_header("X-Ran-Before-Match", "yes")
        return request, response


class PlainStamp:
    """No flag: must keep running after matching, as it always has."""

    @staticmethod
    def before_plain(request, response):
        return request, response


@pytest.fixture(autouse=True)
def _routes():
    Router.clear()
    Middleware._global_middleware = []

    @route_get("/hello")
    async def _hello(request, response):
        return response("ok")

    @route_post("/secured")
    async def _secured(request, response):
        return response("x")

    yield
    Router.clear()
    Middleware._global_middleware = []


def _call(method, path):
    scope = {
        "type": "http", "method": method, "path": path,
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 1),
    }
    return asyncio.run(handle(Request.from_scope(scope, b"")))


def _header(response, name):
    return next((v for k, v in response._headers if k.lower() == name), None)


def test_pre_match_middleware_is_selected_by_the_flag():
    Middleware.use(PreMatchStamp)
    Middleware.use(PlainStamp)

    assert Middleware.pre_match_middleware() == [PreMatchStamp]


def test_middleware_without_the_flag_still_runs_after_matching():
    """NEGATIVE: the default must be unchanged."""
    Middleware.use(PreMatchStamp)
    Middleware.use(PlainStamp)

    assert Middleware.post_match_middleware() == [PlainStamp]


def test_pre_match_middleware_runs_on_a_path_with_no_route_at_all():
    """POSITIVE: it ran even though nothing matched - a post-match pass could not."""
    Middleware.use(PreMatchStamp)

    response = _call("GET", "/no/such/route")
    assert response.status_code == 404
    assert _header(response, "x-ran-before-match") == "yes"


def test_pre_match_middleware_output_survives_a_401():
    """POSITIVE: the case the whole split exists for."""
    Middleware.use(PreMatchStamp)

    response = _call("POST", "/secured")
    assert response.status_code == 401, "expected the write route to be secured by default"
    assert _header(response, "x-ran-before-match") == "yes", (
        "a pre-match middleware's header was lost on the 401"
    )


def test_pre_match_middleware_does_not_open_a_secured_route():
    """NEGATIVE: middleware before a route must not weaken the auth gate."""
    Middleware.use(PreMatchStamp)

    assert _call("POST", "/secured").status_code == 401


def test_a_normal_request_is_unaffected():
    """The happy path must not change at all."""
    Middleware.use(PreMatchStamp)

    response = _call("GET", "/hello")
    assert response.status_code == 200
