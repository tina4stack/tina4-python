# Default-CSP warn-once — the visible half of the secure-by-default CSP.
"""
Issue tina4-nodejs#61. `default-src 'self'` stays the secure default, but when
TINA4_CSP is unset the framework says so ONCE per process, so a cross-origin app
(runtime inline styles, CDN fonts/scripts, a separate API/LiveKit WebSocket) is
not silently broken with the failure only visible in the browser at runtime.

Driven through the REAL dispatcher (`tina4_python.core.server.handle`) with real
ASGI scopes, capturing the REAL log via capfd. NO MOCKS.

Three rules:
1. TINA4_CSP unset -> the warning is emitted exactly ONCE across many requests.
2. TINA4_CSP set   -> NO warning (the app opted in).
3. Behaviour is UNCHANGED: the CSP header is still `default-src 'self'` when unset
   (the fix adds a log line, it does not weaken or drop the header) — and it never
   fails the request.

Mutation-proved: drop the `_csp_default_warn_once()` call and rule 1 goes RED;
warn on every request (remove the ledger guard) and "exactly once" goes RED.

Same case names in all four:
  tina4-php/tests/CspDefaultWarningTest.php
  tina4-ruby/spec/csp_default_warning_spec.rb
  tina4-nodejs/test/cspDefaultWarning.test.ts
"""
from __future__ import annotations

import asyncio

import pytest

import tina4_python.core.middleware as middleware_module
import tina4_python.core.server as server
from tina4_python.core.middleware import Middleware, attach_security_headers
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get

WARNING_MARK = "TINA4_CSP is not set"


def _reset_ledger():
    """Clear the warn-once ledger. `getattr` tolerates its absence so this suite
    still IMPORTS against pre-fix code — the red must be a real assertion failure,
    not an ImportError, or it proves nothing about behaviour."""
    getattr(middleware_module, "_CSP_DEFAULT_WARNED", []).clear()


@pytest.fixture(autouse=True)
def _app(monkeypatch):
    """A real registered route + the middleware attached exactly the way boot
    attaches it, with the ledger reset so 'once' is measured from a clean slate."""
    Router.clear()
    Middleware.reset()
    monkeypatch.delenv("TINA4_CSP", raising=False)

    @route_get("/csp-probe")
    async def _probe(request, response):
        return response("ok")

    attach_security_headers()
    _reset_ledger()
    yield
    Router.clear()
    Middleware.reset()
    _reset_ledger()


def _request():
    scope = {
        "type": "http", "method": "GET", "path": "/csp-probe", "query_string": b"",
        "scheme": "http", "headers": [], "client": ("127.0.0.1", 1),
    }
    return asyncio.run(server.handle(Request.from_scope(scope, b"")))


def _header(response, name):
    return next((v for k, v in response._headers if k.lower() == name.lower()), None)


def test_default_csp_warns_exactly_once(capfd):
    """TINA4_CSP unset -> the heads-up is logged once, not once per request."""
    responses = [_request() for _ in range(3)]
    captured = capfd.readouterr()
    hits = (captured.out + captured.err).count(WARNING_MARK)
    assert hits == 1, f"expected the default-CSP warning exactly once, saw {hits}"
    # Behaviour unchanged: the header is still the secure default on every response.
    for r in responses:
        assert _header(r, "content-security-policy") == "default-src 'self'"


def test_set_csp_does_not_warn(capfd, monkeypatch):
    """TINA4_CSP set -> the app opted in, so there is NO heads-up."""
    monkeypatch.setenv("TINA4_CSP", "default-src 'self' https://api.example")
    _reset_ledger()
    r = _request()
    captured = capfd.readouterr()
    assert WARNING_MARK not in (captured.out + captured.err), (
        "setting TINA4_CSP is an explicit opt-in and must not warn"
    )
    assert _header(r, "content-security-policy") == "default-src 'self' https://api.example"
