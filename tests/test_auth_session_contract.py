"""Regression tests for the feature 41/42 auth + session contract (ADR-0021).

Each test is named for the behaviour it pins and carries a positive AND a
negative case, so reverting a fix reproduces the original bug rather than
silently passing. The case names are IDENTICAL in all four frameworks
(tina4-php/tests/AuthSessionContractTest.php,
tina4-ruby/spec/auth_session_contract_spec.rb,
tina4-nodejs/test/authSessionContract.test.ts).

No doubles anywhere: real Auth against real HMAC digests, real Session against
a real filesystem in a real temp directory.
"""
import base64
import json
import os
import time
from pathlib import Path

import pytest

from tina4_python.auth import Auth
from tina4_python.session import (
    FileSessionHandler,
    Session,
    is_valid_session_id,
)

SECRET = "auth-session-contract-secret"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge(auth: Auth, claims: dict) -> str:
    """Mint a token with arbitrary claims, correctly signed by `auth`.

    The signature is real, so every test below isolates the CLAIM check under
    test rather than accidentally passing because the signature failed.
    """
    header = _b64(json.dumps({"alg": auth.algorithm, "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    return f"{header}.{payload}.{auth._sign(f'{header}.{payload}')}"


# ── 42: a session id is opaque and can never be a filesystem path ──


def test_session_id_from_cookie_cannot_escape_the_session_directory(tmp_path):
    """A traversal id must not read or write outside TINA4_SESSION_PATH.

    Negative half: the escape target must NOT exist afterwards. Positive half:
    a normal session in the same directory still round-trips.
    """
    sessions = tmp_path / "data" / "sessions"
    sessions.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    session = Session(handler=FileSessionHandler(str(sessions)))
    adopted = session.start("../../outside/pwned")
    session.set("owned", "yes")
    session.save()

    assert not (outside / "pwned.json").exists(), (
        "session cookie escaped the session directory - arbitrary file write"
    )
    assert adopted != "../../outside/pwned", (
        "a traversal session id was adopted verbatim"
    )

    # Positive half: a legitimate id in the same handler still works.
    good = Session(handler=FileSessionHandler(str(sessions)))
    good_id = good.start()
    good.set("k", "v")
    good.save()
    resumed = Session(handler=FileSessionHandler(str(sessions)))
    resumed.start(good_id)
    assert resumed.get("k") == "v"


def test_session_id_with_path_separator_is_rejected_and_a_fresh_id_minted(tmp_path):
    """Any id outside the opaque alphabet is replaced, never adopted."""
    handler = FileSessionHandler(str(tmp_path))
    for hostile in ("../../etc/passwd", "a/b", "a\\b", "a.b", "..", "", "a b", "a;b"):
        session = Session(handler=handler)
        adopted = session.start(hostile)
        assert adopted != hostile, f"hostile session id adopted verbatim: {hostile!r}"
        assert is_valid_session_id(adopted), (
            f"replacement id is itself invalid for input {hostile!r}"
        )

    # Positive half: an app is entitled to manage its own id. A short but
    # alphabet-clean id is a TRUSTED programmatic choice, not an attack, and
    # must still round-trip -- the vulnerability was the alphabet, not length.
    session = Session(handler=handler)
    assert session.start("my-session-id") == "my-session-id"


def test_valid_generated_session_id_is_accepted_unchanged(tmp_path):
    """The fix must not break the ids the framework itself mints.

    Negative half is the previous test; this is the positive half and also the
    non-breaking guarantee: every framework's own id shape stays acceptable.
    """
    handler = FileSessionHandler(str(tmp_path))
    session = Session(handler=handler)
    minted = session.start()
    assert is_valid_session_id(minted)

    resumed = Session(handler=handler)
    assert resumed.start(minted) == minted, "a self-minted id was not resumed as-is"

    # The id shapes the other three frameworks mint must also be accepted, so a
    # shared Redis/Mongo session store stays readable across the family.
    for foreign in ("0123456789abcdef0123456789abcdef",           # PHP/Node hex(16)
                    "0" * 64,                                      # Ruby hex(32)
                    "Ab-_9" * 8):                                  # Python token_urlsafe
        assert is_valid_session_id(foreign), f"rejected a sibling id shape: {foreign!r}"


# ── 41: RFC 7519 s4.1.4 - the token MUST NOT be accepted at or after exp ──


def test_jwt_expired_exactly_at_exp_is_rejected():
    """RFC 7519 s4.1.4: "the current date/time MUST be before the expiration".

    At now == exp the token is expired. Ruby already used >=; Python, PHP and
    Node used > and accepted a token for one extra second.
    """
    auth = Auth(secret=SECRET)
    now = int(time.time())
    assert auth.valid_token(_forge(auth, {"user_id": 1, "exp": now})) is None, (
        "token accepted at exactly exp - RFC 7519 s4.1.4 requires now < exp"
    )


def test_jwt_one_second_before_exp_is_accepted():
    """Positive half of the boundary: strictly before exp is still valid."""
    auth = Auth(secret=SECRET)
    now = int(time.time())
    payload = auth.valid_token(_forge(auth, {"user_id": 1, "exp": now + 2}))
    assert payload is not None, "a token two seconds from expiry was rejected"
    assert payload["user_id"] == 1


def test_jwt_non_numeric_exp_is_rejected_not_treated_as_no_expiry():
    """A malformed exp must never read as "this token never expires".

    RFC 7519 s2 defines exp as a NumericDate. PHP and Node skipped the check
    when exp was not a number, turning a malformed claim into an eternal token.
    """
    auth = Auth(secret=SECRET)
    for bad_exp in ("not-a-number", None, [], {}, True):
        assert auth.valid_token(_forge(auth, {"user_id": 1, "exp": bad_exp})) is None, (
            f"token with exp={bad_exp!r} was accepted as non-expiring"
        )


def test_jwt_non_numeric_nbf_is_rejected_not_treated_as_unconstrained():
    """Same rule for nbf: malformed is rejected, absent is unconstrained."""
    auth = Auth(secret=SECRET)
    now = int(time.time())
    for bad_nbf in ("not-a-number", None, [], {}, True):
        claims = {"user_id": 1, "exp": now + 600, "nbf": bad_nbf}
        assert auth.valid_token(_forge(auth, claims)) is None, (
            f"token with nbf={bad_nbf!r} was accepted as unconstrained"
        )

    # Positive half: NO nbf at all stays unconstrained (non-breaking).
    assert auth.valid_token(_forge(auth, {"user_id": 1, "exp": now + 600})) is not None


# ── 41: authenticate_request authenticates, or returns None ──


def test_basic_authorization_header_is_not_an_authenticated_request():
    """Basic credentials are not verified against anything, so they are not auth.

    Python returned a TRUTHY dict for any Basic header, so an app following the
    documented `if auth is None: return 401` idiom authenticated every caller.
    PHP, Ruby and Node all returned None here.
    """
    auth = Auth(secret=SECRET)
    creds = base64.b64encode(b"admin:whatever-i-like").decode()
    assert auth.authenticate_request({"authorization": f"Basic {creds}"}) is None, (
        "an unverified Basic header authenticated the request"
    )

    # Positive half: a real Bearer JWT still authenticates.
    token = auth.get_token({"user_id": 7})
    payload = auth.authenticate_request({"authorization": f"Bearer {token}"})
    assert payload is not None and payload["user_id"] == 7


def test_authenticate_request_api_key_payload_shape_is_uniform():
    """The API-key result carries the same key in all four frameworks."""
    auth = Auth(secret=SECRET)
    previous = os.environ.get("TINA4_API_KEY")
    os.environ["TINA4_API_KEY"] = "contract-api-key-value"
    try:
        payload = auth.authenticate_request(
            {"authorization": "Bearer contract-api-key-value"}
        )
        assert payload == {"_auth": "api_key"}, f"api_key payload shape drifted: {payload!r}"
        # Negative half: a wrong key is not authenticated.
        assert auth.authenticate_request({"authorization": "Bearer wrong-key"}) is None
    finally:
        if previous is None:
            os.environ.pop("TINA4_API_KEY", None)
        else:
            os.environ["TINA4_API_KEY"] = previous


def test_route_gate_api_key_comparison_is_timing_safe():
    """The write-route gate must compare the API key through validate_api_key.

    The gate used a plain `==` on the secret, which leaks the key prefix through
    comparison timing. Asserting on the CALL GRAPH is deliberate: a timing
    measurement is inherently flaky, whereas "the gate calls the timing-safe
    helper" is exact and is the property under test.

    The check walks the AST rather than grepping the source text — a text grep
    for "validate_api_key" is satisfied by a COMMENT mentioning it, so it stayed
    green when the call itself was reverted to `==` (caught by the break-it
    probe on this very test).
    """
    from tina4_python.core import server as server_module
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(server_module._check_auth)))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "validate_api_key" in called, (
        "_check_auth no longer CALLS validate_api_key - the API key is being "
        f"compared some other way (calls seen: {sorted(called)})"
    )
    # No bare == against the API key anywhere in the gate.
    compares = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.Eq) for op in node.ops)
        and "API_KEY" in ast.dump(node)
    ]
    assert not compares, (
        "_check_auth still compares the API key with a timing-unsafe =="
    )

    # Behavioural half, on the real helper the gate now calls.
    previous = os.environ.get("TINA4_API_KEY")
    os.environ["TINA4_API_KEY"] = "gate-key"
    try:
        assert Auth.validate_api_key("gate-key") is True
        assert Auth.validate_api_key("gate-keX") is False
        assert Auth.validate_api_key("") is False
    finally:
        if previous is None:
            os.environ.pop("TINA4_API_KEY", None)
        else:
            os.environ["TINA4_API_KEY"] = previous
