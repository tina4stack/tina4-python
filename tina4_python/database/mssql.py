# Tina4 MSSQL Driver — Uses pymssql (optional).
"""
Microsoft SQL Server adapter using pymssql.

    db = Database("mssql://user:pass@localhost:1433/mydb")

Requires: pip install pymssql
"""
import re
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class MSSQLAdapter(DatabaseAdapter):
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
                "pymssql is required for MSSQL connections. "
                "Install: pip install pymssql"
            )

        parsed = urlparse(connection_string)
        self._conn = pymssql.connect(
            server=parsed.hostname or "localhost",
            port=str(parsed.port or 1433),
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

        # MSSQL does not support RETURNING — strip and emulate
        returning_cols = None
        returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
        if returning_match:
            returning_cols = returning_match.group(1).strip()
            sql = sql[:returning_match.start()]

        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(sql, tuple(params) if params else ())

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
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(as_dict=True)

        # Count total rows
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) AS _count_subquery"
        try:
            cursor.execute(count_sql, tuple(params) if params else ())
            total = cursor.fetchone()["cnt"]
        except Exception:
            total = 0

        # Apply pagination — MSSQL uses OFFSET/FETCH
        # This requires an ORDER BY; if none exists, add a default
        if not re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
            paginated_sql = f"{sql} ORDER BY (SELECT NULL) OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
        else:
            paginated_sql = f"{sql} OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"

        paginated_params = tuple(params or []) + (offset, limit)
        cursor.execute(paginated_sql, paginated_params)
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, limit=limit, offset=offset, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(sql, tuple(params) if params else ())
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert(self, table: str, data: dict) -> DatabaseResult:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        set_clause = ", ".join(f"{k} = %s" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            translated_filter = SQLTranslator.placeholder_style(filter_sql, "%s")
            sql += f" WHERE {translated_filter}"
            all_params += params or []

        return self.execute(sql, all_params)

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        sql = f"DELETE FROM {table}"
        if filter_sql:
            translated_filter = SQLTranslator.placeholder_style(filter_sql, "%s")
            sql += f" WHERE {translated_filter}"
            all_params = params or []
        else:
            all_params = []
        return self.execute(sql, all_params)

    def start_transaction(self):
        cursor = self._conn.cursor()
        cursor.execute("BEGIN TRANSACTION")
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
        row = self.fetch_one(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME = %s",
            [name],
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
        sql = """
            SELECT c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                   CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_primary
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                  ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.TABLE_NAME = %s AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
            WHERE c.TABLE_NAME = %s
            ORDER BY c.ORDINAL_POSITION
        """
        result = self.fetch(sql, [table, table], limit=10000)
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
