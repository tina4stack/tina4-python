# Tina4 Database Connection — Parse DATABASE_URL, auto-detect driver.
"""
The Database class parses a connection URL and creates the right adapter.

    db = Database("sqlite:///data/app.db")
    db = Database("postgresql://user:pass@host:5432/dbname")
    db = Database()  # Reads DATABASE_URL from environment

Connection pooling:
    db = Database("sqlite:///data/app.db", pool=4)  # 4 connections, round-robin
"""
import hashlib
import os
import threading
import time
import weakref
from urllib.parse import urlparse
from tina4_python.database.database_url import DatabaseUrl, redact_url
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


def _connect_or_explain(adapter: DatabaseAdapter, path: str,
                        username: str = "", password: str = "", **kwargs) -> None:
    """Connect, and on failure say WHICH target failed - redacted.

    A driver's own message names the host and the reason but never the
    configured URL, so an operator running several connections could not tell
    which one refused them. ``redact_url`` is the only form allowed to carry
    that context: the connect path IS the full URL for every engine except
    sqlite, so interpolating it raw would put the password in the error that is
    about to be logged, overlaid and shipped to CI.
    """
    try:
        adapter.connect(path, username=username, password=password, **kwargs)
    except ImportError:
        # "install psycopg2" is already the actionable message; wrapping it in
        # a connection error would bury the one instruction that fixes it.
        raise
    except Exception as cause:
        raise ConnectionError(
            f"Database: could not connect to {redact_url(path)}: {cause}"
        ) from cause


class ConnectionPool:
    """Thread-safe connection pool using round-robin rotation.

    When pool_size > 0, maintains multiple adapter instances and rotates
    through them for each operation. Connections are created lazily on
    first use.

    Usage:
        pool = ConnectionPool(pool_size=4, factory=create_adapter,
                              connect_args=("path", {"username": "u", "password": "p"}))
        adapter = pool.checkout()
        try:
            result = adapter.fetch(sql, params, limit, offset)
        finally:
            pool.checkin(adapter)
        pool.close_all()
    """

    def __init__(self, pool_size: int, factory: callable, connect_path: str,
                 username: str = "", password: str = "", **kwargs):
        self._pool_size = pool_size
        self._factory = factory
        self._connect_path = connect_path
        self._username = username
        self._password = password
        self._connect_kwargs = kwargs
        self._adapters: list[DatabaseAdapter | None] = [None] * pool_size
        self._index = 0
        self._lock = threading.Lock()

    def _ensure_adapter(self, idx: int) -> DatabaseAdapter:
        """Lazily create an adapter at the given index."""
        if self._adapters[idx] is None:
            adapter = self._factory()
            _connect_or_explain(adapter, self._connect_path,
                                username=self._username, password=self._password,
                                **self._connect_kwargs)
            self._adapters[idx] = adapter
        return self._adapters[idx]

    def checkout(self) -> DatabaseAdapter:
        """Get the next adapter via round-robin. Thread-safe."""
        with self._lock:
            idx = self._index
            self._index = (self._index + 1) % self._pool_size
            return self._ensure_adapter(idx)

    def checkin(self, adapter: DatabaseAdapter) -> None:
        """Return an adapter to the pool. Currently a no-op for round-robin."""
        pass

    def close_all(self) -> None:
        """Close all active connections in the pool."""
        with self._lock:
            for i, adapter in enumerate(self._adapters):
                if adapter is not None:
                    adapter.close()
                    self._adapters[i] = None

    @property
    def size(self) -> int:
        return self._pool_size

    @property
    def active_count(self) -> int:
        """Number of connections that have been created."""
        with self._lock:
            return sum(1 for a in self._adapters if a is not None)


# Driver registry — maps URL scheme to adapter class
_DRIVERS: dict[str, type] = {}


def register_driver(scheme: str, adapter_class: type):
    """Register a database adapter for a URL scheme."""
    _DRIVERS[scheme] = adapter_class


# Register built-in SQLite
from tina4_python.database.sqlite import SQLiteAdapter
register_driver("sqlite", SQLiteAdapter)

# Register ODBC (lazy — only fails if you actually use it without pyodbc)
try:
    from tina4_python.database.odbc import ODBCAdapter
    register_driver("odbc", ODBCAdapter)
except ImportError:
    pass  # pyodbc not installed — that's fine

# Register PostgreSQL (psycopg2 — optional)
from tina4_python.database.postgres import PostgreSQLAdapter
register_driver("postgresql", PostgreSQLAdapter)
register_driver("postgres", PostgreSQLAdapter)
register_driver("pgsql", PostgreSQLAdapter)  # PDO / Laravel / Doctrine scheme name (issue #58)

# Register MySQL (mysql-connector-python — optional)
from tina4_python.database.mysql import MySQLAdapter
register_driver("mysql", MySQLAdapter)

# Register MSSQL (pymssql — optional)
from tina4_python.database.mssql import MSSQLAdapter
register_driver("mssql", MSSQLAdapter)
register_driver("sqlserver", MSSQLAdapter)

# Register Firebird (fdb — optional)
from tina4_python.database.firebird import FirebirdAdapter
register_driver("firebird", FirebirdAdapter)

# Register MongoDB (pymongo — optional)
try:
    from tina4_python.database.mongodb import MongoDBAdapter
    register_driver("mongodb", MongoDBAdapter)
    register_driver("pymongo", MongoDBAdapter)
except ImportError:
    pass


class Database:
    """Database connection manager.

    Parses DATABASE_URL, selects the right driver, and delegates all
    operations to the adapter. This is what the rest of the framework uses.
    """

    #: Live Database instances, so the request dispatcher can reset the
    #: request-scoped query cache on every connection at the start of a request.
    _instances: "weakref.WeakSet[Database]" = weakref.WeakSet()

    @classmethod
    def get_connection(cls, url: str = None, username: str = "", password: str = "", pool: int = 0, **kwargs) -> "Database":
        """Open a database connection — convention name matching SQLAlchemy
        ``engine.connect()`` and Django's ``connections["default"]``.

        Equivalent to ``Database(url, username, password, pool=pool, **kwargs)``
        but the intent is clearer at call sites: this opens / returns a
        connection rather than constructing a configuration object.

            db = Database.get_connection()                   # from env
            db = Database.get_connection("sqlite:///app.db") # explicit URL
        """
        return cls(url=url, username=username, password=password, pool=pool, **kwargs)

    @property
    def pool(self) -> "ConnectionPool | None":
        """The active connection pool, or ``None`` when running in
        single-connection mode (``pool=0``).

        Useful for pool introspection and diagnostics::

            if db.pool is not None:
                print(f"{db.pool.active_count()}/{db.pool.size()} connections in use")
        """
        return self._pool

    def __init__(self, url: str = None, username: str = "", password: str = "", pool: int = 0, **kwargs):
        self.url = url or os.environ.get("TINA4_DATABASE_URL", "sqlite:///data/tina4.db")
        # Priority: constructor params > env vars > empty
        self.username = username or os.environ.get("TINA4_DATABASE_USERNAME", "")
        self.password = password or os.environ.get("TINA4_DATABASE_PASSWORD", "")
        # Pool size — caller's explicit value wins; otherwise honour
        # TINA4_DB_POOL so deployments can flip pooling on without code
        # changes. 0 = single connection, N>0 = N pooled connections.
        if pool == 0:
            try:
                pool = int(os.environ.get("TINA4_DB_POOL", "0"))
            except (TypeError, ValueError):
                pool = 0
        self.pool_size = pool
        self._connect_kwargs = kwargs  # Extra kwargs passed through to adapter.connect()
        self.last_error = None  # Last execute() error message
        self._last_id = None   # Last insert ID from execute/insert
        self._pk_cache = {}    # table -> primary-key column name (or None)

        if self.pool_size > 0:
            # Pooled mode — create a ConnectionPool with lazy adapter creation
            self._pool = ConnectionPool(
                pool_size=self.pool_size,
                factory=self._create_adapter,
                connect_path=self._connection_path(),
                username=self.username,
                password=self.password,
                **kwargs,
            )
            self._adapter: DatabaseAdapter | None = None
        else:
            # Single-connection mode — current behavior
            self._pool: ConnectionPool | None = None
            self._adapter: DatabaseAdapter = self._create_adapter()
            _connect_or_explain(self._adapter, self._connection_path(),
                                username=self.username, password=self.password, **kwargs)

        # Per-thread transaction adapter pin. While set, every operation
        # on this thread routes to the same adapter — so the round-robin
        # pool can't rotate mid-transaction and silently break atomicity.
        self._tx_local = threading.local()

        # Query cache. One store, two layers — BOTH opt-in:
        #   • request-scoped (DEFAULT OFF — opt-in via TINA4_AUTO_CACHING=true) —
        #     dedupes identical SELECTs within a request. It ships OFF because a
        #     cache that can hand back pre-write state in a read-after-write —
        #     classically `SELECT MAX(id)` (or a generator read) right before an
        #     INSERT in the same request — is a correctness footgun as a default
        #     (duplicate keys, stale grids). _cache_invalidate() on writes helps
        #     but every new query shape has to remember to play along, so we make
        #     it a deliberate per-app choice. When ON it clears at the start of
        #     every HTTP request and on any write, with a short safety TTL.
        #   • persistent (opt-in, TINA4_DB_CACHE=true) — cross-request TTL cache
        #     that is NOT cleared per request; entries expire by TINA4_DB_CACHE_TTL.
        from tina4_python.dotenv import is_truthy
        self._cache_persistent: bool = is_truthy(os.environ.get("TINA4_DB_CACHE", "false"))
        self._cache_request_scoped: bool = is_truthy(os.environ.get("TINA4_AUTO_CACHING", "false"))
        self._cache_enabled: bool = self._cache_persistent or self._cache_request_scoped
        if self._cache_persistent:
            self._cache_ttl: int = int(os.environ.get("TINA4_DB_CACHE_TTL", "30"))
        else:
            self._cache_ttl = int(os.environ.get("TINA4_AUTO_CACHING_TTL", "5"))
        self._query_cache: dict[str, tuple[float, object]] = {}  # key -> (expires_at, result)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._cache_lock = threading.Lock()
        # Persistent mode uses the unified CacheBackend (memory/file/redis/valkey/
        # mongodb/database via TINA4_DB_CACHE_BACKEND) so multiple instances can
        # share one cache with global write-invalidation. Request-scoped mode keeps
        # the in-process dict above (ephemeral, fastest, never serialized).
        self._cache_backend = None
        if self._cache_persistent:
            try:
                from tina4_python.cache import _create_backend
                self._cache_backend = _create_backend(
                    backend=os.environ.get("TINA4_DB_CACHE_BACKEND", "memory"),
                    url=os.environ.get("TINA4_DB_CACHE_URL"),
                )
            except Exception:
                self._cache_backend = None  # fall back to the in-process dict
        Database._instances.add(self)

    @staticmethod
    def _serialize_result(result) -> dict:
        """Flatten a cached read to a JSON-friendly dict for shared backends.

        ``fetch()`` yields a ``DatabaseResult``; ``fetch_one()`` yields a plain
        dict (or None). Both go through here, so both shapes are handled: this
        used to read ``result.records`` unconditionally, which made every
        ``fetch_one()`` raise ``AttributeError`` the moment TINA4_DB_CACHE was
        turned on. The envelope records which shape it holds so the read side
        hands back exactly what the caller expects.
        """
        if isinstance(result, DatabaseResult):
            return {
                "_shape": "result",
                "records": result.records, "count": result.count,
                "limit": result.limit, "offset": result.offset,
                "affected_rows": result.affected_rows, "last_id": result.last_id,
            }
        return {"_shape": "row", "row": result}

    @staticmethod
    def _deserialize_result(data: dict):
        """Reconstruct a cached read from its backend envelope.

        Returns a ``DatabaseResult`` for a ``fetch()`` entry and the plain row
        (dict or None) for a ``fetch_one()`` entry.
        """
        if isinstance(data, dict) and data.get("_shape") == "row":
            return data.get("row")
        return DatabaseResult(
            records=data.get("records", []), count=data.get("count", 0),
            limit=data.get("limit", 0), offset=data.get("offset", 0),
            affected_rows=data.get("affected_rows", 0), last_id=data.get("last_id"),
        )

    def _create_adapter(self) -> DatabaseAdapter:
        """Select adapter based on the URL's canonical engine.

        The engine comes from DatabaseUrl, which resolves aliases once
        (`postgresql`/`pgsql` -> `postgres`, `sqlserver` -> `mssql`,
        `sqlite3` -> `sqlite`), so this no longer re-derives the scheme with its
        own urlparse call and its own startswith("sqlite") special case.
        """
        try:
            scheme = DatabaseUrl(self.url).engine
        except ValueError:
            # DatabaseUrl rejects the scheme before we can look it up. From the
            # facade's point of view that is the same failure, so keep the
            # message callers already handle.
            scheme = (urlparse(self.url).scheme or "").lower()

        if scheme not in _DRIVERS:
            available = ", ".join(_DRIVERS.keys())
            raise ValueError(
                f"Unknown database driver '{scheme}'. "
                f"Available: {available}. "
                f"Install the driver package and it will register automatically."
            )

        return _DRIVERS[scheme]()

    def _connection_path(self) -> str:
        """Extract connection-specific path/params from the URL.

        SQLite URL convention (matches PHP and the Python CLAUDE.md docs):

            sqlite::memory:                → in-memory database
            sqlite:///:memory:             → in-memory database (URL form)
            sqlite:///app.db               → ./app.db  (relative to cwd)
            sqlite:///data/app.db          → ./data/app.db  (relative)
            sqlite:///./data/app.db        → ./data/app.db  (relative, explicit)
            sqlite:////absolute/path.db    → /absolute/path.db  (absolute)
            sqlite:///C:/Users/app.db      → C:/Users/app.db  (Windows absolute)

        Directories are auto-created ONLY when the resolved path is
        inside the current working directory (the project root). We
        never try to ``os.makedirs`` at root (``/data``, ``C:\\data``)
        — that's both hostile on read-only filesystems and not what
        any project actually wants.
        """
        parsed = urlparse(self.url)

        if not parsed.scheme.startswith("sqlite"):
            # For other drivers, return the full URL (adapter parses it)
            return self.url

        # In-memory forms — passthrough
        if self.url in ("sqlite::memory:", "sqlite:///:memory:"):
            return ":memory:"

        # Strip the scheme on the RAW url string, NOT via urlparse. urlparse collapses
        # "sqlite:/x" and "sqlite:///x" to the same .path, which loses the distinction
        # between a one-slash ABSOLUTE path and the documented three-slash RELATIVE form —
        # that was the "sqlite:<abspath> silently goes relative" footgun. Mirror the
        # sequential strip php/ruby/nodejs use (strip sqlite:/// then sqlite:// then sqlite:):
        #   sqlite:///app.db       → "app.db"        (three slashes = relative to cwd)
        #   sqlite:///data/app.db  → "data/app.db"
        #   sqlite:////abs/app.db  → "/abs/app.db"   (four slashes = absolute)
        #   sqlite:///C:/Users/x   → "C:/Users/x"    (Windows absolute)
        #   sqlite:/abs/app.db     → "/abs/app.db"   (one slash = a real absolute path)
        #   sqlite://rel/app.db    → "rel/app.db"    (two-slash legacy = relative)
        #   sqlite:app.db          → "app.db"        (relative)
        url = self.url
        # `sqlite3:` is a documented alias for `sqlite:`. Normalise it FIRST or
        # none of the prefixes below match and `stripped` keeps the whole URL,
        # so the database file is literally named "sqlite3:app.db". That is not
        # merely ugly: a colon is an illegal filename character on Windows, so
        # the documented alias is unusable there.
        #
        # DatabaseUrl._parse_sqlite already normalises it. This function
        # duplicates that strip instead of calling it, which is exactly how the
        # two drifted. Collapsing them is filed as follow-on work.
        if url.startswith("sqlite3:"):
            url = "sqlite:" + url[len("sqlite3:"):]
        if url.startswith("sqlite:///"):
            stripped = url[len("sqlite:///"):]
        elif url.startswith("sqlite://"):
            stripped = url[len("sqlite://"):]
        elif url.startswith("sqlite:"):
            stripped = url[len("sqlite:"):]
        else:
            stripped = url
        if stripped == ":memory:":
            return ":memory:"

        # Windows absolute path (drive-letter form): C:/... or C:\...
        is_windows_abs = (
            len(stripped) >= 3
            and stripped[0].isalpha()
            and stripped[1] == ":"
            and stripped[2] in ("/", "\\")
        )
        # Unix absolute path — a leading "/" that survived the scheme strip
        # (four-slash "sqlite:////abs" or the one-slash "sqlite:/abs" form).
        is_unix_abs = stripped.startswith("/")

        if is_windows_abs or is_unix_abs:
            path = stripped
            # Don't auto-create directories outside cwd. If the user gave
            # an absolute path, they're responsible for it existing.
        else:
            # Relative — resolve under the project root (cwd).
            cwd = os.getcwd()
            path = os.path.join(cwd, stripped)
            # Only auto-create subdirectories *inside* cwd.
            directory = os.path.dirname(path)
            if directory and os.path.commonpath([os.path.abspath(directory), cwd]) == cwd:
                os.makedirs(directory, exist_ok=True)

        return path

    # ── Query Cache ──────────────────────────────────────────────

    @staticmethod
    def _cache_identity(url: str) -> str:
        """Stable identity of the DATABASE a cache entry came from.

        ``engine://host:port/database`` - and deliberately NOTHING else.

        WHY IT EXISTS: the key used to be ``sha256(sql + params)`` with nothing
        naming the connection, so on any SHARED backend two databases
        cross-served each other's rows. Two apps pointed at one Redis, or one
        app with a primary and an analytics connection, silently read each
        other's data. Identical SQL text across tenants is the COMMON case, not
        an edge case, so the collision was the normal outcome.

        WHY NO CREDENTIALS: a password in the key means every rotation silently
        cold-starts the cache, and a shared backend's key namespace is visible
        to every tenant of that backend - a secret must never be folded into it.
        The username is out for the same reason plus a second: two connections
        differing only by role read the SAME rows and should share the entry.

        WHY NOTHING PER-PROCESS: no pid, no object id, no salt. Those would
        isolate the databases by accident and destroy the point of a shared
        cache, because no instance would ever hit another instance's entry.
        """
        try:
            parsed = DatabaseUrl(url)
            return f"{parsed.engine}://{parsed.host or ''}:{parsed.port or ''}/{parsed.database}"
        except Exception:
            # An unparseable URL still needs a STABLE identity, and falling back
            # to a constant would silently restore the cross-serving bug. The
            # raw URL is stable and distinct; it is only reached for a URL the
            # connection layer is about to reject anyway.
            return url

    def _cache_key(self, sql: str, params) -> str:
        """Generate a cache key from DATABASE IDENTITY + SQL + params.

        The NUL separators keep the three parts from running together, so a
        table named after the tail of a database name cannot forge another
        database's key.
        """
        raw = f"{self._cache_identity(self.url)}\x00{sql}\x00{params or []}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str):
        """Return cached result or None if miss/expired."""
        # Persistent mode → shared CacheBackend (serialized DatabaseResult).
        if self._cache_backend is not None:
            raw = self._cache_backend.get(key)
            return self._deserialize_result(raw) if isinstance(raw, dict) else None
        # Request-scoped mode → in-process dict (stores the object directly).
        with self._cache_lock:
            entry = self._query_cache.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if time.monotonic() > expires_at:
                del self._query_cache[key]
                return None
            return result

    def _cache_set(self, key: str, result):
        """Store a result in the cache with TTL."""
        if self._cache_backend is not None:
            self._cache_backend.set(key, self._serialize_result(result), self._cache_ttl)
            return
        with self._cache_lock:
            self._query_cache[key] = (time.monotonic() + self._cache_ttl, result)

    def _cache_invalidate(self):
        """Clear the entire query cache (called on writes)."""
        if self._cache_backend is not None:
            self._cache_backend.clear()
            return
        with self._cache_lock:
            self._query_cache.clear()

    def cache_new_request(self):
        """Clear the request-scoped query cache at the start of an HTTP request.

        No-op in persistent mode (TINA4_DB_CACHE=true) so cross-request entries
        survive up to their TTL. Cumulative hit/miss counters are preserved.
        """
        if self._cache_request_scoped and not self._cache_persistent:
            with self._cache_lock:
                self._query_cache.clear()

    @classmethod
    def reset_request_caches(cls):
        """Clear the request-scoped query cache on every live Database instance.

        The request dispatcher calls this at the start of each HTTP request so
        request-scoped caching never serves rows across requests (zero
        cross-request staleness). Persistent-mode connections are left alone.
        """
        for inst in list(cls._instances):
            try:
                inst.cache_new_request()
            except Exception:
                pass

    def cache_stats(self) -> dict:
        """Return query cache statistics."""
        if self._cache_backend is not None:
            bs = self._cache_backend.stats()
            return {
                "enabled": True,
                "mode": "persistent",
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": bs.get("size", 0),
                "ttl": self._cache_ttl,
                "backend": bs.get("backend", self._cache_backend.name()),
            }
        with self._cache_lock:
            return {
                "enabled": self._cache_enabled,
                "mode": ("persistent" if self._cache_persistent
                         else "request" if self._cache_request_scoped else "off"),
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": len(self._query_cache),
                "ttl": self._cache_ttl,
                "backend": "memory",
            }

    def cache_clear(self):
        """Flush the query cache and reset counters - BOTH layers.

        This used to clear only the in-process dict, so with TINA4_DB_CACHE=true
        it was a no-op on every provider: clearing the cache after a bulk import
        appeared to work in development (where the cache IS in-process) and did
        nothing in production (where it is shared). ``_cache_invalidate()`` on
        the write path already routed to the backend, so the two ways of
        clearing the same cache disagreed. PHP, Ruby and Node all cleared the
        backend already - Python was the outlier.
        """
        if self._cache_backend is not None:
            self._cache_backend.clear()
        with self._cache_lock:
            self._query_cache.clear()
            self._cache_hits = 0
            self._cache_misses = 0

    # ── Pool-aware adapter access ─────────────────────────────

    def _get_adapter(self) -> DatabaseAdapter:
        """Get an adapter for the next operation.

        With pooling enabled, ordinary calls round-robin through the pool.
        Inside a transaction, however, all calls must land on the SAME
        adapter — otherwise start_transaction(), execute() and commit()
        each rotate to a different connection and the transaction is
        meaningless (executes autocommit on whatever adapter they hit;
        the final commit lands on yet another adapter that has nothing
        to commit; rollback() is silently no-op'd).

        We pin the adapter to the calling thread for the duration of the
        transaction. start_transaction() sets the pin, commit()/rollback()
        clear it. While pinned, _get_adapter() returns that same adapter
        for every call so the whole transaction is atomic on one
        connection.
        """
        pinned = getattr(self._tx_local, "adapter", None)
        if pinned is not None:
            return pinned
        if self._pool is not None:
            return self._pool.checkout()
        return self._adapter

    # ── Delegate to adapter — with cache integration ─────────

    def close(self):
        """Close all connections (pool or single)."""
        if self._pool is not None:
            self._pool.close_all()
        elif self._adapter is not None:
            self._adapter.close()

    def get_error(self) -> str | None:
        """Return the last execute() error message, or None if no error."""
        return self.last_error

    def get_last_id(self):
        """Return the last insert ID from execute() or insert()."""
        return self._last_id

    def execute(self, sql: str, params: list = None):
        """Execute a write statement. Returns True for simple writes.

        If the SQL contains RETURNING, CALL, EXEC, or stored procedure calls,
        returns a DatabaseResult with the result set instead.

        On failure, **raises** the underlying database error (and stores the
        message on ``last_error`` for :meth:`get_error`). It does NOT return
        ``False`` — pre-3.13.x it swallowed the driver exception and returned
        ``False``, which silently turned an unchecked ``INSERT``/``UPDATE``/
        ``DELETE`` into a phantom success while the write never landed. execute()
        now fails loud, mirroring :meth:`fetch`, so the caller's ``try/except``
        (or the dev error overlay) sees the real cause. Wrap writes you expect to
        fail in ``try/except`` instead of testing the return value.
        """
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        try:
            result = adapter.execute(sql, params)
            self.last_error = None
            # Capture last_id from adapter result
            if hasattr(result, "last_id") and result.last_id is not None:
                self._last_id = result.last_id
            sql_upper = sql.strip().upper()
            if ("RETURNING" in sql_upper or sql_upper.startswith("CALL ")
                    or sql_upper.startswith("EXEC ") or sql_upper.startswith("SELECT ")):
                return result
            return True
        except Exception as e:
            # Fail LOUD. Capture the cause on last_error for get_error(), then
            # re-raise — same contract as fetch()/_fetch_direct(). Returning
            # False here (the old behaviour) silently dropped failed writes.
            self.last_error = str(e)
            raise

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.execute_many(sql, params_list)

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0, no_cache: bool = False) -> DatabaseResult:
        """Fetch rows with pagination.

        v3.13.11 (issue #49 Gap 3): mirror :meth:`execute` and capture
        ``last_error`` here too — pre-v3.13.11 a failed ``fetch`` left
        ``db.get_error()`` returning ``None`` even though the adapter
        had stored the failure on its own ``last_error``. Callers had
        no way to read the cause via the public API.

        ``no_cache=True`` bypasses the query cache for this one call — no
        lookup and no store — and runs the query straight against the DB.
        Works in either cache mode (request-scoped auto-cache or persistent
        DB cache). The default (``False``) preserves today's behaviour.
        """
        if self._cache_enabled and not no_cache:
            key = self._cache_key(sql + f":L{limit}:S{offset}", params)
            cached = self._cache_get(key)
            if cached is not None:
                with self._cache_lock:
                    self._cache_hits += 1
                return cached
            result = self._fetch_direct(sql, params, limit, offset)
            self._cache_set(key, result)
            with self._cache_lock:
                self._cache_misses += 1
            return result
        return self._fetch_direct(sql, params, limit, offset)

    def _fetch_direct(self, sql: str, params: list, limit: int, offset: int) -> DatabaseResult:
        """Run a fetch straight against the adapter — no cache lookup or store.

        Shared by the cached and ``no_cache`` paths so error capture stays
        identical regardless of caching.

        FAIL LOUD: a SQL error in the adapter's ``fetch`` propagates (same
        contract as :meth:`execute`). The cause is captured on ``last_error``
        for :meth:`get_error` before the re-raise — preferring the adapter's
        own message (set in its error path) over the str() of the exception.
        """
        adapter = self._get_adapter()
        try:
            result = adapter.fetch(sql, params, limit, offset)
            self.last_error = None
            return result
        except Exception as e:
            self.last_error = getattr(adapter, "last_error", None) or str(e) or self.last_error
            raise

    def _fetch_one_direct(self, sql: str, params: list) -> dict | None:
        """Run a fetch_one straight against the adapter — no cache lookup/store.

        v3.13.37 (DB-contract A): ``fetch_one`` used to call the adapter
        directly, so a SQL error raised (good) but ``db.get_error()`` stayed
        ``None`` — the public API couldn't read the cause. Route every
        fetch_one through here so it FAILS LOUD *and* populates ``last_error``
        exactly like :meth:`execute` / :meth:`_fetch_direct`.
        """
        adapter = self._get_adapter()
        try:
            result = adapter.fetch_one(sql, params)
            self.last_error = None
            return result
        except Exception as e:
            self.last_error = getattr(adapter, "last_error", None) or str(e) or self.last_error
            raise

    def fetch_all(self, sql: str, params: list = None,
                  limit: int = 0, offset: int = 0, no_cache: bool = False) -> list[dict]:
        """Fetch ALL rows and return the records list directly.

        Symmetric with ``fetch_one``. For the common case where you just
        want the rows and don't need the ``DatabaseResult`` metadata
        (count, affected_rows, last_id, sql), this is one less attribute
        access than ``fetch(...).records``.

            rows = db.fetch_all("SELECT * FROM users WHERE active = ?", [1])
            for row in rows:
                print(row["name"])

        v3.13.12: default ``limit`` is **0** (no truncation) — the method
        name says ``fetch_all``, so it returns all matching rows. Pre-v3.13.12
        silently truncated to 100. Pass an explicit ``limit=N`` to cap.

        ``no_cache=True`` bypasses the query cache for this one call (see
        :meth:`fetch`). Returns ``[]`` (not ``None``) when no rows match.
        """
        return self.fetch(sql, params, limit, offset, no_cache=no_cache).records

    def fetch_one(self, sql: str, params: list = None, no_cache: bool = False) -> dict | None:
        """Fetch a single row as a dict, or ``None`` when no row matches.

        ``no_cache=True`` bypasses the query cache for this one call — no
        lookup and no store — and runs the query straight against the DB
        (see :meth:`fetch`). The default (``False``) preserves today's
        behaviour.
        """
        if self._cache_enabled and not no_cache:
            key = self._cache_key(sql + ":ONE", params)
            cached = self._cache_get(key)
            if cached is not None:
                with self._cache_lock:
                    self._cache_hits += 1
                return cached
            # _fetch_one_direct RAISES on a SQL error (and captures last_error),
            # so a failed read never reaches _cache_set below — we never cache a
            # null/empty produced by a buried failure.
            result = self._fetch_one_direct(sql, params)
            self._cache_set(key, result)
            with self._cache_lock:
                self._cache_misses += 1
            return result
        return self._fetch_one_direct(sql, params)

    def quote_identifier(self, name: str) -> str:
        """Quote a table/column name for THIS connection's dialect.

        Exposed so the ORM can build SQL that survives a reserved-word name
        (``table_name = "order"``) without knowing which driver is bound.
        """
        return self._get_adapter().quote_identifier(name)

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        result = adapter.insert(table, data)
        if result.last_id is not None:
            self._last_id = result.last_id
        return result

    def primary_key(self, table: str) -> list[str]:
        """The table's primary-key columns, introspected once and cached.

        Returns a LIST because a primary key may span several columns. A
        composite key is still one primary key; it just has more than one
        column. Returns ``[]`` when the table has no primary key or cannot be
        introspected.

        Uses the cross-engine ``get_columns()`` contract (v3.13.14, #48), which
        reports ``primary_key`` per column on every adapter.
        """
        if table not in self._pk_cache:
            try:
                columns = self._get_adapter().get_columns(table)
                self._pk_cache[table] = [
                    c["name"] for c in columns if c.get("primary_key")
                ]
            except Exception:  # noqa: BLE001 - a missing table is not an error here
                self._pk_cache[table] = []
        return self._pk_cache[table]

    def _as_where(self, filter_sql, params):
        """Normalise a filter to ``(sql, params)``, accepting a dict or a string.

        The declared type on ``delete`` has always been ``str | dict | list``, but
        only the base adapter honoured the dict and every engine overrides it, so a
        dict landed in the SQL string verbatim. Normalising here makes the declared
        type true for every engine at once.
        """
        if isinstance(filter_sql, dict):
            if not filter_sql:
                return "", []
            where = " AND ".join(
                f"{self.quote_identifier(k)} = ?" for k in filter_sql
            )
            return where, list(filter_sql.values())
        return filter_sql, params or []

    @staticmethod
    def _match_key_columns(table: str, key_columns: list, data: dict) -> tuple[dict, list]:
        """Map each introspected key column to the caller's own key for it.

        Returns ``({engine_column: caller_key}, [engine columns not in data])``.

        The engines disagree about identifier case BY DESIGN and always will:
        Firebird folds an unquoted identifier to UPPER, PostgreSQL folds it to
        LOWER, MySQL and SQLite preserve what was typed. Introspection therefore
        hands back the ENGINE's spelling while ``data`` carries whatever the
        caller typed, and comparing the two case-sensitively made a correct call
        fail on whichever engine folds the other way.

        That is a case-sensitivity bug, not a Firebird quirk - Firebird only
        made it visible first, because the shared write-path contract writes
        lower-case keys and Firebird reports upper-case ones. PostgreSQL has the
        mirror image for an upper-case caller key.

        Matching case-insensitively fixes both without naming either engine, and
        without lower-casing what introspection returns - which would special-case
        one engine and break a genuinely quoted mixed-case table, a real thing on
        Firebird.

        Ambiguity is refused rather than guessed: if ``data`` carries both ``id``
        and ``ID`` there is no defensible way to choose, and choosing wrong here
        writes the WHERE clause of an UPDATE.
        """
        resolved: dict = {}
        missing: list = []
        for column in key_columns:
            folded = column.lower()
            matches = [key for key in data if str(key).lower() == folded]
            if len(matches) > 1:
                raise ValueError(
                    f"update was given more than one key for the primary-key column "
                    f"{column!r}: {sorted(matches)!r} (table={table!r}). These differ "
                    f"only by case, so which one identifies the row is ambiguous - "
                    f"pass exactly one, or pass an explicit filter."
                )
            if matches:
                resolved[column] = matches[0]
            else:
                missing.append(column)
        return resolved, missing

    def update(self, table: str, data: dict,
               filter_sql: str | dict = "", params: list = None) -> DatabaseResult:
        """Update rows. A write with no filter is an error, not a full-table write.

        With no explicit filter, the primary key is taken out of ``data`` and used
        as the WHERE clause. With neither a filter nor a primary key in ``data``,
        this raises rather than overwriting every row (audit feature 4, P1).
        """
        filter_sql, params = self._as_where(filter_sql, params)

        if not filter_sql:
            pk_columns = self.primary_key(table)
            resolved, missing = self._match_key_columns(table, pk_columns, data)
            if not pk_columns or missing:
                raise ValueError(
                    f"update requires a filter or the complete primary key in the "
                    f"data; pass filter explicitly to update multiple rows "
                    f"(table={table!r}, primary key={pk_columns!r}, "
                    f"missing from data={missing!r}). "
                    f"To empty a table use truncate({table!r})."
                )
            # Every primary-key column becomes part of the WHERE clause. A
            # composite key that used only its first column would match every
            # row sharing that value - the data-loss bug this method exists to
            # prevent, reintroduced.
            #
            # The WHERE is built from the ENGINE's column name and the CALLER's
            # value, which is why the pop goes through `resolved`.
            data = dict(data)
            params = [data.pop(resolved[c]) for c in pk_columns]
            if not data:
                raise ValueError(
                    f"update was given only the primary key {pk_columns!r} and no "
                    f"columns to set (table={table!r})"
                )
            filter_sql = " AND ".join(
                f"{self.quote_identifier(c)} = ?" for c in pk_columns
            )

        if self._cache_enabled:
            self._cache_invalidate()
        result = self._get_adapter().update(table, data, filter_sql, params)
        return self._without_last_id(result)

    def delete(self, table: str,
               filter_sql: str | dict | list = "", params: list = None) -> DatabaseResult:
        """Delete rows. A filterless delete raises; use ``truncate()`` to empty."""
        if isinstance(filter_sql, list):
            total = 0
            for row_filter in filter_sql:
                total += self.delete(table, row_filter).affected_rows
            return DatabaseResult(affected_rows=total)

        filter_sql, params = self._as_where(filter_sql, params)
        if not filter_sql:
            raise ValueError(
                f"delete requires a filter (table={table!r}). "
                f"To remove every row use truncate({table!r})."
            )

        if self._cache_enabled:
            self._cache_invalidate()
        result = self._get_adapter().delete(table, filter_sql, params)
        return self._without_last_id(result)

    def truncate(self, table: str) -> DatabaseResult:
        """Remove every row. The explicit spelling of a whole-table delete."""
        if self._cache_enabled:
            self._cache_invalidate()
        result = self._get_adapter().delete(table, "1 = 1", [])
        return self._without_last_id(result)

    @staticmethod
    def _without_last_id(result: DatabaseResult) -> DatabaseResult:
        """``last_id`` is insert-only, per the documented contract.

        PHP already does this via ``writeResult($adapter, withLastId: false)``;
        Python reported the connection's last insert id on an UPDATE.
        """
        if result is not None and getattr(result, "last_id", None) is not None:
            result.last_id = None
        return result

    def start_transaction(self):
        """Begin a transaction. Pins the adapter to this thread for the
        whole transaction so executes and the final commit/rollback all
        run on the same connection.

        Nested-begin guard (v3.13.37, DB-contract C): a second
        ``start_transaction()`` on a thread that already has a pinned adapter
        is a double-begin — the inner BEGIN silently commits or no-ops on most
        engines, leaving the connection mid-transaction with the caller none
        the wiser. We keep a per-thread depth counter and log a clear warning
        instead of silently re-beginning. The pin is left on the original
        adapter so commit/rollback still land on the right connection.
        """
        pinned = getattr(self._tx_local, "adapter", None)
        if pinned is not None:
            depth = getattr(self._tx_local, "depth", 1)
            try:
                from tina4_python.debug import Log
                Log.warning(
                    "start_transaction() called while a transaction is already "
                    f"open on this thread (depth would become {depth + 1}). "
                    "Nested transactions are not supported — the existing "
                    "transaction stays open on its pinned connection and this "
                    "nested begin is ignored. Commit or rollback the outer "
                    "transaction first."
                )
            except Exception:
                pass
            self._tx_local.depth = depth + 1
            return
        adapter = self._get_adapter()
        self._tx_local.adapter = adapter
        self._tx_local.depth = 1
        adapter.start_transaction()

    def commit(self):
        """Commit the current transaction and release the adapter pin.

        FAIL LOUD (v3.13.37, DB-contract C): if the underlying commit raises,
        capture ``last_error`` and RE-RAISE — never swallow. On failure the
        transaction pin is RETAINED so the caller's follow-up ``rollback()``
        lands on the SAME connection (clearing it would leak a dirty connection
        back into the pool and route the rollback to a different one). The pin
        is cleared ONLY on a successful commit.
        """
        adapter = self._get_adapter()
        depth = getattr(self._tx_local, "depth", 0)
        if depth > 1:
            # Inner commit of an ignored nested begin — just unwind the depth.
            self._tx_local.depth = depth - 1
            return
        try:
            adapter.commit()
            self.last_error = None
        except Exception as e:
            # Keep the pin so rollback() reaches this same connection.
            self.last_error = str(e)
            raise
        # Success — release the pin.
        self._tx_local.adapter = None
        self._tx_local.depth = 0

    def rollback(self):
        """Roll back the current transaction and release the adapter pin.

        Rollback is the terminal cleanup of a transaction, so it ALWAYS clears
        the pin (and the depth counter) — even on a failed commit it routes to
        the retained pinned connection and cleans it up. If the underlying
        rollback itself raises, ``last_error`` is captured and the error
        re-raised, but the pin is still released so a poisoned connection
        doesn't stay pinned to this thread forever.
        """
        adapter = self._get_adapter()
        try:
            adapter.rollback()
            self.last_error = None
        except Exception as e:
            self.last_error = str(e)
            raise
        finally:
            # Terminal cleanup — always release the pin.
            self._tx_local.adapter = None
            self._tx_local.depth = 0

    def table_exists(self, name: str) -> bool:
        adapter = self._get_adapter()
        return adapter.table_exists(name)

    def get_tables(self) -> list[str]:
        adapter = self._get_adapter()
        return adapter.get_tables()

    def get_columns(self, table: str) -> list[dict]:
        adapter = self._get_adapter()
        return adapter.get_columns(table)

    def get_database_type(self) -> str:
        adapter = self._get_adapter()
        return adapter.get_database_type()

    @property
    def autocommit(self) -> bool:
        """Whether writes auto-commit. Off by default, set TINA4_AUTOCOMMIT=true to enable."""
        adapter = self._get_adapter()
        return adapter.autocommit

    @autocommit.setter
    def autocommit(self, value: bool):
        if self._pool is not None:
            # Set autocommit on all active pool connections
            with self._pool._lock:
                for a in self._pool._adapters:
                    if a is not None:
                        a.autocommit = value
        elif self._adapter is not None:
            self._adapter.autocommit = value

    def _ensure_sequence_table(self):
        """Create the tina4_sequences table if it doesn't exist."""
        if not self.table_exists("tina4_sequences"):
            engine = self.get_database_type()
            if engine == "mssql":
                self.execute(
                    "CREATE TABLE tina4_sequences ("
                    "seq_name VARCHAR(200) NOT NULL PRIMARY KEY, "
                    "current_value INTEGER NOT NULL DEFAULT 0)"
                )
            else:
                self.execute(
                    "CREATE TABLE IF NOT EXISTS tina4_sequences ("
                    "seq_name VARCHAR(200) NOT NULL PRIMARY KEY, "
                    "current_value INTEGER NOT NULL DEFAULT 0)"
                )
            self.commit()

    def _sequence_seed_value(self, adapter, table: str, pk_column: str) -> int:
        """Best-effort MAX(pk) seed for a new sequence row. 0 if table missing/empty."""
        if not table:
            return 0
        try:
            max_row = adapter.fetch_one(
                f"SELECT MAX({pk_column}) AS max_id FROM {table}"
            )
            if max_row and max_row.get("max_id") is not None:
                return int(max_row["max_id"])
        except Exception:
            pass  # Table doesn't exist — start at 0
        return 0

    def _sequence_next(self, seq_name: str, table: str = None, pk_column: str = "id") -> int:
        """Atomically increment and return the next value from tina4_sequences.

        v3.13.37 (DB-contract B): the old read-increment-read path had a race —
        two concurrent callers could read the same ``current_value`` and return
        the same id (duplicate primary keys). This now uses a single atomic
        increment-and-return per engine, pinned to ONE connection so the two
        statements (where two are needed) land on the same connection:

          * SQLite >= 3.35:  ``UPDATE ... SET current_value = current_value + 1
            WHERE seq_name = ? RETURNING current_value`` — one atomic statement.
            Older SQLite: wrap read+write in an IMMEDIATE write transaction so
            the increment is serialised under SQLite's write lock.
          * MySQL:  ``UPDATE ... SET current_value = LAST_INSERT_ID(current_value
            + 1) ...`` then ``SELECT LAST_INSERT_ID()`` on the SAME connection
            (LAST_INSERT_ID is per-connection → race-safe).
          * MSSQL:  ``UPDATE ... SET current_value += 1 OUTPUT
            inserted.current_value WHERE seq_name = ?`` — one atomic statement.

        Seeding the row is race-safe: an atomic insert-if-absent (ON CONFLICT /
        INSERT IGNORE / NOT EXISTS) seeded from MAX(pk) runs BEFORE the atomic
        increment, so there is never a read-then-insert gap. On error we RAISE
        (never silently fall back to 1).
        """
        engine = self.get_database_type()

        # Pin a single adapter for the whole sequence operation so the
        # seed + increment + read all hit the SAME connection. Inside an
        # active transaction the adapter is already pinned; otherwise we pin
        # here and release in the finally so the pool can rotate afterwards.
        already_pinned = getattr(self._tx_local, "adapter", None) is not None
        adapter = self._get_adapter()
        if not already_pinned:
            self._tx_local.adapter = adapter

        try:
            if engine == "sqlite":
                # SQLite does ensure-table + seed + increment all under the
                # adapter write lock (single shared connection — concurrent
                # reads/writes on it otherwise raise "API misuse").
                return self._sequence_next_sqlite(adapter, seq_name, table, pk_column)
            self._ensure_sequence_table()
            if engine == "mysql":
                return self._sequence_next_mysql(adapter, seq_name, table, pk_column)
            if engine == "mssql":
                return self._sequence_next_mssql(adapter, seq_name, table, pk_column)
            # Any other engine routed here (defensive) — generic atomic-ish path.
            return self._sequence_next_generic(adapter, seq_name, table, pk_column)
        finally:
            if not already_pinned:
                self._tx_local.adapter = None

    def _sequence_next_sqlite(self, adapter, seq_name: str, table: str, pk_column: str) -> int:
        import sqlite3
        conn = getattr(adapter, "_conn", None)
        if conn is None:
            raise RuntimeError("get_next_id: SQLite adapter has no live connection")

        # The ENTIRE op (ensure-table + seed read + increment) runs under the
        # adapter's process-wide write lock. In single-connection mode every
        # thread shares ONE sqlite3.Connection, so any concurrent .execute()
        # on it — even a read — raises "bad parameter or other API misuse".
        # Holding _write_lock for the whole op serialises every connection
        # touch, and on SQLite >= 3.35 the single UPDATE … RETURNING is itself
        # atomic, so the lock + that one statement are all the atomicity we
        # need — no duplicate ids under concurrency.
        with SQLiteAdapter._write_lock:
            # Ensure the sequence table exists (idempotent) on this connection.
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tina4_sequences'"
            ).fetchone()
            if not exists:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS tina4_sequences ("
                    "seq_name VARCHAR(200) NOT NULL PRIMARY KEY, "
                    "current_value INTEGER NOT NULL DEFAULT 0)"
                )
            seed = self._sequence_seed_value(adapter, table, pk_column)
            conn.execute(
                "INSERT OR IGNORE INTO tina4_sequences (seq_name, current_value) "
                "VALUES (?, ?)",
                [seq_name, seed],
            )
            if sqlite3.sqlite_version_info >= (3, 35, 0):
                # One atomic increment-and-return.
                row = conn.execute(
                    "UPDATE tina4_sequences SET current_value = current_value + 1 "
                    "WHERE seq_name = ? RETURNING current_value",
                    [seq_name],
                ).fetchone()
            else:
                # Older SQLite (< 3.35, no RETURNING): increment then read.
                # Still race-safe because we hold _write_lock across both, so
                # no other caller can read or write the counter in between.
                conn.execute(
                    "UPDATE tina4_sequences SET current_value = current_value + 1 "
                    "WHERE seq_name = ?",
                    [seq_name],
                )
                row = conn.execute(
                    "SELECT current_value FROM tina4_sequences WHERE seq_name = ?",
                    [seq_name],
                ).fetchone()
            # autocommit per statement (isolation_level=None) already persists
            # the increment; commit defensively if a txn is somehow open.
            if conn.in_transaction:
                conn.execute("COMMIT")
        if not row:
            raise RuntimeError(
                f"get_next_id: sequence row '{seq_name}' vanished mid-increment"
            )
        return int(row["current_value"])

    def _sequence_next_mysql(self, adapter, seq_name: str, table: str, pk_column: str) -> int:
        # Race-safe seed: INSERT IGNORE is a no-op if the row exists.
        seed = self._sequence_seed_value(adapter, table, pk_column)
        adapter.execute(
            "INSERT IGNORE INTO tina4_sequences (seq_name, current_value) "
            "VALUES (?, ?)",
            [seq_name, seed],
        )
        self.commit()
        # LAST_INSERT_ID(expr) stashes expr in this CONNECTION's session var
        # and returns it — atomic per-connection, no read-back race.
        adapter.execute(
            "UPDATE tina4_sequences "
            "SET current_value = LAST_INSERT_ID(current_value + 1) "
            "WHERE seq_name = ?",
            [seq_name],
        )
        self.commit()
        row = adapter.fetch_one("SELECT LAST_INSERT_ID() AS next_id")
        if not row:
            raise RuntimeError(
                f"get_next_id: LAST_INSERT_ID() returned nothing for '{seq_name}'"
            )
        return int(list(row.values())[0])

    def _sequence_next_mssql(self, adapter, seq_name: str, table: str, pk_column: str) -> int:
        # Race-safe seed: INSERT only when absent (single statement).
        seed = self._sequence_seed_value(adapter, table, pk_column)
        adapter.execute(
            "INSERT INTO tina4_sequences (seq_name, current_value) "
            "SELECT ?, ? WHERE NOT EXISTS "
            "(SELECT 1 FROM tina4_sequences WHERE seq_name = ?)",
            [seq_name, seed, seq_name],
        )
        self.commit()
        # Single atomic statement: increment + return the new value via OUTPUT.
        result = adapter.execute(
            "UPDATE tina4_sequences SET current_value = current_value + 1 "
            "OUTPUT inserted.current_value AS next_id WHERE seq_name = ?",
            [seq_name],
        )
        self.commit()
        records = getattr(result, "records", None)
        if records:
            return int(records[0]["next_id"])
        raise RuntimeError(
            f"get_next_id: OUTPUT produced no row for sequence '{seq_name}'"
        )

    def _sequence_next_generic(self, adapter, seq_name: str, table: str, pk_column: str) -> int:
        """Fallback atomic-ish path (read-then-insert avoided via best effort).

        Used only for engines not otherwise special-cased. Seeds if absent,
        then increments and reads on the pinned connection.
        """
        seed = self._sequence_seed_value(adapter, table, pk_column)
        try:
            adapter.execute(
                "INSERT INTO tina4_sequences (seq_name, current_value) VALUES (?, ?)",
                [seq_name, seed],
            )
            self.commit()
        except Exception:
            # Row likely already exists (PK conflict) — fine, keep going.
            self.rollback()
        adapter.execute(
            "UPDATE tina4_sequences SET current_value = current_value + 1 "
            "WHERE seq_name = ?",
            [seq_name],
        )
        self.commit()
        row = adapter.fetch_one(
            "SELECT current_value FROM tina4_sequences WHERE seq_name = ?",
            [seq_name],
        )
        if not row:
            raise RuntimeError(f"get_next_id: sequence row '{seq_name}' missing")
        return int(row["current_value"])

    def get_next_id(self, table: str, pk_column: str = "id", generator_name: str = None) -> int:
        """Get the next available ID for a table.

        Engine-specific strategies:
            - Firebird: uses GEN_ID(generator, 1) — atomic increment
            - PostgreSQL: uses nextval(sequence) — atomic increment;
              auto-creates sequence if missing
            - SQLite/MySQL/MSSQL: uses tina4_sequences table with atomic
              UPDATE + SELECT (race-safe, replaces old MAX+1)

        Args:
            table: Table name.
            pk_column: Primary key column name (default: "id").
            generator_name: Firebird generator, PostgreSQL sequence name,
                            or sequence table key override.

        Returns:
            The next integer ID.
        """
        engine = self.get_database_type()

        if engine == "firebird":
            gen_name = generator_name or f"GEN_{table.upper()}_ID"
            # Create generator if it doesn't exist
            try:
                self.execute(f"CREATE GENERATOR {gen_name}")
                self.commit()
            except Exception:
                pass  # Already exists
            row = self.fetch_one(
                f"SELECT GEN_ID({gen_name}, 1) AS next_id FROM RDB$DATABASE"
            )
            return int(row["next_id"]) if row else 1

        if engine == "postgresql":
            seq_name = generator_name or f"{table}_{pk_column}_seq"
            try:
                row = self.fetch_one(f"SELECT nextval('{seq_name}') AS next_id")
                if row and row.get("next_id") is not None:
                    return int(row["next_id"])
            except Exception:
                pass  # Sequence doesn't exist

            # Auto-create sequence seeded from MAX
            try:
                max_row = self.fetch_one(
                    f"SELECT COALESCE(MAX({pk_column}), 0) AS max_id FROM {table}"
                )
                start = int(max_row["max_id"]) + 1 if max_row else 1
                self.execute(f"CREATE SEQUENCE {seq_name} START WITH {start}")
                self.commit()
                row = self.fetch_one(f"SELECT nextval('{seq_name}') AS next_id")
                return int(row["next_id"]) if row else start
            except Exception:
                pass  # Fall through to sequence table

        # SQLite / MySQL / MSSQL / PostgreSQL fallback — atomic sequence table
        seq_key = generator_name or f"{table}.{pk_column}"
        return self._sequence_next(seq_key, table=table, pk_column=pk_column)

    def register_function(self, name: str, num_params: int, func: callable, deterministic: bool = True):
        """Register a custom SQL function (SQLite only).

        Usage:
            db.register_function("double", 1, lambda x: x * 2)
            db.fetch_one("SELECT double(5) as result")  # {"result": 10}
        """
        adapter = self._get_adapter()
        if hasattr(adapter, "register_function"):
            adapter.register_function(name, num_params, func, deterministic)
        else:
            raise NotImplementedError(
                f"{adapter.get_database_type()} does not support custom function registration"
            )

    @property
    def adapter(self) -> DatabaseAdapter:
        """Access the underlying adapter directly (for driver-specific ops).

        With pooling enabled, returns the next adapter from the pool via round-robin.
        """
        return self._get_adapter()

    @property
    def pool(self) -> ConnectionPool | None:
        """Access the connection pool (None if pooling is disabled)."""
        return self._pool

    # ── Factory methods ───────────────────────────────────────────

    @staticmethod
    def create(url: str, username: str = "", password: str = "", pool: int = 0) -> "Database":
        """Static factory — construct and return a Database instance.

        Equivalent to Database(url, username, password, pool=pool) but
        named consistently with the PHP and Node.js Tina4 frameworks.

        Args:
            url:      Connection URL (e.g. "sqlite:///data/app.db").
            username: Database username (optional, overrides env).
            password: Database password (optional, overrides env).
            pool:     Pool size — 0 for single connection, N>0 for N pooled connections.

        Returns:
            A new Database instance.
        """
        return Database(url, username=username, password=password, pool=pool)

    @staticmethod
    def from_env(env_key: str = "TINA4_DATABASE_URL", pool: int = 0) -> "Database | None":
        """Construct a Database instance from environment variables.

        Reads the connection URL from the named env var (default
        TINA4_DATABASE_URL), and TINA4_DATABASE_USERNAME /
        TINA4_DATABASE_PASSWORD for credentials.

        Args:
            env_key: Environment variable name holding the connection URL.
            pool:    Pool size — 0 for single connection, N>0 for N pooled connections.

        Returns:
            A new Database instance, or None if the env var is not set.
        """
        url = os.environ.get(env_key)
        if not url:
            return None
        username = os.environ.get("TINA4_DATABASE_USERNAME", "")
        password = os.environ.get("TINA4_DATABASE_PASSWORD", "")
        return Database(url, username=username, password=password, pool=pool)

    # ── Adapter / pool inspection ─────────────────────────────────

    def get_adapter(self) -> DatabaseAdapter:
        """Return the underlying driver/adapter object.

        With pooling enabled, returns the next adapter from the pool
        via round-robin (same as the internal _get_adapter()).
        Without pooling, returns the single connection adapter.
        """
        return self._get_adapter()

    def pool_size(self) -> int:
        """Return the total number of connections in the pool.

        Returns 1 when pooling is disabled (single-connection mode).
        """
        if self._pool is not None:
            return self._pool.size
        return 1

    def active_count(self) -> int:
        """Return the number of currently created (checked-out) connections.

        In pool mode, counts how many adapter slots have been lazily created.
        In single-connection mode, returns 1 if the adapter is connected, else 0.
        """
        if self._pool is not None:
            return self._pool.active_count
        return 1 if self._adapter is not None else 0

    def checkout(self) -> DatabaseAdapter:
        """Check out an adapter from the pool (round-robin).

        In single-connection mode, returns the single adapter directly.
        """
        if self._pool is not None:
            return self._pool.checkout()
        return self._adapter

    def checkin(self, adapter: DatabaseAdapter) -> None:
        """Return an adapter to the pool.

        In single-connection mode this is a no-op.
        In pool mode, delegates to ConnectionPool.checkin() (currently a no-op
        for round-robin pools, but provided for API consistency).
        """
        if self._pool is not None:
            self._pool.checkin(adapter)

    def close_all(self) -> None:
        """Close all connections — pool or single.

        After calling this, the Database instance should not be used.
        """
        self.close()
