"""
Integration tests verifying that after the validToken() → bool refactor,
AuthMiddleware.before_request correctly:
  - Populates request.auth with the actual payload dict (not True)
  - Returns 401 for missing or invalid Bearer tokens
  - Returns the request unchanged (with .auth set) for valid tokens

Run: .venv/bin/python -m pytest tests/test_router_auth_payload.py -v
"""

import os
import pytest
from tina4_python.auth import Auth, AuthMiddleware, get_token

SECRET = "test-router-auth-secret"


# ── Minimal mock objects ──────────────────────────────────────────────────────

class MockRequest:
    """Minimal request stub — just headers dict and auth attribute."""

    def __init__(self, headers: dict):
        self.headers = headers
        self.auth = None


class MockResponse:
    """
    Minimal response callable.

    When called as response(body, status) it records the status and returns
    itself so the middleware can return (request, response) normally.
    When called with no arguments (checked as is) it represents an unset response.
    """

    def __init__(self):
        self.status_code = 200
        self._called = False

    def __call__(self, body=None, status: int = 200):
        self.status_code = status
        self._called = True
        return self


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    """Ensure SECRET env var is set for every test."""
    monkeypatch.setenv("SECRET", SECRET)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAuthMiddlewarePayload:

    def test_valid_bearer_attaches_payload_dict(self):
        """
        A valid Bearer token must attach the decoded payload dict to
        request.auth — NOT True (the bool returned by valid_token).
        """
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user"})

        request = MockRequest(headers={"authorization": f"Bearer {token}"})
        response = MockResponse()

        req_out, res_out = AuthMiddleware.before_request(request, response)

        assert isinstance(req_out.auth, dict), (
            f"request.auth should be a dict, got {type(req_out.auth).__name__!r} "
            f"(value: {req_out.auth!r}). "
            "Did validToken() change to return bool and break payload assignment?"
        )
        assert req_out.auth.get("sub") == "test-user", (
            f"request.auth['sub'] should be 'test-user', got {req_out.auth.get('sub')!r}"
        )

    def test_valid_bearer_does_not_return_401(self):
        """A valid Bearer token must NOT trigger a 401 response."""
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user", "role": "admin"})

        request = MockRequest(headers={"authorization": f"Bearer {token}"})
        response = MockResponse()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 200, (
            f"Valid token should not produce a non-200 status, got {res_out.status_code}"
        )

    def test_invalid_bearer_returns_401(self):
        """A fake/garbage token must produce a 401 response."""
        request = MockRequest(headers={"authorization": "Bearer garbage.token.here"})
        response = MockResponse()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 401, (
            f"Invalid token should produce 401, got {res_out.status_code}"
        )

    def test_missing_bearer_returns_401(self):
        """A request with no Authorization header must produce a 401 response."""
        request = MockRequest(headers={})
        response = MockResponse()

        _req_out, res_out = AuthMiddleware.before_request(request, response)

        assert res_out.status_code == 401, (
            f"Missing token should produce 401, got {res_out.status_code}"
        )

    def test_payload_contains_all_claims(self):
        """The attached payload should include all claims from the token."""
        auth = Auth(secret=SECRET, expires_in=60)
        token = auth.get_token({"sub": "test-user", "role": "editor", "org": "tina4"})

        request = MockRequest(headers={"authorization": f"Bearer {token}"})
        response = MockResponse()

        req_out, _res_out = AuthMiddleware.before_request(request, response)

        assert isinstance(req_out.auth, dict)
        assert req_out.auth.get("sub") == "test-user"
        assert req_out.auth.get("role") == "editor"
        assert req_out.auth.get("org") == "tina4"
