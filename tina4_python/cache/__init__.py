# Tina4 Response Cache — Multi-backend GET response caching middleware.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
"""
Response cache for GET requests with pluggable backends.

Backends are selected via the ``TINA4_CACHE_BACKEND`` env var:

    memory  — in-process LRU cache (default, zero deps)
    redis   — Redis / Valkey (uses ``redis`` package or raw RESP over TCP)
    file    — JSON files in ``data/cache/``

    from tina4_python.cache import ResponseCache, cache_stats, clear_cache
    from tina4_python.cache import cache_get, cache_set, cache_delete, cache_clear, cache_stats

    # As middleware on a route
    @middleware(ResponseCache)
    @get("/api/products")
    async def products(request, response):
        return response(expensive_query())

    # Direct usage
    cache_set("key", {"data": "value"}, ttl=120)
    value = cache_get("key")
    cache_delete("key")
    cache_clear()
    stats = cache_stats()  # {"hits": 42, "misses": 7, "size": 15, "backend": "memory"}

Environment:
    TINA4_CACHE_BACKEND      — memory | redis | file  (default: memory)
    TINA4_CACHE_URL           — redis://localhost:6379  (redis backend only)
    TINA4_CACHE_TTL           — default TTL in seconds  (default: 60)
    TINA4_CACHE_MAX_ENTRIES   — max cached entries       (default: 1000)
"""
import os
import time
import json
import hashlib
import threading
import socket
from collections import OrderedDict
from pathlib import Path


# ── Backend interface ──────────────────────────────────────────────


class _CacheBackend:
    """Abstract cache backend."""

    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value, ttl: int):
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError

    def stats(self) -> dict:
        raise NotImplementedError

    def name(self) -> str:
        raise NotImplementedError


# ── Memory backend ─────────────────────────────────────────────────


class _MemoryBackend(_CacheBackend):
    """Thread-safe in-memory LRU cache with TTL."""

    def __init__(self, max_entries: int = 1000):
        self._store: OrderedDict[str, tuple] = OrderedDict()  # key -> (value, expires_at)
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if expires_at and time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value, ttl: int):
        with self._lock:
            expires_at = time.monotonic() + ttl if ttl > 0 else None
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self):
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            # Sweep expired
            now = time.monotonic()
            expired = [k for k, (_, exp) in self._store.items() if exp and now > exp]
            for k in expired:
                del self._store[k]
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
                "backend": "memory",
            }

    def name(self) -> str:
        return "memory"


# ── Redis backend ──────────────────────────────────────────────────


class _RedisBackend(_CacheBackend):
    """Redis / Valkey backend. Uses the ``redis`` package if available,
    otherwise falls back to raw RESP protocol over TCP."""

    def __init__(self, url: str = "redis://localhost:6379", max_entries: int = 1000):
        self._url = url
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._prefix = "tina4:cache:"
        self._client = None
        self._use_raw = False

        # Parse URL
        cleaned = url.replace("redis://", "")
        parts = cleaned.split(":")
        self._host = parts[0] or "localhost"
        self._port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
        db_part = cleaned.split("/")
        self._db = int(db_part[1]) if len(db_part) > 1 and db_part[1] else 0

        # Try the redis package first
        try:
            import redis as redis_pkg
            self._client = redis_pkg.Redis(
                host=self._host, port=self._port, db=self._db,
                decode_responses=True, socket_timeout=5,
            )
            self._client.ping()
        except Exception:
            self._client = None
            self._use_raw = True

    def _resp_command(self, *args) -> str | None:
        """Send a command using raw RESP protocol over TCP."""
        try:
            cmd = f"*{len(args)}\r\n"
            for arg in args:
                s = str(arg)
                cmd += f"${len(s)}\r\n{s}\r\n"

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self._host, self._port))
            if self._db != 0:
                select_cmd = f"*2\r\n$6\r\nSELECT\r\n${len(str(self._db))}\r\n{self._db}\r\n"
                sock.sendall(select_cmd.encode())
                sock.recv(1024)
            sock.sendall(cmd.encode())
            response = sock.recv(65536).decode()
            sock.close()

            if response.startswith("+"):
                return response[1:].strip()
            elif response.startswith("$-1"):
                return None
            elif response.startswith("$"):
                lines = response.split("\r\n")
                return lines[1] if len(lines) > 1 else None
            elif response.startswith(":"):
                return response[1:].strip()
            elif response.startswith("-"):
                return None
            return response.strip()
        except Exception:
            return None

    def get(self, key: str):
        full_key = self._prefix + key
        raw = None
        if self._client:
            try:
                raw = self._client.get(full_key)
            except Exception:
                raw = None
        elif self._use_raw:
            raw = self._resp_command("GET", full_key)

        if raw is None:
            self._misses += 1
            return None
        self._hits += 1
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value, ttl: int):
        full_key = self._prefix + key
        serialized = json.dumps(value, default=str)
        if self._client:
            try:
                if ttl > 0:
                    self._client.setex(full_key, ttl, serialized)
                else:
                    self._client.set(full_key, serialized)
            except Exception:
                pass
        elif self._use_raw:
            if ttl > 0:
                self._resp_command("SETEX", full_key, str(ttl), serialized)
            else:
                self._resp_command("SET", full_key, serialized)

    def delete(self, key: str) -> bool:
        full_key = self._prefix + key
        if self._client:
            try:
                return bool(self._client.delete(full_key))
            except Exception:
                return False
        elif self._use_raw:
            result = self._resp_command("DEL", full_key)
            return result == "1"
        return False

    def clear(self):
        self._hits = 0
        self._misses = 0
        if self._client:
            try:
                keys = self._client.keys(self._prefix + "*")
                if keys:
                    self._client.delete(*keys)
            except Exception:
                pass
        elif self._use_raw:
            # Raw RESP doesn't support pattern delete easily,
            # so we just clear stats and let TTL handle cleanup
            pass

    def stats(self) -> dict:
        size = 0
        if self._client:
            try:
                keys = self._client.keys(self._prefix + "*")
                size = len(keys)
            except Exception:
                pass
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": size,
            "backend": "redis",
        }

    def name(self) -> str:
        return "redis"


# ── File backend ───────────────────────────────────────────────────


class _FileBackend(_CacheBackend):
    """File-based cache. Stores entries as JSON files in ``data/cache/``."""

    def __init__(self, cache_dir: str = "data/cache", max_entries: int = 1000):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _key_path(self, key: str) -> Path:
        safe = hashlib.sha256(key.encode()).hexdigest()
        return self._dir / f"{safe}.json"

    def get(self, key: str):
        path = self._key_path(key)
        with self._lock:
            if not path.exists():
                self._misses += 1
                return None
            try:
                data = json.loads(path.read_text())
                expires_at = data.get("expires_at")
                if expires_at and time.time() > expires_at:
                    path.unlink(missing_ok=True)
                    self._misses += 1
                    return None
                self._hits += 1
                return data.get("value")
            except (json.JSONDecodeError, OSError):
                self._misses += 1
                return None

    def set(self, key: str, value, ttl: int):
        path = self._key_path(key)
        expires_at = time.time() + ttl if ttl > 0 else None
        entry = {"key": key, "value": value, "expires_at": expires_at}
        with self._lock:
            # Evict oldest if at capacity
            try:
                files = sorted(self._dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
                while len(files) >= self._max_entries:
                    oldest = files.pop(0)
                    oldest.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                path.write_text(json.dumps(entry, default=str))
            except OSError:
                pass

    def delete(self, key: str) -> bool:
        path = self._key_path(key)
        with self._lock:
            if path.exists():
                path.unlink(missing_ok=True)
                return True
            return False

    def clear(self):
        with self._lock:
            self._hits = 0
            self._misses = 0
            for f in self._dir.glob("*.json"):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass

    def stats(self) -> dict:
        with self._lock:
            # Sweep expired
            now = time.time()
            count = 0
            for f in self._dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    exp = data.get("expires_at")
                    if exp and now > exp:
                        f.unlink(missing_ok=True)
                    else:
                        count += 1
                except (json.JSONDecodeError, OSError):
                    pass
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": count,
                "backend": "file",
            }

    def name(self) -> str:
        return "file"


# ── Backend factory ────────────────────────────────────────────────


def _create_backend(
    backend: str | None = None,
    url: str | None = None,
    max_entries: int | None = None,
    cache_dir: str | None = None,
) -> _CacheBackend:
    """Create a cache backend from explicit params or env vars."""
    backend = backend or os.environ.get("TINA4_CACHE_BACKEND", "memory")
    max_entries = max_entries or int(os.environ.get("TINA4_CACHE_MAX_ENTRIES", "1000"))

    backend = backend.lower().strip()
    if backend == "redis":
        url = url or os.environ.get("TINA4_CACHE_URL", "redis://localhost:6379")
        return _RedisBackend(url=url, max_entries=max_entries)
    elif backend == "file":
        cache_dir = cache_dir or os.environ.get("TINA4_CACHE_DIR", "data/cache")
        return _FileBackend(cache_dir=cache_dir, max_entries=max_entries)
    else:
        return _MemoryBackend(max_entries=max_entries)


# ── Cache entry (for response cache) ──────────────────────────────


class _CacheEntry:
    """Single cached response."""
    __slots__ = ("body", "content_type", "status_code", "expires_at")

    def __init__(self, body: str, content_type: str, status_code: int, expires_at: float):
        self.body = body
        self.content_type = content_type
        self.status_code = status_code
        self.expires_at = expires_at


# ── ResponseCache middleware ───────────────────────────────────────


class ResponseCache:
    """
    Middleware that caches GET responses using a pluggable backend.

    Cache key: method + URL (including query string).
    Configurable via constructor kwargs or environment variables.

    Parameters
    ----------
    ttl : int
        Time-to-live in seconds for each cached entry.
        Falls back to ``TINA4_CACHE_TTL`` env var, then 60.
    max_entries : int
        Maximum number of entries to keep.
        Falls back to ``TINA4_CACHE_MAX_ENTRIES`` env var, then 1000.
    status_codes : list[int]
        Only cache responses with these status codes. Default: ``[200]``.
    cleanup_interval : float
        Seconds between automatic sweeps of expired entries. Default: 30.
    backend : str
        Cache backend: ``memory`` | ``redis`` | ``file``.
        Falls back to ``TINA4_CACHE_BACKEND`` env var, then ``memory``.
    cache_url : str
        Redis URL. Falls back to ``TINA4_CACHE_URL``.
    """

    def __init__(
        self,
        ttl: int | None = None,
        max_entries: int | None = None,
        status_codes: list[int] | None = None,
        cleanup_interval: float = 30.0,
        backend: str | None = None,
        cache_url: str | None = None,
    ):
        env_ttl = os.environ.get("TINA4_CACHE_TTL")
        env_max = os.environ.get("TINA4_CACHE_MAX_ENTRIES")

        self.ttl: int = ttl if ttl is not None else (int(env_ttl) if env_ttl else 60)
        self.max_entries: int = max_entries if max_entries is not None else (int(env_max) if env_max else 1000)
        self.status_codes: set[int] = set(status_codes or [200])
        self._cleanup_interval: float = cleanup_interval

        # Create the backend
        self._backend = _create_backend(
            backend=backend,
            url=cache_url,
            max_entries=self.max_entries,
        )

        # For memory backend, also keep the old LRU store for response caching
        # (direct entry access with expiry tracking)
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
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
            ``{"hits": int, "misses": int, "size": int, "backend": str}``
        """
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
                "backend": self._backend.name(),
            }

    def clear_cache(self) -> None:
        """Flush all cached entries and reset stats."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
        self._backend.clear()

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


# ── Module-level direct cache API (backend-aware) ─────────────────

_default_backend: _CacheBackend | None = None
_default_cache: ResponseCache | None = None
_default_ttl: int | None = None


def _get_backend() -> _CacheBackend:
    """Lazily create a module-level default backend instance."""
    global _default_backend
    if _default_backend is None:
        _default_backend = _create_backend()
    return _default_backend


def _get_default_ttl() -> int:
    """Get the default TTL from env or 60."""
    global _default_ttl
    if _default_ttl is None:
        env_ttl = os.environ.get("TINA4_CACHE_TTL")
        _default_ttl = int(env_ttl) if env_ttl else 60
    return _default_ttl


def _get_default() -> ResponseCache:
    """Lazily create a module-level default cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = ResponseCache()
    return _default_cache


# ── Direct cache functions (same across all 4 languages) ──────────


def cache_get(key: str):
    """Get a value from the cache by key. Returns None on miss."""
    return _get_backend().get(key)


def cache_set(key: str, value, ttl: int | None = None):
    """Store a value in the cache with optional TTL (seconds)."""
    effective_ttl = ttl if ttl is not None else _get_default_ttl()
    _get_backend().set(key, value, effective_ttl)


def cache_delete(key: str) -> bool:
    """Delete a key from the cache. Returns True if it existed."""
    return _get_backend().delete(key)


def cache_clear():
    """Clear all entries from the cache."""
    _get_backend().clear()


def cache_stats() -> dict:
    """Return cache statistics from the active backend."""
    return _get_backend().stats()


# ── Legacy convenience functions ──────────────────────────────────


def clear_cache() -> None:
    """Flush the default ResponseCache instance (legacy API)."""
    _get_default().clear_cache()
