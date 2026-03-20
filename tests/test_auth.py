# Tests for tina4_python.auth
import os
import time
import base64
import pytest
from tina4_python.auth import Auth


@pytest.fixture
def auth():
    return Auth(secret="test-secret-key", token_expiry=30)


# ── JWT Tests ──────────────────────────────────────────────────


class TestJWT:
    def test_create_token(self, auth):
        token = auth.create_token({"user_id": 1})
        assert isinstance(token, str)
        parts = token.split(".")
        assert len(parts) == 3

    def test_validate_token(self, auth):
        token = auth.create_token({"user_id": 1, "role": "admin"})
        payload = auth.validate_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["role"] == "admin"

    def test_token_has_iat(self, auth):
        token = auth.create_token({"user_id": 1})
        payload = auth.validate_token(token)
        assert "iat" in payload

    def test_token_has_exp(self, auth):
        token = auth.create_token({"user_id": 1})
        payload = auth.validate_token(token)
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_token_no_expiry(self, auth):
        token = auth.create_token({"user_id": 1}, expiry_minutes=0)
        payload = auth.validate_token(token)
        assert "exp" not in payload

    def test_token_custom_expiry(self, auth):
        token = auth.create_token({"user_id": 1}, expiry_minutes=5)
        payload = auth.validate_token(token)
        assert payload["exp"] - payload["iat"] == 300

    def test_get_payload_without_validation(self, auth):
        token = auth.create_token({"user_id": 99})
        payload = auth.get_payload(token)
        assert payload["user_id"] == 99

    def test_refresh_token(self, auth):
        original = auth.create_token({"user_id": 1, "role": "admin"}, expiry_minutes=1)
        time.sleep(1.1)  # Ensure different iat
        refreshed = auth.refresh_token(original)
        assert refreshed is not None
        assert refreshed != original
        payload = auth.validate_token(refreshed)
        assert payload["user_id"] == 1
        assert payload["role"] == "admin"


class TestJWTNegative:
    def test_invalid_token(self, auth):
        assert auth.validate_token("not.a.token") is None

    def test_tampered_token(self, auth):
        token = auth.create_token({"user_id": 1})
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        assert auth.validate_token(".".join(parts)) is None

    def test_wrong_secret(self, auth):
        token = auth.create_token({"user_id": 1})
        other = Auth(secret="wrong-secret")
        assert other.validate_token(token) is None

    def test_expired_token(self):
        auth = Auth(secret="test", token_expiry=0)
        token = auth.create_token({"user_id": 1}, expiry_minutes=0)
        # Manually create an expired token
        import json
        from tina4_python.auth import _b64url_encode
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({"user_id": 1, "exp": int(time.time()) - 10}).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired = f"{header}.{payload}.{sig}"
        assert auth.validate_token(expired) is None

    def test_empty_token(self, auth):
        assert auth.validate_token("") is None

    def test_refresh_invalid_token(self, auth):
        assert auth.refresh_token("bad.token.here") is None

    def test_get_payload_bad_token(self, auth):
        assert auth.get_payload("garbage") is None


# ── Password Hashing Tests ────────────────────────────────────


class TestPasswordHashing:
    def test_hash_password(self):
        hashed = Auth.hash_password("secret123")
        assert hashed.startswith("pbkdf2_sha256$")
        assert len(hashed.split("$")) == 4

    def test_check_password_correct(self):
        hashed = Auth.hash_password("mypassword")
        assert Auth.check_password(hashed, "mypassword") is True

    def test_check_password_wrong(self):
        hashed = Auth.hash_password("mypassword")
        assert Auth.check_password(hashed, "wrongpassword") is False

    def test_different_hashes_same_password(self):
        h1 = Auth.hash_password("same")
        h2 = Auth.hash_password("same")
        assert h1 != h2  # Different salts

    def test_check_invalid_hash(self):
        assert Auth.check_password("not_a_hash", "password") is False


# ── API Key Tests ──────────────────────────────────────────────


class TestAPIKey:
    def test_validate_api_key(self):
        os.environ["API_KEY"] = "test-api-key-123"
        try:
            assert Auth.validate_api_key("test-api-key-123") is True
            assert Auth.validate_api_key("wrong-key") is False
        finally:
            del os.environ["API_KEY"]

    def test_no_api_key_configured(self):
        assert Auth.validate_api_key("anything") is False


# ── Request Auth Tests ─────────────────────────────────────────


class TestRequestAuth:
    def test_bearer_jwt(self, auth):
        token = auth.create_token({"user_id": 1})
        result = auth.authenticate_request({"authorization": f"Bearer {token}"})
        assert result is not None
        assert result["user_id"] == 1

    def test_bearer_api_key(self, auth):
        os.environ["API_KEY"] = "my-api-key"
        try:
            result = auth.authenticate_request({"authorization": "Bearer my-api-key"})
            assert result is not None
            assert result["auth_type"] == "api_key"
        finally:
            del os.environ["API_KEY"]

    def test_basic_auth(self, auth):
        creds = base64.b64encode(b"admin:pass123").decode()
        result = auth.authenticate_request({"authorization": f"Basic {creds}"})
        assert result is not None
        assert result["username"] == "admin"
        assert result["password"] == "pass123"

    def test_no_auth_header(self, auth):
        assert auth.authenticate_request({}) is None

    def test_invalid_bearer(self, auth):
        assert auth.authenticate_request({"authorization": "Bearer invalid"}) is None


# ── Env Config Tests ───────────────────────────────────────────


class TestAuthConfig:
    def test_secret_from_env(self):
        os.environ["SECRET"] = "env-secret"
        try:
            auth = Auth()
            assert auth.secret == "env-secret"
        finally:
            del os.environ["SECRET"]

    def test_token_limit_from_env(self):
        os.environ["TINA4_TOKEN_LIMIT"] = "60"
        try:
            auth = Auth()
            assert auth.token_expiry == 60
        finally:
            del os.environ["TINA4_TOKEN_LIMIT"]
