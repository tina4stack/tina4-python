# Every successful OPTIONS response carries Allow (RFC 9110 s9.3.7).
"""
There are TWO OPTIONS paths and they used to answer different questions:

  bare OPTIONS  (no Origin)  - protocol introspection. Link checkers,
                               monitoring probes, ``curl -X OPTIONS``.
  CORS preflight (Origin)    - a browser asking "may I send this?".

A preflight IS an OPTIONS response, so it should carry Allow too. Measured
2026-07-31: Ruby, Python and Node all dropped it on a preflight, and PHP
dropped it on BOTH as soon as CorsMiddleware was registered.

Allow and Access-Control-Allow-Methods are NOT interchangeable and this suite
asserts both: Allow is what the RESOURCE supports (derived from the router),
ACAM is what the CORS POLICY permits cross-origin (a configured static list, as
in every mainstream CORS library). A policy naming DELETE on a GET-only route
is still a 405, so a client that reads only ACAM is misled.

NO MOCKS: real routes through the real dispatcher.

Same case names in all four:
  tina4-ruby/spec/options_allow_conformance_spec.rb
  tina4-php/tests/OptionsAllowConformanceTest.php
  tina4-nodejs/test/optionsAllowConformance.test.ts
"""
import asyncio

import pytest

from tina4_python.core.middleware import Middleware
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get, post as route_post
from tina4_python.core.server import handle

PREFLIGHT = {"origin": "https://example.com", "access-control-request-method": "POST"}


@pytest.fixture(autouse=True)
def _routes():
    Router.clear()
    Middleware._global_middleware = []

    @route_get("/only-get")
    async def _g(request, response):
        return response("ok")

    @route_post("/only-get")
    async def _p(request, response):
        return response("ok")

    yield
    Router.clear()
    Middleware._global_middleware = []


def _options(headers=None):
    scope = {
        "type": "http", "method": "OPTIONS", "path": "/only-get", "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1),
    }
    return asyncio.run(handle(Request.from_scope(scope, b"")))


def _header(response, name):
    return next((v for k, v in response._headers if k.lower() == name.lower()), None)


def test_a_bare_options_carries_allow():
    """A bare OPTIONS must reach the RFC 9110 handler, not be eaten by CORS."""
    response = _options()
    assert response.status_code == 204
    assert _header(response, "Allow") == "GET, POST, HEAD, OPTIONS"


def test_a_cors_preflight_also_carries_allow():
    """The gap this suite was written for."""
    response = _options(PREFLIGHT)
    assert response.status_code == 204
    assert _header(response, "Allow") == "GET, POST, HEAD, OPTIONS", (
        "a CORS preflight returned 204 without Allow"
    )


def test_a_real_preflight_is_still_answered_by_cors():
    """NEGATIVE: the fix must not break CORS itself."""
    response = _options(PREFLIGHT)
    assert _header(response, "access-control-allow-origin") is not None
    assert _header(response, "access-control-allow-methods") is not None


def test_allow_describes_the_resource_not_the_policy():
    """
    Allow describes the RESOURCE; ACAM describes the POLICY. They are different
    values on purpose, and conflating them is the bug this pins: the policy
    names methods the route does not implement.
    """
    response = _options(PREFLIGHT)
    allow = _header(response, "Allow") or ""
    acam = _header(response, "access-control-allow-methods") or ""

    assert "DELETE" not in allow, "Allow named a method the route does not implement"
    assert "DELETE" in acam, "the policy list is expected to be broader than the resource"
    assert allow != acam
