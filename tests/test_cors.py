# Tests for tina4_python.core.middleware.CorsMiddleware (v3)
import os
import pytest
from tina4_python.core.middleware import CorsMiddleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all CORS env vars so defaults apply."""
    for key in (
        "TINA4_CORS_ORIGINS", "TINA4_CORS_METHODS",
        "TINA4_CORS_HEADERS", "TINA4_CORS_MAX_AGE",
        "TINA4_CORS_CREDENTIALS",
    ):
        monkeypatch.delenv(key, raising=False)


class TestCorsDefaults:

    def test_default_origins_is_wildcard(self, clean_env):
        cors = CorsMiddleware()
        assert cors.origins == "*"

    def test_default_methods_includes_common_verbs(self, clean_env):
        cors = CorsMiddleware()
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            assert method in cors.methods

    def test_default_headers_includes_content_type(self, clean_env):
        cors = CorsMiddleware()
        assert "Content-Type" in cors.headers

    def test_default_headers_includes_authorization(self, clean_env):
        cors = CorsMiddleware()
        assert "Authorization" in cors.headers

    def test_default_max_age(self, clean_env):
        cors = CorsMiddleware()
        assert cors.max_age == "86400"

    def test_default_credentials_is_true(self, clean_env):
        cors = CorsMiddleware()
        assert cors.credentials is True


class TestCorsEnvConfig:

    def test_custom_origins(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://example.com")
        cors = CorsMiddleware()
        assert cors.origins == "https://example.com"

    def test_custom_methods(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_METHODS", "GET,POST")
        cors = CorsMiddleware()
        assert cors.methods == "GET,POST"

    def test_custom_headers(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_HEADERS", "X-Custom")
        cors = CorsMiddleware()
        assert cors.headers == "X-Custom"

    def test_custom_max_age(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_MAX_AGE", "3600")
        cors = CorsMiddleware()
        assert cors.max_age == "3600"

    def test_credentials_false(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_CREDENTIALS", "false")
        cors = CorsMiddleware()
        assert cors.credentials is False

    def test_credentials_zero(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_CREDENTIALS", "0")
        cors = CorsMiddleware()
        assert cors.credentials is False


class TestAllowedOrigin:

    def test_wildcard_returns_star(self, clean_env):
        cors = CorsMiddleware()
        assert cors.allowed_origin("https://anything.com") == "*"

    def test_specific_origin_match(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://app.example.com")
        cors = CorsMiddleware()
        assert cors.allowed_origin("https://app.example.com") == "https://app.example.com"

    def test_specific_origin_no_match(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://app.example.com")
        cors = CorsMiddleware()
        assert cors.allowed_origin("https://evil.com") == ""

    def test_multiple_origins(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://a.com, https://b.com")
        cors = CorsMiddleware()
        assert cors.allowed_origin("https://b.com") == "https://b.com"
        assert cors.allowed_origin("https://c.com") == ""


class TestApply:

    def test_apply_sets_allow_origin(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.headers = {"origin": "https://example.com"}
        resp = Response()
        cors.apply(req, resp)
        header_names = [h[0] for h in resp._headers]
        assert "access-control-allow-origin" in header_names

    def test_apply_sets_allow_methods(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.headers = {"origin": "https://example.com"}
        resp = Response()
        cors.apply(req, resp)
        header_dict = dict(resp._headers)
        assert "access-control-allow-methods" in header_dict

    def test_apply_sets_max_age(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.headers = {"origin": "https://example.com"}
        resp = Response()
        cors.apply(req, resp)
        header_dict = dict(resp._headers)
        assert header_dict.get("access-control-max-age") == "86400"

    def test_no_credentials_header_when_wildcard(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.headers = {"origin": "https://example.com"}
        resp = Response()
        cors.apply(req, resp)
        header_dict = dict(resp._headers)
        assert "access-control-allow-credentials" not in header_dict

    def test_credentials_header_for_specific_origin(self, monkeypatch):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", "https://app.com")
        monkeypatch.setenv("TINA4_CORS_CREDENTIALS", "true")
        cors = CorsMiddleware()
        req = Request()
        req.headers = {"origin": "https://app.com"}
        resp = Response()
        cors.apply(req, resp)
        header_dict = dict(resp._headers)
        assert header_dict.get("access-control-allow-credentials") == "true"


class TestIsPreflight:

    def test_options_with_required_headers_is_preflight(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.method = "OPTIONS"
        req.headers = {
            "origin": "https://example.com",
            "access-control-request-method": "POST",
        }
        assert cors.is_preflight(req) is True

    def test_get_request_is_not_preflight(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.method = "GET"
        req.headers = {"origin": "https://example.com"}
        assert cors.is_preflight(req) is False

    def test_options_without_origin_is_not_preflight(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.method = "OPTIONS"
        req.headers = {"access-control-request-method": "POST"}
        assert cors.is_preflight(req) is False

    def test_options_without_request_method_is_not_preflight(self, clean_env):
        cors = CorsMiddleware()
        req = Request()
        req.method = "OPTIONS"
        req.headers = {"origin": "https://example.com"}
        assert cors.is_preflight(req) is False
