# Tina4 Middleware — CORS and Rate Limiter.
"""
Built-in middleware for cross-origin requests and rate limiting.
Zero dependencies — stdlib only.

    from tina4_python.core.middleware import CorsMiddleware, RateLimiter

CORS is configured via environment variables:
    TINA4_CORS_ORIGINS=*                    # Allowed origins (* = all)
    TINA4_CORS_METHODS=GET,POST,PUT,DELETE  # Allowed methods
    TINA4_CORS_HEADERS=Content-Type,Authorization
    TINA4_CORS_MAX_AGE=86400               # Preflight cache (seconds)

Rate limiter uses a sliding window in memory:
    TINA4_RATE_LIMIT=100                   # Requests per window
    TINA4_RATE_WINDOW=60                   # Window in seconds
"""
import os
import time
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
