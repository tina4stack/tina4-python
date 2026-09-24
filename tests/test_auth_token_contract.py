"""Auth-token rules: the cross-framework contract (ADR-0079).

The answer key is tina4-documentation/plan/v3/fixtures/auth_token_contract.json.
Each test name below is a `case` in that fixture, and the SAME case names appear
in the PHP, Ruby and Node suites:

  tina4-php/tests/AuthTokenContractTest.php
  tina4-ruby/spec/auth_token_contract_spec.rb
  tina4-nodejs/test/authTokenContract.test.ts

Everything runs through the real front controller (`server.handle` with a real
`Request.from_scope`), real Frond form tokens, real HMAC, real file sessions and
real child processes for the boot checks. No mocks.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

import tina4_python.core.server as server
from tina4_python.auth import Auth, get_token, refresh_token
from tina4_python.core.request import Request
from tina4_python.core.router import Router, get as route_get, post as route_post, noauth, secured

SECRET = "auth-token-contract-secret-0123456789abcdef"  # 42 bytes


@pytest.fixture(autouse=True)
def _app(monkeypatch, tmp_path):
    Router.clear()
    monkeypatch.setenv("TINA4_SECRET", SECRET)
    monkeypatch.delenv("TINA4_API_KEY", raising=False)
    monkeypatch.delenv("TINA4_CSRF", raising=False)
    monkeypatch.setenv("TINA4_SESSION_BACKEND", "file")
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))

    @noauth()
    @route_post("/contract/session")
    async def _store(request, response):
        # Writes whatever the test hands it into the real session, then the
        # response mints the session cookie.
        for key, value in (request.body or {}).items():
            request.session.set(key, value)
        return response({"ok": True})

    @route_post("/contract/write")
    async def _write(request, response):
        return response({"user": request.user})

    @secured()
    @route_get("/contract/read")
    async def _read(request, response):
        return response({"user": request.user})

    yield
    Router.clear()


def _call(method, path, *, cookie=None, body=None, headers=None, client=("127.0.0.1", 1)):
    raw = json.dumps(body).encode() if body is not None else b""
    header_list = []
    for key, value in (headers or {}).items():
        header_list.append((key.lower().encode(), value.encode()))
    if cookie:
        header_list.append((b"cookie", cookie.encode()))
    if raw:
        header_list.append((b"content-type", b"application/json"))
    scope = {
        "type": "http", "method": method, "path": path, "query_string": b"",
        "scheme": "http", "headers": header_list, "client": client,
    }
    return asyncio.run(server.handle(Request.from_scope(scope, raw)))


def _header(response, name):
    return [v for k, v in response._headers if k.lower() == name.lower()]


def _session_cookie(values: dict) -> str:
    stored = _call("POST", "/contract/session", body=values)
    assert stored.status_code == 200, stored.content
    cookie = "; ".join(c.split(";")[0] for c in _header(stored, "set-cookie"))
    assert cookie, "the session route minted no cookie"
    return cookie


def _form_token() -> str:
    from tina4_python.frond.engine import _generate_form_jwt
    return _generate_form_jwt("")


def _hs256(payload: dict, key: bytes) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    sig = b64(hmac.new(key, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


# ── auth-form-token-is-not-identity ─────────────────────────────────────


def test_a_form_token_in_the_bearer_header_is_refused_by_the_route_gate():
    res = _call("POST", "/contract/write", headers={"Authorization": f"Bearer {_form_token()}"})
    assert res.status_code == 401


def test_a_form_token_in_the_body_is_refused_by_the_route_gate():
    res = _call("POST", "/contract/write", body={"formToken": _form_token()})
    assert res.status_code == 401
    assert _header(res, "FreshToken") == []


def test_a_form_token_in_the_session_is_refused_by_the_route_gate():
    cookie = _session_cookie({"token": _form_token()})
    assert _call("GET", "/contract/read", cookie=cookie).status_code == 401


def test_a_form_token_in_the_body_falls_through_to_the_session_token():
    cookie = _session_cookie({"token": get_token({"user_id": 7})})
    res = _call("POST", "/contract/write", cookie=cookie, body={"formToken": _form_token()})
    assert res.status_code == 200, res.content
    assert json.loads(res.content)["user"]["user_id"] == 7


def test_a_form_token_is_refused_on_a_secured_websocket_upgrade():
    from tina4_python.websocket import ws_authorized
    form = _form_token()
    route = {"auth_required": True}
    assert ws_authorized(route, {"authorization": f"Bearer {form}"}) == (None, False)
    assert ws_authorized(route, {}, subprotocol=f"bearer, {form}") == (None, False)
    assert ws_authorized(route, {}, query_string=f"token={form}") == (None, False)
    payload, ok = ws_authorized(route, {"authorization": f"Bearer {get_token({'user_id': 3})}"})
    assert ok is True and payload["user_id"] == 3


def test_a_form_token_is_refused_by_authenticate_request():
    assert Auth.authenticate_request({"authorization": f"Bearer {_form_token()}"}) is None
    assert Auth.authenticate_request({"authorization": f"Bearer {get_token({'user_id': 4})}"})["user_id"] == 4


def test_refresh_never_issues_a_fresh_token_from_a_form_token():
    # The gate earns no FreshToken from a form token...
    res = _call("POST", "/contract/write", body={"formToken": _form_token()})
    assert _header(res, "FreshToken") == []
    # ...and refresh preserves purpose: a refreshed form token is still a form
    # token (CSRF rotation), so it is still refused as an identity.
    rotated = refresh_token(_form_token())
    assert Auth.valid_token_static(rotated)["type"] == "form"
    assert _call("POST", "/contract/write", headers={"Authorization": f"Bearer {rotated}"}).status_code == 401
    assert Auth.valid_token_static(refresh_token(get_token({"user_id": 5})))["user_id"] == 5


def test_an_auth_token_still_passes_the_route_gate():
    token = get_token({"user_id": 9})
    bearer = _call("POST", "/contract/write", headers={"Authorization": f"Bearer {token}"})
    assert bearer.status_code == 200
    body = _call("POST", "/contract/write", body={"formToken": token})
    assert body.status_code == 200
    assert _header(body, "FreshToken"), "an auth token in the body still earns a FreshToken"


def test_a_form_token_still_passes_csrf(monkeypatch):
    from tina4_python.core.middleware import CsrfMiddleware

    # CSRF skips @noauth routes, so the realistic case is a logged-in user
    # (auth token in the session) posting a rendered form: the form token
    # satisfies CSRF, the session satisfies the route gate.
    @route_post("/contract/csrf", middleware=[CsrfMiddleware])
    async def _csrf(request, response):
        return response({"user": request.user})

    cookie = _session_cookie({"token": get_token({"user_id": 11})})
    passed = _call("POST", "/contract/csrf", cookie=cookie, body={"formToken": _form_token()})
    assert passed.status_code == 200, passed.content
    assert json.loads(passed.content)["user"]["user_id"] == 11
    assert _call("POST", "/contract/csrf", cookie=cookie, body={}).status_code == 403
    # A form token in the Bearer slot is not an API-client identity, so it does
    # not skip the CSRF check either.
    bearer_form = _call("POST", "/contract/csrf", cookie=cookie, body={},
                        headers={"Authorization": f"Bearer {_form_token()}"})
    assert bearer_form.status_code == 403


# ── auth-secret-strength ────────────────────────────────────────────────


def test_signing_with_a_blank_secret_is_refused(monkeypatch):
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    with pytest.raises(ValueError, match=r"TINA4_SECRET.*openssl rand -hex 32"):
        get_token({"user_id": 1})
    with pytest.raises(ValueError, match="TINA4_SECRET"):
        Auth(secret="").get_token({"user_id": 1})


def test_signing_with_a_secret_shorter_than_32_bytes_is_refused():
    with pytest.raises(ValueError, match="32 bytes"):
        Auth(secret="x" * 31).get_token({"user_id": 1})


def test_a_token_forged_with_the_empty_key_is_rejected(monkeypatch):
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    forged = _hs256({"user_id": 1, "exp": int(time.time()) + 600}, b"")
    assert Auth.valid_token_static(forged) is None
    assert Auth(secret="").valid_token(forged) is None
    assert _call("POST", "/contract/write", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_a_weak_key_rejection_names_the_fix(capfd):
    # Rejection alone is guaranteed twice over (the signer refuses too); the
    # verifier's own check is what TELLS the operator why every token fails.
    token = _hs256({"user_id": 1}, b"short")
    assert Auth(secret="short").valid_token(token) is None
    out, err = capfd.readouterr()
    assert "at least 32 bytes" in out + err and "openssl rand -hex 32" in out + err


def test_a_32_byte_secret_signs_and_verifies():
    auth = Auth(secret="k" * 32)
    assert auth.valid_token(auth.get_token({"user_id": 2}))["user_id"] == 2


def _boot(tmp_path, env_lines: str):
    """Boot a real server in a child process; return (exit code, output)."""
    (tmp_path / ".env").write_text(env_lines, encoding="utf-8")
    (tmp_path / "src" / "routes").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_")}
    env.update({"TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true", "PORT": "58917"})
    code = textwrap.dedent("""
        from tina4_python.core.server import run
        run(port=58917, no_browser=True, no_reload=True)
    """)
    try:
        proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:  # it booted and kept serving
        return None, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    return proc.returncode, proc.stdout + proc.stderr


def test_boot_outside_dev_refuses_a_blank_secret(tmp_path):
    code, output = _boot(tmp_path, "TINA4_DEBUG=false\n")
    assert code not in (0, None), output
    assert "TINA4_SECRET" in output and "openssl rand -hex 32" in output


def test_boot_outside_dev_refuses_a_short_secret(tmp_path):
    code, output = _boot(tmp_path, "TINA4_DEBUG=false\nTINA4_SECRET=too-short\n")
    assert code not in (0, None), output
    assert "TINA4_SECRET" in output and "32 bytes" in output


# ── empty-peer-is-not-loopback ──────────────────────────────────────────


def test_an_empty_peer_is_not_loopback():
    from tina4_python.mcp import is_loopback
    assert is_loopback("") is False
    assert is_loopback(None) is False


def test_a_loopback_peer_is_loopback():
    from tina4_python.mcp import is_loopback
    for address in ("127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1", "localhost"):
        assert is_loopback(address) is True, address
    for address in ("10.0.0.1", "0.0.0.0", "192.168.1.5", "::ffff:10.0.0.1"):
        assert is_loopback(address) is False, address


def test_an_empty_peer_is_refused_by_the_mcp_gate(monkeypatch):
    from tina4_python.mcp import is_request_allowed
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.delenv("TINA4_MCP", raising=False)
    monkeypatch.delenv("TINA4_MCP_REMOTE", raising=False)
    assert is_request_allowed("", False) is False
    assert is_request_allowed("127.0.0.1", False) is True


# ── sso-identity-expires ────────────────────────────────────────────────


def _sso(expires_at):
    # "marker" is a plain key: a brand-new session holding ONLY reserved keys is
    # deliberately not persisted, so the fixture gives it one ordinary value.
    return {"marker": 1, "_tina4_sso": {"version": 1, "expires_at": expires_at,
                           "identity": {"issuer": "https://idp.example", "subject": "u-1"}}}


def test_an_expired_sso_identity_is_refused():
    cookie = _session_cookie(_sso(int(time.time()) - 5))
    assert _call("GET", "/contract/read", cookie=cookie).status_code == 401


def test_a_live_sso_identity_passes():
    live = _call("GET", "/contract/read", cookie=_session_cookie(_sso(int(time.time()) + 300)))
    assert live.status_code == 200
    assert json.loads(live.content)["user"]["subject"] == "u-1"
    no_lifetime = _call("GET", "/contract/read", cookie=_session_cookie(_sso(0)))
    assert no_lifetime.status_code == 200


# ── form-token-lifetime ─────────────────────────────────────────────────


def test_a_form_token_lives_token_limit_minutes(monkeypatch):
    monkeypatch.delenv("TINA4_TOKEN_EXPIRES_IN", raising=False)
    monkeypatch.setenv("TINA4_TOKEN_LIMIT", "5")
    payload = Auth.valid_token_static(_form_token())
    assert payload["exp"] - payload["iat"] == 5 * 60


# ── Python-only regression found while proving the rules above ──────────


def test_a_middleware_kwarg_does_not_open_a_write_route():
    """@post(path, middleware=[...]) used to set auth_required=False, so adding
    any middleware through the kwarg made a write route public (ADR-0019 had
    already removed the same bypass from Router.add and @middleware)."""
    from tina4_python.core.middleware import CsrfMiddleware

    @route_post("/contract/with-middleware", middleware=[CsrfMiddleware])
    async def _handler(request, response):
        return response({"ok": True})

    route, _ = Router.match("POST", "/contract/with-middleware")
    assert route["auth_required"] is True
    assert _call("POST", "/contract/with-middleware", body={}).status_code == 401
