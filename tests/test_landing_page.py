"""Regression tests for issue #39 — landing page, template auto-routing,
SPA index serving, and the 404 status line.

Covers:
- Template auto-routing only fires from ``src/templates/pages/``; partials,
  layouts, base.twig, errors, and ``_*`` files never auto-serve.
- ``TINA4_TEMPLATE_ROUTING=off`` is a hard kill switch.
- ``src/public/index.html`` auto-serves at ``/`` (the SPA case).
- The framework landing page only renders when ``TINA4_DEBUG=true``.
- The HTTP/1.1 status line uses the canonical RFC reason phrase per code
  (no more ``HTTP/1.1 404 OK``).
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from tina4_python.core.server import (
    _resolve_template,
    _build_template_cache,
    _try_static,
    _is_dev_mode,
    _http_reason,
    _template_auto_routing_enabled,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A throwaway project root with src/templates/, src/public/, etc."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "templates" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "templates" / "partials").mkdir(parents=True)
    (tmp_path / "src" / "public").mkdir(parents=True)
    # Reset the production cache between tests so each test sees a fresh scan
    import tina4_python.core.server as srv
    srv._template_cache = None
    yield tmp_path
    srv._template_cache = None


# ── 1. Template auto-routing scope ────────────────────────────


class TestTemplateAutoRoutingScope:
    """Only files under src/templates/pages/ become URLs."""

    def test_pages_index_serves_at_root(self, project, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/pages/index.twig").write_text("ok")
        assert _resolve_template("/") == "pages/index.twig"

    def test_pages_about_serves_at_about(self, project, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/pages/about.twig").write_text("ok")
        assert _resolve_template("/about") == "pages/about.twig"

    def test_pages_nested_serves_at_nested_url(self, project, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/pages/products").mkdir()
        (project / "src/templates/pages/products/list.twig").write_text("ok")
        assert _resolve_template("/products/list") == "pages/products/list.twig"

    def test_partials_never_serve(self, project, monkeypatch):
        """Files outside pages/ are NEVER URL-routable, even if URL matches."""
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/partials/nav.twig").write_text("partial")
        assert _resolve_template("/partials/nav") is None

    def test_layouts_never_serve(self, project, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates" / "layouts").mkdir()
        (project / "src/templates/layouts/main.twig").write_text("layout")
        assert _resolve_template("/layouts/main") is None

    def test_base_twig_at_root_never_serves(self, project, monkeypatch):
        """src/templates/base.twig used to be reachable as /base — no longer."""
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/base.twig").write_text("base")
        assert _resolve_template("/base") is None

    def test_errors_never_serve(self, project, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates" / "errors").mkdir()
        (project / "src/templates/errors/404.twig").write_text("err")
        assert _resolve_template("/errors/404") is None

    def test_underscore_prefixed_in_pages_skipped(self, project, monkeypatch):
        """Even inside pages/, _-prefixed files are private."""
        monkeypatch.setenv("TINA4_DEBUG", "true")
        (project / "src/templates/pages/_helper.twig").write_text("private")
        assert _resolve_template("/_helper") is None


class TestTemplateAutoRoutingProduction:
    """Same skip rules apply to the cache built in production mode."""

    def test_cache_only_indexes_pages(self, project, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (project / "src/templates/pages/about.twig").write_text("page")
        (project / "src/templates/partials/nav.twig").write_text("partial")
        (project / "src/templates/base.twig").write_text("base")

        _build_template_cache()
        import tina4_python.core.server as srv
        cache = srv._template_cache
        assert "about" in cache
        assert "partials/nav" not in cache
        assert "base" not in cache

    def test_resolve_uses_cache_in_prod(self, project, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (project / "src/templates/pages/contact.twig").write_text("page")
        assert _resolve_template("/contact") == "pages/contact.twig"


# ── 2. TINA4_TEMPLATE_ROUTING kill switch ─────────────────────


class TestTemplateRoutingKillSwitch:

    @pytest.mark.parametrize("value", ["off", "OFF", "false", "FALSE", "0", "no", "disabled"])
    def test_kill_switch_disables_auto_routing(self, project, monkeypatch, value):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        monkeypatch.setenv("TINA4_TEMPLATE_ROUTING", value)
        (project / "src/templates/pages/about.twig").write_text("ok")
        assert _resolve_template("/about") is None
        assert _template_auto_routing_enabled() is False

    @pytest.mark.parametrize("value", ["on", "true", "1", "yes", ""])
    def test_kill_switch_default_or_truthy_keeps_routing(self, project, monkeypatch, value):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        if value:
            monkeypatch.setenv("TINA4_TEMPLATE_ROUTING", value)
        else:
            monkeypatch.delenv("TINA4_TEMPLATE_ROUTING", raising=False)
        (project / "src/templates/pages/about.twig").write_text("ok")
        assert _resolve_template("/about") == "pages/about.twig"
        assert _template_auto_routing_enabled() is True


# ── 3. src/public/index.html SPA auto-serve ───────────────────


class TestSpaIndexHtmlAutoServe:
    """A Vite/SPA build with src/public/index.html should serve at /."""

    def test_root_serves_public_index_html(self, project):
        (project / "src/public/index.html").write_text("<!doctype html><h1>SPA</h1>")
        resp = _try_static("/")
        assert resp is not None, "root '/' did not pick up src/public/index.html"

    def test_subdirectory_index_html(self, project):
        """`/admin/` should serve `src/public/admin/index.html`."""
        (project / "src/public/admin").mkdir()
        (project / "src/public/admin/index.html").write_text("admin")
        resp = _try_static("/admin/")
        assert resp is not None

    def test_no_index_html_returns_none(self, project):
        """If no index.html, fall through to the next handler."""
        resp = _try_static("/")
        assert resp is None


# ── 4. Landing page hidden in production ──────────────────────


class TestLandingPageHidesInProduction:

    @pytest.mark.parametrize("value", ["true", "1", "yes"])
    def test_dev_mode_truthy_means_landing_visible(self, monkeypatch, value):
        monkeypatch.setenv("TINA4_DEBUG", value)
        assert _is_dev_mode() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_dev_mode_falsy_means_landing_hidden(self, monkeypatch, value):
        monkeypatch.setenv("TINA4_DEBUG", value)
        assert _is_dev_mode() is False

    def test_dev_mode_unset_default_is_off(self, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        assert _is_dev_mode() is False


# ── 5. HTTP/1.1 status reason phrases ─────────────────────────


class TestHttpStatusReasonPhrase:
    """Bug: dev server bridge wrote 'HTTP/1.1 404 OK' regardless of code."""

    def test_200_ok(self):
        assert _http_reason(200) == "OK"

    def test_404_not_found(self):
        assert _http_reason(404) == "Not Found"

    def test_500_internal_server_error(self):
        assert _http_reason(500) == "Internal Server Error"

    def test_302_found(self):
        assert _http_reason(302) == "Found"

    def test_401_unauthorized(self):
        assert _http_reason(401) == "Unauthorized"

    def test_403_forbidden(self):
        assert _http_reason(403) == "Forbidden"

    def test_429_too_many_requests(self):
        assert _http_reason(429) == "Too Many Requests"

    def test_unknown_2xx_falls_back_to_ok(self):
        assert _http_reason(299) == "OK"

    def test_unknown_5xx_falls_back_to_error(self):
        assert _http_reason(599) == "Error"

    def test_no_reason_phrase_is_ever_empty(self):
        for code in range(200, 600, 1):
            assert _http_reason(code), f"empty phrase for {code}"
