"""Security headers on every response, from every entry point (ADR-0066).

The runner for the three ADR-0066 invariants in
tina4-documentation/plan/v3/fixtures/securityheaders_contract.json; the PHP,
Ruby and Node suites carry the same case names.

  * static files, the 404 and 405 fallbacks and the framework's own refusals
    carry the canonical security header set (#137);
  * a header a route already set is kept - only missing headers are filled in;
  * ``run()`` and ``asgi()`` attach the same middleware (security headers and
    CSRF) and mount the configured SSO routes, because both build the app
    through ``_bootstrap_application()`` (#134).

NO MOCKS: the same project served for real by ``run()``'s own server and by
uvicorn over ``asgi()``, real HTTP, and a real OIDC discovery document on a real
loopback socket for the SSO mount.
"""
import http.client
import json
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from conftest import boot_child_server

CANONICAL = ("x-frame-options", "x-content-type-options", "content-security-policy",
             "referrer-policy", "x-xss-protection", "permissions-policy")
ROUTE_CSP = "default-src 'none'; img-src 'self'"

ROUTES = textwrap.dedent(f'''
    from tina4_python.core.router import get, noauth, post


    @noauth()
    @get("/secure-contract/page")
    async def page(request, response):
        return response("page")


    @noauth()
    @get("/secure-contract/own-headers")
    async def own_headers(request, response):
        response.header("Content-Security-Policy", "{ROUTE_CSP}")
        response.header("X-Frame-Options", "DENY")
        return response("shaped by the route")


    @post("/secure-contract/write")
    async def write(request, response):
        return response({{"written": True}})
''')

APPS = {
    "run": "from tina4_python.core import run\nif __name__ == '__main__':\n    run()\n",
    "asgi": textwrap.dedent('''
        import os
        import uvicorn
        from tina4_python.core.server import asgi

        if __name__ == "__main__":
            uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["PORT"]), log_level="warning")
    '''),
}


@pytest.fixture(scope="module")
def issuer():
    """A real OIDC discovery document served on a real loopback socket."""

    class Discovery(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}/realms/contract"
            if self.path != "/realms/contract/.well-known/openid-configuration":
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
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/realms/contract"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module", params=list(APPS))
def served(request, tmp_path_factory, issuer):
    entry = request.param
    root = tmp_path_factory.mktemp(f"secure_contract_{entry}")

    def write_app(project_dir, port):
        (project_dir / "src" / "routes" / "secure_contract.py").write_text(ROUTES)
        public = project_dir / "src" / "public"
        public.mkdir(parents=True, exist_ok=True)
        (public / "hello.html").write_text("<!doctype html><title>static</title><p>static</p>")
        (project_dir / "app.py").write_text(APPS[entry])

    process, port = boot_child_server(
        root, write_app,
        extra_env=lambda port: {
            "TINA4_DEBUG": "false",
            "TINA4_AUTO_MIGRATE": "false",
            "TINA4_CSRF": "true",
            "TINA4_SECRET": "secure-contract-secret",
            "TINA4_SESSION_BACKEND": "file",
            "TINA4_SSO_ISSUER": issuer,
            "TINA4_SSO_CLIENT_ID": "secure-contract-app",
            "TINA4_SSO_CLIENT_SECRET": "secure-contract-secret",
            "TINA4_SSO_REDIRECT_URI": f"http://127.0.0.1:{port}/auth/callback",
        },
        unset_env=("TINA4_CSP", "TINA4_FRAME_OPTIONS", "TINA4_PUBLIC_DIR", "TINA4_RATE_LIMIT"),
        log_dir=root / "logs",
    )
    try:
        yield {"entry": entry, "port": port, "issuer": issuer}
    finally:
        process.terminate()
        process.wait(timeout=15)


def _send(served, method, path):
    connection = http.client.HTTPConnection("127.0.0.1", served["port"], timeout=15)
    body = b"{}" if method in ("POST", "PUT") else None
    connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
    reply = connection.getresponse()
    reply.read()
    connection.close()
    return reply.status, {name.lower(): value for name, value in reply.getheaders()}


def _assert_carries_the_set(served, label, status, headers, expected_status):
    assert status in expected_status, f"{served['entry']}(): {label} answered {status}"
    missing = [name for name in CANONICAL if name not in headers]
    assert not missing, f"{served['entry']}(): {label} ({status}) went out without {missing}"
    assert headers["x-content-type-options"] == "nosniff"


def test_a_static_file_carries_the_security_headers(served):
    status, headers = _send(served, "GET", "/hello.html")
    _assert_carries_the_set(served, "a static file", status, headers, (200,))


def test_a_404_carries_the_security_headers(served):
    status, headers = _send(served, "GET", "/secure-contract/nowhere")
    _assert_carries_the_set(served, "the 404", status, headers, (404,))


def test_a_405_carries_the_security_headers(served):
    status, headers = _send(served, "PUT", "/secure-contract/page")
    _assert_carries_the_set(served, "the 405", status, headers, (405,))


def test_a_refusal_carries_the_security_headers(served):
    status, headers = _send(served, "POST", "/secure-contract/write")
    _assert_carries_the_set(served, "the refused anonymous write", status, headers, (401, 403))


def test_a_header_the_route_already_set_is_not_overwritten(served):
    status, headers = _send(served, "GET", "/secure-contract/own-headers")
    assert status == 200
    assert headers["content-security-policy"] == ROUTE_CSP, "the route's own CSP was overwritten"
    assert headers["x-frame-options"] == "DENY", "the route's own X-Frame-Options was overwritten"
    assert headers["x-content-type-options"] == "nosniff", "a header the route did not set was not filled in"


def test_every_entry_point_attaches_the_security_headers_and_csrf(served):
    status, headers = _send(served, "GET", "/secure-contract/page")
    _assert_carries_the_set(served, "a routed page", status, headers, (200,))
    refused, _ = _send(served, "POST", "/secure-contract/write")
    assert refused in (401, 403), f"{served['entry']}(): a write with no token was accepted ({refused})"


def test_every_entry_point_mounts_the_sso_routes(served):
    status, headers = _send(served, "GET", "/auth/login")
    assert status in (302, 303), f"{served['entry']}(): /auth/login answered {status} with TINA4_SSO_* set"
    location = urlparse(headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == (
        f"{served['issuer']}/protocol/openid-connect/auth"
    )
