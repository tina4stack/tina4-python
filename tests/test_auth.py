#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import os
import pytest
import datetime

import tina4_python
from tina4_python.Auth import Auth


@pytest.fixture(scope="module")
def auth():
    return Auth(tina4_python.root_path)


# --- Password hashing ---

def test_hash_password(auth):
    hashed = auth.hash_password("secret123")
    assert isinstance(hashed, str)
    assert hashed != "secret123"
    assert hashed.startswith("$2")  # bcrypt prefix


def test_check_password_correct(auth):
    hashed = auth.hash_password("mypassword")
    assert auth.check_password(hashed, "mypassword") is True


def test_check_password_wrong(auth):
    hashed = auth.hash_password("mypassword")
    assert auth.check_password(hashed, "wrongpassword") is False


def test_hash_password_different_salts(auth):
    h1 = auth.hash_password("same")
    h2 = auth.hash_password("same")
    assert h1 != h2  # different salts
    assert auth.check_password(h1, "same") is True
    assert auth.check_password(h2, "same") is True


# --- HS256 secret ---

def test_secret_set(auth):
    assert auth.secret is not None
    assert isinstance(auth.secret, str)


# --- JWT creation ---

def test_get_token(auth):
    token = auth.get_token({"user": "test"})
    assert isinstance(token, str)
    parts = token.split(".")
    assert len(parts) == 3  # header.payload.signature


def test_get_token_with_datetime_payload(auth):
    token = auth.get_token({"user": "test", "created": datetime.datetime.now()})
    assert isinstance(token, str)


def test_get_token_auto_expiry(auth):
    token = auth.get_token({"user": "test"})
    payload = auth.get_payload(token)
    assert "expires" in payload


def test_get_token_custom_expiry(auth):
    token = auth.get_token({"user": "test"}, expiry_minutes=60)
    payload = auth.get_payload(token)
    assert "expires" in payload
    expiry = datetime.datetime.fromisoformat(payload["expires"])
    now = datetime.datetime.now(datetime.timezone.utc)
    # Should be roughly 60 minutes from now (allow 5 min tolerance)
    diff = (expiry - now).total_seconds()
    assert 55 * 60 < diff < 65 * 60


def test_get_token_preserves_existing_expiry(auth):
    custom_expiry = "2099-12-31T23:59:59+00:00"
    token = auth.get_token({"user": "test", "expires": custom_expiry})
    payload = auth.get_payload(token)
    assert payload["expires"] == custom_expiry


# --- JWT decoding ---

def test_get_payload(auth):
    token = auth.get_token({"name": "alice", "role": "admin"})
    payload = auth.get_payload(token)
    assert payload["name"] == "alice"
    assert payload["role"] == "admin"


def test_get_payload_invalid_token(auth):
    result = auth.get_payload("not.a.valid.token")
    assert result is None


# --- JWT validation ---

def test_validate_valid_token(auth):
    token = auth.get_token({"user": "test"}, expiry_minutes=10)
    assert auth.validate(token) is True


def test_validate_expired_token(auth):
    # Create a token that expired 1 minute ago
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    token = auth.get_token({"user": "test", "expires": past.isoformat()})
    assert auth.validate(token) is False


def test_validate_no_expiry_claim(auth):
    # Manually create a token without expires (bypass get_token auto-add)
    import jwt as pyjwt
    from tina4_python.Auth import AuthJSONSerializer
    token = pyjwt.encode({"user": "test"}, key=auth.secret, algorithm="HS256",
                         json_encoder=AuthJSONSerializer)
    assert auth.validate(token) is False


def test_validate_garbage_token(auth):
    assert auth.validate("garbage") is False


def test_validate_empty_string(auth):
    assert auth.validate("") is False


def test_valid_alias(auth):
    token = auth.get_token({"user": "test"})
    assert auth.valid(token) == auth.validate(token)


# --- API key fallback ---

def test_validate_api_key(auth):
    os.environ["API_KEY"] = "my-secret-key"
    try:
        assert auth.validate("my-secret-key") is True
        assert auth.validate("wrong-key") is False
    finally:
        del os.environ["API_KEY"]
