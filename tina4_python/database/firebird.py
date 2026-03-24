# Tina4 Firebird Driver — Uses fdb (optional).
"""
Firebird adapter using fdb.

    db = Database("firebird://user:pass@localhost:3050/path/to/database.fdb")

Requires: pip install fdb
"""
import re
from urllib.parse import urlparse, unquote
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult, SQLTranslator


class FirebirdAdapter(DatabaseAdapter):
    """Firebird database driver using fdb."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._in_transaction: bool = False

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Connect to Firebird.

        Connection string: firebird://user:pass@host:port/path/to/db.fdb
        Credentials priority: URL > username/password params > adapter defaults (SYSDBA/masterkey).
        """
        try:
            import fdb
        except ImportError:
            raise ImportError(
                "fdb is required for Firebird connections. "
                "Install: pip install fdb"
            )

        parsed = urlparse(connection_string)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3050
        # Firebird database path — decode URL-encoded characters
        db_path = unquote(parsed.path.lstrip("/")) if parsed.path else ""
        user = parsed.username or username or "SYSDBA"
        password = parsed.password or password or "masterkey"
        charset = kwargs.pop("charset", "UTF8")

        self._conn = fdb.connect(
            host=host,
            port=port,
            database=db_path,
            user=user,
            password=password,
            charset=charset,
            **kwargs,
        )

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        sql = self._translate_sql(sql)

        # Firebird does not support RETURNING in all versions — strip and emulate
        returning_cols = None
        returning_match = re.search(r"\s+RETURNING\s+(.+)$", sql, re.IGNORECASE)
        if returning_match:
            returning_cols = returning_match.group(1).strip()
            sql = sql[:returning_match.start()]

        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])

        records = []
        last_id = None

        if returning_cols:
            # Firebird 2.1+ supports RETURNING but we already stripped it.
            # Use a generator/sequence approach to find the last ID.
            sql_upper = sql.strip().upper()
            if sql_upper.startswith("INSERT"):
                table = self._extract_table(sql)
                try:
                    # Try to get the last inserted row by querying the generator
                    gen_name = f"GEN_{table.upper()}_ID"
                    cursor.execute(f"SELECT GEN_ID({gen_name}, 0) FROM RDB$DATABASE")
                    row = cursor.fetchone()
                    if row:
                        last_id = row[0]
                        if returning_cols.strip() == "*":
                            fetch_sql = f"SELECT * FROM {table} WHERE id = ?"
                        else:
                            fetch_sql = f"SELECT {returning_cols} FROM {table} WHERE id = ?"
                        cursor.execute(fetch_sql, [last_id])
                        desc = cursor.description
                        row = cursor.fetchone()
                        if row and desc:
                            col_names = [d[0] for d in desc]
                            records = [dict(zip(col_names, row))]
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
            sql=sql,
            adapter=self,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 20, offset: int = 0) -> DatabaseResult:
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()

        # Count total rows
        count_sql = f"SELECT COUNT(*) FROM ({sql})"
        try:
            cursor.execute(count_sql, params or [])
            total = cursor.fetchone()[0]
        except Exception:
            total = 0

        # Apply Firebird pagination — ROWS start TO end
        start = offset + 1
        end = offset + limit
        paginated_sql = f"{sql} ROWS {start} TO {end}"
        cursor.execute(paginated_sql, params or [])

        desc = cursor.description
        col_names = [d[0] for d in desc] if desc else []
        rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]

        return DatabaseResult(records=rows, count=total, sql=sql, adapter=self)

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        sql = self._translate_sql(sql)
        cursor = self._conn.cursor()
        cursor.execute(sql, params or [])
        desc = cursor.description
        row = cursor.fetchone()
        if row is None:
            return None
        col_names = [d[0] for d in desc] if desc else []
        return dict(zip(col_names, row))

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
        # fdb starts transactions automatically on first operation
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
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
            "AND TRIM(RDB$RELATION_NAME) = ?",
            [name.upper()],
        )
        return row is not None

    def get_tables(self) -> list[str]:
        result = self.fetch(
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
            "ORDER BY RDB$RELATION_NAME",
            limit=10000,
        )
        return [r["RDB$RELATION_NAME"].strip() for r in result.records]

    def get_columns(self, table: str) -> list[dict]:
        sql = (
            "SELECT RF.RDB$FIELD_NAME, F.RDB$FIELD_TYPE, RF.RDB$NULL_FLAG, "
            "RF.RDB$DEFAULT_SOURCE "
            "FROM RDB$RELATION_FIELDS RF "
            "JOIN RDB$FIELDS F ON RF.RDB$FIELD_SOURCE = F.RDB$FIELD_NAME "
            "WHERE RF.RDB$RELATION_NAME = ? "
            "ORDER BY RF.RDB$FIELD_POSITION"
        )
        result = self.fetch(sql, [table.upper()], limit=10000)
        # Map Firebird field type codes to names
        type_map = {
            7: "SMALLINT", 8: "INTEGER", 10: "FLOAT", 12: "DATE",
            13: "TIME", 14: "CHAR", 16: "BIGINT", 27: "DOUBLE PRECISION",
            35: "TIMESTAMP", 37: "VARCHAR", 261: "BLOB",
        }
        return [
            {
                "name": r["RDB$FIELD_NAME"].strip() if r["RDB$FIELD_NAME"] else "",
                "type": type_map.get(r.get("RDB$FIELD_TYPE"), str(r.get("RDB$FIELD_TYPE", ""))),
                "nullable": r.get("RDB$NULL_FLAG") is None,
                "default": r.get("RDB$DEFAULT_SOURCE"),
                "primary_key": False,
            }
            for r in result.records
        ]

    def get_database_type(self) -> str:
        return "firebird"

    # -- SQL Translation -----------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to Firebird dialect.

        Firebird uses ? placeholders, ROWS...TO instead of LIMIT/OFFSET,
        || for concat (native), no ILIKE, no boolean type, and generators
        instead of AUTOINCREMENT.
        """
        sql = SQLTranslator.limit_to_rows(sql)
        sql = SQLTranslator.ilike_to_like(sql)
        sql = SQLTranslator.boolean_to_int(sql)
        sql = SQLTranslator.auto_increment_syntax(sql, "firebird")
        return sql

    def _supports_returning(self) -> bool:
        # Firebird 2.1+ supports it, but we emulate for consistency
        return False
