# Tests for tina4_python.core.middleware.RateLimiter (v3)
import time
import pytest
from tina4_python.core.middleware import RateLimiter
from tina4_python.core.response import Response


@pytest.fixture
def clean_rate_env(monkeypatch):
    """Remove rate limiter env vars so defaults apply."""
    monkeypatch.delenv("TINA4_RATE_LIMIT", raising=False)
    monkeypatch.delenv("TINA4_RATE_WINDOW", raising=False)


class TestRateLimiterDefaults:

    def test_default_limit(self, clean_rate_env):
        rl = RateLimiter()
        assert rl.limit == 100

    def test_default_window(self, clean_rate_env):
        rl = RateLimiter()
        assert rl.window == 60


class TestRateLimiterEnvConfig:

    def test_custom_limit(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "50")
        rl = RateLimiter()
        assert rl.limit == 50

    def test_custom_window(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_WINDOW", "30")
        rl = RateLimiter()
        assert rl.window == 30


class TestRateLimiterCheck:

    def test_first_request_allowed(self, clean_rate_env):
        rl = RateLimiter()
        allowed, info = rl.check("192.168.1.1")
        assert allowed is True

    def test_info_has_limit_field(self, clean_rate_env):
        rl = RateLimiter()
        _, info = rl.check("192.168.1.1")
        assert "limit" in info
        assert info["limit"] == 100

    def test_info_has_remaining_field(self, clean_rate_env):
        rl = RateLimiter()
        _, info = rl.check("192.168.1.1")
        assert "remaining" in info

    def test_info_has_reset_field(self, clean_rate_env):
        rl = RateLimiter()
        _, info = rl.check("192.168.1.1")
        assert "reset" in info

    def test_info_has_window_field(self, clean_rate_env):
        rl = RateLimiter()
        _, info = rl.check("192.168.1.1")
        assert "window" in info

    def test_remaining_decreases(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "10")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        _, info1 = rl.check("10.0.0.1")
        _, info2 = rl.check("10.0.0.1")
        assert info2["remaining"] < info1["remaining"]

    def test_exceeds_limit_blocked(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "3")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        for _ in range(3):
            rl.check("10.0.0.1")
        allowed, info = rl.check("10.0.0.1")
        assert allowed is False
        assert info["remaining"] == 0

    def test_different_ips_independent(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "2")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        rl.check("10.0.0.1")
        rl.check("10.0.0.1")
        # IP 1 is at limit, IP 2 should still be allowed
        allowed, _ = rl.check("10.0.0.2")
        assert allowed is True


class TestRateLimiterHeaders:

    def test_apply_headers_sets_limit(self, clean_rate_env):
        rl = RateLimiter()
        resp = Response()
        info = {"limit": 100, "remaining": 99, "reset": 60}
        rl.apply_headers(resp, info)
        header_dict = dict(resp._headers)
        assert header_dict.get("x-ratelimit-limit") == "100"

    def test_apply_headers_sets_remaining(self, clean_rate_env):
        rl = RateLimiter()
        resp = Response()
        info = {"limit": 100, "remaining": 50, "reset": 60}
        rl.apply_headers(resp, info)
        header_dict = dict(resp._headers)
        assert header_dict.get("x-ratelimit-remaining") == "50"

    def test_apply_headers_sets_reset(self, clean_rate_env):
        rl = RateLimiter()
        resp = Response()
        info = {"limit": 100, "remaining": 50, "reset": 30}
        rl.apply_headers(resp, info)
        header_dict = dict(resp._headers)
        assert header_dict.get("x-ratelimit-reset") == "30"


class TestRateLimiterCleanup:

    def test_cleanup_removes_expired_ips(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "100")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "1")
        rl = RateLimiter()
        rl.check("10.0.0.1")
        # Simulate time passage by manipulating timestamps
        now = time.monotonic()
        rl._requests["10.0.0.1"] = [now - 10]  # expired
        rl._cleanup(now)
        assert "10.0.0.1" not in rl._requests

    def test_cleanup_keeps_active_ips(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "100")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        rl.check("10.0.0.1")
        now = time.monotonic()
        rl._cleanup(now)
        assert "10.0.0.1" in rl._requests
