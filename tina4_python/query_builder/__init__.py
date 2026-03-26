# Tina4 QueryBuilder — Fluent SQL query builder.
"""
Fluent SQL query builder for Tina4 Python.

Usage:
    # Standalone
    result = QueryBuilder.from_table("users", db) \\
        .select("id", "name") \\
        .where("active = ?", [1]) \\
        .order_by("name ASC") \\
        .limit(10) \\
        .get()

    # From ORM model
    result = User.query() \\
        .where("age > ?", [18]) \\
        .order_by("name") \\
        .get()
"""


class QueryBuilder:
    """Fluent SQL query builder that produces and executes SQL statements."""

    def __init__(self, table: str, db=None):
        """Private-ish constructor. Use from_table() or ORM.query()."""
        self._table = table
        self._db = db
        self._columns: list[str] = ["*"]
        self._wheres: list[tuple[str, str]] = []
        self._params: list = []
        self._joins: list[str] = []
        self._group_by_cols: list[str] = []
        self._havings: list[str] = []
        self._having_params: list = []
        self._order_by_cols: list[str] = []
        self._limit_val: int | None = None
        self._offset_val: int | None = None

    @staticmethod
    def from_table(table_name: str, db=None) -> "QueryBuilder":
        """Create a QueryBuilder for a table.

        Args:
            table_name: The database table name.
            db: Optional database connection (Database or adapter).

        Returns:
            A new QueryBuilder instance.
        """
        return QueryBuilder(table_name, db)

    def select(self, *columns: str) -> "QueryBuilder":
        """Set the columns to select.

        Args:
            *columns: Column names (default is '*').

        Returns:
            self for chaining.
        """
        if columns:
            self._columns = list(columns)
        return self

    def where(self, condition: str, params: list = None) -> "QueryBuilder":
        """Add a WHERE condition with AND.

        Args:
            condition: SQL condition with ? placeholders.
            params: Parameter values for placeholders.

        Returns:
            self for chaining.
        """
        self._wheres.append(("AND", condition))
        if params:
            self._params.extend(params)
        return self

    def or_where(self, condition: str, params: list = None) -> "QueryBuilder":
        """Add a WHERE condition with OR.

        Args:
            condition: SQL condition with ? placeholders.
            params: Parameter values for placeholders.

        Returns:
            self for chaining.
        """
        self._wheres.append(("OR", condition))
        if params:
            self._params.extend(params)
        return self

    def join(self, table: str, on_clause: str) -> "QueryBuilder":
        """Add an INNER JOIN.

        Args:
            table: Table to join.
            on_clause: Join condition.

        Returns:
            self for chaining.
        """
        self._joins.append(f"INNER JOIN {table} ON {on_clause}")
        return self

    def left_join(self, table: str, on_clause: str) -> "QueryBuilder":
        """Add a LEFT JOIN.

        Args:
            table: Table to join.
            on_clause: Join condition.

        Returns:
            self for chaining.
        """
        self._joins.append(f"LEFT JOIN {table} ON {on_clause}")
        return self

    def group_by(self, column: str) -> "QueryBuilder":
        """Add a GROUP BY column.

        Args:
            column: Column name to group by.

        Returns:
            self for chaining.
        """
        self._group_by_cols.append(column)
        return self

    def having(self, expression: str, params: list = None) -> "QueryBuilder":
        """Add a HAVING clause.

        Args:
            expression: HAVING expression with ? placeholders.
            params: Parameter values.

        Returns:
            self for chaining.
        """
        self._havings.append(expression)
        if params:
            self._having_params.extend(params)
        return self

    def order_by(self, expression: str) -> "QueryBuilder":
        """Add an ORDER BY clause.

        Args:
            expression: Column and direction (e.g. "name ASC").

        Returns:
            self for chaining.
        """
        self._order_by_cols.append(expression)
        return self

    def limit(self, count: int, offset: int = None) -> "QueryBuilder":
        """Set LIMIT and optional OFFSET.

        Args:
            count: Maximum rows to return.
            offset: Number of rows to skip.

        Returns:
            self for chaining.
        """
        self._limit_val = count
        if offset is not None:
            self._offset_val = offset
        return self

    def to_sql(self) -> str:
        """Build and return the SQL string without executing.

        Returns:
            The constructed SQL query string.
        """
        sql = f"SELECT {', '.join(self._columns)} FROM {self._table}"

        if self._joins:
            sql += " " + " ".join(self._joins)

        if self._wheres:
            sql += " WHERE " + self._build_where()

        if self._group_by_cols:
            sql += " GROUP BY " + ", ".join(self._group_by_cols)

        if self._havings:
            sql += " HAVING " + " AND ".join(self._havings)

        if self._order_by_cols:
            sql += " ORDER BY " + ", ".join(self._order_by_cols)

        return sql

    def get(self):
        """Execute the query and return the DatabaseResult.

        Returns:
            DatabaseResult from db.fetch().
        """
        self._ensure_db()
        sql = self.to_sql()
        all_params = self._params + self._having_params

        return self._db.fetch(
            sql,
            all_params or None,
            self._limit_val if self._limit_val is not None else 100,
            self._offset_val if self._offset_val is not None else 0,
        )

    def first(self) -> dict | None:
        """Execute the query and return a single row.

        Returns:
            A dict for the first matching row, or None.
        """
        self._ensure_db()
        sql = self.to_sql()
        all_params = self._params + self._having_params

        return self._db.fetch_one(sql, all_params or None)

    def count(self) -> int:
        """Execute the query and return the row count.

        Returns:
            Number of matching rows.
        """
        self._ensure_db()

        # Build a count query by replacing columns
        original = self._columns
        self._columns = ["COUNT(*) as cnt"]
        sql = self.to_sql()
        self._columns = original

        all_params = self._params + self._having_params

        row = self._db.fetch_one(sql, all_params or None)
        if row is None:
            return 0
        # Handle case-insensitive column names
        return int(row.get("cnt", row.get("CNT", 0)))

    def exists(self) -> bool:
        """Check whether any matching rows exist.

        Returns:
            True if at least one row matches.
        """
        return self.count() > 0

    # -- Private helpers --

    def _build_where(self) -> str:
        """Build the WHERE clause from accumulated conditions."""
        parts = []
        for i, (connector, condition) in enumerate(self._wheres):
            if i == 0:
                parts.append(condition)
            else:
                parts.append(f"{connector} {condition}")
        return " ".join(parts)

    def _ensure_db(self):
        """Ensure a database connection is available."""
        if self._db is None:
            # Try to use the global ORM database
            from tina4_python.orm.model import _database
            if _database is not None:
                self._db = _database
            else:
                raise RuntimeError("QueryBuilder: No database connection provided.")
