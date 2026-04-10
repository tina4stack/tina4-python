# Tina4 RateLimiter — sliding window per-IP rate limiter.
"""
In-memory sliding window rate limiter.

Thread-safe. Automatically cleans up expired entries.
Reads configuration from environment variables:
    TINA4_RATE_LIMIT  — max requests per window (default: 100)
    TINA4_RATE_WINDOW — window duration in seconds (default: 60)
"""
import os
import time
import threading


class RateLimiter:
    """Sliding window rate limiter — per-IP, in-memory.

    Thread-safe. Automatically cleans up expired entries.
    """

    _shared_instance = None
    _shared_lock = threading.Lock()

    @classmethod
    def _shared(cls) -> "RateLimiter":
        with cls._shared_lock:
            if cls._shared_instance is None:
                cls._shared_instance = cls()
            return cls._shared_instance

    @staticmethod
    def before_rate_limit(request, response):
        """Class-based middleware entry point — enforces the shared rate limit."""
        limiter = RateLimiter._shared()
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

    def apply(self, request, response):
        """Apply rate limiting to a request/response pair.

        Checks the IP, sets headers, and returns 429 if over limit.
        Returns (request, response).
        """
        ip = getattr(request, "ip", None) or "unknown"
        allowed, info = self.check(ip)
        self.apply_headers(response, info)
        if not allowed:
            retry_after = max(1, int(info.get("reset", self.window)))
            response.header("retry-after", str(retry_after))
            if hasattr(response, "error"):
                response.error("Too Many Requests", f"Rate limit exceeded. Retry in {retry_after}s.", 429)
            else:
                setattr(response, "status_code", 429)
        return request, response

    def reset(self):
        """Clear all tracked request data."""
        with self._lock:
            self._requests.clear()

    def apply_headers(self, response, info: dict):
        """Add rate limit headers to response."""
        response.header("x-ratelimit-limit", str(info["limit"]))
        response.header("x-ratelimit-remaining", str(info["remaining"]))
        response.header("x-ratelimit-reset", str(info["reset"]))
        return response
