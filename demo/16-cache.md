# Cache

Tina4 includes a thread-safe in-memory cache with TTL expiry, LRU eviction, and tag-based invalidation. Zero dependencies -- it uses Python's `threading.RLock` for thread safety.

## Basic Usage

```python
from tina4_python.core.cache import Cache

cache = Cache(default_ttl=300)  # 5-minute default TTL

# Set a value
cache.set("user:1", {"name": "Alice", "role": "admin"})

# Get a value (returns None if expired or missing)
user = cache.get("user:1")
print(user)  # {"name": "Alice", "role": "admin"}

# Get with default
value = cache.get("missing:key", default="fallback")
print(value)  # "fallback"

# Delete
cache.delete("user:1")
```

## Custom TTL Per Key

Override the default TTL on individual keys.

```python
# Cache for 60 seconds
cache.set("short_lived", "data", ttl=60)

# Cache for 1 hour
cache.set("long_lived", "data", ttl=3600)

# Cache forever (no expiry)
cache.set("permanent", "data", ttl=0)
```

## Tags

Tags allow you to invalidate groups of related cache entries at once.

```python
# Tag cached entries
cache.set("user:1", user_data, tags=["users"])
cache.set("user:2", user_data, tags=["users"])
cache.set("user:1:orders", orders, tags=["users", "orders"])

# Clear all entries tagged "users"
cache.clear_tag("users")
# user:1, user:2, and user:1:orders are all removed
```

## LRU Eviction

When the cache exceeds `max_size`, the least recently used entries are evicted.

```python
cache = Cache(default_ttl=300, max_size=1000)

# After 1000 entries, the least-accessed ones are evicted
for i in range(1500):
    cache.set(f"key:{i}", f"value:{i}")

# Accessing a key moves it to the front of the LRU list
cache.get("key:0")  # This key is now "recently used" and won't be evicted next
```

## Database Query Caching

A common pattern: cache expensive database queries.

```python
from tina4_python.core.cache import Cache

query_cache = Cache(default_ttl=120)

def get_active_users():
    cached = query_cache.get("active_users")
    if cached is not None:
        return cached

    users = db.fetch("SELECT * FROM users WHERE active = ?", [1])
    result = users.to_array()
    query_cache.set("active_users", result, tags=["users"])
    return result

# Invalidate when data changes
def create_user(data):
    db.insert("users", data)
    query_cache.clear_tag("users")  # All user-related caches cleared
```

## ORM Cached Queries

The ORM has built-in cache integration via `Model.cached()`.

```python
# Cache for 120 seconds, auto-tagged with model name
users, count = User.cached(
    "SELECT * FROM users WHERE active = ?",
    [1],
    ttl=120,
    limit=50
)

# Automatically invalidated when any User is saved
user = User({"name": "New User"})
user.save()  # Clears all User cache entries
```

## Cache Statistics

```python
# Check if a key exists (without affecting LRU)
exists = cache.get("key") is not None

# Count entries
print(len(cache._store))  # Current number of entries
```

## Route-Level Caching

Cache entire route responses.

```python
from tina4_python.core.cache import Cache

route_cache = Cache(default_ttl=60)

@get("/api/stats")
async def get_stats(request, response):
    cached = route_cache.get("stats")
    if cached is not None:
        return response(cached)

    stats = compute_expensive_stats()
    route_cache.set("stats", stats, ttl=60)
    return response(stats)
```

## Configuration

```python
cache = Cache(
    default_ttl=300,    # Default TTL in seconds (0 = no expiry)
    max_size=1000,      # Max entries before LRU eviction
)
```

## Tips

- Use tags to group related cache entries so you can invalidate them together.
- Set `ttl=0` for data that rarely changes (configuration, lookup tables).
- Use short TTLs (30-60s) for frequently changing data.
- The cache is thread-safe -- you can use it safely across concurrent requests.
- For distributed caching across multiple processes, use Redis sessions or an external cache.
