"""Auth never silently signs with a guessable built-in default.

When TINA4_SECRET is unset, _resolve_secret() returns a blank secret (and the
framework warns) — parity with PHP/Node. The old insecure "tina4-default-secret"
fallback is gone.
"""
from tina4_python.auth import _resolve_secret, Auth, get_token, valid_token


def test_resolve_secret_explicit():
    assert _resolve_secret("abc") == "abc"


def test_resolve_secret_from_env(monkeypatch):
    monkeypatch.setenv("TINA4_SECRET", "envsecret")
    assert _resolve_secret() == "envsecret"


def test_resolve_secret_blank_when_unset(monkeypatch):
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    # Blank — NOT a guessable built-in default.
    assert _resolve_secret() == ""


def test_no_insecure_default_secret(monkeypatch):
    monkeypatch.delenv("TINA4_SECRET", raising=False)
    assert Auth().secret == ""
    assert "tina4-default-secret" not in (Auth().secret or "")


def test_token_roundtrip_with_secret(monkeypatch):
    monkeypatch.setenv("TINA4_SECRET", "s3cr3t-shared")
    token = get_token({"user_id": 7})
    assert valid_token(token)["user_id"] == 7
    assert valid_token(token[:-4] + "AAAA") is None  # tampered rejected
