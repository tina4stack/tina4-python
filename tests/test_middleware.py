# Tests for tina4_python.core.middleware
import os
import time
import pytest
from tina4_python.core.middleware import CorsMiddleware, RateLimiter


class MockRequest:
    """Minimal request stub for middleware tests."""

    def __init__(self, method="GET", headers=None, ip="127.0.0.1"):
        self.method = method
        self.headers = headers or {}
        self.ip = ip


class MockResponse:
    """Minimal response stub for middleware tests."""

    def __init__(self):
        self._headers = {}
        self.status_code = 200

    def header(self, name, value):
        self._headers[name] = value
        return self

    def status(self, code):
        self.status_code = code
        return self


# ── CORS Tests ──────────────────────────────────────────────────


class TestCorsMiddleware:
    """Positive tests for CORS middleware."""

    def test_default_allows_all_origins(self):
        cors = CorsMiddleware()
        assert cors.allowed_origin("https://example.com") == "*"

    def test_apply_sets_cors_headers(self):
        cors = CorsMiddleware()
        req = MockRequest(headers={"origin": "https://example.com"})
        resp = MockResponse()
        cors.apply(req, resp)
        assert resp._headers["access-control-allow-origin"] == "*"
        assert "GET" in resp._headers["access-control-allow-methods"]
        assert "Content-Type" in resp._headers["access-control-allow-headers"]

    def test_specific_origin_allowed(self):
        os.environ["TINA4_CORS_ORIGINS"] = "https://app.com,https://admin.com"
        try:
            cors = CorsMiddleware()
            assert cors.allowed_origin("https://app.com") == "https://app.com"
            assert cors.allowed_origin("https://admin.com") == "https://admin.com"
        finally:
            del os.environ["TINA4_CORS_ORIGINS"]

    def test_credentials_header_for_specific_origin(self):
        os.environ["TINA4_CORS_ORIGINS"] = "https://app.com"
        try:
            cors = CorsMiddleware()
            req = MockRequest(headers={"origin": "https://app.com"})
            resp = MockResponse()
            cors.apply(req, resp)
            assert resp._headers.get("access-control-allow-credentials") == "true"
        finally:
            del os.environ["TINA4_CORS_ORIGINS"]

    def test_preflight_detection(self):
        cors = CorsMiddleware()
        req = MockRequest(
            method="OPTIONS",
            headers={
                "origin": "https://app.com",
                "access-control-request-method": "POST",
            },
        )
        assert cors.is_preflight(req) is True

    def test_custom_max_age(self):
        os.environ["TINA4_CORS_MAX_AGE"] = "3600"
        try:
            cors = CorsMiddleware()
            req = MockRequest(headers={"origin": "https://app.com"})
            resp = MockResponse()
            cors.apply(req, resp)
            assert resp._headers["access-control-max-age"] == "3600"
        finally:
            del os.environ["TINA4_CORS_MAX_AGE"]


class TestCorsMiddlewareNegative:
    """Negative tests for CORS middleware."""

    def test_disallowed_origin(self):
        os.environ["TINA4_CORS_ORIGINS"] = "https://app.com"
        try:
            cors = CorsMiddleware()
            assert cors.allowed_origin("https://evil.com") == ""
        finally:
            del os.environ["TINA4_CORS_ORIGINS"]

    def test_no_origin_header(self):
        cors = CorsMiddleware()
        req = MockRequest(headers={})
        resp = MockResponse()
        cors.apply(req, resp)
        # Still sets * since default is allow all
        assert resp._headers["access-control-allow-origin"] == "*"

    def test_not_preflight_without_request_method(self):
        cors = CorsMiddleware()
        req = MockRequest(method="OPTIONS", headers={"origin": "https://app.com"})
        assert cors.is_preflight(req) is False

    def test_not_preflight_for_get(self):
        cors = CorsMiddleware()
        req = MockRequest(
            method="GET",
            headers={
                "origin": "https://app.com",
                "access-control-request-method": "GET",
            },
        )
        assert cors.is_preflight(req) is False


# ── Rate Limiter Tests ──────────────────────────────────────────


class TestRateLimiter:
    """Positive tests for rate limiter."""

    def test_allows_under_limit(self):
        limiter = RateLimiter()
        limiter.limit = 10
        limiter.window = 60
        allowed, info = limiter.check("10.0.0.1")
        assert allowed is True
        assert info["remaining"] >= 0

    def test_tracks_remaining(self):
        limiter = RateLimiter()
        limiter.limit = 5
        limiter.window = 60
        for i in range(3):
            limiter.check("10.0.0.2")
        allowed, info = limiter.check("10.0.0.2")
        assert allowed is True
        assert info["remaining"] == 1

    def test_separate_ips(self):
        limiter = RateLimiter()
        limiter.limit = 2
        limiter.window = 60
        limiter.check("10.0.0.3")
        limiter.check("10.0.0.3")
        # IP .3 is at limit, but .4 should be fine
        allowed, _ = limiter.check("10.0.0.4")
        assert allowed is True

    def test_headers_applied(self):
        limiter = RateLimiter()
        limiter.limit = 100
        resp = MockResponse()
        info = {"limit": 100, "remaining": 99, "reset": 60}
        limiter.apply_headers(resp, info)
        assert resp._headers["x-ratelimit-limit"] == "100"
        assert resp._headers["x-ratelimit-remaining"] == "99"
        assert resp._headers["x-ratelimit-reset"] == "60"

    def test_env_config(self):
        os.environ["TINA4_RATE_LIMIT"] = "50"
        os.environ["TINA4_RATE_WINDOW"] = "30"
        try:
            limiter = RateLimiter()
            assert limiter.limit == 50
            assert limiter.window == 30
        finally:
            del os.environ["TINA4_RATE_LIMIT"]
            del os.environ["TINA4_RATE_WINDOW"]


class TestRateLimiterNegative:
    """Negative tests for rate limiter."""

    def test_blocks_over_limit(self):
        limiter = RateLimiter()
        limiter.limit = 3
        limiter.window = 60
        for _ in range(3):
            limiter.check("10.0.0.5")
        allowed, info = limiter.check("10.0.0.5")
        assert allowed is False
        assert info["remaining"] == 0

    def test_blocked_response_has_reset(self):
        limiter = RateLimiter()
        limiter.limit = 1
        limiter.window = 60
        limiter.check("10.0.0.6")
        allowed, info = limiter.check("10.0.0.6")
        assert allowed is False
        assert info["reset"] > 0

    def test_window_expiry(self):
        limiter = RateLimiter()
        limiter.limit = 1
        limiter.window = 1  # 1 second window
        limiter.check("10.0.0.7")
        # Should be blocked
        allowed, _ = limiter.check("10.0.0.7")
        assert allowed is False
        # Wait for window to expire
        time.sleep(1.1)
        allowed, _ = limiter.check("10.0.0.7")
        assert allowed is True
