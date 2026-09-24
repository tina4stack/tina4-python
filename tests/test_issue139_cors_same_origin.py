"""Issue #139 - a same-origin request is never warned about, and no warning advises ``*``.

Browsers send ``Origin`` on every same-origin POST/PUT/PATCH/DELETE. The CORS
layer treated any request carrying one as cross-origin, so an app's own SPA
saving a form logged "refused cross-origin request ... (or '*' to allow any
origin)" - advice that would open the API to every website to silence a
warning about the app itself. With an allow-list for other sites it logged
"the browser will block this response", which is also untrue for same-origin.

The contract, the same in all four frameworks: a request whose Origin equals
the request's own origin (scheme://host[:port], http:80 / https:443 as default
ports) is same-origin - no warning, never refused, and nothing is granted by it.
A disallowed cross-origin request still warns, naming the origin to add and
never ``*``. An allowed cross-origin request gets the CORS headers.

NO MOCKS: real child servers (uvicorn over ``asgi()`` and ``run()``'s own
server), real HTTP, and the server's REAL log output read back from its stdout.
"""
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

import pytest

PARTNER = "https://partner.example.com"
STRANGER = "https://stranger.example.com"

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import noauth, post


    @noauth()
    @post("/cors/save")
    async def save(request, response):
        return response({"saved": True})
''')

SERVE = {
    "asgi": textwrap.dedent('''
        import os
        import uvicorn
        from tina4_python.core.server import asgi

        uvicorn.run(asgi(), host="127.0.0.1", port=int(os.environ["CORS_PORT"]), log_level="warning")
    '''),
    "run": textwrap.dedent('''
        import os
        from tina4_python.core.server import run

        run(host="127.0.0.1", port=int(os.environ["CORS_PORT"]), no_browser=True)
    '''),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, entry, policy, base, log_path):
        self.entry, self.policy, self.base, self.log_path = entry, policy, base, log_path

    def log(self) -> str:
        time.sleep(0.2)  # the child writes its log line as it answers
        return self.log_path.read_text(errors="replace")

    def post(self, headers):
        request = urllib.request.Request(
            f"{self.base}/cors/save", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as error:
            return error.code, {k.lower(): v for k, v in error.headers.items()}


@pytest.fixture(scope="module", params=[
    ("asgi", "unset"), ("asgi", "allow-list"), ("run", "unset"), ("run", "allow-list"),
], ids=lambda p: f"{p[0]}-{p[1]}")
def server(request, tmp_path_factory):
    entry, policy = request.param
    project = tmp_path_factory.mktemp(f"cors_{entry}_{policy}")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "cors.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE[entry])
    log_path = project / "server-output.log"
    port = _free_port()
    env = {
        **os.environ,
        "CORS_PORT": str(port),
        "TINA4_DEBUG": "false",
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEFAULT_WEBSERVER": "true",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_AUTO_MIGRATE": "false",
        "TINA4_SECRET": "cors-contract-secret",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
        "TINA4_CSP": "default-src 'self'",  # an explicit CSP keeps the default-CSP notice out of the log
    }
    env.pop("TINA4_CORS_ORIGINS", None)
    if policy == "allow-list":
        env["TINA4_CORS_ORIGINS"] = PARTNER
    with open(log_path, "wb") as output:
        process = subprocess.Popen([sys.executable, "serve.py"], cwd=str(project), env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
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
        yield Server(entry, policy, f"http://127.0.0.1:{port}", log_path)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_same_origin_post_is_served_and_not_warned_about(server):
    """Runs FIRST per server: the warning is once-per-process, so nothing may precede it."""
    status, headers = server.post({"Origin": server.base})
    assert status == 200
    assert "access-control-allow-origin" not in headers, "same-origin must not be granted CORS headers"
    assert "CORS" not in server.log(), (
        f"{server.entry}()/{server.policy}: a same-origin POST logged a CORS warning (#139):\n{server.log()}"
    )


def test_same_origin_on_the_default_port_is_same_origin(server):
    """http://host and http://host:80 are one origin."""
    status, _ = server.post({"Host": "tina4.example:80", "Origin": "http://tina4.example"})
    assert status == 200
    assert "CORS" not in server.log(), f"a default-port same-origin POST was warned about:\n{server.log()}"


def test_disallowed_cross_origin_request_warns_without_advising_a_wildcard(server):
    status, headers = server.post({"Origin": STRANGER})
    assert status == 200, "CORS never refuses on the server - the browser enforces it"
    assert "access-control-allow-origin" not in headers
    log = server.log()
    warning = [line for line in log.splitlines() if "CORS" in line and STRANGER in line]
    assert warning, f"{server.entry}()/{server.policy}: a disallowed cross-origin request was not warned about:\n{log}"
    assert "*" not in warning[0], f"the CORS warning advises '*': {warning[0]}"
    assert f"TINA4_CORS_ORIGINS=" in warning[0] and STRANGER in warning[0]


def test_allowed_cross_origin_request_gets_the_cors_headers(server):
    """Allow-list: the listed partner gets the headers. No policy: nobody does (ADR-0018)."""
    status, headers = server.post({"Origin": PARTNER})
    assert status == 200
    if server.policy == "allow-list":
        assert headers.get("access-control-allow-origin") == PARTNER
        assert "Origin" in headers.get("vary", "")
    else:
        assert "access-control-allow-origin" not in headers
