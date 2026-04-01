# Tina4 Auth — Zero-dependency JWT, password hashing, and token validation.
"""
JWT implementation using Python stdlib only (hmac + hashlib).
No PyJWT, no cryptography package.

    from tina4_python.auth import Auth

    auth = Auth(secret="my-secret")
    token = auth.get_token({"user_id": 1, "role": "admin"})
    payload = auth.valid_token(token)

    # Legacy aliases also work:
    token = auth.get_token({"user_id": 1, "role": "admin"})
    payload = auth.valid_token(token)

    hashed = Auth.hash_password("secret123")
    Auth.check_password("secret123", hashed)  # True
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
                 expires_in: int = None):
        """
        Args:
            secret:     Signing secret (falls back to SECRET env var).
            algorithm:  JWT algorithm (default HS256).
            expires_in: Token lifetime in seconds (default 3600).
        """
        self.secret = secret or os.environ.get("SECRET", "tina4-default-secret")
        self.algorithm = algorithm
        self.expires_in = expires_in or int(
            os.environ.get("TINA4_TOKEN_LIMIT", "60")
        )

    # ── JWT ────────────────────────────────────────────────────────

    def get_token(self, payload: dict, expires_in: int = None) -> str:
        """Create a signed JWT token.

        Args:
            expires_in: Lifetime in minutes (default: self.expires_in).

        Returns: header.payload.signature
        """
        exp_minutes = expires_in if expires_in is not None else self.expires_in
        exp_seconds = exp_minutes * 60

        header = {"alg": self.algorithm, "typ": "JWT"}

        claims = dict(payload)
        claims["iat"] = int(time.time())
        if exp_seconds > 0:
            claims["exp"] = claims["iat"] + exp_seconds

        h = _b64url_encode(json.dumps(header).encode())
        p = _b64url_encode(json.dumps(claims, default=str).encode())
        signature = self._sign(f"{h}.{p}")

        return f"{h}.{p}.{signature}"

    def valid_token(self, token: str) -> dict | None:
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

    def refresh_token(self, token: str, expires_in: int = None) -> str | None:
        """Validate and issue a fresh token with the same claims.

        Args:
            expires_in: Lifetime in minutes (default: self.expires_in).
        """
        payload = self.valid_token(token)
        if payload is None:
            return None
        payload.pop("iat", None)
        payload.pop("exp", None)
        return self.get_token(payload, expires_in=expires_in)

    def _sign(self, message: str) -> str:
        sig = hmac.new(
            self.secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return _b64url_encode(sig)

    # ── Legacy aliases ─────────────────────────────────────────────

    # get_token and valid_token are the primary names

    # ── Class-level convenience methods (read SECRET from env) ────

    @classmethod
    def get_token_static(cls, payload: dict, expires_in: int = 60) -> str:
        """Create a JWT without instantiating Auth — reads SECRET from env."""
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = cls(secret=secret, expires_in=expires_in)
        return auth.get_token(payload)

    @classmethod
    def valid_token_static(cls, token: str) -> dict | None:
        """Validate a JWT without instantiating Auth — reads SECRET from env."""
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = cls(secret=secret)
        return auth.valid_token(token)

    @classmethod
    def get_payload_static(cls, token: str) -> dict | None:
        """Decode payload (no validation) without instantiating Auth."""
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = cls(secret=secret)
        return auth.get_payload(token)

    @classmethod
    def refresh_token_static(cls, token: str, expires_in: int = 60) -> str | None:
        """Refresh a JWT without instantiating Auth — reads SECRET from env."""
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = cls(secret=secret, expires_in=expires_in)
        return auth.refresh_token(token)

    @classmethod
    def authenticate_request_static(cls, headers: dict) -> dict | None:
        """Extract and validate auth from request headers without instantiating Auth.

        Reads SECRET from env. Checks: Bearer JWT, Bearer API key, Basic auth.
        Returns payload dict on success, None on failure.
        """
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = cls(secret=secret)
        return auth.authenticate_request(headers)

    @staticmethod
    def validate_api_key_static(provided: str, expected: str = None) -> bool:
        """Validate an API key without instantiating Auth.

        Alias for validate_api_key (already a staticmethod).
        """
        return Auth.validate_api_key(provided, expected)

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
    def check_password(password: str, hashed: str) -> bool:
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
    def validate_api_key(provided: str, expected: str = None) -> bool:
        """Check an API key against an expected value.

        Args:
            provided: The API key provided in the request.
            expected: The expected API key. If None, reads from
                      TINA4_API_KEY env var (falls back to API_KEY).

        Returns: True if the provided key matches.
        """
        if expected is None:
            expected = os.environ.get("TINA4_API_KEY", os.environ.get("API_KEY", ""))
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
            payload = self.valid_token(token)
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


# ── Module-level convenience functions (use static methods) ────

def get_token(payload: dict, expires_in: int = 60) -> str:
    """Create a JWT — reads SECRET from env. Shortcut for Auth.get_token_static()."""
    return Auth.get_token_static(payload, expires_in=expires_in)


def valid_token(token: str) -> dict | None:
    """Validate a JWT — reads SECRET from env. Shortcut for Auth.valid_token_static()."""
    return Auth.valid_token_static(token)


def get_payload(token: str) -> dict | None:
    """Decode JWT payload (no validation). Shortcut for Auth.get_payload_static()."""
    return Auth.get_payload_static(token)


def refresh_token(token: str, expires_in: int = 60) -> str | None:
    """Refresh a JWT — reads SECRET from env. Shortcut for Auth.refresh_token_static()."""
    return Auth.refresh_token_static(token, expires_in=expires_in)


def authenticate_request(headers: dict) -> dict | None:
    """Validate auth from request headers — reads SECRET from env."""
    return Auth.authenticate_request_static(headers)


def validate_api_key(provided: str, expected: str = None) -> bool:
    """Validate an API key. Shortcut for Auth.validate_api_key()."""
    return Auth.validate_api_key(provided, expected)


class AuthMiddleware:
    """Built-in auth middleware. Validates JWT Bearer tokens on protected routes."""

    @staticmethod
    def before_request(request, response):
        """Check Authorization header for valid JWT token."""
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return request, response({"error": "Unauthorized"}, 401)
        token = auth_header[7:]
        payload = Auth.valid_token_static(token)
        if payload is None:
            return request, response({"error": "Invalid token"}, 401)
        request.auth = payload
        return request, response


__all__ = [
    "Auth", "AuthMiddleware", "get_token", "valid_token", "get_payload",
    "refresh_token", "authenticate_request", "validate_api_key",
]
