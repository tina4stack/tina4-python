# Tina4 MSSQL Driver — Uses pymssql (optional).
"""
Microsoft SQL Server adapter using pymssql.

    db = Database("mssql://user:pass@localhost:1433/mydb")

Requires: pip install pymssql
"""
import re
from urllib.parse import urlparse
from tina4_python.database.database_url import url_credentials
from tina4_python.database.adapter import (
    DatabaseAdapter, DatabaseResult, SQLTranslator,
    call_with_deadline, connect_deadline, driver_connect_timeout_seconds,
)


class MSSQLAdapter(DatabaseAdapter):

    # The marker is the whole of what MSSQL's CRUD used to justify overriding.
    PARAM_MARKER = "%s"
    #: SQL Server uses bracketed identifiers.
    IDENTIFIER_QUOTE = ("[", "]")

    """Microsoft SQL Server database driver using pymssql."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to MSSQL.

        Connection string: mssql://user:pass@host:port/dbname
        Credentials priority: URL > username/password params > adapter defaults.
        """
        try:
            import pymssql
        except ImportError:
            raise ImportError(
                "pymssql is required for MSSQL connections. Install one of:\n"
                "    uv add tina4-python[mssql]    # extra for projects using uv\n"
                "    pip install pymssql           # bare driver\n"
                "    uv add tina4-python[all-db]   # all five database drivers"
            )

        parsed = urlparse(connection_string)

        # Percent-DECODED: urlparse leaves userinfo escaped.

        _url_user, _url_pass = url_credentials(connection_string, username, password)
        host = parsed.hostname or "localhost"
        port = parsed.port or 1433

        # pymssql's login_timeout is NOT sufficient on its own. MEASURED against
        # a server that accepts the TCP connection and then never replies
        # (Ubuntu 24.04, pymssql 2.3.13): login_timeout=2, timeout=2, and both
        # together ALL failed to return — killed at 25s. FreeTDS applies
        # login_timeout to establishing the connection, and a black-holed peer
        # gets past that and then wedges waiting for the login response.
        #
        # So both mechanisms are used: login_timeout still tightens the driver's
        # own 60s default and lets it abort cleanly when it can, and the
        # watchdog is what actually guarantees the bound.
        with connect_deadline(host, port) as timeout_seconds:
            timeout_option = driver_connect_timeout_seconds(timeout_seconds)
            if timeout_option is not None and "login_timeout" not in kwargs:
                kwargs["login_timeout"] = timeout_option
            self._conn = call_with_deadline(
                lambda: pymssql.connect(
                    server=host,
                    port=str(port),
                    user=_url_user,
                    password=_url_pass,
                    database=parsed.path.lstrip("/") if parsed.path else "",
                    autocommit=False,
                    **kwargs,
                ),
                timeout_seconds,
            )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)

        # MSSQL does not support RETURNING — strip and emulate
        returning_cols = None
        returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
        if returning_match:
            returning_cols = returning_match.group(1).strip()
            sql = sql[:returning_match.start()]

        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(sql, tuple(params) if params else ())

        # Capture the affected-row count from the MAIN statement NOW, before any
        # follow-up SELECT (SCOPE_IDENTITY / RETURNING fetch) runs on the SAME
        # cursor and overwrites cursor.rowcount. Reading it at the end reflected
        # the SCOPE_IDENTITY SELECT instead of the INSERT, so every INSERT
        # reported affected_rows=0 (a batch insert summed to 0 even though the
        # rows landed — surfaced by the live MySQL/MSSQL batch test).
        affected = cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0

        records = []
        last_id = None

        # Get last inserted ID for INSERT statements
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT"):
            try:
                cursor.execute("SELECT SCOPE_IDENTITY() AS id")
                row = cursor.fetchone()
                if row and row.get("id") is not None:
                    last_id = int(row["id"])
            except Exception:
                pass

        if returning_cols and last_id:
            table = self._extract_table(sql)
            if returning_cols.strip() == "*":
                fetch_sql = f"SELECT * FROM {table} WHERE id = %s"
            else:
                fetch_sql = f"SELECT {returning_cols} FROM {table} WHERE id = %s"
            cursor.execute(fetch_sql, (last_id,))
            row = cursor.fetchone()
            if row:
                records = [dict(row)]

        if not self._in_transaction and self.autocommit:
            self._conn.commit()

        return DatabaseResult(
            records=records,
            count=len(records),
            affected_rows=affected,
            last_id=last_id,
            sql=sql,
            adapter=self,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        # v3.13.12: strip trailing `;` — see DatabaseAdapter helper.
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(as_dict=True)

        # Count total rows. The COUNT probe is best-effort — a failure here
        # defaults `total` to 0 — but it must NEVER mask a real failure in the
        # MAIN query. We probe on a fresh cursor so a probe failure can't leave
        # the main cursor half-consumed, and the main query below is
        # deliberately NOT wrapped so its error FAILS LOUD (parity with
        # execute()) instead of looking like "no rows".
        # Strip a trailing top-level ORDER BY before wrapping: SQL Server rejects
        # ORDER BY in a derived-table subquery without TOP/OFFSET/FETCH (#262),
        # which otherwise zeroed the count for any query ending in ORDER BY. The
        # paginated query below keeps its ORDER BY.
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({self._strip_trailing_order_by(sql)}) AS _count_subquery"
        probe = self._conn.cursor(as_dict=True)
        try:
            probe.execute(count_sql, tuple(params) if params else ())
            total = probe.fetchone()["cnt"]
        except Exception:
            total = 0
        finally:
            try:
                probe.close()
            except Exception:
                pass

        # Apply pagination — MSSQL uses OFFSET/FETCH.
        # v3.13.12: limit <= 0 means "no pagination" (fetch_all's
        # default — give me ALL rows).
        if limit is None or limit <= 0:
            paginated_sql = sql
            paginated_params = tuple(params or [])
        else:
            # OFFSET/FETCH requires an ORDER BY; if none exists, add a default
            if not re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
                paginated_sql = f"{sql} ORDER BY (SELECT NULL) OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
            else:
                paginated_sql = f"{sql} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
            paginated_params = tuple(params or []) + (offset, limit)
        cursor.execute(paginated_sql, paginated_params)
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(sql, tuple(params) if params else ())
        row = cursor.fetchone()
        return dict(row) if row else None

    def start_transaction(self):
        """Begin a transaction.

        Do NOT issue a raw "BEGIN TRANSACTION". pymssql is connected with
        ``autocommit=False``, so the driver ALREADY holds an open transaction -
        a raw BEGIN nests a second one and @@TRANCOUNT becomes 2. ``commit()``
        below calls the driver's commit, which emits ONE ``COMMIT``, taking
        @@TRANCOUNT 2 -> 1: the transaction stays open and keeps its locks
        while the connection goes idle. The write is visible on its own
        connection, so nothing looks wrong locally, but every OTHER connection
        that touches those rows blocks indefinitely (observed as a sleeping
        session with open_transaction_count = 2 blocking a SELECT on LCK_M_S).
        PHP, Ruby and Node all keep BEGIN/COMMIT balanced; Python was the
        outlier.

        Suppressing the per-statement autocommit in ``execute()`` is what makes
        the following statements one transaction - no SQL is needed here.
        """
        self._in_transaction = True

    def commit(self):
        if self._conn:
            self._conn.commit()
        self._in_transaction = False

    def rollback(self):
        if self._conn:
            self._conn.rollback()
        self._in_transaction = False

    def table_exists(self, name: str) -> bool:
        # v3.13.14 (#48): honour a schema-qualified name ("dbo.widget",
        # "sales.orders"). Schemas are everyday in SQL Server; pre-fix this
        # had no schema filter and matched the whole dotted string as a flat
        # TABLE_NAME, so any qualified table_name was invisible. A bare name
        # still matches in any schema (unchanged behaviour).
        schema, tbl = self._split_schema(name)
        row = self.fetch_one(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME = %s "
            "AND (%s IS NULL OR TABLE_SCHEMA = %s)",
            [tbl, schema, schema],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME",
            limit=10000,
        )
        return [r["TABLE_NAME"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        # v3.13.14 (#48): honour a schema-qualified name; a bare name matches
        # in any schema (unchanged).
        schema, tbl = self._split_schema(table)
        sql = """
            SELECT c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                   CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_primary
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                  ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.TABLE_NAME = %s AND (%s IS NULL OR tc.TABLE_SCHEMA = %s)
                  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
            WHERE c.TABLE_NAME = %s AND (%s IS NULL OR c.TABLE_SCHEMA = %s)
            ORDER BY c.ORDINAL_POSITION
        """
        result = self.fetch(sql, [tbl, schema, schema, tbl, schema, schema], limit=10000)
        return [
            {
                "name": r["COLUMN_NAME"],
                "type": r["DATA_TYPE"],
                "nullable": r["IS_NULLABLE"] == "YES",
                "default": r["COLUMN_DEFAULT"],
                "primary_key": bool(r["is_primary"]),
            }
            for r in result.records
        ]

    def get_database_type(self) -> str:
        return "mssql"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to MSSQL dialect.

        MSSQL uses %s placeholders (pymssql), CONCAT() instead of ||,
        TOP instead of LIMIT, IDENTITY instead of AUTOINCREMENT,
        and no ILIKE.
        """
        sql = SQLTranslator.placeholder_style(sql, "%s")
        sql = SQLTranslator.concat_pipes_to_func(sql)
        sql = SQLTranslator.ilike_to_like(sql)
        sql = SQLTranslator.auto_increment_syntax(sql, "mssql")
        sql = SQLTranslator.boolean_to_int(sql)
        return sql

    def _supports_returning(self) -> bool:
        return False
