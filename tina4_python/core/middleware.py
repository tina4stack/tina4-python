# Tina4 Middleware — CORS, Rate Limiter, CSRF.
"""
Built-in middleware for cross-origin requests, rate limiting, and CSRF protection.
Zero dependencies — stdlib only.

    from tina4_python.core.middleware import CorsMiddleware, RateLimiter, CsrfMiddleware

CORS is configured via environment variables:
    TINA4_CORS_ORIGINS=*                    # Allowed origins (* = all)
    TINA4_CORS_METHODS=GET,POST,PUT,DELETE  # Allowed methods
    TINA4_CORS_HEADERS=Content-Type,Authorization
    TINA4_CORS_MAX_AGE=86400               # Preflight cache (seconds)

Rate limiter uses a sliding window in memory:
    TINA4_RATE_LIMIT=100                   # Requests per window
    TINA4_RATE_WINDOW=60                   # Window in seconds

CSRF protection (off by default):
    TINA4_CSRF=true                        # Enable CSRF token validation
"""
import os
import time
import logging
import threading


class CorsMiddleware:
    """CORS handler — reads config from env, injects headers."""

    def __init__(self):
        self.origins = os.environ.get("TINA4_CORS_ORIGINS", "*")
        self.methods = os.environ.get(
            "TINA4_CORS_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        )
        self.headers = os.environ.get(
            "TINA4_CORS_HEADERS",
            "Content-Type,Authorization,X-Request-ID"
        )
        self.max_age = os.environ.get("TINA4_CORS_MAX_AGE", "86400")
        self.credentials = os.environ.get(
            "TINA4_CORS_CREDENTIALS", "true"
        ).lower() in ("true", "1", "yes")

    def allowed_origin(self, request_origin: str) -> str:
        """Return the origin to set in Access-Control-Allow-Origin."""
        if self.origins == "*":
            return "*"
        allowed = [o.strip() for o in self.origins.split(",")]
        if request_origin in allowed:
            return request_origin
        return ""

    def apply(self, request, response):
        """Inject CORS headers into the response."""
        origin = request.headers.get("origin", "")
        allowed = self.allowed_origin(origin)

        if allowed:
            response.header("access-control-allow-origin", allowed)
            response.header("access-control-allow-methods", self.methods)
            response.header("access-control-allow-headers", self.headers)
            response.header("access-control-max-age", self.max_age)
            if self.credentials and allowed != "*":
                response.header("access-control-allow-credentials", "true")

        return response

    def is_preflight(self, request) -> bool:
        """Check if this is an OPTIONS preflight request."""
        return (
            request.method == "OPTIONS"
            and "origin" in request.headers
            and "access-control-request-method" in request.headers
        )


class RateLimiter:
    """Sliding window rate limiter — per-IP, in-memory.

    Thread-safe. Automatically cleans up expired entries.
    """

    def __init__(self):
        self.limit = int(os.environ.get("TINA4_RATE_LIMIT", "100"))
        self.window = int(os.environ.get("TINA4_RATE_WINDOW", "60"))
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def check(self, ip: str) -> tuple[bool, dict]:
        """Check if request is allowed.

        Returns (allowed, info) where info has remaining/limit/reset fields.
        """
        now = time.monotonic()

        with self._lock:
            # Periodic cleanup every 60 seconds
            if now - self._last_cleanup > 60:
                self._cleanup(now)
                self._last_cleanup = now

            if ip not in self._requests:
                self._requests[ip] = []

            # Remove expired timestamps
            cutoff = now - self.window
            timestamps = self._requests[ip]
            self._requests[ip] = [t for t in timestamps if t > cutoff]
            timestamps = self._requests[ip]

            remaining = max(0, self.limit - len(timestamps))
            reset = int(self.window - (now - timestamps[0])) if timestamps else self.window

            if len(timestamps) >= self.limit:
                return False, {
                    "limit": self.limit,
                    "remaining": 0,
                    "reset": reset,
                    "window": self.window,
                }

            timestamps.append(now)
            return True, {
                "limit": self.limit,
                "remaining": remaining - 1,
                "reset": self.window,
                "window": self.window,
            }

    def _cleanup(self, now: float):
        """Remove IPs with no recent requests."""
        cutoff = now - self.window
        expired = [ip for ip, ts in self._requests.items() if not ts or ts[-1] < cutoff]
        for ip in expired:
            del self._requests[ip]

    def apply_headers(self, response, info: dict):
        """Add rate limit headers to response."""
        response.header("x-ratelimit-limit", str(info["limit"]))
        response.header("x-ratelimit-remaining", str(info["remaining"]))
        response.header("x-ratelimit-reset", str(info["reset"]))
        return response


class SecurityHeadersMiddleware:
    """Injects security headers on every response.

    Configurable via environment variables:
        TINA4_FRAME_OPTIONS        — X-Frame-Options (default: SAMEORIGIN)
        TINA4_HSTS                 — Strict-Transport-Security max-age value
                                     (default: "" = off; set to "31536000" to enable)
        TINA4_CSP                  — Content-Security-Policy (default: "default-src 'self'")
        TINA4_REFERRER_POLICY      — Referrer-Policy (default: strict-origin-when-cross-origin)
        TINA4_PERMISSIONS_POLICY   — Permissions-Policy (default: camera=(), microphone=(), geolocation=())
    """

    @staticmethod
    def before_security(request, response):
        """Set security headers before the route handler runs."""
        response.header(
            "x-frame-options",
            os.environ.get("TINA4_FRAME_OPTIONS", "SAMEORIGIN"),
        )
        response.header("x-content-type-options", "nosniff")

        hsts = os.environ.get("TINA4_HSTS", "")
        if hsts:
            response.header(
                "strict-transport-security",
                f"max-age={hsts}; includeSubDomains",
            )

        response.header(
            "content-security-policy",
            os.environ.get("TINA4_CSP", "default-src 'self'"),
        )
        response.header(
            "referrer-policy",
            os.environ.get("TINA4_REFERRER_POLICY", "strict-origin-when-cross-origin"),
        )
        response.header("x-xss-protection", "0")
        response.header(
            "permissions-policy",
            os.environ.get(
                "TINA4_PERMISSIONS_POLICY",
                "camera=(), microphone=(), geolocation=()",
            ),
        )

        return request, response


class CsrfMiddleware:
    """CSRF token validation middleware.

    Off by default — only active when TINA4_CSRF=true in .env or when
    registered explicitly via Router.use(CsrfMiddleware).

    Behaviour:
        - Skips GET, HEAD, OPTIONS requests.
        - Skips routes marked @noauth().
        - Skips requests with a valid Authorization: Bearer header (API clients).
        - Checks request.body["formToken"] then request.headers["X-Form-Token"].
        - Rejects if token found in request.query["formToken"] (log warning, 403).
        - Validates token with Auth.valid_token using SECRET env var.
        - If token payload has session_id, verifies it matches request.session.session_id.
        - Returns 403 with response.error("CSRF_INVALID", ...) on failure.
    """

    _logger = logging.getLogger("tina4.csrf")

    @staticmethod
    def before_csrf(request, response):
        """Validate CSRF token before the route handler runs."""
        # Check if CSRF is enabled via env (middleware registration bypasses this)
        csrf_env = os.environ.get("TINA4_CSRF", "true").lower() not in ("false", "0", "no")
        # When registered via Router.use(), this method always runs.
        # The env check is only for auto-activation scenarios.

        # Skip safe HTTP methods
        method = getattr(request, "method", "GET").upper()
        if method in ("GET", "HEAD", "OPTIONS"):
            return request, response

        # Skip routes marked @noauth()
        handler = getattr(request, "_handler", None)
        if handler and getattr(handler, "_noauth", False):
            return request, response

        # Skip requests with valid Bearer token (API clients)
        auth_header = ""
        headers = getattr(request, "headers", {})
        if isinstance(headers, dict):
            auth_header = headers.get("authorization", headers.get("Authorization", ""))
        elif hasattr(headers, "get"):
            auth_header = headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            bearer_token = auth_header[7:].strip()
            if bearer_token:
                from tina4_python.auth import Auth as _CsrfAuth
                secret = os.environ.get("SECRET", "tina4-default-secret")
                auth = _CsrfAuth(secret=secret)
                if auth.valid_token(bearer_token) is not None:
                    return request, response

        # Reject if token is in query string (security risk — log warning)
        query = getattr(request, "params", None) or getattr(request, "query", None) or {}
        if isinstance(query, dict) and query.get("formToken"):
            CsrfMiddleware._logger.warning(
                "CSRF token found in query string — rejected for security. "
                "Use POST body or X-Form-Token header instead."
            )
            return request, response.error(
                "CSRF_INVALID",
                "Form token must not be sent in the URL query string",
                403,
            )

        # Extract token: body first, then header
        token = None
        body = getattr(request, "body", None) or {}
        if isinstance(body, dict):
            token = body.get("formToken")

        if not token:
            if isinstance(headers, dict):
                token = headers.get("x-form-token", headers.get("X-Form-Token", ""))
            elif hasattr(headers, "get"):
                token = headers.get("x-form-token", "")

        if not token:
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        # Validate the token
        from tina4_python.auth import Auth as _CsrfAuth
        secret = os.environ.get("SECRET", "tina4-default-secret")
        auth = _CsrfAuth(secret=secret)
        payload = auth.valid_token(token)

        if payload is None:
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        # Session binding — if token has session_id, verify it matches
        token_session_id = payload.get("session_id")
        if token_session_id:
            session = getattr(request, "session", None)
            current_session_id = None
            if session is not None:
                current_session_id = getattr(session, "session_id", None)
                if current_session_id is None and hasattr(session, "get"):
                    current_session_id = session.get("session_id")

            if current_session_id and token_session_id != current_session_id:
                return request, response.error(
                    "CSRF_INVALID",
                    "Invalid or missing form token",
                    403,
                )

        return request, response
