# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CORS - the runner for cors_contract.json (ADR-0018, ADR-0048, ADR-0066).

tina4-documentation/plan/v3/fixtures/cors_contract.json names these cases; the
PHP, Ruby and Node suites carry the same names.

  * deny by default: no policy grants nobody; an allow-list grants only its own;
  * a same-origin request (Origin equals the request's own scheme + host) is
    neither warned about nor granted anything - with or without a policy;
  * the warning for a refused origin names it, says how to add THAT origin and
    never advises '*';
  * refusals are remembered by REASON, never by origin (bounded diagnostics).

Every case boots a REAL child server through ``run()`` (a fresh process, so the
warn-once state starts empty), sends real HTTP and reads the server's REAL log
from its own output file. NO MOCKS.
"""
import http.client
import json
import textwrap
from contextlib import contextmanager

from conftest import boot_child_server

ALLOWED = "https://allowed.example"
OTHER = "https://other.example"
REASONS = {"unconfigured", "denied", "wildcard_credentials"}

ROUTES = textwrap.dedent('''
    from tina4_python.core.middleware import _CORS_DENY_WARNED
    from tina4_python.core.router import get, noauth, post


    @noauth()
    @post("/cors-contract/save")
    async def save(request, response):
        return response({"saved": True})


    @get("/cors-contract/ledger")
    async def ledger(request, response):
        return response({"keys": sorted(_CORS_DENY_WARNED)})
''')


class Served:
    def __init__(self, port, log_path):
        self.port, self.log_path = port, log_path
        self.own_origin = f"http://127.0.0.1:{port}"

    def post(self, origin, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Content-Type": "application/json", "Origin": origin}
        if host:
            headers["Host"] = host
        connection.request("POST", "/cors-contract/save", body=b"{}", headers=headers)
        reply = connection.getresponse()
        reply.read()
        connection.close()
        return reply.status, {name.lower(): value for name, value in reply.getheaders()}

    def ledger(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        connection.request("GET", "/cors-contract/ledger")
        keys = json.loads(connection.getresponse().read())["keys"]
        connection.close()
        return keys

    def cors_warnings(self):
        return [line for line in self.log_path.read_text(errors="replace").splitlines() if "CORS" in line]


@contextmanager
def serve(tmp_path, origins=None):
    def write_app(project_dir, port):
        (project_dir / "src" / "routes" / "cors_contract.py").write_text(ROUTES)
        (project_dir / "app.py").write_text("from tina4_python.core import run\nif __name__ == '__main__':\n    run()\n")

    env = {
        "TINA4_DEBUG": "false",
        "TINA4_AUTO_MIGRATE": "false",
        "TINA4_SECRET": "cors-contract-secret-0123456789abcdef",
        "TINA4_SESSION_BACKEND": "file",
        "TINA4_CSP": "default-src 'self'",  # an explicit CSP keeps the default-CSP notice out of the log
    }
    if origins:
        env["TINA4_CORS_ORIGINS"] = origins
    process, port = boot_child_server(
        tmp_path, write_app, extra_env=env, log_dir=tmp_path / "logs",
        unset_env=("TINA4_CORS_ORIGINS", "TINA4_CORS_CREDENTIALS"),
    )
    try:
        yield Served(port, process.tina4_log_path)
    finally:
        process.terminate()
        process.wait(timeout=15)


def test_a_cross_origin_request_is_denied_by_default(tmp_path):
    with serve(tmp_path) as served:
        status, headers = served.post(OTHER)
    assert status == 200, "CORS never refuses on the server - the browser enforces it"
    assert "access-control-allow-origin" not in headers, "no policy configured, yet an origin was granted"


def test_only_a_listed_origin_is_granted(tmp_path):
    with serve(tmp_path, origins=ALLOWED) as served:
        _, listed = served.post(ALLOWED)
        _, unlisted = served.post(OTHER)
    assert listed.get("access-control-allow-origin") == ALLOWED
    assert "access-control-allow-origin" not in unlisted, f"an unlisted origin was granted: {unlisted}"


def test_a_same_origin_request_is_neither_warned_about_nor_granted(tmp_path):
    for policy in (None, ALLOWED):
        with serve(tmp_path / (policy and "allow-list" or "unset"), origins=policy) as served:
            status, headers = served.post(served.own_origin)
            warnings = served.cors_warnings()
        assert status == 200
        granted = sorted(name for name in headers if name.startswith("access-control-"))
        assert not granted, f"policy={policy}: a same-origin request was granted {granted}"
        assert not warnings, f"policy={policy}: a same-origin request was warned about (#139): {warnings}"


def test_a_different_port_or_scheme_is_cross_origin(tmp_path):
    with serve(tmp_path) as served:
        served.post(f"http://127.0.0.1:{served.port + 1}")
        port_warnings = served.cors_warnings()
    assert port_warnings, "an Origin on another port is cross-origin and must be warned about"
    with serve(tmp_path / "scheme") as served:
        served.post(f"https://127.0.0.1:{served.port}")
        scheme_warnings = served.cors_warnings()
    assert scheme_warnings, "an Origin with another scheme is cross-origin and must be warned about"


def test_a_refused_origin_warning_names_the_origin_and_never_advises_a_wildcard(tmp_path):
    for policy, refused in ((None, OTHER), (ALLOWED, OTHER)):
        with serve(tmp_path / (policy and "allow-list" or "unset"), origins=policy) as served:
            served.post(refused)
            warnings = served.cors_warnings()
        assert len(warnings) == 1, f"policy={policy}: expected one warning, got {warnings}"
        assert refused in warnings[0], f"the warning does not name the refused origin: {warnings[0]}"
        assert "TINA4_CORS_ORIGINS=" in warnings[0], f"the warning does not say how to add it: {warnings[0]}"
        assert "*" not in warnings[0], f"the warning advises a wildcard: {warnings[0]}"


def test_many_refused_origins_produce_one_warning_per_reason_and_no_per_origin_ledger(tmp_path):
    probes = [f"https://probe{number}.attacker.example" for number in range(30)]
    for policy in (None, ALLOWED):
        with serve(tmp_path / (policy and "allow-list" or "unset"), origins=policy) as served:
            for origin in probes:
                served.post(origin)
            warnings = served.cors_warnings()
            keys = served.ledger()
        assert len(warnings) == 1, f"policy={policy}: 30 refused origins logged {len(warnings)} warnings"
        assert set(keys) <= REASONS, f"policy={policy}: the warn-once ledger holds more than reasons: {keys[:5]}"
