# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""#342 — the auth-gate 401 and a throwing middleware's 500 go through the SAME
negotiated error renderer as 404/403/500 (ERR-DEC-02).

The defect (filed against tina4-php, same in all four): a browser that submitted
a form to a protected route without a valid token, or hit a route whose
middleware hook threw, got a raw JSON body instead of the framework error PAGE.
Every other framework error (404, a handler that throws, a middleware that
returns ``False``) already negotiated HTML-vs-JSON on Accept; these two emit
paths did not.

Fixed: a browser (Accept: text/html) gets ``errors/{401,500}.twig``; an API
client (Accept: application/json) gets the one JSON envelope
``{error, code, message, status, request_id}``. The 500 keeps CWE-209 — the real
exception never reaches the client, in either representation.

No mocks: real Router registration, real dispatch through the front controller
via ``TestClient``, real ``TINA4_SECRET``. Mutation-proved — reverting either
emit to an unconditional JSON body turns the HTML-branch assertions red (see
plan/error-negotiation-401-middleware500.md).
"""
from __future__ import annotations

import json
import os

# A real secret so the auth gate behaves exactly as in production. An API key in
# the environment could mask the JWT path, so clear it.
os.environ["TINA4_SECRET"] = "err-neg-342-secret-0123456789abcdef"
os.environ.pop("TINA4_API_KEY", None)

from tina4_python.core.router import get, post, middleware  # noqa: E402
from tina4_python.test_client import TestClient  # noqa: E402

_BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_API = {"Accept": "application/json"}

# A real middleware whose before-hook raises. The exception message carries a
# marker that must NEVER reach the client (CWE-209).
_SECRET_DETAIL = "boom-secret-stack-detail"


class _ThrowingBefore:
    @staticmethod
    def before_explode(request, response):
        raise RuntimeError(f"middleware exploded: {_SECRET_DETAIL}")


class TestAuthGate401Negotiation:
    def setup_method(self, _method):
        # A POST is auth-required by default; registered fresh each test so a
        # registry-clearing suite cannot strip it.
        @post("/err342-secure")
        async def _secure_write(request, response):
            return response({"created": True}, 201)

    def test_browser_without_token_gets_the_html_401_page(self):
        res = TestClient().post("/err342-secure", json={"x": 1}, headers=_BROWSER)
        assert res.status == 401
        assert "text/html" in res.content_type
        body = res.body.decode("utf-8", "replace")
        # The rendered errors/401.twig page, not a JSON body.
        assert "error-home" in body and "401" in body

    def test_api_client_without_token_gets_the_json_envelope(self):
        res = TestClient().post("/err342-secure", json={"x": 1}, headers=_API)
        assert res.status == 401
        assert "application/json" in res.content_type
        body = res.json()
        assert body["error"] is True
        assert body["code"] == "UNAUTHORIZED"
        assert body["status"] == 401
        assert "request_id" in body


class TestMiddleware500Negotiation:
    def setup_method(self, _method):
        # A public GET (no auth to get in the way) whose before-middleware throws.
        @middleware(_ThrowingBefore)
        @get("/err342-boom")
        async def _boom(request, response):
            return response({"never": "reached"})

    def test_browser_gets_the_html_500_page_without_exception_text(self):
        res = TestClient().get("/err342-boom", headers=_BROWSER)
        assert res.status == 500
        assert "text/html" in res.content_type
        body = res.body.decode("utf-8", "replace")
        assert "error-home" in body and "500" in body  # the rendered errors/500.twig page
        assert _SECRET_DETAIL not in body  # CWE-209

    def test_api_client_gets_the_json_envelope_without_exception_text(self):
        res = TestClient().get("/err342-boom", headers=_API)
        assert res.status == 500
        assert "application/json" in res.content_type
        body = res.json()
        assert body["error"] is True
        assert body["code"] == "INTERNAL_SERVER_ERROR"
        assert body["status"] == 500
        assert "request_id" in body
        assert _SECRET_DETAIL not in json.dumps(body)  # CWE-209
