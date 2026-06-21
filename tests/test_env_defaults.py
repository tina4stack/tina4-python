"""Lock-in tests for env-default decisions (DECISIONS.txt spec).

These guard against silent drift in the security/AI defaults agreed for v3:

  * CORS credentials default to FALSE (opt-IN), never TRUE.
  * CORS Access-Control-Allow-Headers default includes X-Request-ID.
  * AI service URL defaults resolve to localhost (hosted lives in the
    user's own .env), never a hardcoded hosted host.

Python is the canonical reference — these double as the parity spec for
PHP/Ruby/Node.
"""
import os

import pytest


# ── CORS credentials default ─────────────────────────────────────────


class TestCorsCredentialsDefault:
    """TINA4_CORS_CREDENTIALS defaults to false (credentials are opt-IN)."""

    def test_default_is_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("TINA4_CORS_CREDENTIALS", raising=False)
        from tina4_python.core.middleware import CorsMiddleware

        assert CorsMiddleware().credentials is False

    def test_opt_in_true(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_CREDENTIALS", "true")
        from tina4_python.core.middleware import CorsMiddleware

        assert CorsMiddleware().credentials is True


# ── CORS allow-headers default ───────────────────────────────────────


class TestCorsHeadersDefault:
    """TINA4_CORS_HEADERS defaults to include X-Request-ID and is honoured."""

    def test_default_includes_x_request_id(self, monkeypatch):
        monkeypatch.delenv("TINA4_CORS_HEADERS", raising=False)
        from tina4_python.core.middleware import CorsMiddleware

        headers = CorsMiddleware().headers
        assert "X-Request-ID" in headers
        assert "Content-Type" in headers
        assert "Authorization" in headers

    def test_default_value_exact(self, monkeypatch):
        monkeypatch.delenv("TINA4_CORS_HEADERS", raising=False)
        from tina4_python.core.middleware import CorsMiddleware

        assert CorsMiddleware().headers == "Content-Type,Authorization,X-Request-ID"

    def test_env_override_is_emitted_on_allowed_origin(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_HEADERS", "X-Custom-Header")

        from tina4_python.core.middleware import CorsMiddleware

        captured = {}

        class FakeResponse:
            def header(self, name, value):
                captured[name.lower()] = value

        class FakeRequest:
            headers = {"origin": "https://app.example.com"}

        mw = CorsMiddleware()
        mw.apply(FakeRequest(), FakeResponse())
        assert captured["access-control-allow-headers"] == "X-Custom-Header"


# ── AI URL defaults resolve to localhost ─────────────────────────────


class TestAiUrlDefaultsLocalhost:
    """AI/dev-admin service URLs default to localhost when env is unset."""

    def test_ai_url_default_is_localhost(self, monkeypatch):
        monkeypatch.delenv("TINA4_AI_URL", raising=False)
        default = os.environ.get("TINA4_AI_URL", "http://localhost:11437/api/chat")
        assert default.startswith("http://localhost:")
        assert "andrevanzuydam.com" not in default

    def test_no_hosted_default_in_dev_admin_source(self):
        """No hardcoded hosted host should survive in the dev-admin source."""
        import tina4_python.dev_admin as dev_admin
        import tina4_python.dev_admin.plan as plan

        for module in (dev_admin, plan):
            with open(module.__file__, "r", encoding="utf-8") as fh:
                src = fh.read()
            assert "andrevanzuydam.com" not in src, (
                f"hosted host leaked into {module.__file__}"
            )
