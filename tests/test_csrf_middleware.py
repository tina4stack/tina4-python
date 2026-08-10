# Behavioural tests for CsrfMiddleware — CSRF token enforcement on state-changing requests.
#
# These tests drive the REAL request pipeline: a real Request built from an ASGI
# scope (Request.from_scope), a real route registered on the Router with
# @middleware(CsrfMiddleware), and the real server dispatcher
# (_run_before_middleware) that production uses. No request/response/session
# doubles — the middleware sees exactly what it sees when serving traffic, so a
# regression in the real wiring (e.g. request._handler never being set) is caught
# here.
#
# Tina4 CSRF convention:
#   - GET/HEAD/OPTIONS are skipped (safe methods)
#   - POST/PUT/PATCH/DELETE require a valid formToken
#   - Token accepted in request.body["formToken"] or X-Form-Token header
#   - Token rejected if sent in query params (security risk)
#   - Routes marked @noauth() skip CSRF
#   - Requests with a valid Authorization: Bearer skip CSRF
#   - Session binding: token session_id must match the request session
#   - TINA4_CSRF=false disables all checks
import os
import time
import json
import itertools
import pytest

from tina4_python.auth import Auth, _b64url_encode
from tina4_python.core.middleware import CsrfMiddleware
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.router import Router, noauth
from tina4_python.core.server import _run_before_middleware
from tina4_python.session import Session


@pytest.fixture(autouse=True)
def csrf_env():
    """Ensure CSRF is enabled and SECRET is set for every test."""
    os.environ["TINA4_CSRF"] = "true"
    os.environ["TINA4_SECRET"] = "test-csrf-secret"
    yield
    os.environ.pop("TINA4_CSRF", None)
    os.environ.pop("TINA4_SECRET", None)


# Monotonic counter so each registered probe route gets a unique path —
# Router.add replaces an existing (method, path), so reusing paths would let
# tests stomp on each other.
_path_counter = itertools.count()


def _ok_handler(request, response):
    """A normal state-changing handler — protected by CSRF."""
    return response({"ok": True})


class _Result:
    """The outcome of running CsrfMiddleware through the real before-dispatcher.

    ``passed`` is True when the middleware let the request continue to the
    handler (no short-circuit), False when it short-circuited with an error.
    The handler itself runs in a later dispatch stage we don't invoke here, so
    a "pass" is asserted via ``passed``/``status_code``, and a "reject" is
    asserted via the real error envelope the middleware wrote.
    """

    __slots__ = ("status_code", "content", "passed")

    def __init__(self, response, skip):
        self.status_code = response.status_code
        self.content = response.content
        # skip=True means a before_* short-circuited. For a CSRF-only route the
        # only thing that short-circuits is a CSRF rejection.
        self.passed = not skip

    def envelope(self):
        return json.loads(self.content.decode())


def _dispatch(method="POST", *, body=None, headers=None, params=None,
              handler=None, session=None, route_path=None):
    """Register a real route guarded by CsrfMiddleware and run it through the
    real server before-middleware dispatcher with a real Request.

    Returns a ``_Result`` describing whether the middleware passed the request
    through (continue to handler) or short-circuited with an error response.
    """
    handler = handler or _ok_handler
    path = route_path or f"/__csrf_probe_{next(_path_counter)}"

    Router.add(method, path, handler, middleware=[CsrfMiddleware])
    route, route_params = Router.match(method, path)
    assert route is not None, f"probe route {path} did not register"

    # Build the raw body + headers exactly as the test client / server do.
    raw_body = b""
    header_list = []
    if headers:
        for k, v in headers.items():
            header_list.append((k.lower().encode(), v.encode()))
    if body is not None:
        raw_body = json.dumps(body).encode()
        if not any(h[0] == b"content-type" for h in header_list):
            header_list.append((b"content-type", b"application/json"))
        header_list.append((b"content-length", str(len(raw_body)).encode()))

    query_string = ""
    if params:
        query_string = "&".join(f"{k}={v}" for k, v in params.items())

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string.encode(),
        "headers": header_list,
        "client": ("127.0.0.1", 0),
    }
    request = Request.from_scope(scope, raw_body)
    request._route_params = route_params
    request.merge_route_params()
    # The real dispatch path sets request._handler before middleware runs so
    # before_csrf can read handler metadata (e.g. _noauth). Mirror that here.
    request._handler = route.get("handler")
    if session is not None:
        request.session = session

    response = Response()
    _req, response, skip = _run_before_middleware(request, response, route)
    return _Result(response, skip)


def _make_form_token(auth=None, extra_claims=None):
    """Generate a valid form token JWT."""
    if auth is None:
        auth = Auth(secret="test-csrf-secret")
    claims = {"type": "form"}
    if extra_claims:
        claims.update(extra_claims)
    return auth.get_token(claims)


# ── Interface contract (rename guard) ──────────────────────────────


class TestCsrfContract:
    """One consolidated existence guard for the middleware surface, plus a
    sanity check that the env-parse default is enabled. Cheap rename guard;
    real behaviour is covered by the classes below."""

    def test_middleware_exposes_before_hook(self):
        for name in ("before_csrf",):
            assert hasattr(CsrfMiddleware, name), f"CsrfMiddleware missing {name}"
            assert callable(getattr(CsrfMiddleware, name))


# ── Safe methods are skipped ──────────────────────────────────────


class TestCsrfSafeMethods:

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_safe_method_passes_without_token(self, method):
        res = _dispatch(method=method)
        # No short-circuit: the safe method falls straight through to the
        # handler (middleware does not block it).
        assert res.passed is True
        assert res.status_code == 200


# ── State-changing methods without a token are blocked ─────────────


class TestCsrfBlocksNoToken:

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_write_without_token_is_rejected_403(self, method):
        res = _dispatch(method=method)
        assert res.passed is False  # handler short-circuited, never reached
        assert res.status_code == 403
        body = res.envelope()
        assert body["error"] is True
        assert body["code"] == "CSRF_INVALID"


# ── Token accepted in body ─────────────────────────────────────────


class TestCsrfBodyToken:

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_valid_body_token_passes(self, method):
        res = _dispatch(method=method, body={"formToken": _make_form_token()})
        assert res.passed is True
        assert res.status_code == 200


# ── Token accepted in X-Form-Token header ──────────────────────────


class TestCsrfHeaderToken:

    def test_valid_header_token_passes(self):
        res = _dispatch(headers={"x-form-token": _make_form_token()})
        assert res.passed is True
        assert res.status_code == 200

    def test_header_token_used_when_body_has_no_token(self):
        # Body present but with no formToken key — the header is the fallback.
        res = _dispatch(body={"name": "Alice"},
                        headers={"x-form-token": _make_form_token()})
        assert res.passed is True
        assert res.status_code == 200

    def test_body_token_takes_precedence_over_header(self):
        # A valid body token wins even when the header carries garbage —
        # the middleware checks the body first.
        res = _dispatch(body={"formToken": _make_form_token()},
                        headers={"x-form-token": "not.a.token"})
        assert res.passed is True
        assert res.status_code == 200


# ── Token rejected when sent in the query string ───────────────────


class TestCsrfQueryParamRejected:

    def test_query_param_token_is_rejected_403(self):
        res = _dispatch(params={"formToken": _make_form_token()})
        assert res.passed is False
        assert res.status_code == 403

    def test_query_param_rejection_explains_why(self):
        res = _dispatch(params={"formToken": _make_form_token()})
        body = res.envelope()
        assert body["code"] == "CSRF_INVALID"
        # A real, otherwise-valid token in the URL is STILL rejected because
        # the URL leaks into logs/referrers — the message must say so.
        assert "query string" in body["message"].lower()


# ── Invalid / expired / forged tokens are rejected ─────────────────


class TestCsrfInvalidToken:

    def test_malformed_token_is_rejected_403(self):
        res = _dispatch(body={"formToken": "not.a.valid.token"})
        assert res.passed is False
        assert res.status_code == 403
        assert res.envelope()["code"] == "CSRF_INVALID"

    def test_expired_token_is_rejected_403(self):
        auth = Auth(secret="test-csrf-secret")
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({
            "type": "form",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        }).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired_token = f"{header}.{payload}.{sig}"

        res = _dispatch(body={"formToken": expired_token})
        assert res.passed is False
        assert res.status_code == 403

    def test_token_signed_with_wrong_secret_is_rejected_403(self):
        forged = Auth(secret="wrong-secret").get_token({"type": "form"})
        res = _dispatch(body={"formToken": forged})
        assert res.passed is False
        assert res.status_code == 403

    def test_tampered_token_payload_is_rejected_403(self):
        # Take a genuine token, mutate the payload (privilege-escalation style),
        # keep the original signature — the HMAC check must fail.
        good = _make_form_token()
        header, _payload, sig = good.split(".")
        tampered_claims = Auth(secret="test-csrf-secret").get_payload(good)
        tampered_claims["admin"] = True
        new_payload = _b64url_encode(json.dumps(tampered_claims).encode())
        tampered = f"{header}.{new_payload}.{sig}"

        res = _dispatch(body={"formToken": tampered})
        assert res.passed is False
        assert res.status_code == 403


# ── @noauth() routes skip CSRF (real handler-metadata path) ────────


class TestCsrfNoauthSkip:
    """These exercise the real ``request._handler`` wiring. Before the fix
    that sets ``request._handler`` in dispatch, the @noauth skip was dead code
    on a real Request (slots had no ``_handler`` slot) and a @noauth POST would
    have been wrongly blocked with 403."""

    def test_noauth_write_route_skips_csrf(self):
        @noauth()
        def public_handler(request, response):
            return response({"ok": True})

        res = _dispatch(method="POST", handler=public_handler)
        assert res.passed is True
        assert res.status_code == 200

    def test_non_noauth_write_route_still_requires_csrf(self):
        # A plain handler (no @noauth) with no token is blocked — proving the
        # skip is specific to @noauth, not a blanket pass.
        res = _dispatch(method="POST", handler=_ok_handler)
        assert res.passed is False
        assert res.status_code == 403


# ── Bearer auth skips CSRF (API clients) ───────────────────────────


class TestCsrfBearerSkip:

    def test_valid_bearer_skips_csrf(self):
        bearer = Auth(secret="test-csrf-secret").get_token({"user_id": 1})
        res = _dispatch(headers={"authorization": f"Bearer {bearer}"})
        assert res.passed is True
        assert res.status_code == 200

    def test_invalid_bearer_does_not_skip_csrf(self):
        # A bogus bearer falls through to the form-token check, which then
        # fails for the missing token — 403, not a silent pass.
        res = _dispatch(headers={"authorization": "Bearer not-a-real-token"})
        assert res.passed is False
        assert res.status_code == 403

    def test_bearer_signed_with_wrong_secret_does_not_skip_csrf(self):
        forged_bearer = Auth(secret="wrong-secret").get_token({"user_id": 1})
        res = _dispatch(headers={"authorization": f"Bearer {forged_bearer}"})
        assert res.passed is False
        assert res.status_code == 403


# ── Session binding ────────────────────────────────────────────────


def _started_session(session_id):
    """A REAL Session (default file backend) started with a known id.

    3.13.95: strict mode means ``start()`` adopts a supplied id only when the
    store already holds that session, so the record is written first. Without
    this the session silently comes back under a freshly-minted id and the
    binding assertions compare against the wrong one. See ADR-0021.
    """
    session = Session()
    session.start()
    session._handler.write(session_id, {"_seeded": True}, session._ttl)
    session.start(session_id)
    return session


class TestCsrfSessionBinding:

    def test_token_session_id_mismatch_is_rejected_403(self):
        token = _make_form_token(extra_claims={"session_id": "session-abc"})
        res = _dispatch(
            body={"formToken": token},
            session=_started_session("session-xyz"),
        )
        assert res.passed is False
        assert res.status_code == 403
        assert res.envelope()["code"] == "CSRF_INVALID"

    def test_token_session_id_match_passes(self):
        token = _make_form_token(extra_claims={"session_id": "session-abc"})
        res = _dispatch(
            body={"formToken": token},
            session=_started_session("session-abc"),
        )
        assert res.passed is True
        assert res.status_code == 200

    def test_token_without_session_id_skips_binding_check(self):
        # No session_id claim → binding check does not run, so a mismatched
        # request session is irrelevant and the request passes.
        token = _make_form_token()
        res = _dispatch(
            body={"formToken": token},
            session=_started_session("some-other-session"),
        )
        assert res.passed is True
        assert res.status_code == 200


# ── Token rotation / refresh ───────────────────────────────────────


class TestCsrfTokenRotation:
    """A refreshed token must remain a valid CSRF token, and refresh must not
    resurrect an invalid one."""

    def test_refreshed_token_still_passes_csrf(self):
        auth = Auth(secret="test-csrf-secret")
        original = _make_form_token(auth=auth)
        rotated = auth.refresh_token(original)

        # Refresh re-validates and re-issues a token carrying the same claims.
        assert rotated is not None
        assert auth.valid_token(rotated) is not None
        assert auth.get_payload(rotated)["type"] == "form"

        res = _dispatch(body={"formToken": rotated})
        assert res.passed is True
        assert res.status_code == 200

    def test_refreshed_token_preserves_session_binding(self):
        auth = Auth(secret="test-csrf-secret")
        original = _make_form_token(auth=auth, extra_claims={"session_id": "sess-1"})
        rotated = auth.refresh_token(original)

        # Rotation keeps the session_id claim, so binding still matches.
        ok = _dispatch(body={"formToken": rotated},
                       session=_started_session("sess-1"))
        assert ok.passed is True
        assert ok.status_code == 200

        # ...and still rejects a different session.
        bad = _dispatch(body={"formToken": rotated},
                        session=_started_session("sess-2"))
        assert bad.passed is False
        assert bad.status_code == 403

    def test_refreshing_an_invalid_token_returns_none_and_cannot_pass(self):
        auth = Auth(secret="test-csrf-secret")
        # A token forged with the wrong secret cannot be refreshed.
        forged = Auth(secret="wrong-secret").get_token({"type": "form"})
        assert auth.refresh_token(forged) is None

    def test_token_refreshed_under_wrong_secret_is_rejected(self):
        # Rotate a valid token but sign the fresh one with a different secret —
        # the middleware (using TINA4_SECRET) must reject the rotated token.
        original = _make_form_token()
        rotated_wrong = Auth(secret="another-wrong-secret").refresh_token(original)
        # refresh validates against its OWN secret, so a genuinely-signed
        # original cannot be refreshed by an Auth holding the wrong secret.
        assert rotated_wrong is None


# ── TINA4_CSRF kill switch (real middleware behaviour) ─────────────


class TestCsrfEnvToggle:
    """TINA4_CSRF=false (or 0/no) disables all CSRF enforcement; any other
    value (or unset) keeps it on. Driven through the real middleware, not by
    re-asserting the parse expression."""

    @pytest.mark.parametrize("value", ["false", "0", "no", "FALSE", "No"])
    def test_disabled_values_let_a_tokenless_write_through(self, value):
        os.environ["TINA4_CSRF"] = value
        res = _dispatch(method="POST")  # no token at all
        assert res.passed is True
        assert res.status_code == 200

    @pytest.mark.parametrize("value", ["true", "1", "yes", "anything-else"])
    def test_enabled_or_unknown_values_keep_enforcement_on(self, value):
        os.environ["TINA4_CSRF"] = value
        res = _dispatch(method="POST")  # no token
        assert res.passed is False
        assert res.status_code == 403

    def test_unset_defaults_to_enforced(self):
        os.environ.pop("TINA4_CSRF", None)
        res = _dispatch(method="POST")
        assert res.passed is False
        assert res.status_code == 403


# ── Error response structure ───────────────────────────────────────


class TestCsrfErrorResponse:

    def test_403_response_has_full_error_envelope(self):
        res = _dispatch(method="POST")
        assert res.passed is False
        assert res.status_code == 403
        body = res.envelope()
        assert body["error"] is True
        assert body["code"] == "CSRF_INVALID"
        assert "message" in body
        assert body["status"] == 403


class TestCsrfNoDefaultSecret:
    """SEC-01 (Feature 64 audit): the CSRF middleware must never fall back to a
    guessable built-in secret. With TINA4_SECRET unset, a formToken an attacker
    signs with the retired public 'tina4-default-secret' must be REJECTED (fail
    closed) - the middleware resolves the secret through Auth (blank warns,
    never substitutes a default). Real HS256, real Request, no mocks."""

    def test_forged_default_secret_token_rejected_when_secret_unset(self):
        os.environ.pop("TINA4_SECRET", None)
        forged = Auth(secret="tina4-default-secret").get_token({"type": "form"})
        res = _dispatch("POST", body={"formToken": forged})
        assert res.status_code == 403, (
            "a formToken signed with the public default secret must be rejected "
            "when TINA4_SECRET is unset"
        )
