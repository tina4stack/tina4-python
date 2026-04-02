# Tina4 Database Adapter — The contract every driver implements.
"""
All database drivers implement DatabaseAdapter. This is the only interface
the rest of the framework touches. Adding a new database = implementing this class.
"""
import re
from dataclasses import dataclass, field


@dataclass
class DatabaseResult:
    """Standard result from any database operation."""
    records: list = field(default_factory=list)
    count: int = 0
    affected_rows: int = 0
    last_id: int | str | None = None
    error: str | None = None
    sql: str | None = None
    adapter: object | None = field(default=None, repr=False)
    _column_info: list | None = field(default=None, init=False, repr=False)

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return self.count

    def __bool__(self):
        return self.error is None

    def to_list(self) -> list:
        return self.records

    def to_paginate(self, page: int = 1, per_page: int = 20) -> dict:
        total_pages = max(1, -(-self.count // per_page))  # ceil division
        offset = (page - 1) * per_page
        data = self.records[offset:offset + per_page]
        return {
            "records": data,        # standard name
            "data": data,           # backwards compat (PHP/Ruby/Node)
            "count": self.count,    # standard name
            "total": self.count,    # backwards compat
            "limit": per_page,      # standard name
            "offset": offset,       # standard name
            "page": page,
            "per_page": per_page,   # backwards compat
            "totalPages": total_pages,   # camelCase standard
            "total_pages": total_pages,  # backwards compat
        }

    def column_info(self) -> list[dict]:
        """Return column metadata for the query's table.

        Lazy — only queries the database when explicitly called. Caches the
        result so subsequent calls return immediately without re-querying.

        Returns a list of dicts with keys:
            name, type, size, decimals, nullable, primary_key
        """
        if self._column_info is not None:
            return self._column_info

        # Try to extract table name from the SQL query
        table = self._extract_table_from_sql()

        # If we have an adapter and a table name, query the database for metadata
        if self.adapter is not None and table:
            try:
                self._column_info = self._query_column_metadata(table)
                return self._column_info
            except Exception:
                pass

        # Fallback: derive basic info from record keys
        self._column_info = self._fallback_column_info()
        return self._column_info

    def _extract_table_from_sql(self) -> str | None:
        """Extract table name from a SQL query using simple regex."""
        if not self.sql:
            return None
        # Match FROM tablename (with optional schema prefix)
        m = re.search(r'\bFROM\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        # Match INSERT INTO tablename
        m = re.search(r'\bINSERT\s+INTO\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        # Match UPDATE tablename
        m = re.search(r'\bUPDATE\s+["\']?(\w+)["\']?', self.sql, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def _query_column_metadata(self, table: str) -> list[dict]:
        """Query the database adapter for column metadata."""
        adapter = self.adapter
        db_type = ""
        try:
            db_type = adapter.get_database_type().lower()
        except (AttributeError, NotImplementedError):
            pass

        if db_type == "sqlite":
            return self._query_sqlite_columns(table)
        elif db_type in ("postgresql", "postgres"):
            return self._query_pg_columns(table)
        elif db_type == "mysql":
            return self._query_mysql_columns(table)
        else:
            # Try get_columns if the adapter supports it
            try:
                raw_cols = adapter.get_columns(table)
                return self._normalize_adapter_columns(raw_cols)
            except (AttributeError, NotImplementedError):
                pass
            return self._fallback_column_info()

    def _query_sqlite_columns(self, table: str) -> list[dict]:
        """Get column metadata from SQLite PRAGMA."""
        result = self.adapter.fetch(f"PRAGMA table_info({table})")
        columns = []
        for row in result.records:
            col_type = (row.get("type") or "TEXT").upper()
            size, decimals = self._parse_type_size(col_type)
            columns.append({
                "name": row.get("name"),
                "type": col_type.split("(")[0],
                "size": size,
                "decimals": decimals,
                "nullable": not bool(row.get("notnull", 0)),
                "primary_key": bool(row.get("pk", 0)),
            })
        return columns

    def _query_pg_columns(self, table: str) -> list[dict]:
        """Get column metadata from PostgreSQL information_schema."""
        sql = (
            "SELECT column_name, data_type, character_maximum_length, "
            "numeric_precision, numeric_scale, is_nullable "
            "FROM information_schema.columns WHERE table_name = ?"
        )
        result = self.adapter.fetch(sql, [table])
        # Determine primary keys
        pk_sql = (
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = ?::regclass AND i.indisprimary"
        )
        pk_names = set()
        try:
            pk_result = self.adapter.fetch(pk_sql, [table])
            pk_names = {r.get("attname") for r in pk_result.records}
        except Exception:
            pass

        columns = []
        for row in result.records:
            columns.append({
                "name": row.get("column_name"),
                "type": (row.get("data_type") or "UNKNOWN").upper(),
                "size": row.get("character_maximum_length") or row.get("numeric_precision"),
                "decimals": row.get("numeric_scale"),
                "nullable": (row.get("is_nullable") or "YES").upper() == "YES",
                "primary_key": row.get("column_name") in pk_names,
            })
        return columns

    def _query_mysql_columns(self, table: str) -> list[dict]:
        """Get column metadata from MySQL information_schema."""
        sql = (
            "SELECT column_name, data_type, character_maximum_length, "
            "numeric_precision, numeric_scale, is_nullable, column_key "
            "FROM information_schema.columns WHERE table_name = ?"
        )
        result = self.adapter.fetch(sql, [table])
        columns = []
        for row in result.records:
            columns.append({
                "name": row.get("column_name") or row.get("COLUMN_NAME"),
                "type": (row.get("data_type") or row.get("DATA_TYPE") or "UNKNOWN").upper(),
                "size": row.get("character_maximum_length") or row.get("CHARACTER_MAXIMUM_LENGTH") or row.get("numeric_precision") or row.get("NUMERIC_PRECISION"),
                "decimals": row.get("numeric_scale") or row.get("NUMERIC_SCALE"),
                "nullable": (row.get("is_nullable") or row.get("IS_NULLABLE") or "YES").upper() == "YES",
                "primary_key": (row.get("column_key") or row.get("COLUMN_KEY") or "") == "PRI",
            })
        return columns

    @staticmethod
    def _parse_type_size(type_str: str) -> tuple:
        """Parse size and decimals from a type string like VARCHAR(255) or NUMERIC(10,2)."""
        m = re.search(r'\((\d+)(?:\s*,\s*(\d+))?\)', type_str)
        if m:
            size = int(m.group(1))
            decimals = int(m.group(2)) if m.group(2) else None
            return size, decimals
        return None, None

    @staticmethod
    def _normalize_adapter_columns(raw_cols: list[dict]) -> list[dict]:
        """Normalize output from adapter.get_columns() to standard format."""
        columns = []
        for col in raw_cols:
            col_type = (col.get("type") or "UNKNOWN").upper()
            size, decimals = DatabaseResult._parse_type_size(col_type)
            columns.append({
                "name": col.get("name"),
                "type": col_type.split("(")[0],
                "size": size,
                "decimals": decimals,
                "nullable": col.get("nullable", True),
                "primary_key": col.get("primary_key", False),
            })
        return columns

    def _fallback_column_info(self) -> list[dict]:
        """Derive basic column info from record keys and values when no adapter is available."""
        if not self.records:
            return []
        row = self.records[0] if isinstance(self.records[0], dict) else {}
        result = []
        for k, v in row.items():
            if isinstance(v, int):
                col_type = "INTEGER"
            elif isinstance(v, float):
                col_type = "REAL"
            elif isinstance(v, bool):
                col_type = "BOOLEAN"
            elif v is None:
                col_type = "TEXT"
            else:
                col_type = "TEXT"
            result.append({
                "name": k,
                "type": col_type,
                "size": None,
                "decimals": None,
                "nullable": True,
                "primary_key": k.lower() == "id",
            })
        return result


class DatabaseAdapter:
    """Base class for all database drivers.

    Every method raises NotImplementedError — drivers must implement all of them.
    The interface is deliberately minimal: 13 methods cover everything.

    Autocommit is OFF by default. Set TINA4_AUTOCOMMIT=true in .env to enable.
    Without autocommit, you must call commit() explicitly after write operations.
    """

    def __init__(self):
        import os
        self._autocommit = os.environ.get(
            "TINA4_AUTOCOMMIT", "false"
        ).lower() in ("true", "1", "yes")

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool):
        self._autocommit = value

    def connect(self, connection_string: str, username: str = "", password: str = "", **kwargs):
        """Establish connection to the database."""
        raise NotImplementedError

    def close(self):
        """Close the database connection."""
        raise NotImplementedError

    def execute(self, sql: str, params: list = None) -> DatabaseResult:
        """Execute a write query (INSERT, UPDATE, DELETE, DDL)."""
        raise NotImplementedError

    def execute_many(self, sql: str, params_list: list[list] = None) -> DatabaseResult:
        """Execute a single SQL statement with multiple parameter sets.

        Like batch insert/update — runs the same SQL for each set of params.

            db.execute_many("INSERT INTO users (name) VALUES (?)", [
                ["Alice"], ["Bob"], ["Eve"]
            ])
        """
        total_affected = 0
        last_id = None
        for params in (params_list or []):
            result = self.execute(sql, params)
            total_affected += result.affected_rows
            if result.last_id is not None:
                last_id = result.last_id
        return DatabaseResult(
            affected_rows=total_affected,
            last_id=last_id,
        )

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        """Execute a read query and return multiple rows."""
        raise NotImplementedError

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        """Execute a read query and return a single row or None."""
        raise NotImplementedError

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        """Insert one or more rows.

        Args:
            table: Table name.
            data: A dict (single row) or a list of dicts (multiple rows).
                  List of dicts uses execute_many internally for efficiency.
        """
        if isinstance(data, list):
            if not data:
                return DatabaseResult()
            # All dicts must have the same keys
            keys = list(data[0].keys())
            columns = ", ".join(keys)
            placeholders = ", ".join(["?"] * len(keys))
            sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            params_list = [list(row[k] for k in keys) for row in data]
            return self.execute_many(sql, params_list)
        raise NotImplementedError

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        """Update rows matching the filter."""
        raise NotImplementedError

    def delete(self, table: str,
               filter_sql: str | dict | list = "", params: list = None) -> DatabaseResult:
        """Delete rows matching the filter.

        Args:
            table: Table name.
            filter_sql: One of:
                - str: SQL WHERE clause (e.g. "age < 18")
                - dict: builds WHERE from dict keys (e.g. {"id": 5} → "id = ?")
                - list of dicts: delete multiple rows by key match
            params: Parameters for the WHERE clause (only with str filter_sql).
        """
        if isinstance(filter_sql, list):
            # List of dicts — delete each row
            total_affected = 0
            for row_filter in filter_sql:
                result = self.delete(table, row_filter)
                total_affected += result.affected_rows
            return DatabaseResult(affected_rows=total_affected)

        if isinstance(filter_sql, dict):
            # Build WHERE from dict
            where_parts = [f"{k} = ?" for k in filter_sql.keys()]
            where_sql = " AND ".join(where_parts)
            return self.delete(table, where_sql, list(filter_sql.values()))

        raise NotImplementedError

    def start_transaction(self):
        """Begin a transaction."""
        raise NotImplementedError

    def commit(self):
        """Commit the current transaction."""
        raise NotImplementedError

    def rollback(self):
        """Roll back the current transaction."""
        raise NotImplementedError

    def table_exists(self, name: str) -> bool:
        """Check if a table exists."""
        raise NotImplementedError

    def get_tables(self) -> list[str]:
        """List all table names in the database."""
        raise NotImplementedError

    def get_columns(self, table: str) -> list[dict]:
        """Get column definitions for a table.

        Returns list of dicts with keys: name, type, nullable, default, primary_key
        """
        raise NotImplementedError

    def get_database_type(self) -> str:
        """Return the driver name (e.g., 'sqlite', 'postgresql')."""
        raise NotImplementedError

    # ── SQL Translation Layer ──────────────────────────────────────
    # Translates portable SQL into engine-specific syntax so users
    # can write one SQL dialect and run on any supported engine.

    def _translate_sql(self, sql: str) -> str:
        """Translate portable SQL to engine-specific syntax.

        Base implementation is a no-op. Drivers override to handle quirks
        like LIMIT→ROWS...TO (Firebird), CONCAT vs ||, etc.
        """
        return sql

    def _supports_returning(self) -> bool:
        """Whether the engine natively supports RETURNING clauses."""
        return False

    @staticmethod
    def _extract_table(sql: str) -> str:
        """Extract the table name from an INSERT/UPDATE/DELETE statement."""
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT"):
            m = re.search(r"INSERT\s+INTO\s+(\S+)", sql, re.IGNORECASE)
        elif sql_upper.startswith("UPDATE"):
            m = re.search(r"UPDATE\s+(\S+)", sql, re.IGNORECASE)
        elif sql_upper.startswith("DELETE"):
            m = re.search(r"DELETE\s+FROM\s+(\S+)", sql, re.IGNORECASE)
        else:
            m = None
        return m.group(1) if m else "unknown"


# ── SQL Translation Rules ──────────────────────────────────────
# Reusable translation functions for common cross-engine quirks.

class SQLTranslator:
    """Cross-engine SQL translator.

    Each database adapter calls the rules it needs. Rules are composable
    and stateless — just string transforms.
    """

    @staticmethod
    def limit_to_rows(sql: str) -> str:
        """Convert LIMIT/OFFSET to Firebird ROWS...TO syntax.

        LIMIT 10 OFFSET 5  →  ROWS 6 TO 15
        LIMIT 10            →  ROWS 1 TO 10
        """
        m = re.search(
            r"\bLIMIT\s+(\d+)\s+OFFSET\s+(\d+)\s*$", sql, re.IGNORECASE
        )
        if m:
            limit, offset = int(m.group(1)), int(m.group(2))
            start = offset + 1
            end = offset + limit
            return sql[:m.start()] + f"ROWS {start} TO {end}"

        m = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if m:
            limit = int(m.group(1))
            return sql[:m.start()] + f"ROWS 1 TO {limit}"

        return sql

    @staticmethod
    def limit_to_top(sql: str) -> str:
        """Convert LIMIT to MSSQL TOP syntax.

        SELECT ... LIMIT 10  →  SELECT TOP 10 ...
        (OFFSET handled via ROW_NUMBER in more complex cases)
        """
        m = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if m and not re.search(r"\bOFFSET\b", sql, re.IGNORECASE):
            limit = int(m.group(1))
            body = sql[:m.start()].strip()
            return re.sub(r"^(SELECT)\b", rf"\1 TOP {limit}", body, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def concat_pipes_to_func(sql: str) -> str:
        """Convert || concatenation to CONCAT() for MySQL/MSSQL.

        'a' || 'b' || 'c'  →  CONCAT('a', 'b', 'c')
        """
        if "||" not in sql:
            return sql
        # Only transform outside of string literals — simple approach
        parts = re.split(r"\|\|", sql)
        if len(parts) > 1:
            return "CONCAT(" + ", ".join(p.strip() for p in parts) + ")"
        return sql

    @staticmethod
    def boolean_to_int(sql: str) -> str:
        """Convert TRUE/FALSE to 1/0 for engines without boolean type."""
        sql = re.sub(r"\bTRUE\b", "1", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bFALSE\b", "0", sql, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def ilike_to_like(sql: str) -> str:
        """Convert ILIKE to LOWER() LIKE LOWER() for engines without ILIKE."""
        def _replace(m):
            col = m.group(1).strip()
            val = m.group(2).strip()
            return f"LOWER({col}) LIKE LOWER({val})"
        return re.sub(r"(\S+)\s+ILIKE\s+(\S+)", _replace, sql, flags=re.IGNORECASE)

    @staticmethod
    def auto_increment_syntax(sql: str, engine: str) -> str:
        """Translate AUTOINCREMENT across engines in DDL."""
        if engine == "mysql":
            return sql.replace("AUTOINCREMENT", "AUTO_INCREMENT")
        if engine == "postgresql":
            # INTEGER ... AUTOINCREMENT → SERIAL
            sql = re.sub(
                r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
                "SERIAL PRIMARY KEY",
                sql, flags=re.IGNORECASE,
            )
            return sql
        if engine == "mssql":
            return re.sub(
                r"AUTOINCREMENT",
                "IDENTITY(1,1)",
                sql, flags=re.IGNORECASE,
            )
        if engine == "firebird":
            # Firebird uses generators — strip AUTOINCREMENT
            return re.sub(r"\s*AUTOINCREMENT\b", "", sql, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def placeholder_style(sql: str, style: str = "?") -> str:
        """Convert ? placeholders to engine-specific style.

        ?  → %s  (MySQL, PostgreSQL)
        ?  → :1, :2, :3  (Oracle, Firebird)
        """
        if style == "%s":
            return sql.replace("?", "%s")
        if style.startswith(":"):
            count = 0
            result = []
            for ch in sql:
                if ch == "?":
                    count += 1
                    result.append(f":{count}")
                else:
                    result.append(ch)
            return "".join(result)
        return sql
