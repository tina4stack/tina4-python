# Tests for tina4_python.auth
import os
import time
import base64
import pytest
from tina4_python.auth import Auth


@pytest.fixture
def auth():
    return Auth(secret="test-secret-key", expires_in=30)


# ── JWT Tests ──────────────────────────────────────────────────


class TestJWT:
    def test_create_token(self, auth):
        token = auth.get_token({"user_id": 1})
        assert isinstance(token, str)
        parts = token.split(".")
        assert len(parts) == 3

    def test_validate_token(self, auth):
        token = auth.get_token({"user_id": 1, "role": "admin"})
        payload = auth.valid_token(token)
        assert payload is not None
        assert payload["user_id"] == 1
        assert payload["role"] == "admin"

    def test_token_has_iat(self, auth):
        token = auth.get_token({"user_id": 1})
        payload = auth.valid_token(token)
        assert "iat" in payload

    def test_token_has_exp(self, auth):
        token = auth.get_token({"user_id": 1})
        payload = auth.valid_token(token)
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_token_no_expiry(self, auth):
        token = auth.get_token({"user_id": 1}, expires_in=0)
        payload = auth.valid_token(token)
        assert "exp" not in payload

    def test_token_custom_expiry(self, auth):
        token = auth.get_token({"user_id": 1}, expires_in=5)
        payload = auth.valid_token(token)
        assert payload["exp"] - payload["iat"] == 300

    def test_get_payload_without_validation(self, auth):
        token = auth.get_token({"user_id": 99})
        payload = auth.get_payload(token)
        assert payload["user_id"] == 99

    def test_refresh_token(self, auth):
        original = auth.get_token({"user_id": 1, "role": "admin"}, expires_in=1)
        time.sleep(1.1)  # Ensure different iat
        refreshed = auth.refresh_token(original)
        assert refreshed is not None
        assert refreshed != original
        payload = auth.valid_token(refreshed)
        assert payload["user_id"] == 1
        assert payload["role"] == "admin"


class TestJWTNegative:
    def test_invalid_token(self, auth):
        assert auth.valid_token("not.a.token") is None

    def test_tampered_token(self, auth):
        token = auth.get_token({"user_id": 1})
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        assert auth.valid_token(".".join(parts)) is None

    def test_wrong_secret(self, auth):
        token = auth.get_token({"user_id": 1})
        other = Auth(secret="wrong-secret")
        assert other.valid_token(token) is None

    def test_expired_token(self):
        auth = Auth(secret="test", expires_in=0)
        token = auth.get_token({"user_id": 1}, expires_in=0)
        # Manually create an expired token
        import json
        from tina4_python.auth import _b64url_encode
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({"user_id": 1, "exp": int(time.time()) - 10}).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired = f"{header}.{payload}.{sig}"
        assert auth.valid_token(expired) is None

    def test_empty_token(self, auth):
        assert auth.valid_token("") is None

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
        assert Auth.check_password("mypassword", hashed) is True

    def test_check_password_wrong(self):
        hashed = Auth.hash_password("mypassword")
        assert Auth.check_password("wrongpassword", hashed) is False

    def test_different_hashes_same_password(self):
        h1 = Auth.hash_password("same")
        h2 = Auth.hash_password("same")
        assert h1 != h2  # Different salts

    def test_check_invalid_hash(self):
        assert Auth.check_password("password", "not_a_hash") is False


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
        token = auth.get_token({"user_id": 1})
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
        os.environ["TINA4_TOKEN_EXPIRES_IN"] = "60"
        try:
            auth = Auth()
            assert auth.expires_in == 60
        finally:
            del os.environ["TINA4_TOKEN_EXPIRES_IN"]

    def test_default_secret(self):
        # When no env var and no kwarg, uses default
        os.environ.pop("SECRET", None)
        auth = Auth()
        assert auth.secret == "tina4-default-secret"

    def test_default_expires_in(self):
        os.environ.pop("TINA4_TOKEN_EXPIRES_IN", None)
        auth = Auth()
        assert auth.expires_in == 60


# ── JWT Standard Claims ────────────────────────────────────────


class TestJWTClaims:
    def test_sub_claim_preserved(self, auth):
        token = auth.get_token({"sub": "user:1", "iss": "tina4"})
        payload = auth.valid_token(token)
        assert payload["sub"] == "user:1"
        assert payload["iss"] == "tina4"

    def test_custom_claims_preserved(self, auth):
        token = auth.get_token({"roles": ["admin", "editor"], "org": "acme"})
        payload = auth.valid_token(token)
        assert payload["roles"] == ["admin", "editor"]
        assert payload["org"] == "acme"

    def test_get_payload_ignores_expiration(self):
        auth = Auth(secret="test")
        import json
        from tina4_python.auth import _b64url_encode
        header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_encode(json.dumps({"user_id": 1, "exp": int(time.time()) - 100}).encode())
        sig = auth._sign(f"{header}.{payload}")
        expired_token = f"{header}.{payload}.{sig}"
        # valid_token should reject it
        assert auth.valid_token(expired_token) is None
        # get_payload should still return payload
        result = auth.get_payload(expired_token)
        assert result is not None
        assert result["user_id"] == 1

    def test_get_payload_ignores_bad_signature(self, auth):
        token = auth.get_token({"user_id": 42})
        # Tamper with signature
        parts = token.split(".")
        parts[2] = parts[2][::-1]  # Reverse signature
        tampered = ".".join(parts)
        result = auth.get_payload(tampered)
        assert result is not None
        assert result["user_id"] == 42


# ── JWT Edge Cases ──────────────────────────────────────────────


class TestJWTEdgeCases:
    def test_two_part_token(self, auth):
        assert auth.valid_token("header.payload") is None

    def test_four_part_token(self, auth):
        assert auth.valid_token("a.b.c.d") is None

    def test_none_payload_handling(self, auth):
        assert auth.get_payload("") is None

    def test_get_payload_two_parts(self, auth):
        assert auth.get_payload("a.b") is None


# ── Password Edge Cases ─────────────────────────────────────────


class TestPasswordEdgeCases:
    def test_empty_password(self):
        hashed = Auth.hash_password("")
        assert Auth.check_password("", hashed) is True
        assert Auth.check_password("x", hashed) is False

    def test_unicode_password(self):
        hashed = Auth.hash_password("p@$$w0rd-émoji-🔑")
        assert Auth.check_password("p@$$w0rd-émoji-🔑", hashed) is True
        assert Auth.check_password("p@$$w0rd-émoji", hashed) is False

    def test_long_password(self):
        long_pw = "a" * 10000
        hashed = Auth.hash_password(long_pw)
        assert Auth.check_password(long_pw, hashed) is True

    def test_check_password_empty_hash(self):
        assert Auth.check_password("password", "") is False

    def test_check_password_wrong_prefix(self):
        assert Auth.check_password("password", "bcrypt$100$salt$hash") is False


# ── Request Auth Edge Cases ───────────────────────────────────


class TestRequestAuthEdgeCases:
    def test_basic_auth_with_colon_in_password(self, auth):
        creds = base64.b64encode(b"user:pass:with:colons").decode()
        result = auth.authenticate_request({"authorization": f"Basic {creds}"})
        assert result is not None
        assert result["username"] == "user"
        assert result["password"] == "pass:with:colons"

    def test_malformed_basic_auth(self, auth):
        result = auth.authenticate_request({"authorization": "Basic !!invalid!!"})
        assert result is None

    def test_unknown_auth_scheme(self, auth):
        result = auth.authenticate_request({"authorization": "Digest abc123"})
        assert result is None

    def test_empty_authorization_header(self, auth):
        result = auth.authenticate_request({"authorization": ""})
        assert result is None

    def test_bearer_without_value(self, auth):
        result = auth.authenticate_request({"authorization": "Bearer "})
        assert result is None


# ── API Key Edge Cases ──────────────────────────────────────────


class TestAPIKeyEdgeCases:
    def test_api_key_empty_env(self):
        os.environ["API_KEY"] = ""
        try:
            assert Auth.validate_api_key("") is False
        finally:
            del os.environ["API_KEY"]

    def test_api_key_case_sensitive(self):
        os.environ["API_KEY"] = "MyKey123"
        try:
            assert Auth.validate_api_key("MyKey123") is True
            assert Auth.validate_api_key("mykey123") is False
        finally:
            del os.environ["API_KEY"]
