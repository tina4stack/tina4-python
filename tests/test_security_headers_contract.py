# Security headers conformance — secure-by-default register + HTTPS-guarded HSTS.
"""
Feature 36 (security headers) conformance suite. See SECHDR-DEC-01/02 and
tina4-documentation/plan/v3/fixtures/securityheaders_contract.json.

Two rules, driven through the REAL dispatcher
(``tina4_python.core.server.handle``) with real ASGI scopes. NO MOCKS.

1. SECURE-BY-DEFAULT. The framework registers ``SecurityHeadersMiddleware`` in
   the default chain at boot via ``attach_security_headers()`` — the SAME call
   ``server.run``/``server.start`` makes (see
   ``tina4_python/core/server.py``). A default app response therefore carries the
   canonical header set with byte-identical VALUES to PHP/Ruby/Node, and CSP is
   ``default-src 'self'``. Before SECHDR-DEC-01 the middleware existed with good
   defaults but was never registered, so a default app had none of these.

2. HSTS IS HTTPS-ONLY. ``Strict-Transport-Security`` is emitted only when
   ``TINA4_HSTS`` is set AND the request is HTTPS (``x-forwarded-proto`` honoured
   first). On plain HTTP it is ABSENT even with ``TINA4_HSTS`` set.

Mutation-proved: unregister the middleware (empty ``attach_security_headers`` /
drop the boot call) and case 1 goes RED; drop the HTTPS guard (emit HSTS on any
scheme) and ``hsts is absent on a plain http request`` goes RED.

Same case names in all four:
  tina4-php/tests/SecurityHeadersContractTest.php
  tina4-ruby/spec/security_headers_contract_spec.rb
  tina4-nodejs/test/securityHeadersContract.test.ts
"""
from __future__ import annotations

import asyncio
import os

import pytest

import tina4_python.core.server as server
from tina4_python.core.middleware import (
    Middleware,
    SecurityHeadersMiddleware,
    attach_security_headers,
)
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get

# The canonical set every framework emits, byte-identical (names are compared
# case-insensitively — HTTP header names are case-insensitive).
CANONICAL = {
    "x-frame-options": "SAMEORIGIN",
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'self'",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-xss-protection": "0",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}
HSTS = "31536000"


@pytest.fixture(autouse=True)
def _app(monkeypatch):
    """A real registered route + the middleware attached exactly the way boot
    attaches it. Env is cleared so defaults are what a default app would see."""
    Router.clear()
    Middleware.reset()
    for name in ("TINA4_HSTS", "TINA4_CSP", "TINA4_FRAME_OPTIONS",
                 "TINA4_REFERRER_POLICY", "TINA4_PERMISSIONS_POLICY", "TINA4_CSRF"):
        monkeypatch.delenv(name, raising=False)

    @route_get("/sec-probe")
    async def _probe(request, response):
        return response("ok")

    # The SAME registration server.run/start performs at boot — secure-by-default.
    attach_security_headers()
    yield
    Router.clear()
    Middleware.reset()


def _request(https: bool = False):
    headers = []
    scheme = "http"
    if https:
        # A TLS-terminating proxy forwards plain HTTP to the app with this header;
        # is_secure_scheme() honours it. This is how HTTPS is expressed on the wire.
        headers.append((b"x-forwarded-proto", b"https"))
    scope = {
        "type": "http", "method": "GET", "path": "/sec-probe", "query_string": b"",
        "scheme": scheme, "headers": headers, "client": ("127.0.0.1", 1),
    }
    return asyncio.run(server.handle(Request.from_scope(scope, b"")))


def _header(response, name):
    return next((v for k, v in response._headers if k.lower() == name.lower()), None)


# --------------------------------------------------------- secure-by-default set

def test_a_default_app_response_carries_the_canonical_security_header_set():
    """A default app (nothing opted in) emits every canonical header with the
    exact shared value — and NOT HSTS (TINA4_HSTS unset)."""
    response = _request()
    assert response.status_code == 200
    for name, value in CANONICAL.items():
        assert _header(response, name) == value, (
            f"default app must emit {name}: {value} — this is the SECHDR-OFF-BY-DEFAULT "
            f"regression: if the middleware is unregistered this goes red"
        )
    # This middleware IS in the default chain — the registration is real, not a
    # per-test hand-wire a real app would not do.
    assert SecurityHeadersMiddleware in Middleware.get_global()
    assert _header(response, "strict-transport-security") is None, (
        "HSTS must NOT be emitted by default (TINA4_HSTS unset)"
    )


def test_csp_defaults_to_default_src_self():
    """CSP defaults to default-src 'self' (relaxable via TINA4_CSP)."""
    assert _header(_request(), "content-security-policy") == "default-src 'self'"


# ------------------------------------------------------------ HSTS HTTPS-guarded

def test_hsts_is_present_on_an_https_request(monkeypatch):
    """With TINA4_HSTS set, an HTTPS request carries the exact HSTS header."""
    monkeypatch.setenv("TINA4_HSTS", HSTS)
    assert _header(_request(https=True), "strict-transport-security") == (
        f"max-age={HSTS}; includeSubDomains"
    )


def test_hsts_is_absent_on_a_plain_http_request(monkeypatch):
    """The guard: even with TINA4_HSTS set, a plain-HTTP request gets NO HSTS.
    Dropping the scheme guard (emit on any scheme) turns this red."""
    monkeypatch.setenv("TINA4_HSTS", HSTS)
    assert _header(_request(https=False), "strict-transport-security") is None, (
        "HSTS on plain HTTP is a downgrade-protection header on an unencrypted "
        "scheme — the framework must guard it behind is_secure_scheme()"
    )
