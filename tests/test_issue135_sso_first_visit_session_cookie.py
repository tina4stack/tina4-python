# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue #135 - a first-visit ``Sso.login()`` must send the session cookie.

On a visitor's first request ``Sso.login()`` stores the pending sign-in state
(state, nonce, PKCE verifier) in a NEW session. The response stage skipped a
new session whenever ``session.all()`` was empty, and ``all()`` deliberately
hides the reserved ``_tina4_sso`` / ``_tina4_sso_pending`` keys - so a session
holding ONLY the pending state looked empty and went out with no cookie. The
provider then redirected back to a callback with a fresh session and the
sign-in failed. Anyone who already had a session never saw it.

The contract pinned here: a new session holding ANY data, reserved SSO keys
included, is saved and its cookie sent; a new session holding nothing is still
never persisted (no orphaned session per anonymous request).

NO MOCKS: a real local OIDC discovery endpoint (http.server on a real socket),
tina4's own ``Sso.login()``, served by a REAL uvicorn child over real HTTP.
"""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

ROUTES = textwrap.dedent('''
    import os
    from tina4_python.core.router import get, noauth
    from tina4_python.sso import Sso

    sso = Sso(
        issuer=os.environ["ISSUE135_ISSUER"], client_id="issue135-app",
        client_secret="issue135-secret", redirect_uri="http://127.0.0.1:7145/sso/callback",
    )


    @noauth()
    @get("/issue135/login")
    async def login(request, response):
        return response({"authorize_at": sso.login(request)})


    @noauth()
    @get("/issue135/pending")
    async def pending(request, response):
        value = request.session.get(Sso.PENDING_KEY) or {}
        return response({"state": value.get("state")})


    @noauth()
    @get("/issue135/anonymous")
    async def anonymous(request, response):
        return response("no session use")
''')

SERVE = textwrap.dedent('''
    import os
    import uvicorn
    from tina4_python.core.server import asgi

    uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["ISSUE135_PORT"]), log_level="warning")
''')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def issuer():
    """A real OIDC discovery document served on a real loopback socket."""

    class Discovery(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}/realms/issue135"
            if self.path != "/realms/issue135/.well-known/openid-configuration":
                self.send_error(404)
                return
            body = json.dumps({
                "issuer": base,
                "authorization_endpoint": f"{base}/protocol/openid-connect/auth",
                "token_endpoint": f"{base}/protocol/openid-connect/token",
                "introspection_endpoint": f"{base}/protocol/openid-connect/token/introspect",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Discovery)
    base = f"http://127.0.0.1:{httpd.server_address[1]}/realms/issue135"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield base
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def server(tmp_path_factory, issuer):
    project = tmp_path_factory.mktemp("issue135_project")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "issue135.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE)
    sessions = project / "sessions"
    port = _free_port()
    env = {
        **os.environ,
        "ISSUE135_PORT": str(port),
        "ISSUE135_ISSUER": issuer,
        "TINA4_DEBUG": "false",
        "TINA4_SECRET": "issue135-contract-secret-0123456789abcdef",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(sessions),
        "TINA4_NO_BROWSER": "true",
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
            pytest.fail(f"issue135 uvicorn child never became ready (exit={process.poll()})")
        yield {"base": f"http://127.0.0.1:{port}", "sessions": sessions}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _browser():
    jar = http.cookiejar.CookieJar()
    return jar, urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def test_first_visit_sso_login_sends_the_session_cookie(server):
    jar, browser = _browser()
    with browser.open(f"{server['base']}/issue135/login", timeout=10) as response:
        assert response.status == 200
        set_cookie = response.headers.get_all("Set-Cookie") or []
        authorize_at = json.loads(response.read())["authorize_at"]
    assert any(value.startswith("tina4_session=") for value in set_cookie), (
        "Sso.login() stored the pending state in a new session, but the response "
        "carried no session cookie: the callback would arrive without it (#135)"
    )

    # The cookie must lead back to the SAME pending state the provider was sent.
    state = parse_qs(urlparse(authorize_at).query)["state"][0]
    with browser.open(f"{server['base']}/issue135/pending", timeout=10) as response:
        assert json.loads(response.read()) == {"state": state}, (
            "the returning browser did not get the session holding the pending SSO state"
        )


def test_a_first_visit_that_never_touches_the_session_still_sets_no_cookie(server):
    """Negative case: the orphaned-session guard must survive the fix."""
    before = set(os.listdir(server["sessions"])) if server["sessions"].exists() else set()
    with urllib.request.urlopen(f"{server['base']}/issue135/anonymous", timeout=10) as response:
        assert response.status == 200
        assert not response.headers.get_all("Set-Cookie"), "an untouched new session sent a cookie"
    after = set(os.listdir(server["sessions"])) if server["sessions"].exists() else set()
    assert after == before, "an untouched new session was persisted to the store"
