"""Session cookie name — WRITE and READ sides honour TINA4_SESSION_NAME.

The bug: the write side (``Session.cookie_header``) resolved the cookie name from
``TINA4_SESSION_NAME`` (default ``tina4_session``), but the incoming-cookie READ
side (``core/server._init_session``) parsed the hardcoded literal
``tina4_session=``. So an operator who set ``TINA4_SESSION_NAME`` wrote a renamed
cookie the framework could never read back — the session silently never resumed.

These tests prove it ON THE WIRE with a REAL child server: a counter route
increments a value stored in the session and returns it. Request 1 gets "1" and
a Set-Cookie under the configured name; request 2 replays that cookie and MUST
get "2" — which only happens if the read side found the session under the SAME
name the write side emitted.

  * custom name: TINA4_SESSION_NAME=my_app_session — the cookie is named
    ``my_app_session`` AND the second request resumes the session (returns "2");
  * default name: unset — the cookie is ``tina4_session`` and resume still works,
    proving the default path is unchanged.

No mocks: every assertion is against headers/bodies a real server emitted over a
real loopback socket. Mirrors the child-server shape of
``tests/test_session_cookie_secure.py``.
"""

import http.client
from pathlib import Path

from conftest import boot_child_server

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── real child-server helpers (mirror test_session_cookie_secure.py) ───────

def _boot_counter_server(tmp_path: Path, extra_env: dict | None = None):
    """Start a REAL child server exposing GET /session/count, which increments a
    per-session counter and returns it as the body. Returns (proc, port).

    Boots through the shared conftest helper, which retries a lost port race and
    reports the child's own output on a real failure. Caller must terminate proc.
    """
    def write_app(proj: Path, port: int) -> None:
        (proj / "app.py").write_text(
            "from tina4_python import get\n"
            "from tina4_python.core.server import start\n\n"
            "@get('/session/count')\n"
            "async def count(request, response):\n"
            "    n = int(request.session.get('n', 0)) + 1\n"
            "    request.session.set('n', n)\n"
            "    return response(str(n))\n\n"
            f"start(port={port}, no_browser=True, no_reload=True)\n"
        )

    def env_for(port: int) -> dict:
        # Session store is per-port so concurrent boots never share state.
        env = {"TINA4_SESSION_PATH": str(tmp_path / f"srv_{port}" / "sessions")}
        if extra_env:
            env.update(extra_env)
        return env

    return boot_child_server(tmp_path, write_app, extra_env=env_for)


def _count(port: int, cookie: str | None = None, timeout: float = 5.0):
    """GET /session/count over a real socket. Returns (body, set_cookie_pairs)
    where set_cookie_pairs is the list of raw Set-Cookie header values."""
    headers = {}
    if cookie is not None:
        headers["Cookie"] = cookie
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/session/count", headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode().strip()
        set_cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        return body, set_cookies
    finally:
        conn.close()


def _cookie_pair(set_cookie_value: str) -> str:
    """Reduce a full Set-Cookie header to the ``name=value`` pair for replay."""
    return set_cookie_value.split(";", 1)[0].strip()


def _terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── wire-level proof: a custom-named cookie resumes the session ────────────

def test_custom_session_name_resumes_on_the_wire(tmp_path):
    """TINA4_SESSION_NAME=my_app_session: the cookie is named my_app_session AND
    a second request replaying it resumes the SAME session. Before the fix the
    read side looked for tina4_session=, never found it, and every request got a
    brand-new session (counter stuck at 1)."""
    proc, port = _boot_counter_server(
        tmp_path, {"TINA4_SESSION_NAME": "my_app_session"}
    )
    try:
        # Request 1: fresh session, counter -> 1, cookie under the custom name.
        body1, set_cookies1 = _count(port)
        assert body1 == "1", body1
        renamed = [c for c in set_cookies1 if c.startswith("my_app_session=")]
        assert renamed, f"expected a my_app_session cookie, got {set_cookies1!r}"
        # The old literal name must NOT be emitted.
        assert not any(c.startswith("tina4_session=") for c in set_cookies1), set_cookies1

        # Request 2: replay the renamed cookie — the session must resume (-> 2),
        # which requires the READ side to look under the SAME custom name.
        cookie = _cookie_pair(renamed[0])
        body2, _ = _count(port, cookie=cookie)
        assert body2 == "2", (
            f"session did not resume under the custom name: request 2 returned "
            f"{body2!r} (cookie={cookie!r}) — expected '2'"
        )

        # Request 3: same cookie again keeps counting up on the one session.
        body3, _ = _count(port, cookie=cookie)
        assert body3 == "3", body3
    finally:
        _terminate(proc)


def test_default_session_name_resumes_on_the_wire(tmp_path):
    """Default (TINA4_SESSION_NAME unset): the cookie is tina4_session and resume
    still works — the default path is unchanged, byte-for-byte."""
    proc, port = _boot_counter_server(tmp_path)
    try:
        body1, set_cookies1 = _count(port)
        assert body1 == "1", body1
        default = [c for c in set_cookies1 if c.startswith("tina4_session=")]
        assert default, f"expected a tina4_session cookie, got {set_cookies1!r}"

        cookie = _cookie_pair(default[0])
        body2, _ = _count(port, cookie=cookie)
        assert body2 == "2", (
            f"default-named session did not resume: request 2 returned {body2!r}"
        )
    finally:
        _terminate(proc)
