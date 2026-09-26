# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue #137 - static files must carry the same security headers as routes.

The static handler (``public/``, ``src/public/``) answered from the no-route
fallback, which returned its Response directly: the security-headers
middleware only ever ran for a MATCHED route, so a static file skipped it even
with it attached. ``/`` resolves to ``index.html``, so a single-page app's front
door was served with no CSP and frameable (clickjacking), and JS/CSS went out
without ``nosniff``.

The middleware is attached explicitly after ``asgi()`` here, exactly as the
issue does, so this file isolates #137 from #134.

NO MOCKS: real files on disk, a REAL uvicorn in a child process, real HTTP.
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

FRAME_OPTIONS = "DENY"  # a non-default value, so a header can only come from the middleware
SECURITY_HEADERS = ("content-security-policy", "x-content-type-options", "x-frame-options")

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import get


    @get("/issue137/page")
    async def page(request, response):
        return response("<!doctype html><title>route</title><p>hello</p>")
''')

SERVE = textwrap.dedent('''
    import os
    import uvicorn
    from tina4_python.core.middleware import attach_security_headers
    from tina4_python.core.server import asgi

    application = asgi()
    attach_security_headers()
    uvicorn.run(application, host="127.0.0.1", port=int(os.environ["ISSUE137_PORT"]), log_level="warning")
''')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    project = tmp_path_factory.mktemp("issue137_project")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "issue137.py").write_text(ROUTES)
    public = project / "src" / "public"
    public.mkdir(parents=True)
    (public / "index.html").write_text("<!doctype html><title>spa</title><div id=app></div>")
    (public / "app.js").write_text("document.getElementById('app').textContent = 'spa';\n")
    (project / "serve.py").write_text(SERVE)
    port = _free_port()
    env = {
        **os.environ,
        "ISSUE137_PORT": str(port),
        "TINA4_DEBUG": "false",
        "TINA4_SECRET": "issue137-contract-secret-0123456789abcdef",
        "TINA4_FRAME_OPTIONS": FRAME_OPTIONS,
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
        "TINA4_NO_BROWSER": "true",
    }
    env.pop("TINA4_PUBLIC_DIR", None)
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
            pytest.fail(f"issue137 uvicorn child never became ready (exit={process.poll()})")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {key.lower(): value for key, value in error.headers.items()}, error.read()


def _assert_secured(server, path, expected_status=200):
    status, headers, body = _get(f"{server}{path}")
    assert status == expected_status, f"GET {path} -> {status}: {body[:200]!r}"
    missing = [name for name in SECURITY_HEADERS if name not in headers]
    assert not missing, f"GET {path} was served without {missing} (#137)"
    assert headers["x-frame-options"] == FRAME_OPTIONS
    assert headers["x-content-type-options"] == "nosniff"
    return headers, body


def test_a_route_carries_the_security_headers(server):
    """Baseline: the attached middleware reaches a matched route."""
    _assert_secured(server, "/issue137/page")


def test_a_static_html_file_carries_the_security_headers(server):
    headers, body = _assert_secured(server, "/index.html")
    assert b"<title>spa</title>" in body, "the static file itself must still be what is served"
    assert headers["content-type"].startswith("text/html")


def test_the_spa_front_door_at_root_carries_the_security_headers(server):
    """``/`` resolves to index.html: the page an attacker would frame."""
    _, body = _assert_secured(server, "/")
    assert b"<title>spa</title>" in body


def test_a_static_script_carries_nosniff(server):
    headers, _ = _assert_secured(server, "/app.js")
    assert "javascript" in headers["content-type"]


def test_the_not_found_page_carries_the_security_headers(server):
    """The same no-route fallback answers a 404; it must not skip them either."""
    _assert_secured(server, "/issue137/no-such-page", expected_status=404)
