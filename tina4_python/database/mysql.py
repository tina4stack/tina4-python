# Tina4 MySQL Driver — Uses mysql-connector-python (optional).
"""
MySQL/MariaDB adapter using mysql-connector-python.

    db = Database("mysql://user:pass@localhost:3306/mydb")

Requires: pip install mysql-connector-python
"""
import re
from urllib.parse import urlparse
from tina4_python.database.database_url import url_credentials
from tina4_python.database.adapter import (
    DatabaseAdapter, DatabaseResult, SQLTranslator,
    connect_deadline, driver_connect_timeout_seconds,
)


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

        # Percent-DECODED: urlparse leaves userinfo escaped.

        _url_user, _url_pass = url_credentials(connection_string, username, password)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3306

        # mysql-connector's own connection_timeout — the socket timeout it
        # applies while establishing the connection and reading the server
        # handshake, so a peer that accepts and then says nothing is bounded
        # too, not just an unroutable host.
        with connect_deadline(host, port) as timeout_seconds:
            timeout_option = driver_connect_timeout_seconds(timeout_seconds)
            if timeout_option is not None and "connection_timeout" not in kwargs:
                kwargs["connection_timeout"] = timeout_option
            self._conn = mysql.connector.connect(
                host=host,
                port=port,
                user=_url_user,
                password=_url_pass,
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
        # last. Normalise via the shared SQLTranslator.batch_last_id helper (the
        # one place that knows the first id and the row count) instead of
        # re-implementing the arithmetic inline (MYSQL-BATCH-ID-DUP).
        last_id = cursor.lastrowid
        if last_id:
            last_id = SQLTranslator.batch_last_id(last_id, cursor.rowcount or 1, "mysql")

        if returning_cols and last_id:
            # MySQL has no RETURNING: emulate it by re-selecting the inserted row
            # by the table's REAL primary key - never a hardcoded `id`
            # (MYSQL-RETURNING-ID). A model whose PK is not named `id` used to get
            # a wrong/empty returned row (SELECT ... WHERE id = ? raised "Unknown
            # column 'id'"). The identifier is strict-backtick-quoted (escaped),
            # not interpolated raw.
            table = self._unquote_ident(self._extract_table(sql))
            pk = self._returning_pk(table)
            if pk:
                cols = "*" if returning_cols.strip() == "*" else returning_cols
                fetch_sql = (
                    f"SELECT {cols} FROM {self._quote_mysql_ident(table)} "
                    f"WHERE {self._quote_mysql_ident(pk)} = %s"
                )
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
        # _has_trailing_limit: only SQLite deduped before, so SQL that already
        # carried its own LIMIT became `... LIMIT 3 LIMIT %s OFFSET %s` here --
        # a syntax error MEASURED on a live PostgreSQL. It worked on sqlite and
        # crashed on the server, which is the swap ADR-0024 exists to protect.
        if limit is None or limit <= 0 or self._has_trailing_limit(sql):
            paginated_sql = sql
            paginated_params = params or []
        else:
            paginated_sql = f"{sql}\nLIMIT %s OFFSET %s"
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
        # DESCRIBE takes an IDENTIFIER, not a bind parameter, so the table name
        # is made injection-safe by STRICT backtick-quoting (escaping embedded
        # backticks) rather than interpolated raw (MYSQL-DESCRIBE-UNPARAM). A
        # crafted/odd name becomes ONE escaped identifier - a clean "unknown
        # table", never runnable SQL - and an odd-but-valid name (reserved word,
        # special char) introspects correctly instead of a syntax error.
        sql = f"DESCRIBE {self._quote_mysql_ident(table)}"
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
        finally:
            cursor.close()
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

    @staticmethod
    def _unquote_ident(token: str) -> str:
        """Strip surrounding backticks (unescaping doubled ones) from a table
        token pulled out of a statement, so it can be re-introspected + re-quoted
        safely. ``INSERT INTO `t` ...`` yields the token ```t```; a raw
        ``INSERT INTO t ...`` yields ``t``."""
        t = (token or "").strip()
        if len(t) >= 2 and t[0] == "`" and t[-1] == "`":
            return t[1:-1].replace("``", "`")
        return t

    def _quote_mysql_ident(self, name: str) -> str:
        """Backtick-quote a (possibly schema-qualified) identifier, ESCAPING
        embedded backticks. DESCRIBE and the RETURNING re-select take an
        identifier, not a bind parameter; strict-quoting makes a crafted name
        one escaped identifier instead of interpolating it raw."""
        schema, table = self._split_schema(name)

        def q(part: str) -> str:
            return "`" + part.replace("`", "``") + "`"

        return q(table) if schema is None else f"{q(schema)}.{q(table)}"

    def _returning_pk(self, table: str) -> str | None:
        """The table's single PRIMARY KEY column, for RETURNING emulation.

        MySQL has no RETURNING, so the provider re-selects the inserted row by
        its REAL primary key - never a hardcoded ``id`` (MYSQL-RETURNING-ID).
        Introspected via :meth:`get_columns` and cached per table. Returns
        ``None`` when the table has no single-column PK (a composite or key-less
        table degrades to no re-select rather than a wrong one)."""
        cache = self.__dict__.setdefault("_returning_pk_cache", {})
        if table not in cache:
            try:
                pks = [c["name"] for c in self.get_columns(table) if c.get("primary_key")]
            except Exception:
                pks = []
            cache[table] = pks[0] if len(pks) == 1 else None
        return cache[table]

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
