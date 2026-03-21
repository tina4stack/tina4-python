# Tina4 PostgreSQL Driver — Uses psycopg2 (optional).
"""
PostgreSQL adapter using psycopg2.

    db = Database("postgresql://user:pass@localhost:5432/mydb")
    db = Database("postgres://user:pass@localhost:5432/mydb")

Requires: pip install psycopg2-binary
"""
import re
from urllib.parse import urlparse
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL database driver using psycopg2."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to PostgreSQL.

        Connection string: postgresql://user:pass@host:port/dbname
        Credentials priority: URL > username/password params > adapter defaults.
        """
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL connections. "
                "Install: pip install psycopg2-binary"
            )

        parsed = urlparse(connection_string)
        self._conn = psycopg2.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=parsed.username or username or "",
            password=parsed.password or password or "",
            dbname=parsed.path.lstrip("/") if parsed.path else "",
            **kwargs,
        )
        # Use RealDictCursor for dict-style rows
        self._conn.autocommit = False

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        import psycopg2.extras

        sql = self._translate_sql(sql)

        # Handle RETURNING clause natively
        has_returning = bool(
            re.search(r"\bRETURNING\b", sql, re.IGNORECASE)
        )

        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql, params or [])

        records = []
        last_id = None

        if has_returning and cursor.description:
            records = [dict(row) for row in cursor.fetchall()]
            if records and "id" in records[0]:
                last_id = records[0]["id"]

        if not has_returning:
            # Try to get last inserted ID for INSERT statements
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("INSERT"):
                try:
                    cursor.execute("SELECT lastval()")
                    row = cursor.fetchone()
                    if row:
                        last_id = list(row.values())[0]
                except Exception:
                    pass

        affected = cursor.rowcount if cursor.rowcount >= 0 else 0

        if not self._in_transaction and self.autocommit:
            self._conn.commit()

        return DatabaseResult(
            records=records,
            count=len(records),
            affected_rows=affected,
            last_id=last_id,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 20, skip: int = 0) -> DatabaseResult:
        import psycopg2.extras

        sql = self._translate_sql(sql)

        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Count total rows
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) AS _count_subquery"
        try:
            cursor.execute(count_sql, params or [])
            total = cursor.fetchone()["cnt"]
        except Exception:
            total = 0

        # Apply pagination
        paginated_sql = f"{sql} LIMIT %s OFFSET %s"
        paginated_params = (params or []) + [limit, skip]
        cursor.execute(paginated_sql, paginated_params)
        rows = [dict(row) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        import psycopg2.extras

        sql = self._translate_sql(sql)
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert(self, table: str, data: dict) -> DatabaseResult:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING *"
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
        # psycopg2 starts transactions automatically, but we track state
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
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = %s",
            [name],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
            limit=10000,
        )
        return [r["tablename"] for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        sql = """
            SELECT c.column_name, c.data_type, c.is_nullable, c.column_default,
                   CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_name = %s AND c.table_schema = 'public'
            ORDER BY c.ordinal_position
        """
        result = self.fetch(sql, [table, table], limit=10000)
        return [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "primary_key": r["is_primary"],
            }
            for r in result.records
        ]

    def get_database_type(self) -> str:
        return "postgresql"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to PostgreSQL dialect.

        PostgreSQL uses %s placeholders, supports ILIKE natively,
        || for concat, RETURNING, and LIMIT/OFFSET.
        """
        sql = SQLTranslator.placeholder_style(sql, "%s")
        sql = SQLTranslator.auto_increment_syntax(sql, "postgresql")
        sql = SQLTranslator.boolean_to_int(sql)
        return sql

    def _supports_returning(self) -> bool:
        return True
