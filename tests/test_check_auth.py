# Tests for _check_auth — validates the three-source auth chain in server.py.
#
# _check_auth validates auth on routes in priority order:
#   1. Authorization: Bearer header (API clients, frond.js after FreshToken)
#   2. request.body["formToken"] (frond.js saveForm with {{ form_token() }})
#   3. request.session.get("token") (for @secured() GET routes after login)
#
# When validating a body formToken, it also returns a FreshToken response
# header so frond.js can use the Authorization header on subsequent requests.
import os
import pytest

from tina4_python.auth import Auth, get_token
from tina4_python.core.response import Response
from tina4_python.core.server import _check_auth


SECRET = "test-check-auth-secret"


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    """Set SECRET for JWT operations and clear API key."""
    monkeypatch.setenv("SECRET", SECRET)
    monkeypatch.delenv("TINA4_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    yield


class _MockSession:
    """Minimal session stand-in."""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


class _MockRequest:
    """Lightweight request object for _check_auth testing."""

    def __init__(self, headers=None, body=None, session=None):
        self.headers = headers or {}
        self.body = body or {}
        self.session = session


def _make_token(claims=None):
    """Generate a valid JWT token."""
    auth = Auth(secret=SECRET)
    return auth.get_token(claims or {"user_id": 1})


def _auth_required_route():
    """Route dict that requires auth."""
    return {"auth_required": True}


def _public_route():
    """Route dict that does NOT require auth."""
    return {"auth_required": False}


# ── Public routes skip auth ──────────────────────────────────────


class TestPublicRoutes:

    def test_public_route_passes_without_any_token(self):
        req = _MockRequest()
        res = Response()
        skipped = _check_auth(req, res, _public_route())
        assert skipped is False

    def test_public_route_ignores_invalid_token(self):
        req = _MockRequest(headers={"authorization": "Bearer invalid-junk"})
        res = Response()
        skipped = _check_auth(req, res, _public_route())
        assert skipped is False


# ── Priority 1: Authorization header ────────────────────────────


class TestAuthorizationHeader:

    def test_valid_bearer_token_passes(self):
        token = _make_token()
        req = _MockRequest(headers={"authorization": f"Bearer {token}"})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_invalid_bearer_token_falls_through(self):
        req = _MockRequest(headers={"authorization": "Bearer not-a-real-jwt"})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_missing_header_falls_through(self):
        req = _MockRequest()
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_api_key_accepted(self, monkeypatch):
        monkeypatch.setenv("TINA4_API_KEY", "my-secret-api-key")
        req = _MockRequest(headers={"authorization": "Bearer my-secret-api-key"})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_wrong_api_key_rejected(self, monkeypatch):
        monkeypatch.setenv("TINA4_API_KEY", "correct-key")
        req = _MockRequest(headers={"authorization": "Bearer wrong-key"})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401


# ── Priority 2: Body formToken ───────────────────────────────────


class TestBodyFormToken:

    def test_valid_form_token_in_body_passes(self):
        token = _make_token({"type": "form"})
        req = _MockRequest(body={"formToken": token})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_form_token_returns_fresh_token_header(self):
        token = _make_token({"type": "form"})
        req = _MockRequest(body={"formToken": token})
        res = Response()
        _check_auth(req, res, _auth_required_route())
        # FreshToken is set via response.header() — check instance _headers list
        fresh_headers = [v for k, v in res._headers if k == "FreshToken"]
        assert len(fresh_headers) == 1
        fresh = fresh_headers[0]
        assert len(fresh) > 0
        # Verify the fresh token is valid
        auth = Auth(secret=SECRET)
        assert auth.valid_token(fresh)

    def test_invalid_form_token_rejected(self):
        req = _MockRequest(body={"formToken": "garbage-token"})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_empty_form_token_rejected(self):
        req = _MockRequest(body={"formToken": ""})
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_form_token_not_checked_when_header_valid(self):
        """If Authorization header is valid, body token is not needed."""
        header_token = _make_token({"user_id": 1})
        req = _MockRequest(
            headers={"authorization": f"Bearer {header_token}"},
            body={"formToken": "this-would-fail-if-checked"},
        )
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_non_dict_body_does_not_crash(self):
        """If body is a string or None, formToken check should not crash."""
        req = _MockRequest(body="raw-string-body")
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401


# ── Priority 3: Session token ───────────────────────────────────


class TestSessionToken:

    def test_valid_session_token_passes(self):
        token = _make_token({"customer_id": 42, "role": "customer"})
        session = _MockSession({"token": token})
        req = _MockRequest(session=session)
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_invalid_session_token_rejected(self):
        session = _MockSession({"token": "expired-or-bad-token"})
        req = _MockRequest(session=session)
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_no_session_rejected(self):
        req = _MockRequest(session=None)
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_empty_session_token_rejected(self):
        session = _MockSession({"token": ""})
        req = _MockRequest(session=session)
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_session_not_checked_when_header_valid(self):
        """If Authorization header is valid, session is not needed."""
        header_token = _make_token()
        session = _MockSession({"token": "bad-token"})
        req = _MockRequest(
            headers={"authorization": f"Bearer {header_token}"},
            session=session,
        )
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_session_not_checked_when_body_token_valid(self):
        """If body formToken is valid, session is not needed."""
        form_token = _make_token({"type": "form"})
        session = _MockSession({"token": "bad-token"})
        req = _MockRequest(body={"formToken": form_token}, session=session)
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False
        # FreshToken header is on the response instance, no cleanup needed


# ── Priority chain ───────────────────────────────────────────────


class TestPriorityChain:

    def test_all_three_sources_invalid_returns_401(self):
        session = _MockSession({"token": "bad"})
        req = _MockRequest(
            headers={"authorization": "Bearer bad"},
            body={"formToken": "bad"},
            session=session,
        )
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is True
        assert res.status_code == 401

    def test_only_session_valid_passes(self):
        """When header and body fail, valid session token saves the day."""
        token = _make_token({"customer_id": 1})
        session = _MockSession({"token": token})
        req = _MockRequest(
            headers={"authorization": "Bearer bad"},
            body={"formToken": "bad"},
            session=session,
        )
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False

    def test_only_body_valid_passes(self):
        """When header fails, valid body formToken saves the day."""
        form_token = _make_token({"type": "form"})
        req = _MockRequest(
            headers={"authorization": "Bearer bad"},
            body={"formToken": form_token},
        )
        res = Response()
        skipped = _check_auth(req, res, _auth_required_route())
        assert skipped is False
        # FreshToken header is on the response instance, no cleanup needed

    def test_401_response_body_is_json(self):
        """Verify the 401 response contains structured error JSON."""
        req = _MockRequest()
        res = Response()
        _check_auth(req, res, _auth_required_route())
        assert res.status_code == 401
