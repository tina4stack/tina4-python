# CORS policy conformance — deny by default, no wildcard+credentials, Vary: Origin.
"""
Feature 10 (CORS middleware) conformance suite. See ADR-0014.

Three rules, each pinned positive AND negative, driven through the REAL
dispatcher (``tina4_python.core.server.handle``) with real ASGI scopes.
NO MOCKS.

1. DENY BY DEFAULT. With ``TINA4_CORS_ORIGINS`` unset, no
   ``Access-Control-Allow-Origin`` is emitted at all and the browser's own
   CORS check blocks the request. ``*`` still works, but must be asked for.
   Breaking change from the old permissive default.

2. NEVER ``ACAO: *`` WITH CREDENTIALS. The Fetch Standard's CORS check treats
   ``*`` as a literal once the request's credentials mode is "include", so the
   pair is rejected by every browser and a server emitting it is broken.
   Measured 2026-07-31: Ruby emitted exactly this pair.

3. ``Vary: Origin`` WHENEVER ACAO IS COMPUTED FROM THE REQUEST. RFC 9110
   s12.5.5: a Vary field name list tells cache recipients they "MUST NOT use
   this response to satisfy a later request unless the later request has the
   same values for the listed header fields as the original request".
   Emitted on an allow-list MISS as well as a match - the miss is exactly the
   case where a shared cache would otherwise serve a no-ACAO response to an
   origin that should have been allowed. NOT emitted for a constant ``*``,
   which genuinely does not vary and would only fragment a CDN's cache.

``Access-Control-Allow-Methods`` / ``-Allow-Headers`` are static configured
lists here, never derived from the request's ``Access-Control-Request-*``
headers, so those field names deliberately do NOT appear in Vary.

Same case names in all four:
  tina4-php/tests/CorsPolicyConformanceTest.php
  tina4-ruby/spec/cors_policy_conformance_spec.rb
  tina4-nodejs/test/corsPolicyConformance.test.ts
"""
import asyncio

import pytest

import tina4_python.core.middleware as middleware_module
import tina4_python.core.server as server
from tina4_python.core.middleware import CorsMiddleware
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get

GOOD = "https://good.example"
EVIL = "https://evil.example"


def _reset_warnings():
    """Clear the warn-once ledger. Tolerates its absence so this suite still
    IMPORTS against pre-fix code — the red must be a real assertion failure,
    not an ImportError, or it proves nothing about behaviour."""
    getattr(middleware_module, "_CORS_DENY_WARNED", set()).clear()


@pytest.fixture(autouse=True)
def _routes(monkeypatch):
    """A real registered route, and CORS config driven purely by env."""
    Router.clear()
    for name in ("TINA4_CORS_ORIGINS", "TINA4_CORS_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)

    @route_get("/api/thing")
    async def _thing(request, response):
        return response("ok")

    yield
    Router.clear()
    _reset_warnings()
    # This suite sets the CORS env directly (it has to rebuild the module-level
    # singleton), so it MUST clean up or it leaks into every later test file.
    import os
    for name in ("TINA4_CORS_ORIGINS", "TINA4_CORS_CREDENTIALS"):
        os.environ.pop(name, None)
    server._cors = CorsMiddleware()


def _configure(origins=None, credentials=None):
    """Rebuild the module-level CORS singleton from the current env."""
    import os
    for name, value in (("TINA4_CORS_ORIGINS", origins),
                        ("TINA4_CORS_CREDENTIALS", credentials)):
        os.environ.pop(name, None)
        if value is not None:
            os.environ[name] = value
    _reset_warnings()
    server._cors = CorsMiddleware()


def _request(method="GET", origin=None):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    if method == "OPTIONS":
        headers["access-control-request-method"] = "GET"
    scope = {
        "type": "http", "method": method, "path": "/api/thing", "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 1),
    }
    return asyncio.run(server.handle(Request.from_scope(scope, b"")))


def _header(response, name):
    return next((v for k, v in response._headers if k.lower() == name.lower()), None)


# ---------------------------------------------------------------- deny by default

def test_deny_by_default_emits_no_allow_origin():
    """TINA4_CORS_ORIGINS unset means no CORS policy, so no ACAO at all."""
    _configure()
    response = _request(origin=EVIL)
    assert _header(response, "access-control-allow-origin") is None, (
        "an unconfigured app must not hand out Access-Control-Allow-Origin"
    )


def test_deny_by_default_still_serves_non_browser_clients():
    """CORS is a BROWSER mechanism. curl and server-to-server are unaffected."""
    _configure()
    response = _request(origin=None)
    assert response.status_code == 200
    assert _header(response, "access-control-allow-origin") is None


def test_explicit_wildcard_still_allows_any_origin():
    """The default changed; the capability did not. '*' is still settable."""
    _configure(origins="*")
    response = _request(origin=EVIL)
    assert _header(response, "access-control-allow-origin") == "*"


def test_preflight_status_is_unchanged_when_denied():
    """Denying must not change the status code — the browser does the blocking."""
    _configure()
    denied = _request(method="OPTIONS", origin=EVIL)
    _configure(origins=GOOD)
    allowed = _request(method="OPTIONS", origin=GOOD)
    assert denied.status_code == allowed.status_code == 204
    assert _header(denied, "access-control-allow-origin") is None


# ------------------------------------------------------ wildcard never + credentials

def test_wildcard_never_pairs_with_credentials():
    """Fetch forbids ACAO:* with credentials. Ruby shipped exactly this pair."""
    _configure(origins="*", credentials="true")
    response = _request(origin=EVIL)
    assert _header(response, "access-control-allow-origin") == "*"
    assert _header(response, "access-control-allow-credentials") is None, (
        "Access-Control-Allow-Origin: * with Access-Control-Allow-Credentials: true "
        "is rejected by every browser — the framework must never emit the pair"
    )


def test_allow_list_match_reflects_origin_and_credentials():
    """The positive case: a named origin DOES get credentials."""
    _configure(origins=f"{GOOD},https://other.example", credentials="true")
    response = _request(origin=GOOD)
    assert _header(response, "access-control-allow-origin") == GOOD
    assert _header(response, "access-control-allow-credentials") == "true"


def test_allow_list_miss_emits_no_allow_origin():
    """An origin outside the list gets nothing — not a reflected value."""
    _configure(origins=GOOD, credentials="true")
    response = _request(origin=EVIL)
    assert _header(response, "access-control-allow-origin") is None
    assert _header(response, "access-control-allow-credentials") is None


# --------------------------------------------------------------------------- Vary

def test_allow_list_always_varies_on_origin():
    """RFC 9110 s12.5.5 — including on a MISS, which is the poisoning case."""
    _configure(origins=GOOD)
    assert _header(_request(origin=GOOD), "vary") == "Origin", "match must vary"

    _configure(origins=GOOD)
    assert _header(_request(origin=EVIL), "vary") == "Origin", (
        "a MISS must vary too — otherwise a shared cache can serve this "
        "no-ACAO response to an origin that should have been allowed"
    )


def test_constant_wildcard_does_not_vary_on_origin():
    """A constant '*' is identical for everyone; Vary would only fragment caches."""
    _configure(origins="*")
    assert _header(_request(origin=EVIL), "vary") is None


def test_vary_origin_does_not_clobber_an_existing_vary():
    """Appending, not overwriting — a pre-existing Vary must survive."""
    _configure(origins=GOOD)
    cors = CorsMiddleware()

    class _Recorder:
        _headers = [("vary", "Accept-Encoding")]

        def header(self, name, value):
            self._headers.append((name, value))
            return self

    recorder = _Recorder()
    cors._vary_origin(recorder)
    assert recorder._headers == [("vary", "Accept-Encoding, Origin")]

    cors._vary_origin(recorder)
    assert recorder._headers == [("vary", "Accept-Encoding, Origin")], "idempotent"
