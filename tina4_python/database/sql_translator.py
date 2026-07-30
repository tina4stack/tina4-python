# Tina4 SQLTranslator — cross-engine SQL dialect rewriting.
"""
Dialect translation, in its own unit.

Feature 3 of the feature audit. This class was correct and already separate from
``DatabaseAdapter`` - the audit's D2 claim that Python mixed the two into one
abstraction did not survive contact with the code - but it shared a FILE with the
adapter contract, where PHP, Ruby and Node each give it its own. Same class, same
behaviour, its own file, so the adapter module is the adapter contract and
nothing else.

``quote_identifier`` deliberately stays on ``DatabaseAdapter``. It is overridden
per adapter (Firebird has its own), because identifier quoting genuinely differs
by engine; moving it here would flatten that override.
"""
import re


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


# QueryCache lives in tina4_python.core.cache (as ``Cache``). Re-exported here
# under the QueryCache alias for cross-framework naming parity with PHP/Ruby/Node.
from tina4_python.core.cache import Cache as QueryCache  # noqa: E402,F401
