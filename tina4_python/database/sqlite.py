# Tina4 SQLite Driver — Zero-config, stdlib only.
"""
SQLite adapter using Python's built-in sqlite3 module.
No external dependencies.
"""
import re
import sqlite3
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


class SQLiteAdapter(DatabaseAdapter):
    """SQLite database driver using Python stdlib."""

    def __init__(self):
        super().__init__()
        self._conn: sqlite3.Connection | None = None
        self._in_transaction: bool = False
        self._custom_functions: list[tuple] = []

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to SQLite database.

        Connection string: path to .db file (e.g., "data/app.db")
        """
        self._conn = sqlite3.connect(
            connection_string, check_same_thread=False,
            isolation_level=None,  # Manual transaction control
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # Re-register any custom functions on reconnect
        for name, num_params, func, det in self._custom_functions:
            self._conn.create_function(name, num_params, func, deterministic=det)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)

        # RETURNING emulation — SQLite 3.35+ supports RETURNING natively,
        # but for older versions and cross-engine compat, we emulate it.
        returning_match = None
        if "RETURNING" in sql.upper():
            import re
            returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
            if returning_match and not self._supports_returning():
                returning_cols = returning_match.group(1).strip()
                sql = sql[:returning_match.start()]

        cursor = self._conn.execute(sql, params or [])

        records = []
        if returning_match and not self._supports_returning():
            # Emulate RETURNING by fetching the last inserted/updated row
            if cursor.lastrowid:
                row = self._conn.execute(
                    f"SELECT {returning_cols} FROM {self._extract_table(sql)} WHERE rowid = ?",
                    [cursor.lastrowid],
                ).fetchone()
                if row:
                    records = [dict(row)]

        if not self._in_transaction and self.autocommit:
            if self._conn.in_transaction:
                self._conn.execute("COMMIT")

        return DatabaseResult(
            records=records,
            count=len(records),
            affected_rows=cursor.rowcount,
            last_id=cursor.lastrowid,
            sql=sql,
            adapter=self,
        )

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        """Optimized batch execute using SQLite's executemany."""
        sql = self._translate_sql(sql)
        cursor = self._conn.executemany(sql, params_list or [])

        if not self._in_transaction and self.autocommit:
            if self._conn.in_transaction:
                self._conn.execute("COMMIT")

        return DatabaseResult(
            affected_rows=cursor.rowcount,
            last_id=cursor.lastrowid,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        # Count total rows (without LIMIT/OFFSET)
        count_sql = f"SELECT COUNT(*) as cnt FROM ({sql})"
        try:
            total = self._conn.execute(count_sql, params or []).fetchone()["cnt"]
        except Exception:
            total = 0

        # Apply pagination — skip if SQL already has LIMIT
        if "LIMIT" in sql.upper().split("--")[0]:
            paginated_sql = sql
            paginated_params = params or []
        else:
            paginated_sql = f"{sql} LIMIT ? OFFSET ?"
            paginated_params = (params or []) + [limit, offset]
        cursor = self._conn.execute(paginated_sql, paginated_params)
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        cursor = self._conn.execute(sql, params or [])
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert(self, table: str, data: dict) -> DatabaseResult:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            sql += f" WHERE {filter_sql}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        sql = f"DELETE FROM {table}"
        if filter_sql:
            sql += f" WHERE {filter_sql}"
        return self.execute(sql, params or [])

    def start_transaction(self):
        self._conn.execute("BEGIN")
        self._in_transaction = True

    def commit(self):
        if self._conn.in_transaction:
            self._conn.execute("COMMIT")
        self._in_transaction = False

    def rollback(self):
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")
        self._in_transaction = False

    def table_exists(self, name: str) -> bool:
        row = self.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            [name]
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            limit=1000
        )
        return [r["name"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        cursor = self._conn.execute(f"PRAGMA table_info({table})")
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": not row["notnull"],
                "default": row["dflt_value"],
                "primary_key": bool(row["pk"]),
            }
            for row in cursor.fetchall()
        ]

    def get_database_type(self) -> str:
        return "sqlite"

    # ── SQL Translation ────────────────────────────────────────────

    def _translate_sql(self, sql: str) -> str:
        """SQLite needs minimal translation — it already uses ? and LIMIT."""
        return sql

    def _supports_returning(self) -> bool:
        """SQLite 3.35+ supports RETURNING natively."""
        return sqlite3.sqlite_version_info >= (3, 35, 0)

    # ── Custom Function Registration ──────────────────────────────

    def register_function(self, name: str, num_params: int, func: callable, deterministic: bool = True):
        """Register a Python function as a SQLite function.

        Once registered, the function is callable directly in SQL:
            db.adapter.register_function("double", 1, lambda x: x * 2)
            db.fetch_one("SELECT double(5) as result")  # → {"result": 10}

        Args:
            name: SQL function name
            num_params: Number of parameters (-1 for variadic)
            func: Python callable
            deterministic: If True, SQLite can cache results for same inputs
        """
        self._custom_functions.append((name, num_params, func, deterministic))
        if self._conn:
            self._conn.create_function(name, num_params, func, deterministic=deterministic)
