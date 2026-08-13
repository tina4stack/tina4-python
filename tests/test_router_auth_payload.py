"""
Integration tests verifying that after the validToken() → bool refactor,
AuthMiddleware.before_request correctly:
  - Populates request.user with the actual payload dict (not True)
  - Returns 401 for missing or invalid Bearer tokens
  - Returns the request unchanged (with .user set) for valid tokens

These tests drive AuthMiddleware.before_request against a REAL Request (built
via Request.from_scope(), the same path a live ASGI connection takes) and a
REAL Response — no request/response doubles. Before 3.13.99 this suite used a
bare MockRequest with no __slots__, which let `request.auth = ...` "work" even
though the real Request class had no `auth` slot at all: AuthMiddleware.
before_request raised AttributeError on every successful authentication
against a real request, and the mock hid it completely (a project no-mock-
testing violation this rewrite closes). REQ-PY-NO-USER (3.13.99) adds a
mutable `user` slot to Request and fixes AuthMiddleware to assign it (the
mock's `.auth` never matched the field name every other Tina4 language uses).

Run: .venv/bin/python -m pytest tests/test_router_auth_payload.py -v
"""

import pytest

from tina4_python.auth import Auth, AuthMiddleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response

SECRET = "test-router-auth-secret"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _real_request(headers: dict) -> Request:
    """Build a REAL Request via the production from_scope() construction path."""
    header_list = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/__auth_payload_probe",
        "query_string": b"",
        "headers": header_list,
        "client": ("127.0.0.1", 0),
        "scheme": "http",
    }
    return Request.from_scope(scope, body=b"")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    """Ensure SECRET env var is set for every test."""
    monkeypatch.setenv("TINA4_SECRET", SECRET)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAuthMiddlewarePayload:

    def test_valid_bearer_attaches_payload_dict(self):
        """
        A valid Bearer token must attach the decoded payload dict to
        request.user — NOT True (the bool returned by valid_token).
        """
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user"})

        request = _real_request(headers={"authorization": f"Bearer {token}"})
        response = Response()

        req_out, res_out = AuthMiddleware.before_request(request, response)

        assert isinstance(req_out.user, dict), (
            f"request.user should be a dict, got {type(req_out.user).__name__!r} "
            f"(value: {req_out.user!r}). "
            "Did validToken() change to return bool and break payload assignment?"
        )
        assert req_out.user.get("sub") == "test-user", (
            f"request.user['sub'] should be 'test-user', got {req_out.user.get('sub')!r}"
        )

    def test_valid_bearer_does_not_return_401(self):
        """A valid Bearer token must NOT trigger a 401 response."""
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user", "role": "admin"})

        request = _real_request(headers={"authorization": f"Bearer {token}"})
        response = Response()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 200, (
            f"Valid token should not produce a non-200 status, got {res_out.status_code}"
        )

    def test_invalid_bearer_returns_401(self):
        """A fake/garbage token must produce a 401 response."""
        request = _real_request(headers={"authorization": "Bearer garbage.token.here"})
        response = Response()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 401, (
            f"Invalid token should produce 401, got {res_out.status_code}"
        )

    def test_missing_bearer_returns_401(self):
        """A request with no Authorization header must produce a 401 response."""
        request = _real_request(headers={})
        response = Response()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 401, (
            f"Missing token should produce 401, got {res_out.status_code}"
        )

    def test_payload_contains_all_claims(self):
        """The attached payload should include all claims from the token."""
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user", "role": "editor", "org": "tina4"})

        request = _real_request(headers={"authorization": f"Bearer {token}"})
        response = Response()

        req_out, _res_out = AuthMiddleware.before_request(request, response)

        assert isinstance(req_out.user, dict)
        assert req_out.user.get("sub") == "test-user"
        assert req_out.user.get("role") == "editor"
        assert req_out.user.get("org") == "tina4"
