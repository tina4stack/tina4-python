# Tina4 ODBC Driver — Generic database access via pyodbc.
"""
ODBC adapter using pyodbc. Provides access to any ODBC-compatible database.

    db = Database("odbc:///DSN=MyDSN")
    db = Database("odbc:///DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=sa;PWD=pass")

Requires: pip install pyodbc
"""
import re

from tina4_python.database.adapter import (
    DatabaseAdapter, DatabaseResult, SqlCrudMixin,
    call_with_deadline, connect_deadline, driver_connect_timeout_seconds,
)


def _odbc_server_and_port(connection_string: str) -> tuple[str, str]:
    """The SERVER= endpoint of an ODBC connection string, for an error message.

    Returns ``(host, port)`` with the port split off a ``host,port`` or
    ``host:port`` SERVER value. Falls back to the DSN name, then a literal
    placeholder. Only ever reads SERVER= / DSN= — an ODBC connection string
    also carries UID= and PWD=, and none of it may reach an exception message.
    """
    server = re.search(r"(?:^|;)\s*SERVER\s*=\s*([^;]*)", connection_string, re.IGNORECASE)
    if server:
        endpoint = server.group(1).strip()
        # SQL Server writes host,port; most other drivers use host:port.
        host, separator, port = endpoint.partition(",")
        if not separator:
            host, separator, port = endpoint.partition(":")
        return host.strip() or "(odbc)", port.strip() or "(default)"
    dsn = re.search(r"(?:^|;)\s*DSN\s*=\s*([^;]*)", connection_string, re.IGNORECASE)
    if dsn and dsn.group(1).strip():
        return f"DSN={dsn.group(1).strip()}", "(dsn)"
    return "(odbc)", "(unknown)"


class ODBCAdapter(SqlCrudMixin, DatabaseAdapter):
    """Generic ODBC database driver using pyodbc."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._cursor = None
        # The connected DBMS name (SQL_DBMS_NAME), cached at connect. Drives the
        # driver-aware last-insert-id: @@IDENTITY is a SQL-Server-ism, not a
        # generic ODBC feature.
        self._dbms_name = ""

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect via ODBC.

        Connection string formats:
        - DSN-based: "DSN=MyDSN;UID=user;PWD=pass"
        - Driver-based: "DRIVER={ODBC Driver};SERVER=host;DATABASE=db;UID=user;PWD=pass"
        - URL form: "odbc:///DSN=MyDSN" (prefix stripped by Database class)

        ``username``/``password`` are honoured: ODBC has no separate-credentials
        API (pyodbc.connect() reads only the string), so when the caller passes
        them and the string does not already carry UID/PWD they are appended.
        This adapter used to ignore them, silently dropping the caller's creds.
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

        # Honour the credential params: append UID/PWD when given and not already
        # embedded in the string (case-insensitive check).
        if username and not re.search(r"(?:^|;)\s*UID\s*=", connection_string, re.IGNORECASE):
            connection_string += f";UID={username}"
        if password and not re.search(r"(?:^|;)\s*PWD\s*=", connection_string, re.IGNORECASE):
            connection_string += f";PWD={password}"

        # pyodbc's timeout= sets SQL_ATTR_LOGIN_TIMEOUT, the ODBC-standard login
        # bound — but whether it is honoured is up to whichever ODBC driver sits
        # underneath, and "ODBC" is not one implementation. pymssql's
        # login_timeout was MEASURED not to cover a peer that accepts and then
        # goes silent (see mssql.py), and there is no reason to assume every
        # ODBC driver does better. So the attribute is set AND the watchdog
        # backs it up, which makes the bound hold whatever driver is loaded.
        host, port = _odbc_server_and_port(connection_string)
        with connect_deadline(host, port) as timeout_seconds:
            timeout_option = driver_connect_timeout_seconds(timeout_seconds)
            login_timeout = {} if timeout_option is None else {"timeout": timeout_option}
            self._conn = call_with_deadline(
                lambda: pyodbc.connect(
                    connection_string, autocommit=self._autocommit, **login_timeout
                ),
                timeout_seconds,
            )

        # Cache the DBMS name so the last-insert-id path stays driver-aware.
        try:
            self._dbms_name = self._conn.getinfo(pyodbc.SQL_DBMS_NAME) or ""
        except Exception:
            self._dbms_name = ""

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])

        # The affected count of THIS statement, read BEFORE any secondary query:
        # a follow-up SELECT on the same cursor overwrites rowcount. The old code
        # read rowcount AFTER a `SELECT @@IDENTITY`, so the INSERT's real count
        # was lost (and on a non-SQL-Server target the failed SELECT left it -1).
        affected_rows = cursor.rowcount

        last_id = self._read_last_insert_id(cursor, sql)

        if not self._conn.autocommit and self._autocommit:
            self._conn.commit()

        return DatabaseResult(
            records=[],
            count=0,
            affected_rows=affected_rows,
            last_id=last_id,
            sql=sql,
            adapter=self,
        )

    def _read_last_insert_id(self, cursor, sql: str):
        """Best-effort last-insert-id, driver-aware.

        ``SELECT @@IDENTITY`` is a SQL-Server-ism, not a generic ODBC feature.
        Running it after EVERY statement (as this adapter used to) errored on any
        non-SQL-Server source and - because the failed SELECT ran on the same
        cursor - clobbered the INSERT's rowcount. It is now attempted ONLY after
        an INSERT and ONLY when the connected DBMS is SQL Server; every other
        target returns None (no generic last-insert-id exists - callers use
        RETURNING or an explicit key).
        """
        if not sql.lstrip().upper().startswith("INSERT"):
            return None
        if "SQL SERVER" not in (self._dbms_name or "").upper():
            return None
        try:
            row = cursor.execute("SELECT @@IDENTITY AS id").fetchone()
            return row[0] if row else None
        except Exception:
            return None

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
        # Real PK, from the ODBC catalog (SQLPrimaryKeys) - not the old `False`
        # stub. Feature 4's filterless-write guard reads primary_key, so without
        # this a PK-keyed `update(table, data)` on ODBC could not introspect the
        # key and threw.
        pk_columns = self._primary_key_columns(table)
        return [
            {
                "name": col.column_name,
                "type": col.type_name,
                "nullable": col.nullable == 1,
                "default": col.column_def,
                "primary_key": col.column_name.lower() in pk_columns,
            }
            for col in columns
        ]

    def _primary_key_columns(self, table: str) -> set:
        """The table's primary-key columns from the ODBC catalog (SQLPrimaryKeys),
        lower-cased for case-insensitive matching. Empty on any target that does
        not report them - the write-guard then requires an explicit filter."""
        try:
            cursor = self._conn.cursor()
            return {
                row.column_name.lower()
                for row in cursor.primaryKeys(table=table).fetchall()
            }
        except Exception:
            return set()

    def get_database_type(self) -> str:
        return "odbc"

    def _translate_sql(self, sql: str) -> str:
        """ODBC generally uses ? placeholders — minimal translation needed."""
        return sql
