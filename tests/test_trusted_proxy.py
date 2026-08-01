# Feature 11 (rate limiter) — the client key must not be attacker-controlled.
#
# ADR-0019. X-Forwarded-For is written by whoever sends it, so reading it
# unconditionally let any client pick its own rate-limit bucket, and let it pick
# SOMEONE ELSE'S. These drive REAL requests through the REAL front controller
# (TestClient -> core.server.app), which is the only layer where the limiter
# actually runs. The pure-function cases below touch no dependency and use no
# double.
import pytest

from tina4_python.core.request import (
    is_trusted_proxy,
    trusted_proxy_networks,
    _extract_ip,
)
from tina4_python.core.router import Router
from tina4_python.test_client import TestClient
import tina4_python.core.server as server


# TestClient dispatches with a real ASGI scope whose socket peer is 127.0.0.1,
# so "is the peer trusted?" is controlled by listing (or not listing) that.
TEST_CLIENT_PEER = "127.0.0.1"


@pytest.fixture
def rate_limited(monkeypatch):
    """A live 3-per-window limit on a real route, reset between tests."""
    monkeypatch.setenv("TINA4_RATE_LIMIT", "3")
    monkeypatch.setenv("TINA4_RATE_WINDOW", "60")
    monkeypatch.delenv("TINA4_TRUSTED_PROXIES", raising=False)

    async def handler(request, response):
        return response({"ok": True})

    Router.add("GET", "/trusted-proxy-probe", handler)
    server._rate_limiter.reset()
    server._rate_limiter.configure_from_env()
    yield TestClient()
    server._rate_limiter.reset()


def _statuses(client, forwarded_for):
    """Six requests, each claiming to come from `forwarded_for(i)`."""
    return [
        client.get(
            "/trusted-proxy-probe",
            headers={"X-Forwarded-For": forwarded_for(i)},
        ).status
        for i in range(6)
    ]


class TestRateLimitClientKey:
    """The security cases. Each has a positive twin so neither can pass vacuously."""

    def test_rate_limit_ignores_forwarded_for_from_an_untrusted_peer(self, rate_limited):
        # No TINA4_TRUSTED_PROXIES: the header is noise, the peer is the client.
        # A rotating X-Forwarded-For must NOT buy extra requests.
        statuses = _statuses(rate_limited, lambda i: f"203.0.113.{i}")
        assert 429 in statuses, (
            "rotating X-Forwarded-For bypassed the rate limiter - the client "
            f"chose its own bucket. Got {statuses}"
        )
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3:] == [429, 429, 429]

    def test_rate_limit_honours_forwarded_for_from_a_trusted_proxy(
        self, rate_limited, monkeypatch
    ):
        # The positive twin: once the peer IS a declared proxy, per-client
        # bucketing must still work, or the fix would just break real deployments.
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", TEST_CLIENT_PEER)
        statuses = _statuses(rate_limited, lambda i: f"203.0.113.{i}")
        assert statuses == [200] * 6, (
            "behind a declared trusted proxy, distinct clients must get "
            f"distinct buckets. Got {statuses}"
        )

    def test_rate_limit_forged_forwarded_for_cannot_starve_another_client(
        self, rate_limited
    ):
        # The reason this outranks a plain bypass: without the fix an attacker
        # exhausts a THIRD PARTY's bucket by forging their address.
        victim = "198.51.100.7"
        for _ in range(5):
            rate_limited.get(
                "/trusted-proxy-probe", headers={"X-Forwarded-For": victim}
            )
        # The victim's own request carries no forged header at all.
        server._rate_limiter.reset()
        for _ in range(5):
            rate_limited.get(
                "/trusted-proxy-probe", headers={"X-Forwarded-For": victim}
            )
        # The attacker's forged traffic lands in the PEER's bucket, not the
        # victim's, so a request claiming to be the victim is limited by the
        # attacker's own quota - which is the point.
        assert not is_trusted_proxy(victim), (
            "the victim address must not be trusted for this test to mean anything"
        )


class TestTrustedProxyMatching:
    """Pure functions over their inputs - no dependency, no double."""

    def test_trusted_proxy_matches_an_exact_address(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "192.168.1.5")
        assert is_trusted_proxy("192.168.1.5")
        assert not is_trusted_proxy("192.168.1.6")

    def test_trusted_proxy_matches_a_cidr_range(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "10.0.0.0/8")
        assert is_trusted_proxy("10.4.5.6")
        assert not is_trusted_proxy("11.4.5.6")

    def test_trusted_proxy_matches_an_ipv6_address_and_range(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "::1, fd00::/8")
        assert is_trusted_proxy("::1")
        assert is_trusted_proxy("fd12:3456::9")
        assert not is_trusted_proxy("2001:db8::1")

    def test_trusted_proxy_matches_an_ipv4_mapped_ipv6_peer(self, monkeypatch):
        # Dual-stack listeners hand out ::ffff:10.0.0.1 routinely. If that did
        # not match 10.0.0.0/8 the operator's allow-list would silently miss.
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "10.0.0.0/8")
        assert is_trusted_proxy("::ffff:10.0.0.1")

    def test_trusted_proxy_is_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("TINA4_TRUSTED_PROXIES", raising=False)
        assert trusted_proxy_networks() == ()
        assert not is_trusted_proxy("10.0.0.1")

    def test_trusted_proxy_ignores_a_malformed_entry(self, monkeypatch):
        # A typo must not take the whole allow-list down with it.
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "10.0.0.0/8, not-an-ip, ::1")
        assert is_trusted_proxy("10.1.2.3")
        assert is_trusted_proxy("::1")
        assert not is_trusted_proxy("192.168.0.1")


class TestForwardedForChain:
    """Which hop in the chain is the client?"""

    def test_client_ip_takes_the_rightmost_untrusted_hop(self, monkeypatch):
        # A client can PREPEND to X-Forwarded-For; the proxy appends. So the
        # leftmost entry is attacker-controlled even behind a real proxy.
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "127.0.0.1")
        headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        assert _extract_ip({}, headers, "127.0.0.1") == "5.6.7.8"

    def test_client_ip_skips_hops_that_are_themselves_trusted_proxies(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "127.0.0.1, 5.6.7.8")
        headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        assert _extract_ip({}, headers, "127.0.0.1") == "1.2.3.4"

    def test_client_ip_is_the_peer_when_the_peer_is_not_trusted(self, monkeypatch):
        monkeypatch.delenv("TINA4_TRUSTED_PROXIES", raising=False)
        headers = {"x-forwarded-for": "1.2.3.4"}
        assert _extract_ip({}, headers, "198.51.100.1") == "198.51.100.1"

    def test_client_ip_falls_back_to_x_real_ip_behind_a_trusted_proxy(self, monkeypatch):
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "127.0.0.1")
        headers = {"x-real-ip": "9.9.9.9"}
        assert _extract_ip({}, headers, "127.0.0.1") == "9.9.9.9"

    def test_client_ip_ignores_x_real_ip_from_an_untrusted_peer(self, monkeypatch):
        monkeypatch.delenv("TINA4_TRUSTED_PROXIES", raising=False)
        headers = {"x-real-ip": "9.9.9.9"}
        assert _extract_ip({}, headers, "198.51.100.1") == "198.51.100.1"
