# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue #134 - ``asgi()`` must attach the same security middleware as ``run()``.

``run()`` registers ``SecurityHeadersMiddleware`` unconditionally and, when
``TINA4_CSRF=true``, ``CsrfMiddleware``. ``asgi()`` - the documented entry for
uvicorn / hypercorn / granian - attached neither, so the same app:

  * shipped NO security headers in production (no CSP, nosniff or frame
    options), and
  * accepted a cross-site forged POST that carried only the session cookie
    (200), where ``run()`` refuses it (403). ``TINA4_CSRF=true`` was set and
    silently not enforced.

NO MOCKS: a real project on disk, served by a REAL uvicorn in a child process
from ``asgi()``, driven over real HTTP. A child process also means no global
middleware registered by another test can leak in and hide the bug.
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

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import get, noauth, post
    from tina4_python.frond.engine import _generate_form_jwt


    @get("/issue134/page")
    async def page(request, response):
        return response("<!doctype html><title>route</title><p>hello</p>")


    @noauth()
    @get("/issue134/sign-in")
    async def sign_in(request, response):
        # What Sso.callback() stores after a real sign-in: enough to pass the
        # write-route auth gate with nothing but the session cookie.
        request.session.set("_tina4_sso", {"identity": {"issuer": "https://idp.example", "subject": "user-1"}})
        request.session.set("name", "Ada")
        return response("signed in")


    @get("/issue134/form-token")
    async def form_token(request, response):
        return response({"token": _generate_form_jwt(session_id=request.session.session_id)})


    @post("/issue134/transfer")
    async def transfer(request, response):
        return response({"moved": True})
''')

SERVE = textwrap.dedent('''
    import os
    import uvicorn
    from tina4_python.core.server import asgi

    uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["ISSUE134_PORT"]), log_level="warning")
''')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    project = tmp_path_factory.mktemp("issue134_project")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "issue134.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE)
    port = _free_port()
    env = {
        **os.environ,
        "ISSUE134_PORT": str(port),
        "TINA4_CSRF": "true",
        "TINA4_DEBUG": "false",
        "TINA4_SECRET": "issue134-contract-secret",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
        "TINA4_NO_BROWSER": "true",
    }
    env.pop("TINA4_CSP", None)
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
            pytest.fail(f"issue134 uvicorn child never became ready (exit={process.poll()})")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _signed_in_opener(base):
    """A real cookie-carrying client that has signed in once."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(f"{base}/issue134/sign-in", timeout=10).read()
    assert any(cookie.name == "tina4_session" for cookie in jar), "sign-in did not set a session cookie"
    return opener


def _post(opener, url, headers=None):
    request = urllib.request.Request(
        url, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_asgi_sends_the_security_headers(server):
    with urllib.request.urlopen(f"{server}/issue134/page", timeout=10) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
    missing = [name for name in SECURITY_HEADERS if name not in headers]
    assert not missing, f"asgi() served a route without {missing} - run() sends them (#134)"
    assert headers["x-content-type-options"] == "nosniff"


def test_asgi_refuses_a_forged_post_with_only_the_session_cookie(server):
    status, body = _post(_signed_in_opener(server), f"{server}/issue134/transfer")
    assert status == 403, (
        f"TINA4_CSRF=true, yet a POST carrying only the session cookie and no form "
        f"token got {status} under asgi(); run() answers 403 (#134). Body: {body[:200]!r}"
    )
    assert b"CSRF" in body


def test_asgi_accepts_the_same_post_with_a_valid_form_token(server):
    """Positive case: CSRF gates the forgery, not the real form."""
    opener = _signed_in_opener(server)
    token = json.loads(opener.open(f"{server}/issue134/form-token", timeout=10).read())["token"]
    status, body = _post(opener, f"{server}/issue134/transfer", {"X-Form-Token": token})
    assert status == 200, f"a POST with a valid form token was refused: {status} {body[:200]!r}"
    assert json.loads(body) == {"moved": True}
