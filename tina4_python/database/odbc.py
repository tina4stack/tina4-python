# Tina4 ODBC Driver — Generic database access via pyodbc.
"""
ODBC adapter using pyodbc. Provides access to any ODBC-compatible database.

    db = Database("odbc:///DSN=MyDSN")
    db = Database("odbc:///DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=sa;PWD=pass")

Requires: pip install pyodbc
"""
import re
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


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
                "pyodbc is required for ODBC connections. Install: pip install pyodbc"
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
              limit: int = 20, offset: int = 0) -> DatabaseResult:
        # Count total
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _t"
        cursor = self._conn.cursor()
        try:
            cursor.execute(count_sql, params or [])
            total = cursor.fetchone()[0]
        except Exception:
            total = 0

        # Apply pagination — use OFFSET/FETCH for ODBC (SQL Server style)
        paginated_sql = f"{sql} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        paginated_params = (params or []) + [offset, limit]

        try:
            cursor.execute(paginated_sql, paginated_params)
        except Exception:
            # Fallback: try LIMIT/OFFSET for non-SQL Server ODBC sources
            paginated_sql = f"{sql} LIMIT ? OFFSET ?"
            paginated_params = (params or []) + [limit, offset]
            cursor.execute(paginated_sql, paginated_params)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

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
