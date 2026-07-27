"""Session cookie Secure attribute — wire-level, proxy-aware (#95).

The bug: ``core/server._finalize_response`` hand-wrote the ``Set-Cookie`` header
itself and never called ``Session.cookie_header()``, so ``TINA4_SESSION_SECURE``
was a silent no-op and there was no proxy-aware ``Secure`` at all. On an HTTPS
deploy the session cookie shipped WITHOUT ``Secure``.

These tests read the ACTUAL ``Set-Cookie`` the server emits — a test against
``cookie_header()`` alone would pass even with the bug, because the builder was
already correct; only the untested hand-written server path shipped. So:

  * a REAL child server over a real loopback socket (the exact emit path that
    ships) proves the scheme matrix: plain http => no Secure; X-Forwarded-Proto:
    http => no Secure; X-Forwarded-Proto: https => Secure; and the comma-chain
    first-hop rule;
  * a second REAL child server booted with TINA4_SESSION_SECURE=true proves the
    env knob now actually forces Secure on plain http;
  * the in-process REAL dispatch (``handle()`` -> ``_finalize_response``) proves
    SameSite=None => Secure;
  * pure-logic asserts on ``Request.is_secure_scheme()`` guard the detection.

No mocks: every assertion is against a header a real server (or the real
in-process dispatch pipeline) emitted.
"""

import http.client
import subprocess
from pathlib import Path

from conftest import boot_child_server

import pytest

from tina4_python.core.request import Request
from tina4_python.core.router import Router
from tina4_python.core.server import handle

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── real child-server helpers (mirror test_server_parity.py) ───────────────

def _boot_session_server(tmp_path: Path, extra_env: dict | None = None):
    """Start a REAL child server exposing GET /session/touch, which writes to the
    session so the framework emits the Set-Cookie. Returns (proc, port).

    Boots through the shared conftest helper, which retries a lost port race and
    reports the child's own output on a real failure. Caller terminates proc.
    """
    def write_app(proj: Path, port: int) -> None:
        (proj / "app.py").write_text(
            "from tina4_python import get\n"
            "from tina4_python.core.server import start\n\n"
            "@get('/session/touch')\n"
            "async def touch(request, response):\n"
            "    request.session.set('hit', '1')\n"
            "    return response('ok')\n\n"
            f"start(port={port}, no_browser=True, no_reload=True)\n"
        )

    def env_for(port: int) -> dict:
        env = {"TINA4_SESSION_PATH": str(tmp_path / f"srv_{port}" / "sessions")}
        if extra_env:
            env.update(extra_env)
        return env

    # Never let the outer test env force Secure unless a case asks for it.
    return boot_child_server(
        tmp_path, write_app, extra_env=env_for,
        unset_env=("TINA4_SESSION_SECURE", "TINA4_SESSION_SAMESITE"),
    )


def _set_cookie_for(port: int, forwarded_proto: str | None = None,
                    timeout: float = 5.0) -> str:
    """GET /session/touch over a real socket and return the tina4_session
    Set-Cookie header value the server actually emitted."""
    headers = {}
    if forwarded_proto is not None:
        headers["X-Forwarded-Proto"] = forwarded_proto
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/session/touch", headers=headers)
        resp = conn.getresponse()
        resp.read()
        cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        for c in cookies:
            if c.startswith("tina4_session="):
                return c
        return ""
    finally:
        conn.close()


def _terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── wire-level proof: the scheme matrix over a real server ─────────────────

def test_session_cookie_secure_on_the_wire(tmp_path):
    """The REAL server's Set-Cookie carries Secure iff the client is on https,
    detected proxy-aware from X-Forwarded-Proto. Plain http never gets Secure."""
    proc, port = _boot_session_server(tmp_path)
    try:
        # Negative: plain http, no proxy header — MUST NOT be Secure (a Secure
        # cookie over plain http is undeliverable and would break the session).
        plain = _set_cookie_for(port)
        assert plain.startswith("tina4_session="), plain
        assert "Secure" not in plain, f"plain http must not be Secure: {plain!r}"
        # The other hardening attributes still ride along.
        assert "HttpOnly" in plain
        assert "SameSite=Lax" in plain

        # Negative: proxy says the client hop was plain http.
        fwd_http = _set_cookie_for(port, "http")
        assert "Secure" not in fwd_http, f"X-Forwarded-Proto: http => no Secure: {fwd_http!r}"

        # Positive: proxy says the client hop was https (TLS terminated at the
        # proxy) — the cookie MUST be Secure. This is the bug: it never was.
        fwd_https = _set_cookie_for(port, "https")
        assert "Secure" in fwd_https, f"X-Forwarded-Proto: https => Secure: {fwd_https!r}"

        # Comma chain: the FIRST hop is the client-facing scheme.
        chain_https_first = _set_cookie_for(port, "https, http")
        assert "Secure" in chain_https_first, chain_https_first
        chain_http_first = _set_cookie_for(port, "http, https")
        assert "Secure" not in chain_http_first, chain_http_first
    finally:
        _terminate(proc)


def test_session_cookie_secure_env_forces_secure_over_plain_http(tmp_path):
    """TINA4_SESSION_SECURE=true forces Secure even on plain http — the knob the
    issue reported as a silent no-op now actually changes the emitted cookie."""
    proc, port = _boot_session_server(tmp_path, {"TINA4_SESSION_SECURE": "true"})
    try:
        cookie = _set_cookie_for(port)  # plain http, no proxy header
        assert cookie.startswith("tina4_session="), cookie
        assert "Secure" in cookie, f"TINA4_SESSION_SECURE=true must force Secure: {cookie!r}"
    finally:
        _terminate(proc)


# ── in-process real dispatch: SameSite=None => Secure ──────────────────────

def _set_cookie_from_response(response) -> str:
    for name, value in response._headers:
        if name.lower() == "set-cookie" and value.startswith("tina4_session="):
            return value
    return ""


async def test_samesite_none_forces_secure_via_real_dispatch(tmp_path, monkeypatch):
    """SameSite=None requires Secure (browsers reject None without it). Proven
    through the real dispatch pipeline (handle() -> _finalize_response), the
    exact code that ships — not the builder in isolation."""
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))
    monkeypatch.setenv("TINA4_SESSION_SAMESITE", "None")
    monkeypatch.delenv("TINA4_SESSION_SECURE", raising=False)
    Router.clear()

    async def touch(request, response):
        request.session.set("hit", "1")
        return response("ok")

    Router.get("/session/touch", touch)
    try:
        req = Request()
        req.method = "GET"
        req.path = "/session/touch"
        req.headers = {}  # plain http, no forwarded header
        resp = await handle(req)
        cookie = _set_cookie_from_response(resp)
        assert cookie.startswith("tina4_session="), cookie
        assert "SameSite=None" in cookie, cookie
        assert "Secure" in cookie, f"SameSite=None must force Secure: {cookie!r}"
    finally:
        Router.clear()


async def test_plain_http_dispatch_stays_insecure(tmp_path, monkeypatch):
    """Guard the negative through the real dispatch too: default env + plain
    http => the emitted cookie is NOT Secure."""
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))
    monkeypatch.delenv("TINA4_SESSION_SECURE", raising=False)
    monkeypatch.delenv("TINA4_SESSION_SAMESITE", raising=False)
    Router.clear()

    async def touch(request, response):
        request.session.set("hit", "1")
        return response("ok")

    Router.get("/session/touch", touch)
    try:
        req = Request()
        req.method = "GET"
        req.path = "/session/touch"
        req.headers = {"x-forwarded-proto": "http"}
        resp = await handle(req)
        cookie = _set_cookie_from_response(resp)
        assert cookie.startswith("tina4_session="), cookie
        assert "Secure" not in cookie, f"plain/forwarded-http must not be Secure: {cookie!r}"
    finally:
        Router.clear()


# ── pure-logic guard on the detection itself (no dependency) ───────────────

def _req(headers=None, scheme="http") -> Request:
    r = Request()
    r.headers = headers or {}
    r.scheme = scheme
    return r


def test_is_secure_scheme_detection():
    """Request.is_secure_scheme() honours x-forwarded-proto (first hop of a
    comma chain), then the native scheme."""
    # No signal at all => not secure.
    assert _req().is_secure_scheme() is False
    # Native TLS (direct https to the app, no proxy header).
    assert _req(scheme="https").is_secure_scheme() is True
    # Proxy header wins over native scheme, both directions.
    assert _req({"x-forwarded-proto": "https"}, scheme="http").is_secure_scheme() is True
    assert _req({"x-forwarded-proto": "http"}, scheme="https").is_secure_scheme() is False
    # Comma chain: first hop is client-facing.
    assert _req({"x-forwarded-proto": "https, http"}).is_secure_scheme() is True
    assert _req({"x-forwarded-proto": "http, https"}).is_secure_scheme() is False
    # Case / whitespace insensitivity.
    assert _req({"x-forwarded-proto": " HTTPS "}).is_secure_scheme() is True


def test_cookie_header_secure_precedence(monkeypatch):
    """cookie_header() sets Secure on ANY of: env opt-in, SameSite=None, or a
    secure request; and stays insecure otherwise."""
    from tina4_python.session import Session

    monkeypatch.delenv("TINA4_SESSION_SECURE", raising=False)
    monkeypatch.delenv("TINA4_SESSION_SAMESITE", raising=False)
    s = Session()
    s.start("abc")

    # No request, default env => not Secure.
    assert "Secure" not in s.cookie_header()

    # Secure request object => Secure.
    assert "Secure" in s.cookie_header(request=_req(scheme="https"))
    assert "Secure" not in s.cookie_header(request=_req(scheme="http"))

    # Env opt-in => Secure even with an http request.
    monkeypatch.setenv("TINA4_SESSION_SECURE", "true")
    assert "Secure" in s.cookie_header(request=_req(scheme="http"))
    monkeypatch.delenv("TINA4_SESSION_SECURE", raising=False)

    # SameSite=None => Secure even over http.
    monkeypatch.setenv("TINA4_SESSION_SAMESITE", "None")
    header = s.cookie_header(request=_req(scheme="http"))
    assert "SameSite=None" in header and "Secure" in header
