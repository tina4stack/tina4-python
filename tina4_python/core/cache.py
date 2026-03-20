# Tina4 Cache — Zero-dependency, thread-safe, TTL-based cache.
"""
In-memory cache with time-to-live expiry. No external dependencies.

    from tina4_python.core.cache import Cache

    cache = Cache(default_ttl=300)  # 5 minute default
    cache.set("key", value)
    cache.get("key")  # → value or None
    cache.delete("key")

For query caching:
    result = cache.get("users:all")
    if result is None:
        result = db.fetch("SELECT * FROM users")
        cache.set("users:all", result, ttl=60)
"""
import time
import threading
import hashlib
import json


class Cache:
    """Thread-safe in-memory cache with TTL expiry.

    Features:
    - Per-key TTL or global default
    - Thread-safe via RLock
    - Lazy expiry (cleaned on access) + periodic sweep
    - Max size with LRU eviction
    - Tags for group invalidation (e.g., clear all "users" cache)
    - SQL query helper for database result caching
    """

    def __init__(self, default_ttl: int = 300, max_size: int = 1000):
        self._store: dict[str, tuple] = {}  # key → (value, expires_at)
        self._tags: dict[str, set[str]] = {}  # tag → set of keys
        self._key_tags: dict[str, set[str]] = {}  # key → set of tags
        self._access_order: list[str] = []  # LRU tracking
        self._lock = threading.RLock()
        self._default_ttl = default_ttl
        self._max_size = max_size

    def get(self, key: str, default=None):
        """Get a value by key. Returns default if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                self._remove_key(key)
                return default
            # Update LRU
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)
            return value

    def set(self, key: str, value, ttl: int = None, tags: list[str] = None):
        """Store a value with optional TTL (seconds) and tags."""
        with self._lock:
            if ttl is None:
                ttl = self._default_ttl
            expires_at = time.time() + ttl if ttl > 0 else None
            self._store[key] = (value, expires_at)

            # LRU tracking
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

            # Tag tracking
            if tags:
                self._key_tags[key] = set(tags)
                for tag in tags:
                    if tag not in self._tags:
                        self._tags[tag] = set()
                    self._tags[tag].add(key)

            # Evict if over max size
            while len(self._store) > self._max_size:
                oldest = self._access_order.pop(0)
                self._remove_key(oldest)

    def delete(self, key: str) -> bool:
        """Remove a key. Returns True if it existed."""
        with self._lock:
            return self._remove_key(key)

    def clear(self):
        """Remove all entries."""
        with self._lock:
            self._store.clear()
            self._tags.clear()
            self._key_tags.clear()
            self._access_order.clear()

    def clear_tag(self, tag: str) -> int:
        """Remove all entries with the given tag. Returns count removed."""
        with self._lock:
            keys = self._tags.pop(tag, set())
            for key in keys:
                self._remove_key(key)
            return len(keys)

    def has(self, key: str) -> bool:
        """Check if a key exists and hasn't expired."""
        return self.get(key) is not None

    def size(self) -> int:
        """Number of entries (including potentially expired ones)."""
        return len(self._store)

    def sweep(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            now = time.time()
            expired = [
                k for k, (_, exp) in self._store.items()
                if exp and now > exp
            ]
            for key in expired:
                self._remove_key(key)
            return len(expired)

    def _remove_key(self, key: str) -> bool:
        if key not in self._store:
            return False
        del self._store[key]
        if key in self._access_order:
            self._access_order.remove(key)
        # Clean up tags
        for tag in self._key_tags.pop(key, set()):
            if tag in self._tags:
                self._tags[tag].discard(key)
                if not self._tags[tag]:
                    del self._tags[tag]
        return True

    # ── Query Cache Helper ─────────────────────────────────────────

    @staticmethod
    def query_key(sql: str, params: list = None) -> str:
        """Generate a cache key from a SQL query and parameters."""
        raw = sql + "|" + json.dumps(params or [], default=str)
        return "query:" + hashlib.md5(raw.encode()).hexdigest()

    def remember(self, key: str, ttl: int, factory: callable):
        """Get from cache or compute, store, and return.

        Usage:
            result = cache.remember("users:all", 60, lambda: db.fetch("SELECT * FROM users"))
        """
        value = self.get(key)
        if value is not None:
            return value
        value = factory()
        self.set(key, value, ttl=ttl)
        return value
