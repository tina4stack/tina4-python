# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Every refusal carries the security headers - under ``run()`` and ``asgi()``.

The PHP worker found a CSRF 403 going out WITHOUT the security headers: CSRF
refused the request before the headers were added. Python had the same shape.
Global middleware runs in registration order, CSRF is attached before the
security headers, and a refusing ``before_*`` hook skips every hook after it -
so the CSRF 403 never reached ``SecurityHeadersMiddleware.before_security``.
The rate limiter answers before middleware runs at all, so its 429 had none
either. A refusal page is still a page: it can be framed and sniffed like any
other.

The contract: with the security middleware attached, EVERY response - route
refusals from CSRF, the auth gate, route middleware and the rate limiter
included - carries CSP, ``nosniff`` and ``X-Frame-Options``.

NO MOCKS: real child servers (uvicorn over ``asgi()``, and ``run()``'s own
server), real HTTP, real cookies and form tokens.
"""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

import pytest

SECURITY_HEADERS = ("content-security-policy", "x-content-type-options", "x-frame-options")
RATE_LIMIT = 40

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import get, middleware, noauth, post, secured
    from tina4_python.frond.engine import _generate_form_jwt


    class Deny:
        @staticmethod
        def before_deny(request, response):
            return request, response("denied", 403)


    @middleware(Deny)
    @get("/refusal/denied")
    async def denied(request, response):
        return response("never reached")


    @secured()
    @get("/refusal/secret")
    async def secret(request, response):
        return response("secret")


    @noauth()
    @get("/refusal/sign-in")
    async def sign_in(request, response):
        request.session.set("_tina4_sso", {"identity": {"issuer": "https://idp.example", "subject": "user-1"}})
        return response("signed in")


    @noauth()
    @get("/refusal/form-token")
    async def form_token(request, response):
        return response({"token": _generate_form_jwt()})


    @post("/refusal/write")
    async def write(request, response):
        return response({"written": True})
''')

SERVE = {
    "asgi": textwrap.dedent('''
        import os
        import uvicorn
        from tina4_python.core.server import asgi

        uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["REFUSAL_PORT"]), log_level="warning")
    '''),
    "run": textwrap.dedent('''
        import os
        from tina4_python.core.server import run

        run(host="127.0.0.1", port=int(os.environ["REFUSAL_PORT"]), no_browser=True)
    '''),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module", params=["asgi", "run"])
def server(request, tmp_path_factory):
    entry = request.param
    project = tmp_path_factory.mktemp(f"refusal_{entry}")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "refusal.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE[entry])
    port = _free_port()
    env = {
        **os.environ,
        "REFUSAL_PORT": str(port),
        "TINA4_CSRF": "true",
        "TINA4_RATE_LIMIT": str(RATE_LIMIT),
        "TINA4_RATE_WINDOW": "300",
        "TINA4_DEBUG": "false",
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEFAULT_WEBSERVER": "true",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_AUTO_MIGRATE": "false",
        "TINA4_SECRET": "refusal-contract-secret",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
    }
    process = subprocess.Popen([sys.executable, "serve.py"], cwd=str(project), env=env)
    try:
        deadline = time.time() + 20
        while time.time() < deadline and process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail(f"{entry} child server never became ready (exit={process.poll()})")
        yield {"entry": entry, "base": f"http://127.0.0.1:{port}"}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _send(opener, url, method="GET", headers=None):
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def _assert_refused_with_headers(server, label, status, headers, body, expected_status):
    assert status == expected_status, f"{server['entry']}(): {label} -> {status}: {body[:200]!r}"
    missing = [name for name in SECURITY_HEADERS if name not in headers]
    assert not missing, f"{server['entry']}(): the {label} refusal ({status}) was sent without {missing}"
    assert headers["x-content-type-options"] == "nosniff"


def test_csrf_refusal_of_an_anonymous_write_carries_the_headers(server):
    status, headers, body = _send(urllib.request.build_opener(), f"{server['base']}/refusal/write", "POST")
    _assert_refused_with_headers(server, "CSRF (no session)", status, headers, body, 403)
    assert b"CSRF" in body


def test_csrf_refusal_of_a_signed_in_forged_write_carries_the_headers(server):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(f"{server['base']}/refusal/sign-in", timeout=10).read()
    status, headers, body = _send(opener, f"{server['base']}/refusal/write", "POST")
    _assert_refused_with_headers(server, "CSRF (session cookie only)", status, headers, body, 403)
    assert b"CSRF" in body


def test_auth_gate_refusal_of_a_write_carries_the_headers(server):
    """A valid form token gets past CSRF; no credentials, so the auth gate says 401."""
    opener = urllib.request.build_opener()
    token = json.loads(opener.open(f"{server['base']}/refusal/form-token", timeout=10).read())["token"]
    status, headers, body = _send(opener, f"{server['base']}/refusal/write", "POST", {"X-Form-Token": token})
    _assert_refused_with_headers(server, "auth gate (write)", status, headers, body, 401)


def test_auth_gate_refusal_of_a_secured_read_carries_the_headers(server):
    status, headers, body = _send(urllib.request.build_opener(), f"{server['base']}/refusal/secret")
    _assert_refused_with_headers(server, "auth gate (secured GET)", status, headers, body, 401)


def test_route_middleware_refusal_carries_the_headers(server):
    status, headers, body = _send(urllib.request.build_opener(), f"{server['base']}/refusal/denied")
    _assert_refused_with_headers(server, "route middleware", status, headers, body, 403)


def test_rate_limit_refusal_carries_the_headers(server):
    """Last on purpose: it spends this server's whole rate budget."""
    opener = urllib.request.build_opener()
    for _ in range(RATE_LIMIT + 5):
        status, headers, body = _send(opener, f"{server['base']}/refusal/secret")
        if status == 429:
            break
    _assert_refused_with_headers(server, "rate limiter", status, headers, body, 429)
