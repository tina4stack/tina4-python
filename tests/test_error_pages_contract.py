# Configurable error pages — Accept-based negotiation, converged 403, request-id, escaping.
"""
Feature 42 (configurable error pages) conformance suite. See ERR-DEC-01/ERR-DEC-02 and
tina4-documentation/plan/v3/fixtures/error_pages_contract.json.

Driven through the REAL front controller (``tina4_python.core.server.app`` via
``TestClient``) - NO mocks. Real Accept headers, a real middleware denial for the 403
case, a real malicious path.

Cases (shared names, all four):
  1. prod_500_has_no_stack_and_a_request_id  - the LOCKED CWE-209 guarantee (do not
     reopen; re-proven here as part of this feature's negotiated 500 path).
  2. json_accept_yields_a_json_error_body    - Accept: application/json on 404/403/500
     -> {error,code,message,status,request_id}.
  3. browser_accept_yields_the_html_error_page - Accept: text/html or */* -> the HTML
     errors/{code}.twig page.
  4. the_403_renders_identically_across_the_four - a middleware denial now renders
     through the SAME negotiated path as 404/500 (was raw JSON with no request_id).
  5. a_custom_error_template_overrides_the_builtin - src/templates/errors/{code}.twig
     wins over the framework default, for 404 AND 500.
  6. a_reflected_path_in_an_error_page_is_escaped - a <script> path/query on 404/403/500
     never appears unescaped in the HTML body.
  7. the_404_carries_a_request_id - the negotiated JSON body carries request_id (PHP/
     Ruby/Node gained this; Python already had it in the template data).

Same case names in all four:
  tina4-php/tests/ErrorPagesContractTest.php
  tina4-ruby/spec/error_pages_contract_spec.rb
  tina4-nodejs/test/errorPagesContract.test.ts
"""
from __future__ import annotations

import os

os.environ.setdefault("TINA4_SECRET", "error-pages-feature-42-secret")

import pytest

import tina4_python.core.response as response_mod
from tina4_python.core.middleware import Middleware
from tina4_python.core.router import get as route_get, middleware as mw_decorator
from tina4_python.test_client import TestClient

SECRET_MARKER = "SECRET-500-TRACE-do-not-leak-e42a"


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """A clean router, clean middleware, TINA4_DEBUG off, and a FRESH Frond
    singleton bound to a scratch cwd - so an override test's src/templates/
    is genuinely picked up instead of a stale engine from an earlier test's
    cwd (the Frond singletons in core.response are process-global)."""
    from tina4_python.core.router import Router

    Router.clear()
    Middleware.reset()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TINA4_DEBUG", raising=False)
    response_mod._global_frond = None
    response_mod._framework_frond = None
    yield
    Router.clear()
    Middleware.reset()
    response_mod._global_frond = None
    response_mod._framework_frond = None


def _register_denying_route(path: str = "/blocked"):
    """A route behind a middleware that says no without setting its own
    response - the generic 403 fallback under test (ERR-403-SPLIT)."""

    class DenyAll:
        @staticmethod
        def before_deny(request, response):
            return False

    @mw_decorator(DenyAll)
    @route_get(path)
    async def _blocked(request, response):
        return response({"should": "never get here"})


def _register_boom_route(path: str = "/boom"):
    @route_get(path)
    async def _boom(request, response):
        raise RuntimeError(SECRET_MARKER)


# ------------------------------------------------------- 1. CWE-209, locked

def test_prod_500_has_no_stack_and_a_request_id():
    """The gated CWE-209 guarantee: production 500 leaks neither the message nor
    a traceback, and carries a request_id (on both the header and, now, the
    negotiated JSON body). DO NOT reopen this contract - only re-prove it."""
    _register_boom_route()
    client = TestClient()

    r = client.get("/boom")
    assert r.status == 500
    body_text = r.text()
    for marker in (SECRET_MARKER, "Traceback", 'File "', "RuntimeError"):
        assert marker not in body_text, f"CWE-209 regression: 500 body leaked {marker!r}"
    assert r.headers.get("x-request-id")

    r_json = client.get("/boom", headers={"Accept": "application/json"})
    assert r_json.status == 500
    body = r_json.json()
    assert SECRET_MARKER not in str(body)
    assert body["message"] == "Internal Server Error"
    assert body["request_id"]
    assert body["request_id"] == r_json.headers.get("x-request-id")


# --------------------------------------------- 2 & 3. content negotiation

@pytest.mark.parametrize("code,path,setup", [
    (404, "/does-not-exist", None),
    (403, "/blocked", _register_denying_route),
    (500, "/boom", _register_boom_route),
])
def test_json_accept_yields_a_json_error_body(code, path, setup):
    if setup:
        setup()
    r = TestClient().get(path, headers={"Accept": "application/json"})
    assert r.status == code
    assert "application/json" in r.content_type
    body = r.json()
    assert body["error"] is True
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["message"], str) and body["message"]
    assert body["status"] == code
    assert body["request_id"]


@pytest.mark.parametrize("code,path,setup,accept", [
    (404, "/does-not-exist", None, "text/html"),
    (404, "/does-not-exist", None, "*/*"),
    (403, "/blocked", _register_denying_route, "text/html"),
    (500, "/boom", _register_boom_route, "text/html"),
])
def test_browser_accept_yields_the_html_error_page(code, path, setup, accept):
    if setup:
        setup()
    r = TestClient().get(path, headers={"Accept": accept})
    assert r.status == code
    assert "text/html" in r.content_type
    assert f'"error-code">{code}<' in r.text()


# ------------------------------------------------------------ 4. 403 split

def test_the_403_renders_identically_across_the_four():
    """A middleware denial (no body of its own) now negotiates like 404/500,
    instead of the old bare/JSON-only shortcut - the SAME body shape a JSON
    client gets from 404/500, and the SAME HTML page shape a browser gets."""
    _register_denying_route()
    client = TestClient()

    r_json = client.get("/blocked", headers={"Accept": "application/json"})
    assert r_json.status == 403
    body = r_json.json()
    assert body == {
        "error": True, "code": "FORBIDDEN", "message": "Forbidden",
        "status": 403, "request_id": body["request_id"],
    }
    assert body["request_id"]

    r_html = client.get("/blocked", headers={"Accept": "text/html"})
    assert r_html.status == 403
    assert "text/html" in r_html.content_type
    assert '"error-code">403<' in r_html.text()


# ---------------------------------------------------- 5. override the built-in

def test_a_custom_error_template_overrides_the_builtin(tmp_path):
    errors_dir = tmp_path / "src" / "templates" / "errors"
    errors_dir.mkdir(parents=True)
    (errors_dir / "404.twig").write_text("CUSTOM-404 path={{ path }}")
    (errors_dir / "500.twig").write_text("CUSTOM-500 rid={{ request_id }}")
    response_mod._global_frond = None  # pick up the files just written

    _register_boom_route()
    client = TestClient()

    r404 = client.get("/nope")
    assert r404.status == 404
    assert "CUSTOM-404" in r404.text()

    r500 = client.get("/boom")
    assert r500.status == 500
    assert "CUSTOM-500" in r500.text()


# --------------------------------------------------- 6. reflected-path escaping

_MALICIOUS_PATH = "/<script>alert(1)</script>"
_MALICIOUS_URL = _MALICIOUS_PATH + '?x=%22onload%3D%22alert(2)'


@pytest.mark.parametrize("code,url,setup", [
    (404, _MALICIOUS_URL, None),
    (403, _MALICIOUS_PATH, _register_denying_route),
    (500, _MALICIOUS_PATH, _register_boom_route),
])
def test_a_reflected_path_in_an_error_page_is_escaped(code, url, setup):
    if setup:
        setup(_MALICIOUS_PATH)

    r = TestClient().get(url)
    assert r.status == code
    body = r.text()
    assert "<script>alert(1)</script>" not in body, f"XSS: raw <script> reflected in a {code} page"
    if code != 500:
        # 404/403 templates show {{ path }}; the built-in 500.twig does not
        # (only error_message/request_id, and error_message is empty in prod
        # per CWE-209) so there is nothing for it to reflect either way.
        assert "&lt;script&gt;" in body, "expected the escaped form (proves it WAS reflected, safely)"


# ------------------------------------------------------- 7. 404 request-id

def test_the_404_carries_a_request_id():
    r = TestClient().get("/does-not-exist", headers={"Accept": "application/json"})
    assert r.status == 404
    body = r.json()
    assert body["request_id"], "404 JSON body has no request_id"
    assert body["request_id"] == r.headers.get("x-request-id")
