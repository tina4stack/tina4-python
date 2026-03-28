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
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


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
            adapter.connect(self._connect_path, username=self._username, password=self._password, **self._connect_kwargs)
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


class Database:
    """Database connection manager.

    Parses DATABASE_URL, selects the right driver, and delegates all
    operations to the adapter. This is what the rest of the framework uses.
    """

    def __init__(self, url: str = None, username: str = "", password: str = "", pool: int = 0, **kwargs):
        self.url = url or os.environ.get("DATABASE_URL", "sqlite:///data/tina4.db")
        # Priority: constructor params > env vars > empty
        self.username = username or os.environ.get("DATABASE_USERNAME", "")
        self.password = password or os.environ.get("DATABASE_PASSWORD", "")
        self.pool_size = pool  # 0 = single connection, N>0 = N pooled connections
        self._connect_kwargs = kwargs  # Extra kwargs passed through to adapter.connect()

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
            self._adapter.connect(self._connection_path(), username=self.username, password=self.password, **kwargs)

        # Query cache — off by default, opt-in via TINA4_DB_CACHE=true
        from tina4_python.dotenv import is_truthy
        self._cache_enabled: bool = is_truthy(os.environ.get("TINA4_DB_CACHE", "false"))
        self._cache_ttl: int = int(os.environ.get("TINA4_DB_CACHE_TTL", "30"))
        self._query_cache: dict[str, tuple[float, object]] = {}  # key -> (expires_at, result)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._cache_lock = threading.Lock()

    def _create_adapter(self) -> DatabaseAdapter:
        """Select adapter based on URL scheme."""
        parsed = urlparse(self.url)
        scheme = parsed.scheme.lower()

        # Handle sqlite:///path (three slashes = absolute, two = relative)
        if scheme.startswith("sqlite"):
            scheme = "sqlite"

        if scheme not in _DRIVERS:
            available = ", ".join(_DRIVERS.keys())
            raise ValueError(
                f"Unknown database driver '{scheme}'. "
                f"Available: {available}. "
                f"Install the driver package and it will register automatically."
            )

        return _DRIVERS[scheme]()

    def _connection_path(self) -> str:
        """Extract connection-specific path/params from the URL."""
        parsed = urlparse(self.url)

        if parsed.scheme.startswith("sqlite"):
            # sqlite:///data/app.db → data/app.db
            # sqlite:////absolute/path.db → /absolute/path.db
            path = parsed.path
            if path.startswith("/"):
                path = path[1:]  # Remove leading slash for relative paths

            # Ensure directory exists
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            return path

        # For other drivers, return the full URL (adapter parses it)
        return self.url

    # ── Query Cache ──────────────────────────────────────────────

    @staticmethod
    def _cache_key(sql: str, params) -> str:
        """Generate a cache key from SQL + params."""
        raw = sql + str(params or [])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str):
        """Return cached result or None if miss/expired."""
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
        with self._cache_lock:
            self._query_cache[key] = (time.monotonic() + self._cache_ttl, result)

    def _cache_invalidate(self):
        """Clear the entire query cache (called on writes)."""
        with self._cache_lock:
            self._query_cache.clear()

    def cache_stats(self) -> dict:
        """Return query cache statistics."""
        with self._cache_lock:
            return {
                "enabled": self._cache_enabled,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": len(self._query_cache),
                "ttl": self._cache_ttl,
            }

    def cache_clear(self):
        """Flush the query cache and reset counters."""
        with self._cache_lock:
            self._query_cache.clear()
            self._cache_hits = 0
            self._cache_misses = 0

    # ── Pool-aware adapter access ─────────────────────────────

    def _get_adapter(self) -> DatabaseAdapter:
        """Get an adapter — from pool (round-robin) or single connection."""
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

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.execute(sql, params)

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.execute_many(sql, params_list)

    def fetch(self, sql: str, params: list = None,
              limit: int = 20, offset: int = 0) -> DatabaseResult:
        """Fetch rows with pagination."""
        if self._cache_enabled:
            key = self._cache_key(sql + f":L{limit}:S{offset}", params)
            cached = self._cache_get(key)
            if cached is not None:
                with self._cache_lock:
                    self._cache_hits += 1
                return cached
            adapter = self._get_adapter()
            result = adapter.fetch(sql, params, limit, offset)
            self._cache_set(key, result)
            with self._cache_lock:
                self._cache_misses += 1
            return result
        adapter = self._get_adapter()
        return adapter.fetch(sql, params, limit, offset)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        if self._cache_enabled:
            key = self._cache_key(sql + ":ONE", params)
            cached = self._cache_get(key)
            if cached is not None:
                with self._cache_lock:
                    self._cache_hits += 1
                return cached
            adapter = self._get_adapter()
            result = adapter.fetch_one(sql, params)
            self._cache_set(key, result)
            with self._cache_lock:
                self._cache_misses += 1
            return result
        adapter = self._get_adapter()
        return adapter.fetch_one(sql, params)

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.insert(table, data)

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.update(table, data, filter_sql, params)

    def delete(self, table: str,
               filter_sql: str | dict | list = "", params: list = None) -> DatabaseResult:
        if self._cache_enabled:
            self._cache_invalidate()
        adapter = self._get_adapter()
        return adapter.delete(table, filter_sql, params)

    def start_transaction(self):
        adapter = self._get_adapter()
        adapter.start_transaction()

    def commit(self):
        adapter = self._get_adapter()
        adapter.commit()

    def rollback(self):
        adapter = self._get_adapter()
        adapter.rollback()

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
