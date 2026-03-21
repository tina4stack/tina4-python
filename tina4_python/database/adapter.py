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
        return {
            "data": self.records,
            "total": self.count,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }


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

    def fetch(self, sql: str, params: list = None,
              limit: int = 20, skip: int = 0) -> DatabaseResult:
        """Execute a read query and return multiple rows."""
        raise NotImplementedError

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        """Execute a read query and return a single row or None."""
        raise NotImplementedError

    def insert(self, table: str, data: dict) -> DatabaseResult:
        """Insert a row and return the last inserted ID."""
        raise NotImplementedError

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        """Update rows matching the filter."""
        raise NotImplementedError

    def delete(self, table: str,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        """Delete rows matching the filter."""
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
