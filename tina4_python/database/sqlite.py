# Tina4 SQLite Driver — Zero-config, stdlib only.
"""
SQLite adapter using Python's built-in sqlite3 module.
No external dependencies.
"""
import datetime
import re
import sqlite3
import threading
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


# ── Explicit datetime/date adapters (Python 3.12+ deprecation) ─────────
# Python's built-in default sqlite3 datetime/date adapters were deprecated
# in 3.12 (`DeprecationWarning: The default datetime adapter is deprecated`)
# and will be removed in a future release — which would break DateTimeField
# writes on SQLite, since ORM.save() binds a real `datetime` straight through
# to the driver. The framework owns the conversion explicitly instead of
# relying on the soon-to-vanish built-ins.
#
# We store ISO-8601 text: a space separator for datetimes (matching the
# historic default so existing rows AND the ORM read path via
# `datetime.fromisoformat` — see orm/fields.py:Field.validate — still
# round-trip unchanged), and plain ISO for dates. Reads come back as ISO
# strings because connect() deliberately does NOT pass `detect_types`, so no
# converter is registered and no round-trip parsing happens at the driver.
#
# `register_adapter` merely sets a process-global dict entry, so registering
# at module import is idempotent (a re-import is a no-op) and runs once.
sqlite3.register_adapter(datetime.datetime, lambda value: value.isoformat(sep=" "))
sqlite3.register_adapter(datetime.date, lambda value: value.isoformat())


class SQLiteAdapter(DatabaseAdapter):
    """SQLite database driver using Python stdlib."""

    # Class-level write lock shared across all SQLiteAdapter instances in the
    # process.  SQLite's WAL mode allows concurrent readers, but concurrent
    # writers from different threads (or asyncio tasks on the same thread) will
    # get SQLITE_BUSY.  This lock serialises all writes so the busy_timeout is
    # a last-resort safety net rather than the primary protection.
    _write_lock: threading.Lock = threading.Lock()

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
            connection_string,
            check_same_thread=False,
            isolation_level=None,   # Manual transaction control
            timeout=30,             # sqlite3 module-level lock wait (seconds)
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 30000")  # SQLite-level wait (ms)
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
        returning_cols = None
        if "RETURNING" in sql.upper():
            returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
            if returning_match and not self._supports_returning():
                returning_cols = returning_match.group(1).strip()
                sql = sql[:returning_match.start()]

        # Serialise writes to prevent SQLITE_BUSY / deadlock when multiple
        # threads or asyncio tasks write concurrently (common in dev server).
        with self._write_lock:
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
        """Optimized batch execute using SQLite's executemany — ATOMIC (one txn).

        The batch runs inside one transaction so a bad row mid-batch rolls the
        WHOLE batch back (all-or-nothing) instead of leaving the rows applied
        before the failure in an open, uncommitted transaction. Mirrors the base
        DatabaseAdapter.execute_many owns-transaction guard and the other engines.
        """
        sql = self._translate_sql(sql)
        rows = params_list or []

        # Own (and commit/rollback) the batch transaction only for a standalone
        # write in autocommit mode — never inside a caller's explicit transaction.
        standalone = self.autocommit and not self._in_transaction
        if standalone and not self._conn.in_transaction:
            self._conn.execute("BEGIN")

        try:
            self._conn.executemany(sql, rows)
            # cursor.rowcount / cursor.lastrowid are unreliable after executemany()
            # in sqlite3 (rowcount can come back 0 or -1, lastrowid is not set).
            # The batch is all-or-nothing, so every supplied row was applied; read
            # the last inserted id deterministically from last_insert_rowid().
            affected = len(rows)
            last_row = self._conn.execute("SELECT last_insert_rowid()").fetchone()
            last_id = last_row[0] if last_row and last_row[0] else None
        except Exception:
            # Roll the partial batch back so nothing is left half-applied, then
            # FAIL LOUD (re-raise) — parity with execute() and the other engines.
            if standalone and self._conn.in_transaction:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise

        if standalone and self._conn.in_transaction:
            self._conn.execute("COMMIT")

        return DatabaseResult(
            affected_rows=affected,
            last_id=last_id,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        # v3.13.12: strip trailing `;` before wrapping — see DatabaseAdapter.
        sql = self._strip_trailing_semicolons(sql)
        # Count total rows (without LIMIT/OFFSET). The COUNT probe is
        # best-effort — a failure here defaults `total` to 0 — but it must
        # NEVER mask a real failure in the MAIN query below. The main query
        # is deliberately NOT wrapped in try/except so its error FAILS LOUD
        # (parity with execute()). A typo'd query then raises, instead of the
        # old behaviour where a buried probe error made it look like "no rows".
        count_sql = f"SELECT COUNT(*) as cnt FROM ({sql})"
        try:
            total = self._conn.execute(count_sql, params or []).fetchone()["cnt"]
        except Exception:
            total = 0

        # Apply pagination — skip if SQL already has LIMIT, or if
        # limit <= 0 (v3.13.12: fetch_all's "give me all rows" path).
        if limit is None or limit <= 0:
            paginated_sql = sql
            paginated_params = params or []
        elif "LIMIT" in sql.upper().split("--")[0]:
            paginated_sql = sql
            paginated_params = params or []
        else:
            paginated_sql = f"{sql} LIMIT ? OFFSET ?"
            paginated_params = (params or []) + [limit, offset]
        cursor = self._conn.execute(paginated_sql, paginated_params)  # FAILS LOUD
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._strip_trailing_semicolons(sql)
        cursor = self._conn.execute(sql, params or [])
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        # A list of dicts is a batch insert — delegate to the base class, which
        # builds one parameterised INSERT and runs it per row via execute_many.
        # (Database.insert / the docs advertise ``data: dict | list``; without
        # this branch a list crashed with ``'list' object has no attribute
        # 'keys'`` because this override only handled the single-dict case.)
        if isinstance(data, list):
            return super().insert(table, data)
        columns = ", ".join(self.quote_identifier(c) for c in data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {self.quote_identifier(table)} ({columns}) VALUES ({placeholders})"
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        set_clause = ", ".join(f"{self.quote_identifier(k)} = ?" for k in data.keys())
        sql = f"UPDATE {self.quote_identifier(table)} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            sql += f" WHERE {filter_sql}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        sql = f"DELETE FROM {self.quote_identifier(table)}"
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
        # v3.13.14 (#48): honour an attached-database prefix ("attached.table").
        # SQLite's "schema" is an ATTACH alias; each has its own sqlite_master.
        # Bare names use the main database (unchanged). The alias must be a
        # plain identifier (it's developer-supplied, but guard against the dot
        # being part of an odd name).
        schema, tbl = self._split_schema(name)
        master = f"{schema}.sqlite_master" if schema and schema.isidentifier() else "sqlite_master"
        row = self.fetch_one(
            f"SELECT name FROM {master} WHERE type='table' AND name=?",
            [tbl if (schema and schema.isidentifier()) else name]
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            limit=1000
        )
        return [r["name"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        # v3.13.14 (#48): honour an attached-database prefix via
        # `PRAGMA <schema>.table_info(<table>)`.
        schema, tbl = self._split_schema(table)
        if schema and schema.isidentifier() and tbl.isidentifier():
            cursor = self._conn.execute(f"PRAGMA {schema}.table_info({tbl})")
        else:
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
