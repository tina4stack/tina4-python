# Error-overlay conformance — dead-code removal, redaction, frame cap, self-throw guard.
"""
Feature 126 (development error overlay) conformance suite. See OVERLAY-DEC-01..04
and tina4-documentation/plan/v3/fixtures/overlay_contract.json.

Four rules, driven through the REAL server dispatch
(``tina4_python.core.server.handle`` with real ASGI scopes / a real thrown 500).
NO MOCKS.

1. WIRED PRODUCTION NO-LEAK (OVERLAY-DEC-01). The dead ``render_production_error``
   is deleted; the real production 500 renders ``errors/500.twig`` with an empty
   ``error_message`` (CWE-209). A real production 500 leaks neither the exception
   message nor a traceback. This replaces the old unit test that only exercised the
   never-invoked sibling.

2. REDACTION (OVERLAY-DEC-02). The dev overlay masks ``Authorization``/``Cookie``
   headers and password-like body keys, so a bearer token or submitted password is
   never rendered in cleartext even under TINA4_DEBUG.

3. FRAME CAP (OVERLAY-DEC-03). A 5000-deep recursive stack renders a bounded page
   (the innermost _MAX_FRAMES frames + a truncation note), not one div per frame.

4. SELF-THROW GUARD (OVERLAY-DEC-03). If the overlay render itself raises (an
   unrenderable request value), the dispatch still returns a safe 500 instead of
   double-faulting out of the crash handler.

Mutation-proved (macOS, Python 3.13): make ``_redact`` return the value unchanged and
case 2 goes RED (``sekret``/``hunter2`` appear); drop the ``_MAX_FRAMES`` slice and case
3 goes RED (5001 frame divs, no note); drop the try/except around the overlay call in
``_handle_route_error`` and case 4 goes RED (``server.handle`` raises instead of
returning a 500).

Same case names in all four:
  tina4-php/tests/OverlayContractTest.php
  tina4-ruby/spec/overlay_contract_spec.rb
  tina4-nodejs/test/overlayContract.test.ts
"""
from __future__ import annotations

import asyncio
import sys
import threading

import pytest

import tina4_python.core.server as server
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get
from tina4_python.debug.error_overlay import render_error_overlay, _MAX_FRAMES

SECRET_MARKER = "SECRET-MARKER-do-not-leak-9f3a"

# Secret VALUES live here as named constants, referenced by name below, so the
# literal never sits in a stack frame's rendered source window (the overlay shows a
# seven-line source window per frame, and this test file is itself on the stack). The
# redaction under test is about the REQUEST table, not the test's own source.
AUTH_SECRET = "sekret-auth-71c2"
COOKIE_SECRET = "sekret-cookie-4d8e"
PASSWORD_SECRET = "hunter2-9a1f"

# Same reasoning for the self-throw-guard case (test 4 below): a named constant
# kept away from any test body, so it can never coincide with a legitimate
# source-context panel — the exact failure mode this marker replaces (see
# _UnrenderablePoison and test_a_throwing_overlay_render_still_returns_a_safe_500).
POISON_MARKER = "POISON-MARKER-overlay-self-throw-6c2f"


def _secret_request():
    """Build the (scope, body) carrying a bearer token, a session cookie and a
    password. Returns before the dispatch throws, so this frame is never on the
    traceback and its source is never rendered."""
    headers = [
        (b"authorization", ("Bearer " + AUTH_SECRET).encode()),
        (b"cookie", ("session=" + COOKIE_SECRET).encode()),
        (b"content-type", b"application/json"),
        (b"host", b"localhost"),
    ]
    body = ('{"password": "%s", "username": "alice"}' % PASSWORD_SECRET).encode()
    return _scope(path="/overlay-secret", headers=headers), body


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """Real routes, a clean router, and TINA4_DEBUG under test control so the gate
    is exactly what a real app would see."""
    Router.clear()
    monkeypatch.chdir(tmp_path)  # keep any data/.broken writes out of the repo
    yield
    Router.clear()
    monkeypatch.delenv("TINA4_DEBUG", raising=False)


def _dispatch(scope: dict, body: bytes = b""):
    return asyncio.run(server.handle(Request.from_scope(scope, body)))


def _scope(method: str = "GET", path: str = "/overlay-boom", headers=None):
    return {
        "type": "http", "method": method, "path": path, "query_string": b"",
        "scheme": "http", "headers": headers or [], "client": ("127.0.0.1", 1),
    }


# ------------------------------------------------ 1. wired production no-leak

def test_a_wired_production_500_does_not_leak_the_exception(monkeypatch):
    """Production (TINA4_DEBUG off): a real route throw yields a 500 whose body
    carries neither the exception message nor any traceback marker (CWE-209)."""
    monkeypatch.delenv("TINA4_DEBUG", raising=False)

    @route_get("/overlay-boom")
    async def _boom(request, response):
        raise RuntimeError(SECRET_MARKER)

    response = _dispatch(_scope(path="/overlay-boom"))
    body = (response.content or b"").decode("utf-8", "replace")

    assert response.status_code == 500
    for marker in (SECRET_MARKER, "Traceback", 'File "', "RuntimeError", "error_overlay"):
        assert marker not in body, f"CWE-209 regression: production 500 body leaked {marker!r}"


# ---------------------------------------------------------- 2. redaction (dev)

def test_the_dev_overlay_redacts_authorization_and_secret_body_fields(monkeypatch):
    """Dev overlay renders the request table but masks the Authorization + Cookie
    headers and the password body field. Removing _redact makes this RED."""
    monkeypatch.setenv("TINA4_DEBUG", "true")

    @route_get("/overlay-secret")
    async def _boom(request, response):
        raise RuntimeError("handler exploded")

    scope, body = _secret_request()
    response = _dispatch(scope, body)
    html = (response.content or b"").decode("utf-8", "replace")

    assert response.status_code == 500
    # The overlay DID render the request section (proves redaction is masking, not
    # merely hiding the whole section):
    assert "Request Details" in html
    assert "alice" in html  # a non-sensitive body value is shown verbatim
    assert "[redacted]" in html
    # ...but every secret is masked:
    for secret in (AUTH_SECRET, COOKIE_SECRET, PASSWORD_SECRET):
        assert secret not in html, f"dev overlay leaked a secret: {secret!r}"


# ------------------------------------------------------------- 3. frame cap

def _make_deep_exception(depth: int = 5000) -> BaseException:
    """Build a genuinely deep recursive traceback (no mock). Run in a thread with a
    large C stack so 5000 Python frames never overflow it."""
    holder: dict = {}

    def deep(n):
        if n <= 0:
            raise RuntimeError("deep stack marker")
        return deep(n - 1)

    def worker():
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(depth + 2000)
        try:
            deep(depth)
        except RuntimeError as exc:
            holder["exc"] = exc
        finally:
            sys.setrecursionlimit(old_limit)

    old_size = threading.stack_size()
    threading.stack_size(256 * 1024 * 1024)
    try:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    finally:
        threading.stack_size(old_size)
    return holder["exc"]


def test_a_deep_recursive_stack_renders_a_frame_capped_page():
    """A 5000-deep stack renders a bounded page: at most _MAX_FRAMES frame blocks
    plus a truncation note. Dropping the cap slice makes this RED (5001 blocks)."""
    exc = _make_deep_exception(5000)
    html = render_error_overlay(exc)

    frame_blocks = html.count('<div style="margin-bottom:16px;">')
    assert frame_blocks <= _MAX_FRAMES, (
        f"frame count {frame_blocks} exceeds the cap {_MAX_FRAMES} — unbounded render"
    )
    assert "more stack frames hidden" in html, "truncation note missing on a deep stack"


# --------------------------------------------------------- 4. self-throw guard

class _UnrenderablePoison:
    """A real request value whose string conversion raises — the 'malformed frame /
    edge' the overlay guard exists for. NOT a mock: the real overlay really runs and
    really fails on this genuinely-unrenderable input."""

    def __str__(self):
        raise RuntimeError(POISON_MARKER)

    __repr__ = __str__


def test_a_throwing_overlay_render_still_returns_a_safe_500(monkeypatch):
    """Dev mode: the handler enriches ``request.params`` with an unrenderable value.
    ``params`` is router-attached and stays mutable under REQ-IMMUTABILITY-DIVERGE
    (only the wire-derived fields — ``body`` among them — are frozen once built), so
    this assignment succeeds and the handler's own exception reaches the overlay.
    Rendering the Request Details panel then calls ``str()`` on the poison value and
    raises. The dispatch guard must still return a safe 500 (no exception
    propagates, no detail leaks). Removing the guard makes server.handle RAISE
    instead of returning a 500.

    (Injecting via ``request.body`` here would raise at the ASSIGNMENT itself —
    REQ-IMMUTABILITY-DIVERGE — before the handler's intended ``raise``, which is a
    different, already-covered failure mode, not the overlay self-throw this test
    targets.)
    """
    monkeypatch.setenv("TINA4_DEBUG", "true")

    @route_get("/overlay-poison")
    async def _boom(request, response):
        request.params["poison"] = _UnrenderablePoison()
        raise RuntimeError("handler boom marker")

    response = _dispatch(_scope(path="/overlay-poison"))
    body = (response.content or b"").decode("utf-8", "replace")

    assert response.status_code == 500, "dispatch must still serve a 500 when the overlay throws"
    assert POISON_MARKER not in body
    assert "handler boom marker" not in body
    assert "Traceback" not in body
