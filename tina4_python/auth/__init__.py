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
import functools


class _DualMethod:
    """Descriptor that makes a method callable on both the class and an instance.

    - ``Auth.get_token(payload)``  — creates a temporary Auth() using env TINA4_SECRET
    - ``auth.get_token(payload)``  — uses the instance's own secret / settings
    """

    def __init__(self, func):
        self._func = func
        functools.update_wrapper(self, func)

    def __get__(self, obj, cls=None):
        if obj is None:
            # Called on the class: Auth.get_token(payload, ...)
            @functools.wraps(self._func)
            def _class_call(*args, **kwargs):
                inst = cls()          # Auth() reads TINA4_SECRET from env
                return self._func(inst, *args, **kwargs)
            return _class_call
        # Called on an instance: auth_instance.get_token(payload, ...)
        return functools.partial(self._func, obj)


def _is_ci() -> bool:
    """True when running under a CI system.

    Honours the de-facto ``CI`` env var that GitHub Actions, GitLab CI,
    CircleCI, Travis, etc. all set to a truthy value. We never generate or
    persist a dev secret in CI — a CI run with a blank secret must surface
    the actionable warning, not silently mint one.
    """
    from tina4_python.dotenv import is_truthy
    return is_truthy(os.environ.get("CI"))


def _is_dev() -> bool:
    """True when the framework is in development mode (TINA4_DEBUG truthy)."""
    from tina4_python.dotenv import is_truthy
    return is_truthy(os.environ.get("TINA4_DEBUG"))


def _is_production() -> bool:
    """True when running in production (TINA4_ENV=production)."""
    return os.environ.get("TINA4_ENV", "development") == "production"


# Actionable message shown when TINA4_SECRET is blank in CI/prod — tells the
# operator exactly what to set and how. Kept as a constant so the bootstrap
# and the lazy resolver emit the identical guidance.
_BLANK_SECRET_WARNING = (
    "Auth: TINA4_SECRET is not set — JWT signing is insecure. "
    "Set TINA4_SECRET to a random value (e.g. `openssl rand -hex 32`) "
    "in your environment or .env before serving traffic. "
    "For LOCAL DEV, set TINA4_DEBUG=true and a per-machine secret is generated "
    "automatically into .env.local (gitignored). Seeing this warning means the "
    "run was NOT detected as dev — typically a container or CI without "
    "TINA4_DEBUG set, or TINA4_ENV=production."
)


def ensure_dev_secret(cwd: str = None) -> str | None:
    """Generate a per-machine development JWT secret once, at server boot.

    Fail-safe default for local dev: a blank ``TINA4_SECRET`` used to log a
    loud warning on every boot even though the developer was never told what
    to set. Instead, in DEV (and only in dev), we mint a cryptographically
    random secret, persist it to a gitignored ``.env.local`` so it survives
    restarts, and set it in the process env for this run.

    Generation happens ONLY when ALL of these hold:
      * ``TINA4_SECRET`` is currently blank, AND
      * we are in DEV (``TINA4_DEBUG`` truthy), AND
      * we are NOT in CI (``CI`` env var not truthy), AND
      * we are NOT in production (``TINA4_ENV`` != "production").

    SECURITY: never generate or persist a secret in CI or production, and
    only ever write to ``.env.local`` (gitignored) — never ``.env``. The
    signing secret must never become a guessable built-in default.

    In CI/prod with a blank secret, this emits the actionable warning instead
    of generating anything.

    Args:
        cwd: Directory in which to create/append ``.env.local`` (defaults to
            the current working directory). Used by tests to point at a temp
            dir without chdir'ing the whole process.

    Returns:
        The generated secret string when one was minted, else ``None``.
    """
    if os.environ.get("TINA4_SECRET"):
        return None  # already configured — nothing to do

    if not _is_dev() or _is_ci() or _is_production():
        # CI / prod / non-dev with a blank secret: warn actionably, never mint.
        _warn_blank_secret()
        return None

    # Dev, not CI, not prod, blank secret → mint a per-machine dev secret.
    new_secret = secrets.token_hex(32)
    os.environ["TINA4_SECRET"] = new_secret  # available for THIS run immediately

    from pathlib import Path
    base = Path(cwd) if cwd else Path.cwd()
    env_local = base / ".env.local"
    try:
        # Append (create if missing). A trailing newline keeps the file
        # parseable if it already held entries without a final newline.
        prefix = ""
        if env_local.exists():
            existing = env_local.read_text(encoding="utf-8")
            if existing and not existing.endswith("\n"):
                prefix = "\n"
        with env_local.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}TINA4_SECRET={new_secret}\n")
        _log_info(
            "Auth: generated a development secret, saved to .env.local (gitignored)"
        )
    except Exception as exc:
        # Never crash boot over a file write — keep the in-memory secret for
        # this run and warn that it won't persist.
        _log_warning(
            "Auth: generated a development secret but could not write "
            f".env.local ({exc}); using it for this run only"
        )
    return new_secret


def _log_info(message: str) -> None:
    try:
        from tina4_python.debug import Log
        Log.info(message)
    except Exception:
        import sys
        print(message, file=sys.stderr)


def _log_warning(message: str) -> None:
    try:
        from tina4_python.debug import Log
        Log.warning(message)
    except Exception:
        import sys
        print(message, file=sys.stderr)


def _warn_blank_secret() -> None:
    _log_warning(_BLANK_SECRET_WARNING)


def _resolve_secret(secret: str = None) -> str:
    """Resolve the JWT signing secret.

    Reads ``TINA4_SECRET`` from the environment. When neither an explicit
    secret nor ``TINA4_SECRET`` is set, warns loudly with an actionable
    message and returns a blank secret — parity with the PHP/Node frameworks.
    Tina4 never silently signs with a guessable built-in default, which would
    make tokens forgeable. (In dev, ``ensure_dev_secret()`` runs at boot and
    mints + persists a secret so this blank path is hit only in CI/prod or
    when auth is used before boot.)
    """
    if secret:
        return secret
    env_secret = os.environ.get("TINA4_SECRET", "")
    if not env_secret:
        _warn_blank_secret()
        return ""
    return env_secret


# Supported JWT algorithms. HMAC only — the whole family is in hashlib, so this
# stays zero-dependency. The header's "alg" is now always the one we actually sign
# with (python#105): the digest is looked up here rather than hardcoded.
_HMAC_ALGORITHMS = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}

# Seconds of clock skew tolerated on the "nbf" (not-before) claim. Without this a
# token minted on one host and validated on another a second behind is rejected
# for no real reason; RFC 7519 explicitly allows "a small leeway".
_JWT_LEEWAY_SECONDS = 60


def _resolve_algorithm(algorithm: str = None) -> str:
    """Pick the JWT algorithm: explicit arg, else TINA4_JWT_ALGORITHM, else HS256.

    Raises ValueError naming the supported set when asked for one we cannot sign
    (python#106 — the env var was registered in the CLI's known_vars and then
    silently ignored, so a user could set HS512 and still get HS256 tokens).
    """
    chosen = (algorithm or os.environ.get("TINA4_JWT_ALGORITHM") or "HS256").strip()
    if chosen not in _HMAC_ALGORITHMS:
        raise ValueError(
            f"Unsupported JWT algorithm {chosen!r}. Tina4 signs with "
            f"{', '.join(sorted(_HMAC_ALGORITHMS))} (HMAC only, zero-dependency). "
            f"Set TINA4_JWT_ALGORITHM to one of those."
        )
    return chosen


class Auth:
    """JWT authentication and password hashing — zero dependencies."""

    def __init__(self, secret: str = None, algorithm: str = None,
                 expires_in: int = None):
        """
        Args:
            secret:     Signing secret (falls back to the TINA4_SECRET env var).
            algorithm:  JWT algorithm (falls back to TINA4_JWT_ALGORITHM, then HS256).
            expires_in: Token lifetime in seconds (default 3600).
        """
        self.secret = secret if secret is not None else _resolve_secret()
        self.algorithm = _resolve_algorithm(algorithm)
        # JWT expiry env var:
        # - TINA4_TOKEN_EXPIRES_IN (preferred — matches docs and the
        #   form-token expiry env var used by Frond)
        # - TINA4_TOKEN_LIMIT (legacy — accepted for backward compat)
        # Constructor arg wins over both env vars.
        self.expires_in = expires_in or int(
            os.environ.get("TINA4_TOKEN_EXPIRES_IN")
            or os.environ.get("TINA4_TOKEN_LIMIT", "60")
        )

    # ── JWT ────────────────────────────────────────────────────────

    @_DualMethod
    def get_token(self, payload: dict, expires_in: int = None, secret: str = None) -> str:
        """Create a signed JWT token.

        Args:
            expires_in: Lifetime in minutes (default: self.expires_in).
            secret:     Override signing secret (default: self.secret / TINA4_SECRET env var).

        Returns: header.payload.signature
        """
        if secret is not None:
            return Auth(secret=secret, algorithm=self.algorithm,
                        expires_in=self.expires_in).get_token(payload, expires_in=expires_in)
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

    @_DualMethod
    def valid_token(self, token: str) -> "dict | None":
        """Validate a JWT signature + expiry. Returns the decoded payload
        on success, or ``None`` if invalid / expired / malformed.

        The payload dict is truthy for valid tokens and ``None`` is falsy,
        so the legacy ``if Auth.valid_token(t):`` boolean-style usage keeps
        working unchanged. Callers that want the payload can now read it
        directly instead of a separate ``get_payload(t)`` call::

            payload = Auth.valid_token(token)
            if payload is None:
                return response("Unauthorized", 401)
            user_id = payload["user_id"]

        Matches the convention used by PyJWT, python-jose, and authlib —
        validity check returns the payload because the validation IS the
        payload decode. Returning bare True/False discarded that information.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            h, p, sig = parts

            # Pin the algorithm to OUR configured one instead of trusting the
            # token's header. A token asking to be verified as anything else --
            # "none", a weaker HMAC, or an RSA alg we do not implement -- is
            # rejected before any signature work. Matches the Ruby check.
            header = json.loads(_b64url_decode(h))
            if header.get("alg") != self.algorithm:
                return None

            expected = self._sign(f"{h}.{p}")
            if not hmac.compare_digest(sig, expected):
                return None

            payload = json.loads(_b64url_decode(p))

            now = time.time()
            if "exp" in payload and now > payload["exp"]:
                return None

            # "nbf" (not-before): a post-dated token is not valid yet. Was
            # honoured only by Ruby, so Python/PHP/Node accepted tokens their
            # issuer had explicitly marked as not-yet-usable (python#107).
            if "nbf" in payload and now + _JWT_LEEWAY_SECONDS < payload["nbf"]:
                return None

            return payload
        except Exception:
            return None

    @_DualMethod
    def get_payload(self, token: str) -> dict | None:
        """Decode payload WITHOUT validating signature or expiry."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            return json.loads(_b64url_decode(parts[1]))
        except Exception:
            return None

    @_DualMethod
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
        # Digest comes from the configured algorithm, so the "alg" we advertise in
        # the header is the one that actually produced this signature.
        sig = hmac.new(
            self.secret.encode(), message.encode(), _HMAC_ALGORITHMS[self.algorithm]
        ).digest()
        return _b64url_encode(sig)

    # ── Legacy aliases ─────────────────────────────────────────────

    # get_token and valid_token are the primary names

    # ── Class-level convenience methods (read TINA4_SECRET from env) ────

    @classmethod
    def get_token_static(cls, payload: dict, expires_in: int = 60) -> str:
        """Create a JWT without instantiating Auth — reads TINA4_SECRET from env."""
        secret = _resolve_secret()
        auth = cls(secret=secret, expires_in=expires_in)
        return auth.get_token(payload)

    @classmethod
    def valid_token_static(cls, token: str) -> "dict | None":
        """Validate a JWT without instantiating Auth — reads TINA4_SECRET from env.

        Returns the decoded payload on success, ``None`` on failure.
        """
        secret = _resolve_secret()
        auth = cls(secret=secret)
        return auth.valid_token(token)

    @classmethod
    def get_payload_static(cls, token: str) -> dict | None:
        """Decode payload (no validation) without instantiating Auth."""
        secret = _resolve_secret()
        auth = cls(secret=secret)
        return auth.get_payload(token)

    @classmethod
    def refresh_token_static(cls, token: str, expires_in: int = 60) -> str | None:
        """Refresh a JWT without instantiating Auth — reads TINA4_SECRET from env."""
        secret = _resolve_secret()
        auth = cls(secret=secret, expires_in=expires_in)
        return auth.refresh_token(token)

    @classmethod
    def authenticate_request_static(cls, headers: dict) -> dict | None:
        """Extract and validate auth from request headers without instantiating Auth.

        Reads TINA4_SECRET from env. Checks: Bearer JWT, Bearer API key, Basic auth.
        Returns payload dict on success, None on failure.
        """
        secret = _resolve_secret()
        auth = cls(secret=secret)
        return auth.authenticate_request(headers)

    # ── Password Hashing ──────────────────────────────────────────

    @staticmethod
    def hash_password(password: str, salt: str = None, iterations: int = 260000) -> str:
        """Hash using PBKDF2-HMAC-SHA256. Returns: algorithm$iterations$salt$hash

        Args:
            password:   Plaintext password to hash.
            salt:       Hex-encoded salt; auto-generated if None.
            iterations: PBKDF2 iteration count (default 260000).
        """
        if salt is None:
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
            expected = os.environ.get("TINA4_API_KEY", "")
        if not expected:
            return False
        return hmac.compare_digest(provided, expected)

    # ── Request Auth Helper ───────────────────────────────────────

    @_DualMethod
    def authenticate_request(self, headers: dict, secret: str = None, algorithm: str = None) -> dict | None:
        """Extract and validate auth from request headers.

        Args:
            secret:    Override signing secret (default: self.secret / TINA4_SECRET env var).
            algorithm: JWT algorithm override (default: self.algorithm / TINA4_JWT_ALGORITHM).

        Checks: Bearer JWT, Bearer API key, Basic auth.
        Returns payload dict on success, None on failure.
        """
        # Both overrides used to be accepted and then dropped on the floor: the
        # body called self.valid_token(), so a caller passing secret= or
        # algorithm= silently got this instance's values instead. Honour them.
        if secret is not None or algorithm is not None:
            return Auth(secret=secret if secret is not None else self.secret,
                        algorithm=algorithm or self.algorithm,
                        expires_in=self.expires_in).authenticate_request(headers)

        auth_header = headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if self.valid_token(token):
                return self.get_payload(token)
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

def get_token(payload: dict, expires_in: int = 60, secret: str = None) -> str:
    """Create a JWT — reads TINA4_SECRET from env. Shortcut for Auth.get_token_static()."""
    if secret is not None:
        return Auth(secret=secret).get_token(payload, expires_in=expires_in)
    return Auth.get_token_static(payload, expires_in=expires_in)


def valid_token(token: str) -> "dict | None":
    """Validate a JWT signature and expiry — reads TINA4_SECRET from env.

    Returns the decoded payload dict on success, ``None`` on failure.
    The truthy/falsy split keeps legacy ``if valid_token(t):`` code working
    while letting new code read the payload directly.
    """
    return Auth.valid_token_static(token)


def get_payload(token: str) -> dict | None:
    """Decode JWT payload (no validation). Shortcut for Auth.get_payload_static()."""
    return Auth.get_payload_static(token)


def refresh_token(token: str, expires_in: int = 60) -> str | None:
    """Refresh a JWT — reads TINA4_SECRET from env. Shortcut for Auth.refresh_token_static()."""
    return Auth.refresh_token_static(token, expires_in=expires_in)


def authenticate_request(headers: dict, secret: str = None, algorithm: str = None) -> dict | None:
    """Validate auth from request headers — reads TINA4_SECRET from env."""
    if secret is not None or algorithm is not None:
        return Auth(secret=secret, algorithm=algorithm).authenticate_request(headers)
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
        if not Auth.valid_token_static(token):
            return request, response({"error": "Invalid token"}, 401)
        request.auth = Auth.get_payload_static(token)
        return request, response


__all__ = [
    "Auth", "AuthMiddleware", "get_token", "valid_token", "get_payload",
    "refresh_token", "authenticate_request", "validate_api_key",
    "ensure_dev_secret",
]
