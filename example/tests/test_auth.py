"""Test authentication — demonstrates: Auth.hash_password, check_password, get_token, valid_token."""
import pytest
from tina4_python.auth import Auth, get_token, valid_token


class TestPasswordHashing:
    def test_hash_and_check(self):
        hashed = Auth.hash_password("my-secret")
        assert Auth.check_password("my-secret", hashed) is True
        assert Auth.check_password("wrong", hashed) is False

    def test_hash_is_unique(self):
        h1 = Auth.hash_password("same-password")
        h2 = Auth.hash_password("same-password")
        assert h1 != h2  # different salts

    def test_empty_password(self):
        hashed = Auth.hash_password("")
        assert Auth.check_password("", hashed) is True
        assert Auth.check_password("not-empty", hashed) is False


class TestJWT:
    def test_create_and_validate_token(self):
        token = get_token({"user_id": 42, "role": "admin"})
        payload = valid_token(token)
        assert payload is not None
        assert payload["user_id"] == 42
        assert payload["role"] == "admin"

    def test_invalid_token(self):
        result = valid_token("invalid.token.here")
        assert result is None

    def test_token_payload_extraction(self):
        from tina4_python.auth import get_payload
        token = get_token({"customer_id": 7})
        payload = get_payload(token)
        assert payload["customer_id"] == 7


class TestLoginFlow:
    def test_customer_login_correct_password(self, db, sample_customer):
        from src.orm.customer import Customer
        customers = Customer.where("email = ?", params=["alice@example.com"])
        assert len(customers) == 1
        assert Auth.check_password("secret123", customers[0].password_hash) is True

    def test_customer_login_wrong_password(self, db, sample_customer):
        from src.orm.customer import Customer
        customers = Customer.where("email = ?", params=["alice@example.com"])
        assert Auth.check_password("wrong", customers[0].password_hash) is False

    def test_customer_login_nonexistent_email(self, db):
        from src.orm.customer import Customer
        results = Customer.where("email = ?", params=["nobody@example.com"])
        assert len(results) == 0
