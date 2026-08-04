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

    def sweep(self) -> int:
        """Drop expired entries, returning how many went.

        In-process backends (memory, file) hold entries until something looks
        at them, so an explicit sweep is the only way to reclaim the space.
        Network backends expire server-side and report 0. Mirrors PHP's
        ``CacheBackend::sweep()``.
        """
        return 0

    def is_available(self) -> bool:
        """Whether this backend is actually usable (driver present + service
        reachable). Local backends are always available; network/driver backends
        override this so the factory can fall back to the file backend."""
        return True


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

    def sweep(self) -> int:
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (_, exp) in self._store.items() if exp and now > exp]
            for k in expired:
                del self._store[k]
            return len(expired)

    def name(self) -> str:
        return "memory"


# ── Redis backend ──────────────────────────────────────────────────


class _RedisBackend(_CacheBackend):
    """Redis / Valkey backend. Uses the ``redis`` package if available,
    otherwise falls back to raw RESP protocol over TCP."""

    def __init__(self, url: str = "redis://localhost:6379", max_entries: int = 1000,
                 name: str = "redis"):
        self._url = url
        self._max_entries = max_entries
        self._name = name
        self._hits = 0
        self._misses = 0
        self._prefix = "tina4:cache:"
        self._client = None
        self._use_raw = False

        # Parse URL: scheme://[user[:password]@]host[:port][/db]. Credentials may
        # also be supplied via TINA4_CACHE_USERNAME / TINA4_CACHE_PASSWORD
        # (mirrors TINA4_DATABASE_USERNAME / TINA4_DATABASE_PASSWORD).
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url if "://" in url else "redis://" + url)
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or 6379
        db_path = (parsed.path or "").lstrip("/")
        self._db = int(db_path) if db_path.isdigit() else 0
        self._username = (unquote(parsed.username) if parsed.username
                          else os.environ.get("TINA4_CACHE_USERNAME", "")) or None
        self._password = (unquote(parsed.password) if parsed.password
                          else os.environ.get("TINA4_CACHE_PASSWORD", "")) or None

        # Try the redis package first
        try:
            import redis as redis_pkg
            kwargs = dict(host=self._host, port=self._port, db=self._db,
                          decode_responses=True, socket_timeout=5)
            if self._password:
                kwargs["password"] = self._password
            if self._username:
                kwargs["username"] = self._username
            self._client = redis_pkg.Redis(**kwargs)
            self._client.ping()
            self._available = True
        except Exception:
            self._client = None
            self._use_raw = True
            # No client — usable only if the server answers (and authenticates).
            self._available = self._probe()

    def _probe(self) -> bool:
        # Real AUTH+PING handshake so wrong credentials also fall back to file.
        try:
            return self._resp_command("PING") == "PONG"
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._available

    @staticmethod
    def _resp_encode(*args) -> bytes:
        """Encode one command as a RESP array of bulk strings."""
        out = [f"*{len(args)}\r\n".encode()]
        for arg in args:
            raw = str(arg).encode()
            out.append(b"$%d\r\n%s\r\n" % (len(raw), raw))
        return b"".join(out)

    @staticmethod
    def _resp_read(reader):
        """Read ONE complete RESP reply and return str | None | list.

        Reads through a buffered file object so a reply LARGER than one socket
        read is assembled in full. The previous implementation did a single
        ``recv(65536)`` and string-split the result, which silently truncated
        any bulk value or multi-bulk reply bigger than the buffer - so a large
        cached entry came back corrupt and a key scan came back short.
        """
        line = reader.readline()
        if not line:
            return None
        prefix, body = line[:1], line[1:].strip()
        if prefix in (b"+", b":"):
            return body.decode()
        if prefix == b"-":
            return None
        if prefix == b"$":
            length = int(body)
            if length < 0:
                return None
            payload = reader.read(length + 2)  # value + trailing CRLF
            return payload[:length].decode()
        if prefix == b"*":
            count = int(body)
            if count < 0:
                return None
            return [_RedisBackend._resp_read(reader) for _ in range(count)]
        return body.decode()

    def _resp_session(self):
        """Open an authenticated RESP socket and return (socket, reader).

        The caller closes both. Kept separate from ``_resp_command`` so a
        multi-step conversation (a SCAN cursor loop) runs over ONE connection
        instead of reconnecting per command.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((self._host, self._port))
        reader = sock.makefile("rb")
        if self._password:
            if self._username:
                sock.sendall(self._resp_encode("AUTH", self._username, self._password))
            else:
                sock.sendall(self._resp_encode("AUTH", self._password))
            if self._resp_read(reader) != "OK":
                reader.close()
                sock.close()
                raise OSError("redis AUTH rejected")
        if self._db != 0:
            sock.sendall(self._resp_encode("SELECT", self._db))
            self._resp_read(reader)
        return sock, reader

    def _resp_command(self, *args):
        """Send one command using the raw RESP protocol over TCP.

        Returns the decoded reply: a string for simple/bulk/integer replies,
        ``None`` for a nil or an error, and a LIST for a multi-bulk reply.
        """
        sock = reader = None
        try:
            sock, reader = self._resp_session()
            sock.sendall(self._resp_encode(*args))
            return self._resp_read(reader)
        except Exception:
            return None
        finally:
            for handle in (reader, sock):
                try:
                    if handle is not None:
                        handle.close()
                except Exception:
                    pass

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
        """Remove EVERY entry this cache can serve - on BOTH transports.

        The raw RESP path used to be a literal ``pass``: "no easy pattern
        delete, let the TTL handle it". That made clear() a no-op on the
        ZERO-DEPENDENCY default install, so a write never invalidated the
        persistent DB query cache and every instance kept serving pre-write rows
        until the TTL ran out (ADR-0024 rule 4: the default provider counts
        double). The bug survived because `uv sync --extra test` installs the
        `redis` package, so every redis test took the DRIVER path.

        SCAN, not KEYS: clear() runs on every write in persistent DB-cache mode,
        and KEYS is O(N) and blocks the whole server for its duration. Redis's
        own documentation says to prefer SCAN in production. The scan is scoped
        to our prefix, so another application sharing the server is untouched -
        FLUSHALL/FLUSHDB would take their data with it and is never used here.
        """
        self._hits = 0
        self._misses = 0
        if self._client:
            try:
                batch = []
                for key in self._client.scan_iter(match=self._prefix + "*", count=500):
                    batch.append(key)
                    if len(batch) >= 500:
                        self._client.delete(*batch)
                        batch = []
                if batch:
                    self._client.delete(*batch)
            except Exception:
                pass
            return
        if not self._use_raw:
            return
        sock = reader = None
        try:
            sock, reader = self._resp_session()
            cursor = "0"
            while True:
                sock.sendall(self._resp_encode(
                    "SCAN", cursor, "MATCH", self._prefix + "*", "COUNT", "500"))
                reply = self._resp_read(reader)
                if not isinstance(reply, list) or len(reply) != 2:
                    break
                cursor, keys = reply[0], reply[1]
                if isinstance(keys, list) and keys:
                    sock.sendall(self._resp_encode("DEL", *keys))
                    self._resp_read(reader)
                if cursor in ("0", 0, None):
                    break
        except Exception:
            pass
        finally:
            for handle in (reader, sock):
                try:
                    if handle is not None:
                        handle.close()
                except Exception:
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
            "backend": self._name,
        }

    def name(self) -> str:
        return self._name


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

    def sweep(self) -> int:
        with self._lock:
            now = time.time()
            removed = 0
            for f in self._dir.glob("*.json"):
                try:
                    exp = json.loads(f.read_text()).get("expires_at")
                    if exp and now > exp:
                        f.unlink(missing_ok=True)
                        removed += 1
                except (json.JSONDecodeError, OSError):
                    pass
            return removed

    def name(self) -> str:
        return "file"


# ── Valkey backend (Redis-protocol compatible) ─────────────────────


class _ValkeyBackend(_RedisBackend):
    """Valkey backend. Valkey speaks the Redis wire protocol, so it reuses the
    Redis client / raw-RESP transport and only reports a different name."""

    def __init__(self, url: str = "valkey://localhost:6379", max_entries: int = 1000):
        super().__init__(url=url.replace("valkey://", "redis://"),
                         max_entries=max_entries, name="valkey")


# ── Memcached backend (zero-dependency text protocol) ──────────────


class _MemcachedBackend(_CacheBackend):
    """Memcached backend using the zero-dependency text protocol over TCP."""

    def __init__(self, url: str = "memcached://localhost:11211", max_entries: int = 1000):
        cleaned = url.replace("memcached://", "").replace("memcache://", "")
        parts = cleaned.split("/")[0].split(":")
        self._host = parts[0] or "localhost"
        self._port = int(parts[1]) if len(parts) > 1 and parts[1] else 11211
        self._max_entries = max_entries
        self._prefix = "tina4:cache:"
        # The SHARED namespace generation counter. clear() bumps it; every real
        # key carries it, so a bump invalidates every instance at once.
        self._gen_key = self._prefix + "generation"
        self._hits = 0
        self._misses = 0
        # Keys THIS backend wrote, with the moment each expires (0 = no expiry).
        # Memcached has no KEYS/prefix scan, so a scoped count cannot be read
        # back from the server - see stats() for why the global counter it does
        # expose is the wrong answer.
        self._own: dict[str, float] = {}
        self._available = self._command(b"version\r\n", b"\r\n").startswith(b"VERSION")

    def is_available(self) -> bool:
        return self._available

    def _generation(self) -> str:
        """Read the SHARED namespace generation from the server.

        memcached has no KEYS scan and no prefix delete, so the only way to
        invalidate globally without destroying other tenants is the documented
        namespace idiom: every real key carries a generation, and clear() bumps
        it. Every instance then computes a different key and the old entries
        become unreachable at once, expiring under the server's own TTL/LRU.

        The generation is read from the server on every operation, deliberately.
        Caching it in-process would reintroduce exactly the bug this fixes: an
        instance holding a stale generation keeps computing the OLD key, and the
        old key still holds the old value, so it serves a stale hit after
        another instance cleared. One extra round trip on a sub-millisecond
        local service is the price of cross-instance invalidation.
        """
        resp = self._command(f"get {self._gen_key}\r\n".encode(), b"END\r\n")
        if resp.startswith(b"VALUE"):
            try:
                header, rest = resp.split(b"\r\n", 1)
                nbytes = int(header.split()[3])
                return rest[:nbytes].decode()
            except Exception:
                pass
        return "0"

    def _mc_key(self, key: str) -> str:
        # Hash to a safe, bounded key (memcached keys: no spaces/control, <=250
        # chars). The generation sits IN the key so a clear() on ANY instance
        # orphans it for every instance at once.
        return (self._prefix + self._generation() + ":"
                + hashlib.sha256(key.encode()).hexdigest())

    def _command(self, payload: bytes, terminator: bytes) -> bytes:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self._host, self._port))
            sock.sendall(payload)
            buf = b""
            while terminator not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            sock.close()
            return buf
        except Exception:
            return b""

    def get(self, key: str):
        resp = self._command(f"get {self._mc_key(key)}\r\n".encode(), b"END\r\n")
        if resp.startswith(b"VALUE"):
            try:
                header, rest = resp.split(b"\r\n", 1)
                nbytes = int(header.split()[3])
                self._hits += 1
                return json.loads(rest[:nbytes].decode())
            except Exception:
                pass
        self._misses += 1
        return None

    def set(self, key: str, value, ttl: int):
        data = json.dumps(value, default=str).encode()
        exptime = ttl if ttl > 0 else 0
        mc_key = self._mc_key(key)
        payload = f"set {mc_key} 0 {exptime} {len(data)}\r\n".encode() + data + b"\r\n"
        self._command(payload, b"\r\n")
        self._own[mc_key] = (time.time() + exptime) if exptime > 0 else 0.0

    def delete(self, key: str) -> bool:
        mc_key = self._mc_key(key)
        resp = self._command(f"delete {mc_key}\r\n".encode(), b"\r\n")
        self._own.pop(mc_key, None)
        return resp.startswith(b"DELETED")

    def clear(self):
        """Invalidate EVERY entry this cache can serve, on EVERY instance.

        Two wrong answers were shipped before this one. `flush_all` wipes EVERY
        key on the instance including every other application's - cache_clear()
        is public API, so calling it destroyed other tenants' data. Deleting
        only the keys THIS process wrote fixed that but broke the contract the
        other way: a second instance kept serving rows the first had just
        invalidated, because it had never seen those keys.

        The namespace generation does both. Bumping the shared counter orphans
        every previously-written entry for every instance at once, and touches
        nothing outside our own prefix. The orphans are reclaimed by memcached's
        own TTL and LRU - unreachable is what "removed" means for a cache.

        The local write log is still cleared so stats() reports honestly, and
        its keys are deleted eagerly so the space comes back immediately rather
        than waiting for eviction.
        """
        self._hits = 0
        self._misses = 0
        for mc_key in list(self._own):
            self._command(f"delete {mc_key}\r\n".encode(), b"\r\n")
        self._own.clear()
        # incr is atomic, so two instances clearing at once still both advance.
        resp = self._command(f"incr {self._gen_key} 1\r\n".encode(), b"\r\n")
        if not resp.strip().isdigit():
            # No counter yet: create it. `add` fails harmlessly if another
            # instance created it in the gap, and the incr then applies.
            self._command(f"add {self._gen_key} 0 0 1\r\n1\r\n".encode(), b"\r\n")
            self._command(f"incr {self._gen_key} 1\r\n".encode(), b"\r\n")

    def stats(self) -> dict:
        """Report OUR entries, not the whole server's.

        This used to read memcached's `curr_items`, which is a GLOBAL counter:
        it includes every key written by every other tenant of that server. On a
        shared memcached (the normal deployment) `size` was therefore reporting
        somebody else's data, and every other backend here is scoped - memory
        counts its own dict, redis/valkey scan their own prefix, file counts its
        own directory, mongo its own collection, database its own table.
        Memcached was the only one leaking.

        It cannot be fixed by asking the server: memcached has no KEYS or
        prefix-scan command. So the count comes from our own write log, filtered
        by the TTLs we set. That is exact for the keys this process wrote; a key
        EVICTED early under memory pressure is invisible to us and would be
        over-counted, which is a far smaller and more honest error than counting
        another application's keys.
        """
        now = time.time()
        live = [k for k, expires in self._own.items() if expires == 0.0 or expires > now]
        # Drop the expired ones so the log cannot grow without bound.
        if len(live) != len(self._own):
            self._own = {k: self._own[k] for k in live}
        return {"hits": self._hits, "misses": self._misses, "size": len(live), "backend": "memcached"}

    def name(self) -> str:
        return "memcached"


# ── MongoDB backend (TTL collection) ───────────────────────────────


class _MongoBackend(_CacheBackend):
    """MongoDB backend backed by a TTL collection. Requires ``pymongo``.

    Reuses the same connection style as the Mongo session handler; the cache
    lives in collection ``tina4_cache`` with a TTL index on ``expires_at``."""

    def __init__(self, url: str = "mongodb://localhost:27017", max_entries: int = 1000):
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._coll = None
        try:
            import pymongo
            mongo_kwargs = {"serverSelectionTimeoutMS": 5000}
            # Credentials from env when not embedded in the URL (parity with DB layer).
            if "@" not in url:
                mu = os.environ.get("TINA4_CACHE_USERNAME")
                mp = os.environ.get("TINA4_CACHE_PASSWORD")
                if mu:
                    mongo_kwargs["username"] = mu
                if mp:
                    mongo_kwargs["password"] = mp
            client = pymongo.MongoClient(url, **mongo_kwargs)
            try:
                db = client.get_default_database()
            except Exception:
                db = None
            if db is None:
                db = client["tina4_cache"]
            self._coll = db["tina4_cache"]
            self._coll.create_index("expires_at", expireAfterSeconds=0)
            client.admin.command("ping")
        except Exception:
            self._coll = None

    def is_available(self) -> bool:
        return self._coll is not None

    def get(self, key: str):
        if self._coll is None:
            self._misses += 1
            return None
        try:
            from datetime import datetime, timezone
            doc = self._coll.find_one({"_id": key})
            if not doc:
                self._misses += 1
                return None
            exp = doc.get("expires_at")
            if exp is not None and exp.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                self._coll.delete_one({"_id": key})
                self._misses += 1
                return None
            self._hits += 1
            return json.loads(doc["value"])
        except Exception:
            self._misses += 1
            return None

    def set(self, key: str, value, ttl: int):
        if self._coll is None:
            return
        try:
            from datetime import datetime, timedelta, timezone
            doc = {"_id": key, "value": json.dumps(value, default=str)}
            if ttl > 0:
                doc["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            self._coll.replace_one({"_id": key}, doc, upsert=True)
        except Exception:
            pass

    def delete(self, key: str) -> bool:
        if self._coll is None:
            return False
        try:
            return self._coll.delete_one({"_id": key}).deleted_count > 0
        except Exception:
            return False

    def clear(self):
        self._hits = 0
        self._misses = 0
        if self._coll is not None:
            try:
                self._coll.delete_many({})
            except Exception:
                pass

    def stats(self) -> dict:
        size = 0
        if self._coll is not None:
            try:
                size = self._coll.count_documents({})
            except Exception:
                pass
        return {"hits": self._hits, "misses": self._misses, "size": size, "backend": "mongodb"}

    def name(self) -> str:
        return "mongodb"


# ── Database backend (cache table in any Tina4-supported DB) ───────


class _DatabaseBackend(_CacheBackend):
    """Database backend — stores entries in a ``tina4_cache`` table in any
    Tina4-supported database. Zero extra infrastructure; reuses the Database
    layer. Its own connection has query caching disabled to avoid recursion."""

    def __init__(self, url: str | None = None, max_entries: int = 1000):
        from tina4_python.database.connection import Database
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._db = None
        self._available = False
        # The database backend reads TINA4_CACHE_URL (interpreted as a SQL URL),
        # falling back to the app's own TINA4_DATABASE_URL — cache in the DB you
        # already run, no extra connection var needed.
        url = (url or os.environ.get("TINA4_CACHE_URL")
               or os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/tina4.db"))
        # The cache's own DB connection must not itself cache (no recursion).
        prev_auto = os.environ.get("TINA4_AUTO_CACHING")
        prev_db = os.environ.get("TINA4_DB_CACHE")
        os.environ["TINA4_AUTO_CACHING"] = "false"
        os.environ["TINA4_DB_CACHE"] = "false"
        try:
            self._db = Database(url)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS tina4_cache "
                "(cache_key VARCHAR(255) PRIMARY KEY, value TEXT, expires_at DOUBLE PRECISION)"
            )
            self._available = True
        except Exception:
            self._available = False
        finally:
            for k, v in (("TINA4_AUTO_CACHING", prev_auto), ("TINA4_DB_CACHE", prev_db)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def is_available(self) -> bool:
        return self._available

    def get(self, key: str):
        row = self._db.fetch_one(
            "SELECT value, expires_at FROM tina4_cache WHERE cache_key = ?", [key])
        if not row:
            self._misses += 1
            return None
        exp = row.get("expires_at")
        if exp and float(exp) > 0 and time.time() > float(exp):
            self._db.execute("DELETE FROM tina4_cache WHERE cache_key = ?", [key])
            self._misses += 1
            return None
        self._hits += 1
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set(self, key: str, value, ttl: int):
        exp = (time.time() + ttl) if ttl > 0 else 0
        serialized = json.dumps(value, default=str)
        self._db.execute("DELETE FROM tina4_cache WHERE cache_key = ?", [key])
        self._db.execute(
            "INSERT INTO tina4_cache (cache_key, value, expires_at) VALUES (?, ?, ?)",
            [key, serialized, exp])

    def delete(self, key: str) -> bool:
        existed = self._db.fetch_one(
            "SELECT 1 AS x FROM tina4_cache WHERE cache_key = ?", [key]) is not None
        self._db.execute("DELETE FROM tina4_cache WHERE cache_key = ?", [key])
        return existed

    def clear(self):
        self._hits = 0
        self._misses = 0
        self._db.execute("DELETE FROM tina4_cache")

    def stats(self) -> dict:
        row = self._db.fetch_one("SELECT COUNT(*) AS c FROM tina4_cache")
        size = int(row["c"]) if row and row.get("c") is not None else 0
        return {"hits": self._hits, "misses": self._misses, "size": size, "backend": "database"}

    def name(self) -> str:
        return "database"


# ── Backend factory ────────────────────────────────────────────────


def _create_backend(
    backend: str | None = None,
    url: str | None = None,
    max_entries: int | None = None,
    cache_dir: str | None = None,
) -> _CacheBackend:
    """Create a cache backend from explicit params or env vars.

    Backends: memory (default), file, redis, valkey, memcached, mongodb, database.
    """
    backend = backend or os.environ.get("TINA4_CACHE_BACKEND", "memory")
    max_entries = max_entries or int(os.environ.get("TINA4_CACHE_MAX_ENTRIES", "1000"))

    backend = backend.lower().strip()
    if backend == "redis":
        url = url or os.environ.get("TINA4_CACHE_URL", "redis://localhost:6379")
        be = _RedisBackend(url=url, max_entries=max_entries)
    elif backend == "valkey":
        url = url or os.environ.get("TINA4_CACHE_URL", "valkey://localhost:6379")
        be = _ValkeyBackend(url=url, max_entries=max_entries)
    elif backend in ("memcached", "memcache"):
        url = url or os.environ.get("TINA4_CACHE_URL", "memcached://localhost:11211")
        be = _MemcachedBackend(url=url, max_entries=max_entries)
    elif backend in ("mongodb", "mongo"):
        url = url or os.environ.get("TINA4_CACHE_URL", "mongodb://localhost:27017")
        be = _MongoBackend(url=url, max_entries=max_entries)
    elif backend in ("database", "db"):
        be = _DatabaseBackend(url=url, max_entries=max_entries)
    elif backend == "file":
        cache_dir = cache_dir or os.environ.get("TINA4_CACHE_DIR", "data/cache")
        return _FileBackend(cache_dir=cache_dir, max_entries=max_entries)
    elif backend in ("memory", ""):
        return _MemoryBackend(max_entries=max_entries)
    else:
        # An UNRECOGNISED name RAISES, naming the bad value and the valid ones
        # — the same contract the session layer settled on. Falling through to
        # memory turned a typo (TINA4_CACHE_BACKEND=redsi) into a running app
        # with a per-process cache while the operator believed it was in Redis.
        raise ValueError(
            f"Unknown cache backend '{backend}'. Valid backends: "
            "memory, file, redis, valkey, memcached, mongodb, database."
        )

    # Graceful degradation: if the configured backend's driver is missing or the
    # service is unreachable, fall back to the file backend (persistent, zero-dep,
    # always available) rather than silently degrading to a no-op cache.
    if not be.is_available():
        try:
            from tina4_python.debug import Log
            Log.warning(
                f"Cache backend '{backend}' is unavailable "
                f"(driver missing or service unreachable) — falling back to 'file'."
            )
        except Exception:
            pass
        cache_dir = cache_dir or os.environ.get("TINA4_CACHE_DIR", "data/cache")
        return _FileBackend(cache_dir=cache_dir, max_entries=max_entries)
    return be


# ── Shared response-cache backend ─────────────────────────────────

_response_backend: _CacheBackend | None = None


def _get_response_backend() -> _CacheBackend:
    """The backend every default ResponseCache shares.

    Memoised at module level so a dispatcher that builds a fresh middleware
    instance per request still reads and writes ONE store. Mirrors Node's
    ``_getResponseBackend``.
    """
    global _response_backend
    if _response_backend is None:
        _response_backend = _create_backend()
    return _response_backend


def _reset_response_backend() -> None:
    """Drop the shared response-cache backend so the next use rebuilds it.

    Test seam only — mirrors Node's ``_resetBackend()``. Production code never
    needs it; ``clear_cache()`` empties the store without rebuilding it.
    """
    global _response_backend
    _response_backend = None


# ── Cache entry (for response cache) ──────────────────────────────


class _CacheEntry:
    """Single cached response."""
    __slots__ = ("body", "content_type", "status_code", "expires_at", "vary", "vary_values")

    def __init__(self, body: str, content_type: str, status_code: int, expires_at: float,
                 vary: list | None = None, vary_values: dict | None = None):
        self.body = body
        self.content_type = content_type
        self.status_code = status_code
        self.expires_at = expires_at
        # RFC 9111 s4.1 — the field names the origin nominated, and the values
        # they had on the request that caused this response to be stored.
        self.vary = vary or []
        self.vary_values = vary_values or {}

    def to_dict(self) -> dict:
        """Plain JSON-serialisable form, so every backend can round-trip it."""
        return {
            "body": self.body,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "expires_at": self.expires_at,
            "vary": self.vary,
            "vary_values": self.vary_values,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild from whatever a backend handed back, or None if unusable."""
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict) or "body" not in data:
            return None
        return cls(
            body=data.get("body", ""),
            content_type=data.get("content_type", "application/json"),
            status_code=int(data.get("status_code", 200)),
            expires_at=float(data.get("expires_at", 0.0)),
            vary=data.get("vary") or [],
            vary_values=data.get("vary_values") or {},
        )


# Response directives that let a SHARED cache store a response to a request
# carrying Authorization (RFC 9111 s3.5).
_SHARED_CACHE_DIRECTIVES = ("public", "s-maxage", "must-revalidate")


def _header_value(carrier, name: str) -> str | None:
    """Case-insensitive header lookup on a request or response, or None.

    Handles both shapes the framework uses: the ``Request``'s ``headers`` dict
    and the ``Response``'s ``_headers`` list of ``(name, value)`` pairs. Reading
    only the dict form made every Vary/Cache-Control check silently no-op on a
    real response.
    """
    target = name.lower()
    headers = getattr(carrier, "headers", None)
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == target:
                return str(value)
    pairs = getattr(carrier, "_headers", None)
    if isinstance(pairs, (list, tuple)):
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and str(pair[0]).lower() == target:
                return str(pair[1])
    return None


def _vary_fields(response) -> list:
    """The lower-cased field names in a response's Vary header."""
    raw = _header_value(response, "Vary")
    if not raw:
        return []
    return [f.strip().lower() for f in raw.split(",") if f.strip()]


def _shared_cache_allowed(response) -> bool:
    """Does the response carry a directive that lets a shared cache store it?"""
    cc = (_header_value(response, "Cache-Control") or "").lower()
    return any(directive in cc for directive in _SHARED_CACHE_DIRECTIVES)


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

        # The backend stores the cached RESPONSES too, so a redis/valkey/
        # memcached/mongodb/database backend distributes them across workers
        # and instances (parity with PHP/Ruby/Node). Before 3.13.95 this object
        # was built and then never read on the request path: responses went to
        # a private per-instance dict, so TINA4_CACHE_BACKEND=redis reported
        # "redis" while two workers — and even two ResponseCache instances in
        # one process — shared nothing.
        #
        # With no explicit backend the module-level one is shared, so every
        # @middleware(ResponseCache) route hits the same store even when the
        # dispatcher builds a fresh instance per request (mirrors Node's
        # memoised _getResponseBackend). An explicit backend/URL gets its own.
        if backend is not None or cache_url is not None or max_entries is not None:
            self._backend = _create_backend(
                backend=backend,
                url=cache_url,
                max_entries=self.max_entries,
            )
        else:
            self._backend = _get_response_backend()

        self._lock = threading.Lock()
        self._hits: int = 0
        self._misses: int = 0

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

        cache_key = self.cache_key(request)
        entry = _CacheEntry.from_dict(self._backend.get(cache_key))

        if entry is not None and time.time() < entry.expires_at and self._vary_matches(entry, request):
            with self._lock:
                self._hits += 1
            remaining = max(0, int(round(entry.expires_at - time.time())))
            hit_response = response(entry.body, entry.status_code)
            self._set_cache_headers(hit_response, "HIT", remaining)
            # Returning the Response OBJECT is what short-circuits — see
            # Middleware.apply_hook_result: "a Response object -> SHORT-CIRCUIT,
            # and that object IS the response, at ANY status". Returning the
            # (request, response) pair only REBINDS and continues, so the
            # handler still ran and the cache never saved a single call.
            return hit_response

        with self._lock:
            self._misses += 1
        return request, response

    def after_cache(self, request, response):
        """
        Middleware hook (after_* convention).

        Capture the response body and cache it if the status code is
        in the allowed set.

        The key is RECOMPUTED from the request rather than read off a tag the
        before-hook wrote: the framework ``Request`` uses ``__slots__``, so
        tagging it raised ``AttributeError`` on every real request and the
        middleware never worked outside the test stubs.
        """
        if self.ttl <= 0:
            return request, response

        method = getattr(request, "method", "GET")
        if method.upper() != "GET":
            return request, response

        # This response came OUT of the cache — the after pass still runs on a
        # short-circuit (by design, so audit/header hooks fire), so without this
        # the HIT would be re-stored and its X-Cache header overwritten to MISS.
        if _header_value(response, "X-Cache") == "HIT":
            return request, response

        route_ttl = self._get_route_ttl(request)
        cache_ttl = route_ttl if route_ttl is not None else self.ttl
        if cache_ttl <= 0:
            return request, response

        status_code = self._extract_status(response)
        if status_code not in self.status_codes:
            return request, response

        if not self._may_store(request, response):
            return request, response

        vary = _vary_fields(response)
        entry = _CacheEntry(
            body=self._extract_body(response),
            content_type=self._extract_content_type(response),
            status_code=status_code,
            expires_at=time.time() + cache_ttl,
            vary=vary,
            vary_values={field: _header_value(request, field) for field in vary},
        )
        self._backend.set(self.cache_key(request), entry.to_dict(), cache_ttl)

        # The handler ran for this request → MISS. Advertise the TTL the
        # entry was just stored with so clients can see how long the next
        # HIT will live.
        self._set_cache_headers(response, "MISS", cache_ttl)

        return request, response

    # ── RFC 9111 conformance ─────────────────────────────────────

    @staticmethod
    def _may_store(request, response) -> bool:
        """May a SHARED cache store this response? (RFC 9111 s3, s4.1)

        Two normative constraints are enforced here:

        * s3 — "if the cache is shared: the Authorization header field is not
          present in the request ... or a response directive is present that
          explicitly allows shared caching". Without this, a response built for
          one authenticated caller is replayed to every later caller of the same
          URL, because the key is method + URL only.
        * s4.1 — "A stored response with a Vary header field value containing a
          member '*' always fails to match", so storing one is pointless.
        """
        if "*" in _vary_fields(response):
            return False
        if _header_value(request, "Authorization") is not None:
            return _shared_cache_allowed(response)
        return True

    @staticmethod
    def _vary_matches(entry, request) -> bool:
        """Do the nominated request headers match the ones that were stored?

        RFC 9111 s4.1 — the cache MUST NOT use a stored response unless every
        request header field nominated by its Vary value matches. An absent
        field only matches an absent field.
        """
        for field in entry.vary:
            if _header_value(request, field) != entry.vary_values.get(field):
                return False
        return True

    def cache_key(self, request) -> str:
        """The cache key for a request: method + URL + sorted query params."""
        url = getattr(request, "url", "/")
        params = getattr(request, "params", None)
        if params:
            qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            return f"GET:{url}?{qs}"
        return f"GET:{url}"

    # ── Public API ───────────────────────────────────────────────

    def cache_stats(self) -> dict:
        """Return cache statistics.

        Returns
        -------
        dict
            ``{"hits": int, "misses": int, "size": int, "backend": str}``
        """
        with self._lock:
            hits, misses = self._hits, self._misses
        stats = self._backend.stats()
        return {
            "hits": hits,
            "misses": misses,
            "size": stats.get("size", 0),
            "backend": self._backend.name(),
        }

    def sweep(self) -> int:
        """Remove all expired entries. Returns count removed."""
        return self._backend.sweep() if hasattr(self._backend, "sweep") else 0

    def clear_cache(self) -> None:
        """Flush all cached entries and reset stats."""
        with self._lock:
            self._hits = 0
            self._misses = 0
        self._backend.clear()

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _set_cache_headers(response, status: str, ttl: int) -> None:
        """Set ``X-Cache`` / ``X-Cache-TTL`` on the outgoing response.

        ``status`` is ``"HIT"`` (served from cache) or ``"MISS"`` (handler
        ran). ``ttl`` is the entry's remaining seconds on a HIT, or the
        configured TTL on a MISS. We deliberately do NOT emit
        ``Cache-Control`` — browser-cache directives are the app's call.

        Works with the framework ``Response`` (``add_header``) and with any
        object exposing a ``headers`` dict, so middleware stubs and other
        response shapes keep working.
        """
        if response is None:
            return
        headers = {"X-Cache": status, "X-Cache-TTL": str(int(ttl))}
        setter = getattr(response, "add_header", None) or getattr(response, "header", None)
        if callable(setter):
            for name, value in headers.items():
                setter(name, value)
            return
        existing = getattr(response, "headers", None)
        if isinstance(existing, dict):
            existing.update(headers)

    @staticmethod
    def _get_route_ttl(request) -> int | None:
        """The per-route TTL from ``@cached(max_age=N)``, or None.

        Read off the matched handler, which the dispatcher attaches to the
        request as ``_handler``. ``@cached`` stamps ``_cache_max_age`` on the
        function; nothing read it before, so the decorator was inert and the
        documented per-route override did nothing. ``_route_meta`` is still
        honoured for callers that supply one, but it can never exist on a real
        ``Request`` (``__slots__``), which is why the handler is the source.
        """
        handler = getattr(request, "_handler", None)
        max_age = getattr(handler, "_cache_max_age", None)
        if max_age is not None:
            return int(max_age)
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
        """Best-effort extraction of the response body.

        The framework ``Response`` holds bytes; ``str(b'{"n":1}')`` yields the
        literal ``b'{"n":1}'``, which is what a HIT would then replay to the
        client. Decode instead.
        """
        body = getattr(response, "body", None)
        if body is None:
            body = getattr(response, "content", None)
        if body is None:
            return str(response)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body).decode("utf-8", errors="replace")
        return body if isinstance(body, str) else str(body)

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
        """Drop expired entries from the backend."""
        self._backend.sweep()


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


def sweep() -> int:
    """Remove expired entries from the cache. Returns count removed."""
    return _get_backend().sweep() if hasattr(_get_backend(), "sweep") else 0


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
