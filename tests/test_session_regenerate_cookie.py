# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Session regenerate mid-request re-emits the cookie on the serve path.

Parity guard for tina4stack/tina4-php#253. That bug was in PHP's native
``$_SESSION`` bridge under the socket server: a mid-request
``session_regenerate_id()`` (the standard session-fixation defence on login)
rotated the id but never sent the new id to the client, so the session was lost
on the very next request.

Python's own session subsystem has never had that defect — ``_stage_session_save``
emits a Set-Cookie on every request that saved a session, so a rotated id always
reaches the client — but the bug was reported against one framework and almost
always exists in the others, so it gets a permanent regression test here too. If
the serve path ever stopped propagating a rotated id, this test goes red.

Proven ON THE WIRE with a REAL child server, no mocks: request 1 writes the
session and regenerates its id, request 2 replays the rotated cookie and must
find the SAME data under the new id.
"""

import http.client
import subprocess
from pathlib import Path

from conftest import boot_child_server

REPO_ROOT = Path(__file__).resolve().parent.parent


def _boot_regen_server(tmp_path: Path, extra_env: dict | None = None):
    """Start a REAL child server with two routes:

    GET /regen   — writes the session, rotates its id via session.regenerate(),
                   returns the new id.
    GET /whoami  — returns the current session id and the stored value.
    """

    def write_app(proj: Path, port: int) -> None:
        (proj / "app.py").write_text(
            "from tina4_python import get\n"
            "from tina4_python.core.server import start\n\n"
            "@get('/regen')\n"
            "async def regen(request, response):\n"
            "    request.session.set('hit', int(request.session.get('hit', 0)) + 1)\n"
            "    new_id = request.session.regenerate()\n"
            "    return response({'id': new_id, 'hit': request.session.get('hit')})\n\n"
            "@get('/whoami')\n"
            "async def whoami(request, response):\n"
            "    sid = getattr(request.session, 'session_id', None) or getattr(request.session, 'id', None)\n"
            "    return response({'id': sid, 'hit': request.session.get('hit')})\n\n"
            f"start(port={port}, no_browser=True, no_reload=True)\n"
        )

    def env_for(port: int) -> dict:
        env = {"TINA4_SESSION_PATH": str(tmp_path / f"srv_{port}" / "sessions")}
        if extra_env:
            env.update(extra_env)
        return env

    return boot_child_server(tmp_path, write_app, extra_env=env_for,
                             unset_env=("TINA4_SESSION_NAME",))


def _get(port: int, path: str, cookie: str | None = None, timeout: float = 5.0):
    """GET path over a real socket. Returns (body_text, set_cookie_values)."""
    headers = {}
    if cookie is not None:
        headers["Cookie"] = cookie
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode().strip()
        set_cookies = [v for (k, v) in resp.getheaders() if k.lower() == "set-cookie"]
        return body, set_cookies
    finally:
        conn.close()


def _session_cookie(set_cookies) -> str | None:
    """The tina4_session name=value pair from a set of Set-Cookie values, or None."""
    for value in set_cookies:
        if value.startswith("tina4_session="):
            return value.split(";", 1)[0].strip()
    return None


def _terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_regenerate_mid_request_re_emits_the_new_cookie_and_survives(tmp_path):
    """A mid-request regenerate must send the NEW id, and the session must survive
    to the next request under that id."""
    import json

    proc, port = _boot_regen_server(tmp_path)
    try:
        # Request 1: write + rotate the id in one request.
        body1, set_cookies1 = _get(port, "/regen")
        first = json.loads(body1)
        assert first["hit"] == 1, body1
        rotated_id = first["id"]
        assert rotated_id, body1

        emitted = _session_cookie(set_cookies1)
        assert emitted is not None, (
            f"a request that rotated the session id must emit a Set-Cookie; got {set_cookies1!r}"
        )
        assert emitted.split("=", 1)[1] == rotated_id, (
            f"the emitted cookie must carry the rotated id {rotated_id!r}; got {emitted!r}"
        )

        # Request 2: replay the rotated cookie — the session must resume under the
        # new id (hit persisted), not come back empty.
        body2, _ = _get(port, "/whoami", cookie=emitted)
        second = json.loads(body2)
        assert second["hit"] == 1, (
            f"the rotated session must survive to the next request (hit=1); got {body2!r}"
        )
        assert second["id"] == rotated_id, (
            f"the next request must run under the rotated id {rotated_id!r}; got {body2!r}"
        )
    finally:
        _terminate(proc)
