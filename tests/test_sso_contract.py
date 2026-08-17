"""Feature 136 — provider-neutral OIDC and Tina4 Session handoff."""
import http.cookiejar
import html
import os
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

import pytest

from tina4_python.session import FileSessionHandler, Session
from tina4_python.sso import Sso, SsoError
from tina4_python.core.router import Router
from tina4_python.test_client import TestClient


def options():
    issuer = os.environ.get("TINA4_TEST_OIDC_ISSUER", "http://127.0.0.1:58080/realms/tina4-contract")
    return dict(
        issuer=issuer, client_id="tina4-app", client_secret="tina4-secret",
        redirect_uri="http://127.0.0.1:7145/auth/callback",
    )


def session(path):
    value = Session(FileSessionHandler(path))
    value.start()
    return value


def test_surface_and_configuration_fail_closed():
    contract = __import__("json").loads((Path(__file__).parent / "fixtures" / "sso_contract.json").read_text())
    assert contract["adr"] == "ADR-0056" and len(contract["invariants"]) == 10
    value = Sso(**options())
    assert all(callable(getattr(value, method)) for method in (
        "discover", "login", "callback", "identity", "refresh", "logout"
    ))
    assert Sso._safe_return("/dashboard") == "/dashboard"
    assert Sso._safe_return("https://evil.example") == "/"
    assert Sso._safe_return("//evil.example") == "/"
    with pytest.raises(SsoError):
        Sso(**{**options(), "issuer": "http://identity.example/realm"})
    with pytest.raises(SsoError, match="cryptography capability"):
        Sso(**{**options(), "verify": "jwks"})


def test_reserved_sso_values_never_appear_in_session_all():
    with tempfile.TemporaryDirectory() as directory:
        value = session(directory)
        value.set("cart", [1])
        value.set(Sso.PENDING_KEY, {"state": "secret-state"})
        value.set(Sso.SESSION_KEY, {"access_token": "secret-token"})
        assert value.all() == {"cart": [1]}


def test_sso_session_feeds_the_existing_secured_route_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path))
    current = session(str(tmp_path))
    current.set(Sso.SESSION_KEY, {"identity": {
        "issuer": options()["issuer"], "subject": "user-1", "roles": [], "groups": [],
    }})
    current.save()

    async def handler(request, response):
        return response.json({"subject": request.user["subject"]})

    Router.get("/sso-contract-secured", handler).secure()
    result = TestClient().get("/sso-contract-secured", headers={
        "Cookie": f"tina4_session={current.session_id}",
    })
    assert result.status == 200
    assert result.json() == {"subject": "user-1"}


class StopAtCallback(HTTPRedirectHandler):
    def __init__(self, callback):
        self.callback = callback
        self.location = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(self.callback):
            self.location = newurl
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def browser_code(login_url, callback):
    stopper = StopAtCallback(callback)
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), stopper)
    page = opener.open(login_url, timeout=10).read().decode()
    # The disposable provider advertises production-style Secure cookies even
    # on its loopback-only HTTP lab listener. A real deployment is HTTPS. Let
    # the lab browser return those cookies over this private loopback socket.
    for cookie in jar:
        cookie.secure = False
    match = re.search(r'<form[^>]+action="([^"]+)"[^>]*>', page)
    assert match, "real provider login form was not found"
    action = html.unescape(match.group(1))
    try:
        opener.open(Request(action, data=urlencode({
            "username": "andre", "password": "tina4-pass", "credentialId": "",
        }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10)
    except HTTPError as exc:
        assert exc.code in (302, 303)
    assert stopper.location, "provider did not redirect to the configured callback"
    return {key: values[0] for key, values in parse_qs(urlparse(stopper.location).query).items()}


@pytest.mark.skipif(not os.environ.get("TINA4_REQUIRE_OIDC"), reason="real OIDC gate runs on the lab")
def test_real_oidc_pkce_callback_session_refresh_and_logout():
    value = Sso.from_issuer(**options())
    with tempfile.TemporaryDirectory() as directory:
        current = session(directory)
        current.set("cart", [42])
        old_id = current.session_id
        login_url = value.login(current, "/dashboard")
        query = parse_qs(urlparse(login_url).query)
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        callback_query = browser_code(login_url, value.redirect_uri)
        result = value.callback(current, callback_query)
        assert current.session_id != old_id
        assert current.get("cart") == [42]
        assert result["return_to"] == "/dashboard"
        assert result["identity"]["username"] == "andre"
        assert "admin" in result["identity"]["roles"]
        assert "developer" in result["identity"]["roles"]
        assert result["identity"]["groups"] == ["/engineering"]
        assert Sso.SESSION_KEY not in current.all()
        refreshed = value.refresh(current)
        assert refreshed["subject"] == result["identity"]["subject"]
        logout_url = value.logout(current, "/")
        assert current.session_id is None
        assert "logout" in logout_url
