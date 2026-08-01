# Tina4 ODBC Driver — Generic database access via pyodbc.
"""
ODBC adapter using pyodbc. Provides access to any ODBC-compatible database.

    db = Database("odbc:///DSN=MyDSN")
    db = Database("odbc:///DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=sa;PWD=pass")

Requires: pip install pyodbc
"""
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult


class ODBCAdapter(DatabaseAdapter):
    """Generic ODBC database driver using pyodbc."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._cursor = None

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect via ODBC.

        Connection string formats:
        - DSN-based: "DSN=MyDSN;UID=user;PWD=pass"
        - Driver-based: "DRIVER={ODBC Driver};SERVER=host;DATABASE=db;UID=user;PWD=pass"
        - URL form: "odbc:///DSN=MyDSN" (prefix stripped by Database class)
        """
        try:
            import pyodbc
        except ImportError:
            raise ImportError(
                "pyodbc is required for ODBC connections. Install one of:\n"
                "    uv add tina4-python[odbc]    # extra for projects using uv\n"
                "    pip install pyodbc           # bare driver\n"
                "    uv add tina4-python[all-db]  # all five database drivers"
            )

        # Strip URL prefix if present
        if connection_string.startswith("odbc:///"):
            connection_string = connection_string[8:]

        self._conn = pyodbc.connect(connection_string, autocommit=self._autocommit)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])

        records = []
        last_id = None

        # Try to get last inserted ID
        try:
            row = cursor.execute("SELECT @@IDENTITY AS id").fetchone()
            if row:
                last_id = row[0]
        except Exception:
            pass

        if not self._conn.autocommit and self._autocommit:
            self._conn.commit()

        return DatabaseResult(
            records=records,
            count=0,
            affected_rows=cursor.rowcount,
            last_id=last_id,
            sql=sql,
            adapter=self,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        # v3.13.12 parity: strip trailing `;` BEFORE any wrapping. This adapter
        # wraps the caller's SQL twice (count probe + pagination) and a trailing
        # semicolon breaks both — `SELECT COUNT(*) FROM (SELECT * FROM t;) AS _t`
        # is a syntax error, and so is `SELECT * FROM t; OFFSET ? ROWS ...`.
        sql = self._strip_trailing_semicolons(sql)

        # Count total. The closing paren goes on a NEW LINE: a trailing
        # `-- comment` in the caller's SQL otherwise comments it out, the probe
        # fails, the bare `except` below swallows it, and the result reports
        # count=0 alongside real records. Same fix already shipped in sqlite.py.
        count_sql = f"SELECT COUNT(*) FROM ({sql}\n) AS _t"
        cursor = self._conn.cursor()
        try:
            cursor.execute(count_sql, params or [])
            total = cursor.fetchone()[0]
        except Exception:
            total = 0

        # Apply pagination — ODBC gets the SQL Server style OFFSET/FETCH, with a
        # LIMIT/OFFSET fallback for the many non-SQL-Server ODBC sources.
        #
        # This adapter had NO already-paginated guard at all, so a caller who
        # wrote their own trailing LIMIT got a second clause appended on top of
        # it — a syntax error on BOTH paths (the OFFSET/FETCH attempt fails, the
        # fallback then appends `LIMIT ? OFFSET ?` after the caller's LIMIT and
        # fails too). `_has_trailing_limit` scrubs literals, quoted identifiers
        # and comments first and anchors to the end of the statement, so a column
        # named `rate_limit` or a `-- LIMIT 5` comment can neither defeat the cap
        # nor fake one. Same helper the sqlite/postgres/mysql adapters use, so
        # all engines answer the question identically.
        # limit <= 0 still means "no pagination" (fetch_all's give-me-everything).
        if limit is None or limit <= 0 or self._has_trailing_limit(sql):
            cursor.execute(sql, params or [])
        else:
            # The clause goes on a NEW LINE. Appended inline it lands INSIDE a
            # trailing `-- comment` and is silently swallowed — a bug at the
            # append site that survives even a perfect detector.
            try:
                cursor.execute(
                    f"{sql}\nOFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                    (params or []) + [offset, limit],
                )
            except Exception:
                # Fallback: try LIMIT/OFFSET for non-SQL Server ODBC sources
                cursor.execute(
                    f"{sql}\nLIMIT ? OFFSET ?",
                    (params or []) + [limit, offset],
                )

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def start_transaction(self):
        self._conn.autocommit = False

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def table_exists(self, name: str) -> bool:
        cursor = self._conn.cursor()
        tables = cursor.tables(table=name, tableType="TABLE").fetchall()
        return len(tables) > 0

    def get_tables(self) -> list[str]:
        cursor = self._conn.cursor()
        tables = cursor.tables(tableType="TABLE").fetchall()
        return [t.table_name for t in tables]

    def get_columns(self, table: str) -> list[dict]:
        cursor = self._conn.cursor()
        columns = cursor.columns(table=table).fetchall()
        return [
            {
                "name": col.column_name,
                "type": col.type_name,
                "nullable": col.nullable == 1,
                "default": col.column_def,
                "primary_key": False,  # Would need additional query
            }
            for col in columns
        ]

    def get_database_type(self) -> str:
        return "odbc"

    def _translate_sql(self, sql: str) -> str:
        """ODBC generally uses ? placeholders — minimal translation needed."""
        return sql
