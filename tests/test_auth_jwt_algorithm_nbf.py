"""Regression tests for the JWT algorithm/nbf cluster (python#105, #106, #107).

Each test is named for the behaviour it pins and carries a positive AND a negative
case, so reverting the fix reproduces the original bug rather than silently passing.
No doubles anywhere: these exercise the real Auth against real HMAC digests.
"""
import base64
import hashlib
import hmac
import json
import os
import time

import pytest

from tina4_python.auth import Auth, _JWT_LEEWAY_SECONDS

SECRET = "jwt-cluster-regression-secret"


def _parts(token):
    h, p, s = token.split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
    return (json.loads(base64.urlsafe_b64decode(pad(h))),
            json.loads(base64.urlsafe_b64decode(pad(p))),
            s)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ── python#105: the header must name the algorithm that actually signed ──

@pytest.mark.parametrize("alg,digest", [
    ("HS256", hashlib.sha256),
    ("HS384", hashlib.sha384),
    ("HS512", hashlib.sha512),
])
def test_header_alg_matches_the_digest_that_signed_it(alg, digest):
    """POSITIVE: for every supported alg the signature is that alg's HMAC.

    Before the fix _sign hardcoded sha256, so an Auth(algorithm="HS512") emitted a
    header saying HS512 over an HMAC-SHA256 signature - any RFC-conformant verifier
    reading the header computed a different digest and rejected the token.
    """
    auth = Auth(secret=SECRET, algorithm=alg)
    token = auth.get_token({"user_id": 7})
    header, _, sig = _parts(token)

    assert header["alg"] == alg
    signing_input = ".".join(token.split(".")[:2])
    expected = _b64(hmac.new(SECRET.encode(), signing_input.encode(), digest).digest())
    assert sig == expected, f"{alg} header does not match the signing digest"


@pytest.mark.parametrize("alg,digest_bytes", [("HS256", 32), ("HS384", 48), ("HS512", 64)])
def test_signature_length_is_the_digest_size_of_the_declared_alg(alg, digest_bytes):
    """NEGATIVE: proves the digest really varies with alg, independent of the
    signing input.

    Comparing an HS256 token's signature to an HS512 token's is NOT a valid probe
    here - the header is part of the signing input, so the two differ even when
    both are secretly signed with sha256. The digest LENGTH cannot lie: sha256 is
    32 bytes, sha384 48, sha512 64. Under the old hardcoded sha256 every token
    carried 32 bytes regardless of the alg it advertised.
    """
    token = Auth(secret=SECRET, algorithm=alg).get_token({"user_id": 7})
    sig = token.split(".")[2]
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    assert len(raw) == digest_bytes


def test_token_is_rejected_when_header_alg_is_not_the_configured_one():
    """NEGATIVE: alg pinning. A token whose header asks for a different algorithm
    is refused even before the signature is checked - including alg "none"."""
    auth = Auth(secret=SECRET, algorithm="HS256")
    token = auth.get_token({"user_id": 7})
    h, p, sig = token.split(".")

    for forged_alg in ("none", "HS512", "RS256"):
        forged_header = _b64(json.dumps({"alg": forged_alg, "typ": "JWT"}).encode())
        assert auth.valid_token(f"{forged_header}.{p}.{sig}") is None

    assert auth.valid_token(token) is not None  # untampered still valid


# ── python#106: TINA4_JWT_ALGORITHM must actually be read ──

def test_env_algorithm_is_honoured_when_no_explicit_algorithm_given(monkeypatch):
    """POSITIVE: setting the env var changes the algorithm used to sign.

    It was registered in the CLI's known_vars and then never read, so a user
    could set HS512, see it listed as a known variable, and still get HS256.
    """
    monkeypatch.setenv("TINA4_JWT_ALGORITHM", "HS512")
    assert Auth(secret=SECRET).algorithm == "HS512"
    header, _, _ = _parts(Auth(secret=SECRET).get_token({"user_id": 1}))
    assert header["alg"] == "HS512"


def test_explicit_algorithm_argument_beats_the_env_var(monkeypatch):
    """NEGATIVE for precedence: an explicit arg must win over the environment."""
    monkeypatch.setenv("TINA4_JWT_ALGORITHM", "HS512")
    assert Auth(secret=SECRET, algorithm="HS256").algorithm == "HS256"


def test_default_is_hs256_when_env_var_is_unset(monkeypatch):
    monkeypatch.delenv("TINA4_JWT_ALGORITHM", raising=False)
    assert Auth(secret=SECRET).algorithm == "HS256"


def test_unsupported_algorithm_fails_loudly_naming_the_supported_set():
    """NEGATIVE: an algorithm we cannot sign raises instead of quietly
    downgrading to HS256 - a silent downgrade is the whole bug in #106."""
    with pytest.raises(ValueError) as excinfo:
        Auth(secret=SECRET, algorithm="RS256")
    message = str(excinfo.value)
    assert "RS256" in message
    for supported in ("HS256", "HS384", "HS512"):
        assert supported in message
    assert "TINA4_JWT_ALGORITHM" in message


def test_unsupported_env_algorithm_also_raises(monkeypatch):
    monkeypatch.setenv("TINA4_JWT_ALGORITHM", "banana")
    with pytest.raises(ValueError):
        Auth(secret=SECRET)


# ── python#107: nbf (not-before) must be validated ──

def test_post_dated_token_is_rejected_until_its_nbf_passes():
    """NEGATIVE: a token the issuer marked not-yet-valid must not authenticate.

    Only Ruby honoured nbf, so Python accepted tokens explicitly stamped as
    unusable - a deliberately post-dated credential worked immediately.
    """
    auth = Auth(secret=SECRET)
    future = int(time.time()) + _JWT_LEEWAY_SECONDS + 600
    assert auth.valid_token(auth.get_token({"user_id": 1, "nbf": future})) is None


def test_token_whose_nbf_has_passed_is_accepted():
    """POSITIVE: nbf in the past does not block a valid token."""
    auth = Auth(secret=SECRET)
    past = int(time.time()) - 600
    payload = auth.valid_token(auth.get_token({"user_id": 1, "nbf": past}))
    assert payload is not None and payload["user_id"] == 1


def test_nbf_within_the_leeway_still_validates():
    """POSITIVE: clock skew tolerance. An nbf a few seconds ahead - the normal
    case for a token minted on another host - must not be rejected."""
    auth = Auth(secret=SECRET)
    slightly_ahead = int(time.time()) + max(1, _JWT_LEEWAY_SECONDS // 2)
    assert auth.valid_token(auth.get_token({"user_id": 1, "nbf": slightly_ahead})) is not None


def test_token_without_nbf_is_unaffected():
    """POSITIVE: absent nbf means no not-before constraint, so existing tokens
    keep working - this is what keeps the change non-breaking for them."""
    auth = Auth(secret=SECRET)
    token = auth.get_token({"user_id": 1})
    assert "nbf" not in _parts(token)[1]
    assert auth.valid_token(token) is not None


def test_expiry_is_still_enforced_alongside_nbf():
    """NEGATIVE: adding nbf must not have displaced the exp check.

    expires_in=0 means "do not stamp an exp", which lets the payload's own exp
    survive - that is how we get a token that is already expired.
    """
    auth = Auth(secret=SECRET)
    token = auth.get_token({"user_id": 1, "exp": int(time.time()) - 600}, expires_in=0)
    assert auth.valid_token(token) is None


def test_non_positive_expires_in_stamps_no_exp_claim():
    """Documents a real footgun: expires_in <= 0 does NOT mean "expire now", it
    means "no exp claim", i.e. a token that never expires on its own."""
    auth = Auth(secret=SECRET)
    for expiry in (0, -1):
        claims = _parts(auth.get_token({"user_id": 1}, expires_in=expiry))[1]
        assert "exp" not in claims
        assert auth.valid_token(auth.get_token({"user_id": 1}, expires_in=expiry)) is not None


# ── authenticate_request overrides were accepted and dropped ──

def test_authenticate_request_honours_the_secret_override():
    """NEGATIVE: passing secret= used to be ignored, so a token signed with a
    different secret was validated against the instance's secret instead."""
    issued = Auth(secret="the-other-secret").get_token({"user_id": 42})
    headers = {"authorization": f"Bearer {issued}"}

    wrong = Auth(secret=SECRET)
    assert wrong.authenticate_request(headers) is None
    ok = wrong.authenticate_request(headers, secret="the-other-secret")
    assert ok is not None and ok["user_id"] == 42


def test_authenticate_request_honours_the_algorithm_override():
    issued = Auth(secret=SECRET, algorithm="HS512").get_token({"user_id": 42})
    headers = {"authorization": f"Bearer {issued}"}

    hs256 = Auth(secret=SECRET, algorithm="HS256")
    assert hs256.authenticate_request(headers) is None
    ok = hs256.authenticate_request(headers, algorithm="HS512")
    assert ok is not None and ok["user_id"] == 42


def test_authenticate_request_default_path_does_not_recurse():
    """A default call must not re-enter itself. The override branch keys off
    `is not None`, so a non-None default here would recurse until the stack blew."""
    os.environ["TINA4_SECRET"] = SECRET
    auth = Auth(secret=SECRET)
    headers = {"authorization": f"Bearer {auth.get_token({'user_id': 5})}"}
    assert auth.authenticate_request(headers)["user_id"] == 5


# ── round-trip across every supported algorithm ──

@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_sign_then_validate_round_trip(alg):
    auth = Auth(secret=SECRET, algorithm=alg)
    payload = auth.valid_token(auth.get_token({"user_id": 3, "role": "admin"}))
    assert payload is not None
    assert payload["user_id"] == 3 and payload["role"] == "admin"


@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512"])
def test_a_different_secret_never_validates(alg):
    token = Auth(secret=SECRET, algorithm=alg).get_token({"user_id": 3})
    assert Auth(secret="not-the-secret", algorithm=alg).valid_token(token) is None
