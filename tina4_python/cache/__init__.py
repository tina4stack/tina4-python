# Tina4 Response Cache — In-memory GET response caching middleware.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
In-memory response cache for GET requests.

    from tina4_python.cache import ResponseCache, cache_stats, clear_cache

    # As middleware on a route
    @middleware(ResponseCache)
    @get("/api/products")
    async def products(request, response):
        return response(expensive_query())

    # Per-route TTL override via @cached decorator
    @cached(True, max_age=120)
    @get("/api/slow")
    async def slow(request, response):
        return response(very_slow_query())

Environment:
    TINA4_CACHE_TTL          — default TTL in seconds (default: 60)
    TINA4_CACHE_MAX_ENTRIES  — max cached entries     (default: 1000)
"""
import os
import time
import threading
from collections import OrderedDict


class _CacheEntry:
    """Single cached response."""
    __slots__ = ("body", "content_type", "status_code", "expires_at")

    def __init__(self, body: str, content_type: str, status_code: int, expires_at: float):
        self.body = body
        self.content_type = content_type
        self.status_code = status_code
        self.expires_at = expires_at


class ResponseCache:
    """
    Middleware that caches GET responses in memory.

    Cache key: method + URL (including query string).
    Configurable via constructor kwargs or environment variables.

    Parameters
    ----------
    ttl : int
        Time-to-live in seconds for each cached entry.
        Falls back to ``TINA4_CACHE_TTL`` env var, then 60.
    max_entries : int
        Maximum number of entries to keep. When exceeded the least-recently
        used entry is evicted (LRU).
        Falls back to ``TINA4_CACHE_MAX_ENTRIES`` env var, then 1000.
    status_codes : list[int]
        Only cache responses with these status codes. Default: ``[200]``.
    cleanup_interval : float
        Seconds between automatic sweeps of expired entries. Default: 30.
    """

    def __init__(
        self,
        ttl: int | None = None,
        max_entries: int | None = None,
        status_codes: list[int] | None = None,
        cleanup_interval: float = 30.0,
    ):
        env_ttl = os.environ.get("TINA4_CACHE_TTL")
        env_max = os.environ.get("TINA4_CACHE_MAX_ENTRIES")

        self.ttl: int = ttl if ttl is not None else (int(env_ttl) if env_ttl else 60)
        self.max_entries: int = max_entries if max_entries is not None else (int(env_max) if env_max else 1000)
        self.status_codes: set[int] = set(status_codes or [200])
        self._cleanup_interval: float = cleanup_interval

        # LRU store: OrderedDict maintains insertion/access order
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Stats
        self._hits: int = 0
        self._misses: int = 0

        # Start periodic cleanup if TTL is positive
        if self.ttl > 0:
            self._start_cleanup_timer()

    # ── Middleware interface ──────────────────────────────────────

    def before_cache(self, request, response):
        """
        Middleware hook (before_* convention).

        If a valid cached entry exists for this GET request, return the
        cached response immediately. Otherwise let the request continue.
        """
        if self.ttl <= 0:
            return request, response

        method = getattr(request, "method", "GET")
        if method.upper() != "GET":
            return request, response

        url = getattr(request, "url", "/")
        params = getattr(request, "params", None)
        if params:
            qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            cache_key = f"GET:{url}?{qs}"
        else:
            cache_key = f"GET:{url}"

        # Check for per-route TTL override
        route_ttl = self._get_route_ttl(request)

        with self._lock:
            entry = self._store.get(cache_key)
            if entry is not None and time.monotonic() < entry.expires_at:
                self._hits += 1
                # Move to end (most recently used)
                self._store.move_to_end(cache_key)
                return request, response(entry.body, entry.status_code)

            self._misses += 1

        # Tag the request so after_cache can store the response
        request._cache_key = cache_key
        request._cache_ttl = route_ttl if route_ttl is not None else self.ttl
        return request, response

    def after_cache(self, request, response):
        """
        Middleware hook (after_* convention).

        Capture the response body and cache it if the status code is
        in the allowed set.
        """
        if self.ttl <= 0:
            return request, response

        cache_key = getattr(request, "_cache_key", None)
        if cache_key is None:
            return request, response

        cache_ttl = getattr(request, "_cache_ttl", self.ttl)
        if cache_ttl <= 0:
            return request, response

        # Extract response data
        status_code = self._extract_status(response)
        if status_code not in self.status_codes:
            return request, response

        body = self._extract_body(response)
        content_type = self._extract_content_type(response)

        entry = _CacheEntry(
            body=body,
            content_type=content_type,
            status_code=status_code,
            expires_at=time.monotonic() + cache_ttl,
        )

        with self._lock:
            # Evict LRU if at capacity
            while len(self._store) >= self.max_entries:
                self._store.popitem(last=False)

            self._store[cache_key] = entry
            self._store.move_to_end(cache_key)

        return request, response

    # ── Public API ───────────────────────────────────────────────

    def cache_stats(self) -> dict:
        """Return cache statistics.

        Returns
        -------
        dict
            ``{"hits": int, "misses": int, "size": int}``
        """
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
            }

    def clear_cache(self) -> None:
        """Flush all cached entries and reset stats."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _get_route_ttl(request) -> int | None:
        """Check for a per-route cache TTL set via the @cached decorator."""
        meta = getattr(request, "_route_meta", None)
        if meta and "cache_max_age" in meta:
            return int(meta["cache_max_age"])
        return None

    @staticmethod
    def _extract_status(response) -> int:
        """Best-effort extraction of the HTTP status code from the response."""
        if hasattr(response, "status_code"):
            return int(response.status_code)
        if hasattr(response, "http_code"):
            return int(response.http_code)
        return 200

    @staticmethod
    def _extract_body(response) -> str:
        """Best-effort extraction of the response body."""
        if hasattr(response, "body"):
            body = response.body
            return body if isinstance(body, str) else str(body)
        if hasattr(response, "content"):
            return str(response.content)
        return str(response)

    @staticmethod
    def _extract_content_type(response) -> str:
        """Best-effort extraction of the content type."""
        if hasattr(response, "content_type"):
            return str(response.content_type)
        if hasattr(response, "headers") and isinstance(response.headers, dict):
            for key, val in response.headers.items():
                if key.lower() == "content-type":
                    return str(val)
        return "application/json"

    def _cleanup_expired(self) -> None:
        """Remove entries whose TTL has expired."""
        now = time.monotonic()
        with self._lock:
            expired_keys = [k for k, v in self._store.items() if now >= v.expires_at]
            for key in expired_keys:
                del self._store[key]

    def _start_cleanup_timer(self) -> None:
        """Start a daemon thread that periodically cleans expired entries."""
        def _run():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_expired()

        t = threading.Thread(target=_run, daemon=True, name="tina4-cache-cleanup")
        t.start()


# ── Module-level convenience (singleton) ─────────────────────────

_default_cache: ResponseCache | None = None


def _get_default() -> ResponseCache:
    """Lazily create a module-level default cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = ResponseCache()
    return _default_cache


def cache_stats() -> dict:
    """Return stats from the default cache instance."""
    return _get_default().cache_stats()


def clear_cache() -> None:
    """Flush the default cache instance."""
    _get_default().clear_cache()
