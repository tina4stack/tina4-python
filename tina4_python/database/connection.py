# Tina4 Database Connection — Parse DATABASE_URL, auto-detect driver.
"""
The Database class parses a connection URL and creates the right adapter.

    db = Database("sqlite:///data/app.db")
    db = Database("postgresql://user:pass@host:5432/dbname")
    db = Database()  # Reads DATABASE_URL from environment
"""
import os
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


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

    def __init__(self, url: str = None, username: str = "", password: str = ""):
        self.url = url or os.environ.get("DATABASE_URL", "sqlite:///data/tina4.db")
        # Priority: constructor params > env vars > empty
        self.username = username or os.environ.get("DATABASE_USERNAME", "")
        self.password = password or os.environ.get("DATABASE_PASSWORD", "")
        self._adapter: DatabaseAdapter = self._create_adapter()
        self._adapter.connect(self._connection_path(), username=self.username, password=self.password)

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

    # Delegate everything to the adapter — clean and simple

    def close(self):
        self._adapter.close()

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        return self._adapter.execute(sql, params)

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        return self._adapter.execute_many(sql, params_list)

    def fetch(self, sql: str, params: list = None,
              limit: int = 20, skip: int = 0) -> DatabaseResult:
        return self._adapter.fetch(sql, params, limit, skip)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        return self._adapter.fetch_one(sql, params)

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        return self._adapter.insert(table, data)

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        return self._adapter.update(table, data, filter_sql, params)

    def delete(self, table: str,
               filter_sql: str | dict | list = "", params: list = None) -> DatabaseResult:
        return self._adapter.delete(table, filter_sql, params)

    def start_transaction(self):
        self._adapter.start_transaction()

    def commit(self):
        self._adapter.commit()

    def rollback(self):
        self._adapter.rollback()

    def table_exists(self, name: str) -> bool:
        return self._adapter.table_exists(name)

    def get_tables(self) -> list[str]:
        return self._adapter.get_tables()

    def get_columns(self, table: str) -> list[dict]:
        return self._adapter.get_columns(table)

    def get_database_type(self) -> str:
        return self._adapter.get_database_type()

    @property
    def autocommit(self) -> bool:
        """Whether writes auto-commit. Off by default, set TINA4_AUTOCOMMIT=true to enable."""
        return self._adapter.autocommit

    @autocommit.setter
    def autocommit(self, value: bool):
        self._adapter.autocommit = value

    def register_function(self, name: str, num_params: int, func: callable, deterministic: bool = True):
        """Register a custom SQL function (SQLite only).

        Usage:
            db.register_function("double", 1, lambda x: x * 2)
            db.fetch_one("SELECT double(5) as result")  # {"result": 10}
        """
        if hasattr(self._adapter, "register_function"):
            self._adapter.register_function(name, num_params, func, deterministic)
        else:
            raise NotImplementedError(
                f"{self._adapter.get_database_type()} does not support custom function registration"
            )

    @property
    def adapter(self) -> DatabaseAdapter:
        """Access the underlying adapter directly (for driver-specific ops)."""
        return self._adapter
