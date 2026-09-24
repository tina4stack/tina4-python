"""Medium security finding F6 — X-Forwarded-Host must only be honoured when the
raw socket peer is a trusted proxy (TINA4_TRUSTED_PROXIES).

An untrusted client can otherwise forge X-Forwarded-Host and control the absolute
``request.url`` the app builds — the base for password-reset links, cache keys and
open-redirect targets. The existing trusted-proxy gate covered X-Forwarded-For
only; this pins the same rule for the host. Case names match the sibling
regressions in tina4-nodejs/test/forwardedHostTrust.test.ts,
tina4-php/tests/ForwardedHostTrustTest.php and
tina4-ruby/spec/forwarded_host_trust_spec.rb.

TestClient dispatches a real ASGI scope whose socket peer is 127.0.0.1, so
"is the peer trusted?" is controlled purely by listing (or not) that address.
No mocks.
"""
import pytest

from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


@pytest.fixture
def url_probe(monkeypatch):
    monkeypatch.delenv("TINA4_TRUSTED_PROXIES", raising=False)

    async def handler(request, response):
        return response({"url": request.url})

    Router.add("GET", "/forwarded-host-probe", handler)
    return TestClient()


def _probe(client, host):
    return client.get(
        "/forwarded-host-probe",
        headers={"X-Forwarded-Host": host},
    ).json()["url"]


class TestForwardedHostTrust:
    def test_forwarded_host_ignored_from_an_untrusted_peer(self, url_probe):
        # No TINA4_TRUSTED_PROXIES: the header is attacker-controlled noise and
        # must not reach request.url.
        url = _probe(url_probe, "evil.com")
        assert "evil.com" not in url, (
            f"forged X-Forwarded-Host leaked into request.url: {url}"
        )

    def test_forwarded_host_honoured_from_a_trusted_proxy(self, url_probe, monkeypatch):
        # Positive twin: behind a declared proxy the forwarded host is used, or
        # the fix would break real deployments.
        monkeypatch.setenv("TINA4_TRUSTED_PROXIES", "127.0.0.1/8")
        url = _probe(url_probe, "app.example.com")
        assert "app.example.com" in url, (
            f"forwarded host not honoured behind a trusted proxy: {url}"
        )
