# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The framework's own inline content runs under the strict default CSP (ADR-0088).

The framework serves ``default-src 'self'`` by default. A browser refuses every
inline ``<style>``/``<script>`` under that policy unless the element carries a
nonce the ``Content-Security-Policy`` header also names. So the framework mints
one nonce per response, injects ``'nonce-<X>'`` into style-src AND script-src,
and stamps the SAME value on every inline ``<style>``/``<script>`` it emits. It
also de-inlines every ``style="..."`` attribute, because a nonce covers a
``<style>`` ELEMENT but never a style attribute.

NO MOCKS: a real project served by ``run()``'s own server over real HTTP. The
welcome page at ``/`` is the page the reported bug rendered unstyled.
"""
import http.client
import re

import pytest

from conftest import boot_child_server

# A project with NO "/" route, so GET / falls through to the framework's own
# welcome page (served at "/" in dev mode).
APP = "from tina4_python.core import run\nif __name__ == '__main__':\n    run()\n"


def _write_app(project_dir, port):
    (project_dir / "app.py").write_text(APP)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    root = tmp_path_factory.mktemp("csp_nonce_inline")
    process, port = boot_child_server(
        root, _write_app,
        extra_env=lambda port: {
            "TINA4_DEBUG": "true",
            "TINA4_AUTO_MIGRATE": "false",
            "TINA4_NO_BROWSER": "true",
            "TINA4_OVERRIDE_CLIENT": "true",
            "TINA4_SECRET": "csp-nonce-secret-0123456789abcdef",
        },
        unset_env=("TINA4_CSP",),
        log_dir=root / "logs",
    )
    try:
        yield port
    finally:
        process.terminate()
        process.wait(timeout=15)


def _get(port, path="/"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    connection.request("GET", path)
    reply = connection.getresponse()
    body = reply.read().decode("utf-8", "replace")
    headers = {name.lower(): value for name, value in reply.getheaders()}
    connection.close()
    return reply.status, headers, body


def _csp_nonce(csp):
    match = re.search(r"'nonce-([^']+)'", csp)
    return match.group(1) if match else None


def test_welcome_csp_header_carries_a_nonce_in_style_and_script_src(served):
    status, headers, _ = _get(served)
    assert status == 200, status
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp, csp
    directives = {d.strip().split()[0]: d.strip() for d in csp.split(";") if d.strip()}
    assert "'nonce-" in directives.get("style-src", ""), csp
    assert "'nonce-" in directives.get("script-src", ""), csp
    assert "'unsafe-inline'" not in csp, csp


def test_welcome_inline_style_and_script_carry_the_header_nonce(served):
    status, headers, body = _get(served)
    assert status == 200, status
    nonce = _csp_nonce(headers["content-security-policy"])
    assert nonce, headers["content-security-policy"]

    # Every inline <style>/<script> the framework emits must carry THIS nonce.
    # An external <script src=...> (the dev toolbar) is exempt and must NOT be
    # forced to carry one, so only inspect tags with no src attribute.
    inline_style_open = re.findall(r"<style\b([^>]*)>", body)
    inline_script_open = re.findall(r"<script\b([^>]*)>", body)
    assert inline_style_open, "welcome page emitted no <style>"
    assert inline_script_open, "welcome page emitted no <script>"

    for attrs in inline_style_open:
        assert f'nonce="{nonce}"' in attrs, f"<style{attrs}> missing the header nonce"
    for attrs in inline_script_open:
        if "src=" in attrs:
            continue  # external script needs no nonce
        assert f'nonce="{nonce}"' in attrs, f"<script{attrs}> missing the header nonce"


def test_welcome_page_emits_no_inline_style_attribute(served):
    status, _, body = _get(served)
    assert status == 200, status
    # The welcome page is framework-served HTML; the dev toolbar it injects is
    # itself CSP-clean (external link + script), so zero style= is the contract.
    assert 'style="' not in body, "framework welcome page still emits a style= attribute"
    # An inline event handler is an attribute like onclick="..."; a nonce does
    # not cover it, so the framework must bind via addEventListener instead.
    assert 'onclick="' not in body, (
        "framework welcome page still emits an inline onclick handler"
    )


def test_each_response_gets_a_distinct_nonce(served):
    _, h1, _ = _get(served)
    _, h2, _ = _get(served)
    n1 = _csp_nonce(h1["content-security-policy"])
    n2 = _csp_nonce(h2["content-security-policy"])
    assert n1 and n2 and n1 != n2, f"nonce reused across responses: {n1}"
