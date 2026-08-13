"""Real-bug audit (3.13.99): the built-in server's FIRST-TIME session cookie.

CONFIRMED BROKEN in PHP: ``Tina4\\Server`` (the raw-socket engine `tina4 serve`
boots) never triggers PHP's ``headers_sent()`` — a raw socket engages no real
PHP SAPI header-sending mechanism at all — so ``Router::emitSessionCookie()``
took the native ``setcookie()`` branch, which writes into a void nothing reads
back under that engine. A first-time session login under `tina4 serve` emitted
NO Set-Cookie at all: session auth was silently broken on the framework's own
recommended dev/prod server. Fixed in PHP by giving ``Response`` a
``rawSocket`` flag ``Tina4\\Server`` sets, read by ``emitSessionCookie()``.

CROSS-CHECKED HERE: Python's built-in server has no such split — there is no
second, "native" cookie-writing mechanism outside the Response object the way
PHP's CGI-heritage ``setcookie()`` is; every server mode (the built-in asyncio
server, and a production ASGI server) reads ``response.headers`` uniformly.
``core/server.py``'s ``_stage_session_save`` calls
``ctx.response.header("set-cookie", ...)`` unconditionally — the SAME call
whether driven by TestClient, the built-in server, or a production server.
CODE WINS: this suite is a real, no-mock proof (not merely read from source)
that a REAL child ``python app.py`` process — the exact command a developer
runs — emits a first-time Set-Cookie and that replaying it resumes the
session, mirroring ``test_session_cookie_secure.py``'s established real-child-
server pattern (``boot_child_server``).

Same case name in all four (tina4-documentation/plan/v3/fixtures/session_contract.json):
  - first_time_session_cookie_is_emitted_and_a_replay_resumes_it
"""

import http.client
import subprocess
from pathlib import Path

from conftest import boot_child_server


def _boot_login_server(tmp_path: Path):
    """A REAL child server: POST /login (noauth) writes to the session, so the
    framework must emit a first-time Set-Cookie; GET /whoami reads it back."""

    def write_app(proj: Path, port: int) -> None:
        (proj / "app.py").write_text(
            "from tina4_python.core import run\n"
            "from tina4_python.core.router import post, get, noauth\n\n"
            "@noauth()\n"
            "@post('/login')\n"
            "async def login(request, response):\n"
            "    request.session.set('token', 'abc')\n"
            "    return response({'ok': True})\n\n"
            "@get('/whoami')\n"
            "async def whoami(request, response):\n"
            "    return response({'token': request.session.get('token')})\n\n"
            "run()\n"
        )

    return boot_child_server(tmp_path, write_app)


def _post(port: int, path: str, timeout: float = 5.0):
    """A REAL POST over a real socket. Returns (status, body, set_cookie_lines)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", path, body="{}", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        return resp.status, body, cookies
    finally:
        conn.close()


def _get(port: int, path: str, cookie: str | None = None, timeout: float = 5.0):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Cookie": cookie} if cookie else {}
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body
    finally:
        conn.close()


def _terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_first_time_session_cookie_is_emitted_and_a_replay_resumes_it(tmp_path):
    """A REAL `python app.py` child, REAL sockets, no mocks. This is the exact
    process a developer runs (`tina4 serve` -> TINA4_OVERRIDE_CLIENT boots the
    same core.server.run()). A first-time POST that writes to the session must
    emit a Set-Cookie; replaying that cookie on a second real request must
    resume the SAME session (not just receive A cookie)."""
    proc, port = _boot_login_server(tmp_path)
    try:
        status, body, cookies = _post(port, "/login")
        assert status == 200, f"login must succeed: {status} {body}"
        assert cookies, (
            "a first-time session write over the REAL built-in server must emit "
            "a Set-Cookie - this is the exact defect confirmed in PHP's Tina4\\Server"
        )
        tina4_cookies = [c for c in cookies if c.startswith("tina4_session=")]
        assert tina4_cookies, f"no tina4_session cookie among: {cookies}"
        cookie_value = tina4_cookies[0].split(";", 1)[0]

        status2, body2 = _get(port, "/whoami", cookie=cookie_value)
        assert status2 == 200
        assert '"token": "abc"' in body2 or '"token":"abc"' in body2, (
            f"replaying the first-time cookie must RESUME the session (token=abc); got {body2!r}"
        )
    finally:
        _terminate(proc)
