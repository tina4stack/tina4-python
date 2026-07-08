"""TestClient routes through the REAL auth gate (#PY2).

Regression for the eval finding: the in-process ``TestClient`` used to execute a
matched route's handler WITHOUT running the framework's auth check, so a tokenless
write returned 201 in a test while the live server returned 401. A green test hid
a live failure — the verification layer lied.

``TestClient`` now calls the same ``_check_auth`` the live dispatch uses, so:

* an auth-required write (POST/PUT/PATCH/DELETE by default, or any ``@secured()``
  route) with no valid token returns **401**, exactly as in production;
* a valid ``Authorization: Bearer <jwt>`` header (or a ``formToken`` in the body,
  or the ``TINA4_API_KEY``) lets it through;
* a public route (``GET``, or a write marked ``@noauth()``) is unaffected.

NOT a mock: real Router registration, real JWTs via ``get_token`` /
``valid_token_static`` signed with a real ``TINA4_SECRET``, real ``_check_auth``.

Routes are registered in ``setup_method`` (not at import time) so they survive
other suites that clear the route registry between tests.
"""
from __future__ import annotations

import os

# A real signing secret so get_token() and valid_token_static() agree. Set before
# any token is minted; the auth helpers read TINA4_SECRET from the env at call time.
os.environ["TINA4_SECRET"] = "py2-testclient-auth-secret"
# Ensure a stray API key from the environment can't mask the JWT path.
os.environ.pop("TINA4_API_KEY", None)

from tina4_python.auth import get_token
from tina4_python.core.router import get, post, noauth, secured
from tina4_python.test_client import TestClient


class TestTestClientAuthGate:
    def setup_method(self, _method):
        # Register the routes fresh before each test — immune to any suite that
        # clears the route registry between tests.
        @post("/py2-secure-write")
        async def _secure_write(request, response):
            return response({"created": True}, 201)

        @noauth()
        @post("/py2-public-write")
        async def _public_write(request, response):
            return response({"created": True}, 201)

        @get("/py2-public-read")
        async def _public_read(request, response):
            return response({"ok": True})

        @secured()
        @get("/py2-secured-read")
        async def _secured_read(request, response):
            return response({"secret": True})

    def _client(self) -> TestClient:
        return TestClient()

    def test_tokenless_write_is_rejected(self):
        """The core fix: a write to an auth-required route with no token 401s."""
        res = self._client().post("/py2-secure-write", json={"name": "Alice"})
        assert res.status == 401, "tokenless write must be rejected, not silently accepted"
        body = res.json()
        assert body["status"] == 401
        assert body["error"] == "Unauthorized"

    def test_write_with_valid_bearer_token_passes(self):
        token = get_token({"user_id": 1})
        res = self._client().post(
            "/py2-secure-write",
            json={"name": "Alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status == 201
        assert res.json() == {"created": True}

    def test_write_with_valid_form_token_passes(self):
        """frond.js sends the token in the body as formToken — that path works too."""
        token = get_token({"user_id": 1})
        res = self._client().post("/py2-secure-write", json={"name": "Bob", "formToken": token})
        assert res.status == 201

    def test_write_with_invalid_token_is_rejected(self):
        res = self._client().post(
            "/py2-secure-write",
            json={"name": "Mallory"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert res.status == 401

    def test_noauth_write_is_public(self):
        """A write explicitly opened with @noauth() needs no token."""
        res = self._client().post("/py2-public-write", json={"name": "Anon"})
        assert res.status == 201

    def test_public_get_needs_no_token(self):
        res = self._client().get("/py2-public-read")
        assert res.status == 200
        assert res.json() == {"ok": True}

    def test_secured_get_without_token_is_rejected(self):
        res = self._client().get("/py2-secured-read")
        assert res.status == 401

    def test_secured_get_with_token_passes(self):
        token = get_token({"user_id": 1})
        res = self._client().get("/py2-secured-read", headers={"Authorization": f"Bearer {token}"})
        assert res.status == 200
        assert res.json() == {"secret": True}
