# Tina4 Middleware — orchestrator plus built-in middleware classes.
"""
Standardized middleware orchestrator and built-in middleware.

Middleware classes follow a simple convention:
    - Static methods named ``before_*`` run BEFORE the route handler
    - Static methods named ``after_*`` run AFTER the route handler
    - Each method receives ``(request, response)`` and returns ``(request, response)``
    - If a before method sets the response status to >= 400, the chain short-circuits

Usage::

    from tina4_python.core.middleware import Middleware, CorsMiddleware

    Middleware.use(CorsMiddleware)
    request, response = Middleware.run_before([CorsMiddleware], request, response)
    request, response = Middleware.run_after([RequestLoggerMiddleware], request, response)

Zero dependencies — stdlib only.
"""
import os
import time
import logging
import threading

from tina4_python.core.rate_limiter import RateLimiter  # noqa: F401 — re-export for backward compat


class Middleware:
    """Standardized middleware orchestrator.

    Registers middleware classes globally and runs their ``before_*`` /
    ``after_*`` static methods in alphabetical order. Mirrors the PHP,
    Ruby and Node.js orchestrators.
    """

    _global_middleware: list = []

    @classmethod
    def use(cls, middleware_class) -> None:
        """Register a middleware class to run on every request."""
        if middleware_class not in cls._global_middleware:
            cls._global_middleware.append(middleware_class)

    @classmethod
    def get_global(cls) -> list:
        """Return the list of globally registered middleware classes."""
        return list(cls._global_middleware)

    @classmethod
    def reset(cls) -> None:
        """Clear all globally registered middleware (primarily for tests)."""
        cls._global_middleware = []

    @classmethod
    def run_before(cls, middleware_classes, request, response):
        """Run every ``before_*`` static method on the given classes.

        Short-circuits if the response status becomes >= 400.
        Returns ``(request, response)``.
        """
        for mw_class in middleware_classes:
            for method_name in cls._discover_methods(mw_class, "before_"):
                result = getattr(mw_class, method_name)(request, response)
                if isinstance(result, tuple) and len(result) >= 2:
                    request, response = result[0], result[1]
                status = getattr(response, "status_code", None) or getattr(response, "status", 0)
                if isinstance(status, int) and status >= 400:
                    return request, response
        return request, response

    @classmethod
    def run_after(cls, middleware_classes, request, response):
        """Run every ``after_*`` static method on the given classes."""
        for mw_class in middleware_classes:
            for method_name in cls._discover_methods(mw_class, "after_"):
                result = getattr(mw_class, method_name)(request, response)
                if isinstance(result, tuple) and len(result) >= 2:
                    request, response = result[0], result[1]
        return request, response

    @staticmethod
    def _discover_methods(mw_class, prefix: str) -> list:
        """Return sorted list of public static method names with ``prefix``."""
        names = [
            name
            for name in dir(mw_class)
            if name.startswith(prefix) and callable(getattr(mw_class, name, None))
        ]
        return sorted(names)


class CorsMiddleware:
    """CORS handler — reads config from env, injects headers."""

    @staticmethod
    def before_cors(request, response):
        """Inject CORS headers on every request (class-based middleware convention)."""
        instance = CorsMiddleware()
        if instance.is_preflight(request):
            instance.apply(request, response)
            return request, response
        instance.apply(request, response)
        return request, response

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


class RateLimiterMiddleware:
    """Static rate limiter middleware — tracks requests per IP, returns 429 when exceeded.

    Config via env: TINA4_RATE_LIMIT (default 100), TINA4_RATE_WINDOW (default 60s).
    Delegates to the RateLimiter class for the actual sliding window logic.
    """

    _limiter = None
    _lock = threading.Lock()

    @classmethod
    def _get_limiter(cls):
        with cls._lock:
            if cls._limiter is None:
                cls._limiter = RateLimiter()
            return cls._limiter

    @staticmethod
    def before_rate_limit(request, response):
        """Middleware hook — enforces rate limiting before the route handler."""
        limiter = RateLimiterMiddleware._get_limiter()
        ip = getattr(request, "ip", None) or "unknown"
        allowed, info = limiter.check(ip)
        limiter.apply_headers(response, info)
        if not allowed:
            retry_after = max(1, int(info.get("reset", limiter.window)))
            response.header("retry-after", str(retry_after))
            if hasattr(response, "error"):
                response.error("Too Many Requests", f"Rate limit exceeded. Retry in {retry_after}s.", 429)
            else:
                setattr(response, "status_code", 429)
        return request, response

    @staticmethod
    def check(ip: str):
        """Check if an IP is within rate limits. Returns (allowed, info)."""
        limiter = RateLimiterMiddleware._get_limiter()
        return limiter.check(ip)


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
                from tina4_python.auth import Auth as _CsrfAuth, _resolve_secret
                secret = _resolve_secret()
                auth = _CsrfAuth(secret=secret)
                if auth.valid_token(bearer_token):
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
        from tina4_python.auth import Auth as _CsrfAuth, _resolve_secret
        secret = _resolve_secret()
        auth = _CsrfAuth(secret=secret)
        if not auth.valid_token(token):
            return request, response.error(
                "CSRF_INVALID",
                "Invalid or missing form token",
                403,
            )

        payload = auth.get_payload(token) or {}

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


class RequestLoggerMiddleware:
    """Request logger — stamps start time before the handler and logs elapsed time after.

    Mirrors the PHP, Ruby and Node.js RequestLogger classes.

    v3.13.14: routes through the Tina4 ``Log`` class (was stdlib
    ``logging.getLogger``, whose ``info()`` is silently dropped by an
    unconfigured root logger — so these lines never reached stdout).
    The dev server also logs every request globally (see
    ``server._finalize_response``); this middleware remains for callers
    that want per-route request logging.
    """

    _start_times: dict = {}
    _lock = threading.Lock()

    @staticmethod
    def before_log(request, response):
        """Record the request start time."""
        key = id(request)
        with RequestLoggerMiddleware._lock:
            RequestLoggerMiddleware._start_times[key] = time.monotonic()
        return request, response

    @staticmethod
    def after_log(request, response):
        """Log the request method, path, status code, and elapsed time."""
        key = id(request)
        with RequestLoggerMiddleware._lock:
            start = RequestLoggerMiddleware._start_times.pop(key, None)
        elapsed_ms = round((time.monotonic() - start) * 1000, 3) if start is not None else 0.0
        method = getattr(request, "method", "?")
        path = getattr(request, "url", None) or getattr(request, "path", "/")
        status = getattr(response, "status_code", None) or getattr(response, "status", 0)
        from tina4_python.debug import Log
        Log.info(f"{method} {path} -> {status} ({elapsed_ms}ms)")
        return request, response
