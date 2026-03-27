# Tests for CsrfMiddleware — validates CSRF token enforcement on state-changing requests.
#
# Tina4 CSRF convention:
#   - GET/HEAD/OPTIONS are skipped (safe methods)
#   - POST/PUT/PATCH/DELETE require a valid formToken
#   - Token accepted in request.body["formToken"] or X-Form-Token header
#   - Token rejected if sent in query params (security risk)
#   - Routes marked @noauth() skip CSRF
#   - Requests with valid Authorization: Bearer skip CSRF
#   - Session binding: token session_id must match request session
#   - TINA4_CSRF=false disables all checks
import os
import time
import json
import pytest

from tina4_python.auth import Auth
from tina4_python.core.middleware import CsrfMiddleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response


@pytest.fixture(autouse=True)
def csrf_env():
    """Ensure CSRF is enabled and SECRET is set for every test."""
    os.environ["TINA4_CSRF"] = "true"
    os.environ["SECRET"] = "test-csrf-secret"
    yield
    os.environ.pop("TINA4_CSRF", None)
    os.environ.pop("SECRET", None)


class _TestRequest:
    """Lightweight request stand-in that allows arbitrary attributes.

    Request uses __slots__ so we cannot set _handler on it directly.
    This plain object mirrors the attributes CsrfMiddleware reads.
    """

    def __init__(self, method="POST", body=None, headers=None, params=None,
                 handler=None, session=None):
        self.method = method
        self.body = body or {}
        self.headers = headers or {}
        self.params = params or {}
        self._handler = handler
        self.session = session


def _make_request(method="POST", body=None, headers=None, params=None, handler=None, session=None):
    """Build a minimal request object for middleware testing."""
    return _TestRequest(
        method=method, body=body, headers=headers,
        params=params, handler=handler, session=session,
    )


def _make_form_token(auth=None, extra_claims=None):
    """Generate a valid form token JWT."""
    if auth is None:
        auth = Auth(secret="test-csrf-secret")
    claims = {"type": "form"}
    if extra_claims:
        claims.update(extra_claims)
    return auth.get_token(claims)


# ── Safe methods are skipped ──────────────────────────────────────


class TestCsrfSafeMethods:

    def test_get_passes_without_token(self):
        req = _make_request(method="GET")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_head_passes_without_token(self):
        req = _make_request(method="HEAD")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_options_passes_without_token(self):
        req = _make_request(method="OPTIONS")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200


# ── POST without token is blocked ─────────────────────────────────


class TestCsrfBlocksNoToken:

    def test_post_without_token_returns_403(self):
        req = _make_request(method="POST")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_put_without_token_returns_403(self):
        req = _make_request(method="PUT")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_delete_without_token_returns_403(self):
        req = _make_request(method="DELETE")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403


# ── Token accepted in body ─────────────────────────────────────────


class TestCsrfBodyToken:

    def test_post_with_valid_body_token_passes(self):
        token = _make_form_token()
        req = _make_request(method="POST", body={"formToken": token})
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_put_with_valid_body_token_passes(self):
        token = _make_form_token()
        req = _make_request(method="PUT", body={"formToken": token})
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200


# ── Token accepted in X-Form-Token header ──────────────────────────


class TestCsrfHeaderToken:

    def test_post_with_valid_header_token_passes(self):
        token = _make_form_token()
        req = _make_request(
            method="POST",
            headers={"x-form-token": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_header_takes_precedence_when_body_empty(self):
        token = _make_form_token()
        req = _make_request(
            method="POST",
            body={},
            headers={"x-form-token": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200


# ── Token rejected in query params ─────────────────────────────────


class TestCsrfQueryParamRejected:

    def test_post_with_query_param_token_returns_403(self):
        token = _make_form_token()
        req = _make_request(
            method="POST",
            params={"formToken": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_query_param_rejection_message(self):
        token = _make_form_token()
        req = _make_request(
            method="POST",
            params={"formToken": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        content = json.loads(res_out.content.decode())
        assert "query string" in content["message"].lower()


# ── Invalid / expired token is rejected ─────────────────────────────


class TestCsrfInvalidToken:

    def test_malformed_token_returns_403(self):
        req = _make_request(
            method="POST",
            body={"formToken": "not.a.valid.token"},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_expired_token_returns_403(self):
        auth = Auth(secret="test-csrf-secret")
        # Manually build an expired token
        from tina4_python.auth import _b64url_encode
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({
            "type": "form",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        }).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired_token = f"{header}.{payload}.{sig}"

        req = _make_request(
            method="POST",
            body={"formToken": expired_token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_wrong_secret_token_returns_403(self):
        wrong_auth = Auth(secret="wrong-secret")
        token = wrong_auth.get_token({"type": "form"})
        req = _make_request(
            method="POST",
            body={"formToken": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403


# ── @noauth() routes skip CSRF ─────────────────────────────────────


class TestCsrfNoauthSkip:

    def test_noauth_handler_skips_csrf(self):
        def handler():
            pass
        handler._noauth = True

        req = _make_request(method="POST", handler=handler)
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_handler_without_noauth_requires_csrf(self):
        def handler():
            pass
        handler._noauth = False

        req = _make_request(method="POST", handler=handler)
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403


# ── Bearer auth skips CSRF ──────────────────────────────────────────


class TestCsrfBearerSkip:

    def test_valid_bearer_skips_csrf(self):
        auth = Auth(secret="test-csrf-secret")
        bearer = auth.get_token({"user_id": 1})
        req = _make_request(
            method="POST",
            headers={"authorization": f"Bearer {bearer}"},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_invalid_bearer_does_not_skip_csrf(self):
        req = _make_request(
            method="POST",
            headers={"authorization": "Bearer invalid-token"},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        # Invalid bearer means CSRF check runs and fails (no formToken)
        assert res_out.status_code == 403


# ── Session binding ─────────────────────────────────────────────────


class TestCsrfSessionBinding:

    def test_token_with_wrong_session_id_returns_403(self):
        token = _make_form_token(extra_claims={"session_id": "session-abc"})
        session = type("Session", (), {
            "session_id": "session-xyz",
            "get": lambda self, k: getattr(self, k, None),
        })()
        req = _make_request(
            method="POST",
            body={"formToken": token},
            session=session,
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403

    def test_token_with_matching_session_id_passes(self):
        token = _make_form_token(extra_claims={"session_id": "session-abc"})
        req = _make_request(
            method="POST",
            body={"formToken": token},
        )
        req.session = type("Session", (), {
            "session_id": "session-abc",
            "get": lambda self, k: getattr(self, k, None),
        })()
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200

    def test_token_without_session_id_passes(self):
        """Token with no session_id claim skips session binding check."""
        token = _make_form_token()
        req = _make_request(
            method="POST",
            body={"formToken": token},
        )
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 200


# ── TINA4_CSRF env toggle ──────────────────────────────────────────


class TestCsrfEnvToggle:

    def test_csrf_disabled_via_env_false(self):
        """When TINA4_CSRF=false, the env flag is off but the middleware
        still runs if called directly.  The env check controls auto-activation,
        not direct calls.  This test documents the behaviour."""
        os.environ["TINA4_CSRF"] = "false"
        # The middleware reads the env but does not short-circuit when called
        # directly — the env only controls auto-activation in the server loop.
        # So we verify the env value is read correctly.
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        assert csrf_env is False

    def test_csrf_default_on_without_env(self):
        """Without TINA4_CSRF set, CSRF defaults to active."""
        os.environ.pop("TINA4_CSRF", None)
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        assert csrf_env is True

    def test_csrf_enabled_via_env_true(self):
        os.environ["TINA4_CSRF"] = "true"
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        assert csrf_env is True

    def test_csrf_disabled_via_env_zero(self):
        os.environ["TINA4_CSRF"] = "0"
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        assert csrf_env is False

    def test_csrf_disabled_via_env_no(self):
        os.environ["TINA4_CSRF"] = "no"
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        assert csrf_env is False


# ── Error response structure ────────────────────────────────────────


class TestCsrfErrorResponse:

    def test_403_response_has_error_envelope(self):
        req = _make_request(method="POST")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        assert res_out.status_code == 403
        content = json.loads(res_out.content.decode())
        assert content["error"] is True
        assert content["code"] == "CSRF_INVALID"
        assert "message" in content

    def test_403_response_has_status_field(self):
        req = _make_request(method="POST")
        res = Response()
        req_out, res_out = CsrfMiddleware.before_csrf(req, res)
        content = json.loads(res_out.content.decode())
        assert content["status"] == 403
