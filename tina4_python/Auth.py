#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""JWT authentication and password hashing for Tina4.

Provides the ``Auth`` class which handles:
    - HS256 JWT token creation and validation using the ``SECRET`` env var
    - Configurable token expiry (default 2 minutes, override via
      ``TINA4_TOKEN_LIMIT`` environment variable)
    - Password hashing and verification using bcrypt
    - Payload extraction from valid or expired tokens

The framework creates a global ``tina4_python.tina4_auth`` instance at
startup. Sessions, secured routes, and middleware all delegate to this
instance for token operations.

Example::

    from tina4_python import tina4_auth

    token = tina4_auth.get_token({"user_id": 42})
    is_valid = tina4_auth.valid(token)
    payload = tina4_auth.get_payload(token)
    hashed = tina4_auth.get_password("secret")
    ok = tina4_auth.check_password("secret", hashed)
"""

__all__ = ["Auth", "AuthJSONSerializer"]

import datetime
import os
import jwt
import bcrypt
from json import JSONEncoder


class AuthJSONSerializer(JSONEncoder):
    """
    Custom JSON encoder used by PyJWT when serializing payload objects.

    Ensures that ``datetime.datetime`` instances are correctly converted to ISO-8601
    strings so they can be embedded in JWT claims.
    """

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


class Auth:
    """
    Authentication & authorization helper for Tina4 projects.

    Handles:
      - Password hashing/verification (bcrypt)
      - Signing JWT tokens with HS256 (SECRET env var)
      - Verifying JWT tokens with HS256
      - Simple API-KEY fallback validation

    Environment variables used:
        - ``SECRET``            → HMAC-SHA256 signing secret for JWT
        - ``API_KEY``           → optional static API key (checked before JWT)
        - ``TINA4_TOKEN_LIMIT`` → default token lifetime in minutes (default: 2)
    """

    secret: str | None = None
    root_path: str = None

    # ------------------------------------------------------------------
    # Password handling (bcrypt)
    # ------------------------------------------------------------------
    def hash_password(self, text: str) -> str:
        """
        Generate a bcrypt hash for the given plain-text password.

        Args:
            text (str): Plain-text password.

        Returns:
            str: bcrypt hash (as UTF-8 string). Safe to store in a database.
        """
        password_bytes = text.encode("utf-8")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    def check_password(self, password_hash: str, text: str) -> bool:
        """
        Verify a plain-text password against a previously created bcrypt hash.

        Args:
            password_hash (str): Hash returned by :meth:`hash_password`.
            text (str): Plain-text password to verify.

        Returns:
            bool: ``True`` if the password matches the hash.
        """
        password_bytes = text.encode("utf-8")
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------
    def __init__(self, root_path: str):
        """
        Initialise the Auth helper.

        Detects and removes legacy RS256 key files from older Tina4 installs,
        printing a one-time migration notice when found.

        Args:
            root_path (str): Absolute path to the project root.
        """
        from tina4_python.Debug import Debug
        from tina4_python import Messages

        self.root_path = root_path
        self.secret = os.environ.get("SECRET", "{self.secret}")
        if self.secret == "{self.secret}":
            Debug.warning(Messages.MSG_AUTH_NO_SECRET)

        # ------------------------------------------------------------------
        # One-time RS256 → HS256 migration: remove old key files if present
        # ------------------------------------------------------------------
        secrets_dir = os.path.join(root_path, "secrets")
        legacy_files = [
            os.path.join(secrets_dir, "private.key"),
            os.path.join(secrets_dir, "public.key"),
            os.path.join(secrets_dir, "domain.cert"),
        ]
        if any(os.path.isfile(f) for f in legacy_files):
            for f in legacy_files:
                if os.path.isfile(f):
                    os.remove(f)
            Debug.warning(Messages.MSG_AUTH_RS256_MIGRATION)

    # ------------------------------------------------------------------
    # JWT creation & verification (HS256)
    # ------------------------------------------------------------------
    def get_token(self, payload_data: dict, expiry_minutes: int = 0) -> str:
        """
        Create a signed JWT (HS256) containing the supplied payload.

        If ``expires`` is not present in ``payload_data`` an expiration claim
        will be added automatically using ``TINA4_TOKEN_LIMIT`` (default 2 minutes)
        or the value supplied via ``expiry_minutes``.

        Args:
            payload_data (dict): Claims to embed in the token.
            expiry_minutes (int): Override default token lifetime (0 = use env default).

        Returns:
            str: Signed JWT (compact serialization).
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        if "expires" not in payload_data:
            token_limit_minutes = int(os.environ.get("TINA4_TOKEN_LIMIT", 2))
            if expiry_minutes != 0:
                token_limit_minutes = expiry_minutes
            expiry_time = now + datetime.timedelta(minutes=token_limit_minutes)
            payload_data["expires"] = expiry_time.isoformat()

        token = jwt.encode(
            payload=payload_data,
            key=self.secret,
            algorithm="HS256",
            json_encoder=AuthJSONSerializer,
        )
        return token

    def get_payload(self, token: str) -> dict | None:
        """
        Decode a JWT and return its payload (without verification of expiry).

        Args:
            token (str): JWT to decode.

        Returns:
            dict | None: Payload dictionary or ``None`` on invalid signature.
        """
        try:
            payload = jwt.decode(
                token,
                key=self.secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            return payload
        except Exception:
            return None

    def validate(self, token: str) -> bool:
        """
        Full token validation.

        Checks:
          1. Optional static ``API_KEY`` environment variable (quick bypass)
          2. HS256 signature using SECRET
          3. Presence and validity of the ``expires`` claim

        Args:
            token (str): Bearer token.

        Returns:
            bool: ``True`` if the token is valid and not expired.
        """
        if os.environ.get("API_KEY") and token == os.environ.get("API_KEY"):
            return True

        try:
            payload = jwt.decode(
                token,
                key=self.secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )

            if "expires" not in payload:
                return False

            expiry_time = datetime.datetime.fromisoformat(payload["expires"])
            if expiry_time.tzinfo is None:
                expiry_time = expiry_time.replace(tzinfo=datetime.timezone.utc)

            return datetime.datetime.now(datetime.timezone.utc) <= expiry_time

        except Exception:  # noqa: BLE001
            return False

    def valid(self, token: str) -> bool:
        """Alias of :meth:`validate`. Kept for backward compatibility."""
        return self.validate(token)
