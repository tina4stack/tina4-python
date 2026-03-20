# Tina4 Auth — Zero-dependency JWT, password hashing, and token validation.
"""
JWT implementation using Python stdlib only (hmac + hashlib).
No PyJWT, no cryptography package.

    from tina4_python.auth import Auth

    auth = Auth(secret="my-secret")
    token = auth.create_token({"user_id": 1, "role": "admin"})
    payload = auth.validate_token(token)

    hashed = Auth.hash_password("secret123")
    Auth.check_password(hashed, "secret123")  # True
"""
import os
import hmac
import json
import time
import base64
import hashlib
import secrets


class Auth:
    """JWT authentication and password hashing — zero dependencies."""

    def __init__(self, secret: str = None, algorithm: str = "HS256",
                 token_expiry: int = None):
        self.secret = secret or os.environ.get("SECRET", "tina4-default-secret")
        self.algorithm = algorithm
        self.token_expiry = token_expiry or int(
            os.environ.get("TINA4_TOKEN_LIMIT", "30")
        )

    # ── JWT ────────────────────────────────────────────────────────

    def create_token(self, payload: dict, expiry_minutes: int = None) -> str:
        """Create a signed JWT token.

        Returns: header.payload.signature
        """
        exp = expiry_minutes if expiry_minutes is not None else self.token_expiry
        header = {"alg": self.algorithm, "typ": "JWT"}

        claims = dict(payload)
        claims["iat"] = int(time.time())
        if exp > 0:
            claims["exp"] = claims["iat"] + (exp * 60)

        h = _b64url_encode(json.dumps(header).encode())
        p = _b64url_encode(json.dumps(claims, default=str).encode())
        signature = self._sign(f"{h}.{p}")

        return f"{h}.{p}.{signature}"

    def validate_token(self, token: str) -> dict | None:
        """Validate a JWT and return the payload. None if invalid/expired."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            h, p, sig = parts
            expected = self._sign(f"{h}.{p}")
            if not hmac.compare_digest(sig, expected):
                return None

            payload = json.loads(_b64url_decode(p))

            if "exp" in payload and time.time() > payload["exp"]:
                return None

            return payload
        except Exception:
            return None

    def get_payload(self, token: str) -> dict | None:
        """Decode payload WITHOUT validating signature or expiry."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            return json.loads(_b64url_decode(parts[1]))
        except Exception:
            return None

    def refresh_token(self, token: str, expiry_minutes: int = None) -> str | None:
        """Validate and issue a fresh token with the same claims."""
        payload = self.validate_token(token)
        if payload is None:
            return None
        payload.pop("iat", None)
        payload.pop("exp", None)
        return self.create_token(payload, expiry_minutes)

    def _sign(self, message: str) -> str:
        sig = hmac.new(
            self.secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return _b64url_encode(sig)

    # ── Password Hashing ──────────────────────────────────────────

    @staticmethod
    def hash_password(password: str, iterations: int = 260000) -> str:
        """Hash using PBKDF2-HMAC-SHA256. Returns: algorithm$iterations$salt$hash"""
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), iterations
        )
        return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"

    @staticmethod
    def check_password(hashed: str, password: str) -> bool:
        """Verify a password against its PBKDF2 hash."""
        try:
            parts = hashed.split("$")
            if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
                return False
            iterations = int(parts[1])
            salt = parts[2]
            expected = parts[3]
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), iterations
            )
            return hmac.compare_digest(dk.hex(), expected)
        except Exception:
            return False

    # ── API Key Auth ──────────────────────────────────────────────

    @staticmethod
    def validate_api_key(provided: str) -> bool:
        """Check a Bearer token against the API_KEY env var."""
        expected = os.environ.get("API_KEY", "")
        if not expected:
            return False
        return hmac.compare_digest(provided, expected)

    # ── Request Auth Helper ───────────────────────────────────────

    def authenticate_request(self, headers: dict) -> dict | None:
        """Extract and validate auth from request headers.

        Checks: Bearer JWT, Bearer API key, Basic auth.
        Returns payload dict on success, None on failure.
        """
        auth_header = headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = self.validate_token(token)
            if payload:
                return payload
            if self.validate_api_key(token):
                return {"auth_type": "api_key"}
            return None

        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                username, password = decoded.split(":", 1)
                return {"auth_type": "basic", "username": username, "password": password}
            except Exception:
                return None

        return None


# ── Base64url helpers (RFC 7515) ───────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


__all__ = ["Auth"]
