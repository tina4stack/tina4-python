# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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


class TestRateLimiterEnforcement:
    """Lock the enforcement entry points, not just check()/apply_headers().

    RateLimiter.apply() holds the enforcement path, and the two before_rate_limit
    staticmethods (the class-based middleware entry points) delegate to it. These
    entry points had no coverage before, so a refactor could quietly stop
    returning the 429 with nothing going red. Real Response object, plain request
    holder — no doubles.
    """

    def _request(self, ip="10.0.0.1"):
        import types
        return types.SimpleNamespace(ip=ip)

    def test_apply_allows_under_limit(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "3")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        resp = Response()
        _, out = rl.apply(self._request(), resp)
        assert out.status_code == 200
        assert dict(resp._headers).get("x-ratelimit-limit") == "3"

    def test_apply_refuses_over_limit_with_429_and_retry_after(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "3")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        rl = RateLimiter()
        req = self._request()
        statuses = []
        for _ in range(4):
            resp = Response()
            _, out = rl.apply(req, resp)
            statuses.append(out.status_code)
        assert statuses == [200, 200, 200, 429]
        # the refused response carries retry-after and the rate-limit headers
        assert dict(resp._headers).get("retry-after") is not None
        assert dict(resp._headers).get("x-ratelimit-remaining") == "0"

    def test_shared_before_rate_limit_refuses_over_limit(self, monkeypatch):
        monkeypatch.setenv("TINA4_RATE_LIMIT", "2")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        RateLimiter._shared_instance = None
        req = self._request("10.0.0.2")
        statuses = []
        for _ in range(3):
            resp = Response()
            _, out = RateLimiter.before_rate_limit(req, resp)
            statuses.append(out.status_code)
        RateLimiter._shared_instance = None
        assert statuses == [200, 200, 429]

    def test_middleware_before_rate_limit_refuses_over_limit(self, monkeypatch):
        from tina4_python.core.middleware import RateLimiterMiddleware
        monkeypatch.setenv("TINA4_RATE_LIMIT", "2")
        monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
        RateLimiterMiddleware._limiter = None
        req = self._request("10.0.0.3")
        statuses = []
        for _ in range(3):
            resp = Response()
            _, out = RateLimiterMiddleware.before_rate_limit(req, resp)
            statuses.append(out.status_code)
        RateLimiterMiddleware._limiter = None
        assert statuses == [200, 200, 429]
