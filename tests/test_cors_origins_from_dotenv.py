# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A CORS policy written only in ``.env`` is applied, under ``run()`` and ``asgi()``.

The CORS singleton in ``core/server.py`` is built at import, and import comes
before the boot loads ``.env``. ``TINA4_CORS_ORIGINS`` set in ``.env`` alone was
therefore never seen: every cross-origin request got no
``Access-Control-Allow-Origin`` and a log line telling the operator to set the
variable they had already set.

NO MOCKS: a real project with a real ``.env``, real child servers, real HTTP.
The policy is kept OUT of the child's process environment, so ``.env`` is the
only place it can come from.
"""
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest

ALLOWED = "https://allowed.example"
OTHER = "https://other.example"

ROUTES = textwrap.dedent('''
    from tina4_python.core.router import get, noauth


    @noauth()
    @get("/cors/page")
    async def page(request, response):
        return response({"ok": True})
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


@pytest.fixture(scope="module", params=["asgi", "run"])
def server(request, tmp_path_factory):
    entry = request.param
    project = tmp_path_factory.mktemp(f"cors_dotenv_{entry}")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "cors_page.py").write_text(ROUTES)
    (project / "serve.py").write_text(SERVE[entry])
    (project / ".env").write_text(f"TINA4_CORS_ORIGINS={ALLOWED}\n")
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINA4_CORS_")}
    env.update({
        "CORS_PORT": str(port),
        "TINA4_DEBUG": "false",
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEFAULT_WEBSERVER": "true",
        "TINA4_SUPPRESS": "true",
        "TINA4_NO_BROWSER": "true",
        "TINA4_AUTO_MIGRATE": "false",
        "TINA4_SECRET": "cors-dotenv-contract-secret-0123456789abcdef",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
    })
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


def _allow_origin(url, origin, method="GET"):
    headers = {"Origin": origin}
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "POST"
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.headers.get("Access-Control-Allow-Origin")


def test_dotenv_origin_is_allowed(server):
    got = _allow_origin(f"{server['base']}/cors/page", ALLOWED)
    assert got == ALLOWED, (
        f"{server['entry']}(): TINA4_CORS_ORIGINS={ALLOWED} in .env, but the response "
        f"carried Access-Control-Allow-Origin={got!r} - the policy in .env was not applied"
    )


def test_dotenv_origin_is_allowed_on_preflight(server):
    got = _allow_origin(f"{server['base']}/cors/page", ALLOWED, method="OPTIONS")
    assert got == ALLOWED, f"{server['entry']}(): preflight carried ACAO={got!r}"


def test_origin_not_in_dotenv_is_still_refused(server):
    assert _allow_origin(f"{server['base']}/cors/page", OTHER) is None
