# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""``run()`` and ``asgi()`` share ONE bootstrap - configured SSO routes included.

#134 found ``asgi()`` skipping the security middleware ``run()`` attaches. The
same drift hid a second gap: ``run()`` mounts the canonical OIDC routes
(``/auth/login``, ``/auth/callback``, ``/auth/logout``) when ``TINA4_SSO_*`` is
configured, and ``asgi()`` did not, so under uvicorn ``/auth/login`` was a 404.
Each gap was the symptom; two hand-maintained boot sequences were the cause.
Both entry points now call ``_bootstrap_application()``, and this file pins it:

  * behaviourally - the SAME project, served by ``asgi()`` under uvicorn and by
    ``run()``, redirects ``/auth/login`` to the provider's authorize endpoint;
  * structurally - both functions call the shared bootstrap, and neither
    re-grows a private copy of its steps.

NO MOCKS: a real OIDC discovery document on a real socket, real child servers,
real HTTP.
"""
import ast
import inspect
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import get


    @get("/bootstrap/page")
    async def page(request, response):
        return response("ok")
''')

SERVE = {
    "asgi": textwrap.dedent('''
        import os
        import uvicorn
        from tina4_python.core.server import asgi

        uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["BOOTSTRAP_PORT"]), log_level="warning")
    '''),
    "run": textwrap.dedent('''
        import os
        from tina4_python.core.server import run

        run(host="127.0.0.1", port=int(os.environ["BOOTSTRAP_PORT"]), no_browser=True)
    '''),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def issuer():
    """A real OIDC discovery document served on a real loopback socket."""

    class Discovery(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}/realms/bootstrap"
            if self.path != "/realms/bootstrap/.well-known/openid-configuration":
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
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/realms/bootstrap"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module", params=["asgi", "run"])
def server(request, tmp_path_factory, issuer):
    entry = request.param
    project = tmp_path_factory.mktemp(f"bootstrap_{entry}")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "bootstrap.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE[entry])
    port = _free_port()
    env = {
        **os.environ,
        "BOOTSTRAP_PORT": str(port),
        "TINA4_DEBUG": "false",
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEFAULT_WEBSERVER": "true",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_AUTO_MIGRATE": "false",
        "TINA4_SECRET": "bootstrap-contract-secret",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
        "TINA4_SSO_ISSUER": issuer,
        "TINA4_SSO_CLIENT_ID": "bootstrap-app",
        "TINA4_SSO_CLIENT_SECRET": "bootstrap-secret",
        "TINA4_SSO_REDIRECT_URI": f"http://127.0.0.1:{port}/auth/callback",
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
        yield {"entry": entry, "base": f"http://127.0.0.1:{port}", "issuer": issuer}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_configured_sso_login_route_is_mounted(server):
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        opener.open(f"{server['base']}/auth/login", timeout=10)
        status, location = 200, None
    except urllib.error.HTTPError as error:
        status, location = error.code, error.headers.get("Location")
    assert status in (302, 303), (
        f"{server['entry']}(): GET /auth/login answered {status} with TINA4_SSO_* "
        "configured - the canonical SSO routes were not mounted"
    )
    authorize = urlparse(location)
    assert f"{authorize.scheme}://{authorize.netloc}{authorize.path}" == (
        f"{server['issuer']}/protocol/openid-connect/auth"
    )
    assert parse_qs(authorize.query)["client_id"] == ["bootstrap-app"]


def test_discovered_routes_still_answer(server):
    with urllib.request.urlopen(f"{server['base']}/bootstrap/page", timeout=10) as response:
        assert response.status == 200
        assert response.read() == b"ok"


def _calls(function) -> set:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_run_and_asgi_share_one_bootstrap():
    """Structural lock: one boot sequence, called from both entry points."""
    from tina4_python.core import server as server_module

    for entry in (server_module.run, server_module.asgi):
        calls = _calls(entry)
        assert "_bootstrap_application" in calls, f"{entry.__name__}() does not call the shared bootstrap"
        private_copies = calls & {"_auto_discover", "_attach_security_middleware", "_auto_wire_i18n"}
        assert not private_copies, (
            f"{entry.__name__}() calls {sorted(private_copies)} itself - a private copy of the "
            "boot sequence is how asgi() drifted from run() (#134)"
        )
