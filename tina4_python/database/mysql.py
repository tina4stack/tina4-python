# Tina4 MySQL Driver — Uses mysql-connector-python (optional).
"""
MySQL/MariaDB adapter using mysql-connector-python.

    db = Database("mysql://user:pass@localhost:3306/mydb")

Requires: pip install mysql-connector-python
"""
import re
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class MySQLAdapter(DatabaseAdapter):

    # The marker is the whole of what MySQL's CRUD used to justify overriding.
    PARAM_MARKER = "%s"
    #: MySQL quotes identifiers with backticks (ANSI_QUOTES is not the default).
    IDENTIFIER_QUOTE = ("`", "`")

    """MySQL/MariaDB database driver using mysql-connector-python."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to MySQL.

        Connection string: mysql://user:pass@host:port/dbname
        Credentials priority: URL > username/password params > adapter defaults.
        """
        try:
            import mysql.connector
        except ImportError:
            raise ImportError(
                "mysql-connector-python is required for MySQL connections. Install one of:\n"
                "    uv add tina4-python[mysql]            # extra for projects using uv\n"
                "    pip install mysql-connector-python    # bare driver\n"
                "    uv add tina4-python[all-db]           # all five database drivers"
            )

        parsed = urlparse(connection_string)
        self._conn = mysql.connector.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username or username or "",
            password=parsed.password or password or "",
            database=parsed.path.lstrip("/") if parsed.path else "",
            autocommit=False,
            **kwargs,
        )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)

        # MySQL does not support RETURNING — strip it and emulate
        returning_cols = None
        returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
        if returning_match:
            returning_cols = returning_match.group(1).strip()
            sql = sql[:returning_match.start()]

        cursor = self._conn.cursor(dictionary=True)
        cursor.execute(sql, params or [])

        records = []
        # MySQL reports the FIRST generated id of a MULTI-ROW INSERT, not the
        # last (verified live: a 3-row insert into a fresh table reports 1 while
        # MAX(id) is 3). Every other engine reports the last, and callers -
        # get_last_id(), ORM.save(), the batch DatabaseResult - all expect the
        # last. The ids in one statement are consecutive, so normalise here,
        # where both the first id and the row count are known; doing it further
        # up would leave get_last_id() disagreeing with the returned result.
        last_id = cursor.lastrowid
        if last_id:
            last_id = int(last_id) + max(int(cursor.rowcount or 1), 1) - 1

        if returning_cols and last_id:
            table = self._extract_table(sql)
            if returning_cols.strip() == "*":
                fetch_sql = f"SELECT * FROM {table} WHERE id = %s"
            else:
                fetch_sql = f"SELECT {returning_cols} FROM {table} WHERE id = %s"
            cursor.execute(fetch_sql, [last_id])
            row = cursor.fetchone()
            if row:
                records = [dict(row)]

        affected = cursor.rowcount if cursor.rowcount >= 0 else 0

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
        # v3.13.12: strip trailing `;` before wrapping with COUNT(*)
        # and appending LIMIT/OFFSET — see DatabaseAdapter helper.
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(dictionary=True)

        # Count total rows. The COUNT probe is best-effort — a failure here
        # defaults `total` to 0 — but it must NEVER mask a real failure in the
        # MAIN query. We use a fresh cursor for the probe so a probe failure
        # can't leave the main cursor in a half-consumed state, and the main
        # query below is deliberately NOT wrapped so its error FAILS LOUD
        # (parity with execute()) instead of looking like "no rows".
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) AS _count_subquery"
        probe = self._conn.cursor(dictionary=True)
        try:
            probe.execute(count_sql, params or [])
            total = probe.fetchone()["cnt"]
        except Exception:
            total = 0
        finally:
            try:
                probe.close()
            except Exception:
                pass

        # Apply pagination — v3.13.12: limit <= 0 means "no pagination"
        # (fetch_all's default — give me ALL rows).
        if limit is None or limit <= 0:
            paginated_sql = sql
            paginated_params = params or []
        else:
            paginated_sql = f"{sql} LIMIT %s OFFSET %s"
            paginated_params = (params or []) + [limit, offset]
        cursor.execute(paginated_sql, paginated_params)  # FAILS LOUD
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._strip_trailing_semicolons(sql)
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(dictionary=True)
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        return dict(row) if row else None

    def start_transaction(self):
        self._conn.start_transaction()
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
        # v3.13.14 (#48): honour a database-qualified name ("otherdb.table").
        # In MySQL "schema" == database; default to the connected database.
        # Pre-fix this matched the whole dotted string as a flat TABLE_NAME
        # under DATABASE() only, so a cross-database qualified name was never
        # found and create_table()/migrations misfired.
        schema, tbl = self._split_schema(name)
        row = self.fetch_one(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = COALESCE(%s, DATABASE()) AND TABLE_NAME = %s",
            [schema, tbl],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME",
            limit=10000,
        )
        return [r["TABLE_NAME"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        sql = "DESCRIBE " + table
        cursor = self._conn.cursor(dictionary=True)
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [
            {
                "name": r["Field"],
                "type": r["Type"],
                "nullable": r["Null"] == "YES",
                "default": r["Default"],
                "primary_key": r["Key"] == "PRI",
            }
            for r in rows
        ]

    def get_database_type(self) -> str:
        return "mysql"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to MySQL dialect.

        MySQL uses %s placeholders, CONCAT() instead of ||,
        AUTO_INCREMENT, and ILIKE must be lowered.
        """
        sql = SQLTranslator.placeholder_style(sql, "%s")
        sql = SQLTranslator.concat_pipes_to_func(sql)
        sql = SQLTranslator.ilike_to_like(sql)
        sql = SQLTranslator.auto_increment_syntax(sql, "mysql")
        return sql

    def _supports_returning(self) -> bool:
        return False
