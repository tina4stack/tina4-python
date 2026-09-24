# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CORS denial diagnostics are BOUNDED (ADR-0048): one warning per REASON, never per origin.

ADR-0048: "no per-origin ledger and no per-origin warning". Python keyed the
denied warning by origin (``_cors_warn_once(f"denied:{origin}", ...)``), so
every new attacker-chosen ``Origin`` header added an entry to
``_CORS_DENY_WARNED`` that was never freed, and wrote another log line - an
unbounded ledger and an unbounded log, both driven by the client.

The contract: every CORS warning is keyed by its reason (unconfigured, denied,
wildcard_credentials). The message may name the origin that triggered the first
occurrence, but 50 distinct origins produce exactly one warning per reason and
a ledger no bigger than the number of reasons.

NO MOCKS: real child servers (uvicorn over ``asgi()``, and ``run()``'s own
server), real HTTP, the server's real stdout log, and the ledger size read from
inside the serving process.
"""
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

import pytest

ORIGINS = [f"https://probe{number}.attacker.example" for number in range(50)]
PARTNER = "https://partner.example.com"
REASONS = ("unconfigured", "denied", "wildcard_credentials")

ROUTES = textwrap.dedent('''
    from tina4_python.core.middleware import _CORS_DENY_WARNED
    from tina4_python.core.router import get, noauth, post


    @noauth()
    @post("/cors-bound/save")
    async def save(request, response):
        return response({"saved": True})


    @get("/cors-bound/ledger")
    async def ledger(request, response):
        return response({"size": len(_CORS_DENY_WARNED), "keys": sorted(_CORS_DENY_WARNED)})
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


@pytest.fixture(scope="module", params=[
    ("asgi", "unset"), ("asgi", "allow-list"), ("run", "unset"), ("run", "allow-list"),
], ids=lambda p: f"{p[0]}-{p[1]}")
def server(request, tmp_path_factory):
    entry, policy = request.param
    project = tmp_path_factory.mktemp(f"cors_bound_{entry}_{policy}")
    (project / "src" / "routes").mkdir(parents=True)
    (project / "src" / "routes" / "cors_bound.py").write_text(ROUTES)
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
        "TINA4_SECRET": "cors-bound-secret-0123456789abcdef",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_SESSION_PATH": str(project / "sessions"),
        "TINA4_CSP": "default-src 'self'",
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
        yield {"entry": entry, "policy": policy, "base": f"http://127.0.0.1:{port}", "log": log_path}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _post(base, origin):
    request = urllib.request.Request(
        f"{base}/cors-bound/save", data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_fifty_distinct_origins_warn_once_per_reason_and_the_ledger_stays_bounded(server):
    for origin in ORIGINS:
        assert _post(server["base"], origin) == 200
    time.sleep(0.3)
    log = server["log"].read_text(errors="replace")
    warnings = [line for line in log.splitlines() if "CORS" in line]
    assert len(warnings) == 1, (
        f"{server['entry']}()/{server['policy']}: 50 distinct origins produced {len(warnings)} CORS "
        f"warnings - ADR-0048 allows one per reason:\n" + "\n".join(warnings[:5])
    )
    assert ORIGINS[0] in warnings[0], "the one warning should name the origin that triggered it"

    with urllib.request.urlopen(f"{server['base']}/cors-bound/ledger", timeout=10) as response:
        ledger = json.loads(response.read())
    assert ledger["size"] <= len(REASONS), (
        f"{server['entry']}()/{server['policy']}: the warn-once ledger grew to {ledger['size']} "
        f"entries for 50 origins - it must be keyed by reason: {ledger['keys'][:5]}"
    )
    assert set(ledger["keys"]) <= set(REASONS), f"ledger keys are not reasons: {ledger['keys'][:5]}"
