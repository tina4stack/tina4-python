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
from unittest.mock import MagicMock

import pytest

from tina4_python.core.middleware import CorsMiddleware

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


# ── TestClient loads .env itself (#296), so it must apply the policy too ──────

def test_test_client_applies_a_dotenv_origin(tmp_path, monkeypatch):
    """TestClient never calls run(); it loads .env itself, and the CORS policy
    in that .env must reach the dispatcher the same way."""
    from tina4_python.core import server
    from tina4_python.core.router import Router, get as route_get, noauth
    from tina4_python.test_client import TestClient

    for name in [k for k in os.environ if k.startswith("TINA4_CORS_")]:
        monkeypatch.delenv(name)
    # load_env() below sets TINA4_CORS_ORIGINS. delenv() on an unset variable
    # records nothing to restore, so set it first: teardown then unsets it.
    monkeypatch.setenv("TINA4_CORS_ORIGINS", "")
    monkeypatch.delenv("TINA4_CORS_ORIGINS")
    # The refresh updates _cors in place: give this test its own instance, so
    # the policy it applies does not stay behind on the shared one.
    monkeypatch.setattr(server, "_cors", CorsMiddleware())
    (tmp_path / ".env").write_text(f"TINA4_CORS_ORIGINS={ALLOWED}\n")
    monkeypatch.chdir(tmp_path)
    Router.clear()
    try:
        @noauth()
        @route_get("/cors/page")
        async def page(request, response):
            return response({"ok": True})

        client = TestClient()
        allowed = client.get("/cors/page", headers={"Origin": ALLOWED})
        other = client.get("/cors/page", headers={"Origin": OTHER})
    finally:
        Router.clear()
    acao = {k.lower(): v for k, v in allowed.headers.items()}.get("access-control-allow-origin")
    assert acao == ALLOWED, f"TestClient: .env CORS policy not applied (ACAO={acao!r})"
    assert "access-control-allow-origin" not in {k.lower() for k in other.headers}


def _no_cors_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("TINA4_CORS_")]:
        monkeypatch.delenv(name)


def test_refresh_checks_the_live_instance_not_a_stale_record(monkeypatch):
    """The refresh compares the settings against what the CURRENT ``_cors`` was
    built from. Suites replace ``server._cors`` directly (the conformance
    teardown builds a fresh ``CorsMiddleware()`` after popping the env); a
    record kept beside the object went stale and the next refresh skipped a
    rebuild it needed."""
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    monkeypatch.setattr(server, "_cors", CorsMiddleware())
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    server._refresh_cors_from_env()
    assert server._cors.allowed_origin(ALLOWED) == ALLOWED

    # What a suite teardown does: reset the env and the singleton by hand.
    monkeypatch.delenv("TINA4_CORS_ORIGINS")
    server._cors = CorsMiddleware()
    # The next project's .env sets the same policy again.
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    server._refresh_cors_from_env()
    assert server._cors.allowed_origin(ALLOWED) == ALLOWED, (
        "a CorsMiddleware swapped in from an empty env was kept for a policy that is set"
    )


def test_refresh_does_nothing_when_the_settings_did_not_change(monkeypatch):
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    monkeypatch.setattr(server, "_cors", CorsMiddleware())
    calls = []
    real_init = CorsMiddleware.__init__
    monkeypatch.setattr(CorsMiddleware, "__init__",
                        lambda self: calls.append(1) or real_init(self))
    server._refresh_cors_from_env()
    assert calls == [], "re-read although the settings did not change"


def test_refresh_updates_a_reference_held_elsewhere(monkeypatch):
    """The singleton is re-read in place, so code that imported it before the
    .env was loaded sees the policy too."""
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    monkeypatch.setattr(server, "_cors", CorsMiddleware())
    held = server._cors
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    server._refresh_cors_from_env()
    assert server._cors is held
    assert held.allowed_origin(ALLOWED) == ALLOWED


def test_refresh_follows_every_change_not_only_the_first(monkeypatch):
    """Each .env load re-reads the policy: A, then B, then none."""
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    monkeypatch.setattr(server, "_cors", CorsMiddleware())
    for origins in (ALLOWED, OTHER):
        monkeypatch.setenv("TINA4_CORS_ORIGINS", origins)
        server._refresh_cors_from_env()
        assert server._cors.allowed_origin(origins) == origins
    monkeypatch.delenv("TINA4_CORS_ORIGINS")
    server._refresh_cors_from_env()
    assert not server._cors.is_configured()


@pytest.mark.parametrize("make", [object, lambda: MagicMock(spec=CorsMiddleware)],
                         ids=["object", "spec-mock"])
def test_refresh_leaves_a_test_double_alone(monkeypatch, make):
    """Something other than a plain CorsMiddleware was installed on purpose,
    including a mock that passes isinstance()."""
    from tina4_python.core import server

    monkeypatch.setattr(server, "_cors", make())
    double = server._cors
    before = dict(getattr(double, "__dict__", {}))
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    server._refresh_cors_from_env()
    assert server._cors is double
    assert dict(getattr(double, "__dict__", {})) == before


def _left_alone(monkeypatch, installed, origin_kept):
    """Install ``installed``, set a different .env policy, refresh, and check the
    instance still allows ``origin_kept`` and does not allow the new one."""
    from tina4_python.core import server

    monkeypatch.setattr(server, "_cors", installed)
    monkeypatch.setenv("TINA4_CORS_ORIGINS", OTHER)
    server._refresh_cors_from_env()
    assert server._cors is installed
    assert installed.allowed_origin(origin_kept) == origin_kept
    assert installed.allowed_origin(OTHER) != OTHER


def test_refresh_leaves_a_cors_subclass_alone(monkeypatch):
    """A CorsMiddleware subclass was installed and configured by its owner;
    re-reading it would drop whatever its constructor was given."""
    class Mine(CorsMiddleware):
        def __init__(self, origins=OTHER):
            super().__init__()
            self.origins = origins

    _no_cors_env(monkeypatch)
    _left_alone(monkeypatch, Mine(ALLOWED), ALLOWED)


def test_refresh_leaves_a_subclass_that_only_overrides_behaviour(monkeypatch):
    """A subclass that keeps the env-built policy is still its owner's: its
    constructor may need arguments the refresh cannot supply."""
    class Logged(CorsMiddleware):
        def allowed_origin(self, origin):
            return super().allowed_origin(origin)

    _no_cors_env(monkeypatch)
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    installed = Logged()
    _left_alone(monkeypatch, installed, ALLOWED)


@pytest.mark.parametrize("key", ["TINA4_CORS_ORIGINS", "TINA4_CORS_MAX_AGE"])
def test_refresh_keeps_a_policy_set_by_hand(monkeypatch, key):
    """Origins set on the singleton by hand are its owner's choice: a .env
    policy, or an unrelated CORS setting, does not throw them away."""
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    configured = CorsMiddleware()
    configured.origins = ALLOWED
    monkeypatch.setattr(server, "_cors", configured)
    monkeypatch.setenv(key, OTHER if key == "TINA4_CORS_ORIGINS" else "600")
    server._refresh_cors_from_env()
    assert configured.allowed_origin(ALLOWED) == ALLOWED
    assert configured.max_age == "86400"


def test_refresh_keeps_an_override_set_on_the_instance(monkeypatch):
    """A method replaced on the instance is a change by hand too."""
    from tina4_python.core import server

    _no_cors_env(monkeypatch)
    configured = CorsMiddleware()
    configured.allowed_origin = lambda origin: origin
    monkeypatch.setattr(server, "_cors", configured)
    monkeypatch.setenv("TINA4_CORS_ORIGINS", ALLOWED)
    server._refresh_cors_from_env()
    assert configured.origins == ""
    assert "allowed_origin" in vars(configured)


def test_refresh_leaves_an_instance_built_without_init_alone(monkeypatch):
    """An instance made with __new__ and configured by hand records nothing
    it was built from, so there is nothing to compare: it is kept."""
    bare = CorsMiddleware.__new__(CorsMiddleware)
    bare.origins, bare.methods, bare.headers = ALLOWED, "GET", "Content-Type"
    bare.max_age, bare.credentials = "60", False
    _no_cors_env(monkeypatch)
    _left_alone(monkeypatch, bare, ALLOWED)
    assert bare.max_age == "60"
