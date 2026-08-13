# Default landing page — dev-only welcome page, 404-in-prod info-leak guard.
"""
Feature 46 conformance suite. See LAND-DEC-01/LAND-DEC-02 and
tina4-documentation/plan/v3/fixtures/landing_page_contract.json.

Driven through the REAL front controller (``tina4_python.core.server.app`` via
``TestClient``) - NO mocks. Real GET /, ``TINA4_DEBUG`` toggled for real.

Cases (shared names, all four):
  1. dev_mode_serves_the_branded_landing_page  - TINA4_DEBUG on, no user /
     route -> 200 + the branded banner.
  2. production_returns_404_and_leaks_nothing  - TINA4_DEBUG off -> 404, and
     the body carries NO framework version, NO /__dev link, NO gallery (the
     SECURITY case - LAND-PROD-DECIDED; this is the info-leak guard the prior
     doc's "allow it in production" recommendation would have reopened).
  3. a_user_root_route_always_wins - a registered GET / handler wins in BOTH
     dev and prod.
  4. a_pages_index_template_suppresses_the_landing - a
     src/templates/pages/index.* is served at / instead of the landing.

Same case names in all four:
  tina4-php/tests/LandingPageContractTest.php
  tina4-ruby/spec/landing_page_contract_spec.rb
  tina4-nodejs/test/landingPageContract.test.ts
"""
from __future__ import annotations

import pytest

from tina4_python import __version__
from tina4_python.core.router import get as route_get
from tina4_python.test_client import TestClient


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """A clean router, a scratch cwd (so a pages/index.* case is genuinely
    isolated), and TINA4_DEBUG unset by default."""
    from tina4_python.core.router import Router
    import tina4_python.core.server as srv

    Router.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TINA4_DEBUG", raising=False)
    srv._template_cache = None
    yield
    Router.clear()
    srv._template_cache = None


# ------------------------------------------------- 1. dev shows the banner

def test_dev_mode_serves_the_branded_landing_page(monkeypatch):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    r = TestClient().get("/")
    assert r.status == 200
    assert "Tina4Python" in r.text()


# ------------------------------------------- 2. prod 404s and leaks nothing

def test_production_returns_404_and_leaks_nothing(monkeypatch):
    monkeypatch.delenv("TINA4_DEBUG", raising=False)
    r = TestClient().get("/")
    assert r.status == 404
    body = r.text()
    assert "Tina4Python" not in body
    assert __version__ not in body
    assert "/__dev" not in body
    assert 'id="gallery"' not in body


# --------------------------------------------- 3. a user / route always wins

@pytest.mark.parametrize("debug", ["true", None], ids=["dev", "prod"])
def test_a_user_root_route_always_wins(monkeypatch, debug):
    if debug:
        monkeypatch.setenv("TINA4_DEBUG", debug)
    else:
        monkeypatch.delenv("TINA4_DEBUG", raising=False)

    @route_get("/")
    async def _user_root(request, response):
        return response("USER-ROOT-MARKER-PYTHON")

    r = TestClient().get("/")
    assert r.status == 200
    assert "USER-ROOT-MARKER-PYTHON" in r.text()
    assert "Tina4Python" not in r.text()


# ------------------------------------- 4. pages/index beats the landing

def test_a_pages_index_template_suppresses_the_landing(monkeypatch, tmp_path):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    pages_dir = tmp_path / "src" / "templates" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "index.twig").write_text("PAGES-INDEX-MARKER-PYTHON")

    r = TestClient().get("/")
    assert r.status == 200
    assert "PAGES-INDEX-MARKER-PYTHON" in r.text()
    assert "Tina4Python" not in r.text()
