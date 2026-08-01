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
    limit: int = 0
    offset: int = 0
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

    def __getitem__(self, index):
        """Index / slice access into the result rows.

        v3.13.16: ``result[0]`` (and slicing) are documented (book ch5 §4
        "Index Access") but used to raise ``TypeError: 'DatabaseResult'
        object is not subscriptable``. Delegate to the materialised rows so
        index and slice access behave like a list.
        """
        return self.records[index]

    def __bool__(self):
        return self.error is None

    def size(self) -> int:
        """Return the total count of records."""
        return self.count

    @property
    def columns(self) -> list[str]:
        """Return the column names of the result set.

        Cheap property — derived from the first row's keys. For richer
        metadata (type, nullable, primary key), call ``column_info()``.

            >>> result = db.fetch("SELECT id, name FROM users LIMIT 1")
            >>> result.columns
            ['id', 'name']

        Returns ``[]`` when no rows.
        """
        if not self.records:
            return []
        return list(self.records[0].keys())

    def to_list(self) -> list:
        return self.records

    def to_array(self) -> list:
        """Return list of row dicts (alias for records)."""
        return self.records

    def to_json(self) -> str:
        """Return JSON string of records."""
        import json
        return json.dumps(self.records)

    def to_csv(self) -> str:
        """Return CSV string with header row."""
        if not self.records:
            return ""
        columns = list(self.records[0].keys())

        def escape(val) -> str:
            if val is None:
                return ""
            s = str(val)
            if "," in s or '"' in s or "\n" in s:
                return f'"{s.replace(chr(34), chr(34)+chr(34))}"'
            return s

        header = ",".join(escape(c) for c in columns)
        rows = [",".join(escape(row.get(c)) for c in columns) for row in self.records]
        return "\n".join([header] + rows)

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

    Autocommit is ON by default: a standalone write (execute/insert/update/delete
    made outside an explicit transaction) commits on its own connection before
    returning. Inside start_transaction()/commit()/rollback() the commit is
    deferred — the per-statement commit branches are gated on `not self._in_transaction`
    so explicit transactions stay atomic. Set TINA4_AUTOCOMMIT=false in .env for
    strict manual mode (every write needs an explicit commit()).
    """

    def __init__(self):
        import os
        self._autocommit = os.environ.get(
            "TINA4_AUTOCOMMIT", "true"
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
        rows = params_list or []
        if not rows:
            return DatabaseResult(affected_rows=0)
        # Run the whole batch in ONE transaction on ONE connection so it is
        # atomic AND affected_rows/last_id are reliable. In autocommit mode each
        # standalone execute() commits on its own (possibly different, pooled)
        # connection, which scattered the per-row rowcount / last_insert_id and
        # made the aggregate non-deterministic. When already inside an explicit
        # transaction we just join it (never nest).
        owns_txn = self._autocommit and not getattr(self, "_in_transaction", False)
        if owns_txn:
            self.start_transaction()
        total_affected = 0
        last_id = None
        # ONE round-trip per CHUNK instead of one per ROW. Looping execute()
        # here pays a full network round-trip for every row: 500 rows took
        # 9848ms on PostgreSQL against 15.8ms as a single multi-row VALUES
        # (625x), MySQL 216x, MSSQL 121x. build_batch_inserts returns an empty
        # list for anything it cannot collapse safely - RETURNING, upserts,
        # non-INSERT statements, ragged rows, Firebird - and then this falls
        # back to the row-at-a-time loop below, unchanged.
        batched = SQLTranslator.build_batch_inserts(sql, rows, self.get_database_type())
        try:
            if batched:
                for chunk_sql, chunk_params in batched:
                    result = self.execute(chunk_sql, chunk_params)
                    # The collapse must be invisible: affected_rows is the total
                    # ROW count, never the number of statements run.
                    total_affected += result.affected_rows
                    # last_id stays the LAST inserted row's id. MySQL reports the
                    # FIRST id of a multi-row INSERT; its ADAPTER normalises that
                    # at write time (the only place that knows both the first id
                    # and the row count), so get_last_id() and this result always
                    # agree. Normalising here instead would double-apply.
                    if result.last_id is not None:
                        last_id = result.last_id
            else:
                for params in rows:
                    result = self.execute(sql, params)
                    total_affected += result.affected_rows
                    if result.last_id is not None:
                        last_id = result.last_id
            if owns_txn:
                self.commit()
        except Exception:
            if owns_txn:
                self.rollback()
            raise
        return DatabaseResult(
            affected_rows=total_affected,
            last_id=last_id,
        )

    @staticmethod
    def _strip_trailing_semicolons(sql: str) -> str:
        """v3.13.12: normalize user-supplied SQL by stripping trailing
        semicolons and whitespace.

        ``fetch()`` and ``fetch_one()`` wrap the user's SQL — fetch()
        builds a ``SELECT COUNT(*) FROM ({sql}) AS _count_subquery``
        for the pagination probe and appends ``LIMIT/OFFSET`` to the
        real query. A trailing ``;`` in the user's SQL breaks both:

            user input:  "SELECT * FROM users;"
            wrapped:     "SELECT COUNT(*) FROM (SELECT * FROM users;) ..."   ← syntax error
            paginated:   "SELECT * FROM users; LIMIT 100 OFFSET 0"           ← invalid

        Stripping trailing semicolons before any wrapping is the
        single-line defence. Internal semicolons (between meaningful
        SQL statements) are left alone — the driver will reject those
        if multi-statement isn't supported on the engine.
        """
        if not sql:
            return sql
        stripped = sql.rstrip()
        while stripped.endswith(";"):
            stripped = stripped[:-1].rstrip()
        return stripped

    @staticmethod
    def _scrub_sql_text(sql: str) -> str:
        """Blank out string literals, quoted identifiers and comments so a
        keyword search sees only real SQL.

        Blanks are spaces of the SAME LENGTH (newlines preserved), so offsets
        and line structure still line up with the original.

        MEASURED 2026-08-01 on a real 150-row SQLite table with the 100-row cap
        in force. The old test was ``"LIMIT" in sql.upper().split("--")[0]``,
        and each of these returned ALL 150 ROWS instead of 100:

            SELECT * FROM t WHERE label != 'LIMIT' ORDER BY id     literal
            SELECT * FROM t ORDER BY id -- LIMIT 5                 line comment
            SELECT id, label AS rate_limit FROM t                  identifier

        A silently uncapped read of a whole table is the production incident the
        cap exists to prevent, and an ordinary column name was enough to cause it.
        """
        if not sql:
            return sql

        out = []
        i = 0
        n = len(sql)
        while i < n:
            ch = sql[i]
            nxt = sql[i + 1] if i + 1 < n else ""

            if ch in ("'", '"'):
                quote = ch
                out.append(" ")
                i += 1
                while i < n:
                    if sql[i] == quote:
                        if i + 1 < n and sql[i + 1] == quote:
                            out.append("  ")
                            i += 2
                            continue
                        out.append(" ")
                        i += 1
                        break
                    out.append("\n" if sql[i] == "\n" else " ")
                    i += 1
                continue

            if ch == "-" and nxt == "-":
                while i < n and sql[i] != "\n":
                    out.append(" ")
                    i += 1
                continue

            if ch == "/" and nxt == "*":
                out.append("  ")
                i += 2
                while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                    out.append("\n" if sql[i] == "\n" else " ")
                    i += 1
                if i < n:
                    out.append("  ")
                    i += 2
                continue

            out.append(ch)
            i += 1

        return "".join(out)

    @staticmethod
    def _has_trailing_limit(sql: str) -> bool:
        """True when the statement ENDS with its own LIMIT clause.

        Anchored to the END on purpose: a bare "contains LIMIT" test also matches
        a LIMIT inside a subquery, where the OUTER statement still needs its cap.
        This is tina4-php's ``SqlNormalizerTrait::hasTrailingLimit`` regex, ported
        verbatim so all four frameworks answer identically. It accepts a numeric
        value, ``?``/``$1``/``:name`` placeholders, MySQL's ``LIMIT a, b``, and a
        trailing OFFSET.

        Literals and comments are scrubbed before matching (see _scrub_sql_text).
        """
        val = r"(?:\d+|\?|\$\d+|:\w+|%s)"
        pattern = (
            r"\bLIMIT\s+" + val + r"(?:\s*,\s*" + val + r")?"
            r"(?:\s+OFFSET\s+" + val + r")?\s*;?\s*$"
        )
        return bool(re.search(pattern, DatabaseAdapter._scrub_sql_text(sql or ""), re.IGNORECASE))

    @staticmethod
    def _strip_trailing_order_by(sql: str) -> str:
        """Strip a trailing top-level ``ORDER BY`` so the SQL can be safely
        wrapped in ``SELECT COUNT(*) FROM (<sql>)`` for the row-count probe.

        SQL Server rejects an ``ORDER BY`` inside a derived-table subquery
        unless it carries ``TOP``/``OFFSET``/``FETCH`` (error 20018), which
        silently zeroed the MSSQL count probe for any query ending in
        ``ORDER BY`` (issue #262 -- the bug existed in this master adapter too,
        not only the mirrors). ``ORDER BY`` does not affect ``COUNT(*)``, so
        dropping it for the probe ONLY is safe; the paginated query keeps its
        ``ORDER BY`` for ``OFFSET/FETCH``. An ``ORDER BY`` nested in a subquery,
        or one already legalised by a following ``OFFSET``/``FETCH``/``FOR``, is
        left intact. Parity with PHP ``SqlNormalizerTrait::stripTrailingOrderBy``.
        """
        if not sql or not re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
            return sql
        last_top_level = -1
        for match in re.finditer(r"\bORDER\s+BY\b", sql, re.IGNORECASE):
            pos = match.start()
            before = sql[:pos]
            balanced_before = before.count("(") == before.count(")")
            depth = 0
            balanced_after = True
            for ch in sql[pos:]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        balanced_after = False
                        break
            if balanced_before and balanced_after:
                last_top_level = pos
        if last_top_level == -1:
            return sql
        tail = sql[last_top_level:]
        if re.search(r"\b(?:OFFSET|FETCH|FOR)\b", tail, re.IGNORECASE):
            return sql
        return sql[:last_top_level].rstrip()

    @staticmethod
    def _split_schema(name: str) -> tuple[str | None, str]:
        """Split a possibly-qualified table name into (schema, table).

        v3.13.14 (#48): a model whose ``table_name`` is qualified —
        PostgreSQL ``gift_cards.gift_card``, MSSQL ``dbo.widget``,
        MySQL ``otherdb.table``, SQLite ``attached.table`` — lives in
        that schema/catalog, not the default. Each adapter's
        ``table_exists`` / ``get_columns`` use this to query the right
        namespace instead of matching the whole dotted string as one
        flat table name. Returns ``(None, name)`` for a bare name so
        callers default to the engine's current namespace. Splits on the
        first dot; quoted identifiers with embedded dots aren't supported
        (they weren't before either). Firebird has no schemas, so its
        adapter ignores this.
        """
        if "." in name:
            schema, _, table = name.partition(".")
            return schema, table
        return None, name

    def fetch(self, sql: str, params: list = None,
              limit: int = 100, offset: int = 0) -> DatabaseResult:
        """Execute a read query and return multiple rows."""
        raise NotImplementedError

    def fetch_one(self, sql: str, params: list = None) -> dict | None:
        """Execute a read query and return a single row or None."""
        raise NotImplementedError

    #: Identifier quoting for this dialect. ANSI double quotes work on SQLite,
    #: PostgreSQL and Firebird; MySQL and SQL Server override this.
    IDENTIFIER_QUOTE = ('"', '"')

    def quote_identifier(self, name: str) -> str:
        """Quote a table/column name so a SQL reserved word can be used.

        ``CREATE TABLE order (...)`` / ``SELECT * FROM order`` are syntax errors
        on every engine; quoting makes ``order``, ``group``, ``user`` etc. usable
        as names. Idempotent (an already-quoted name is returned unchanged) and
        dot-aware (``schema.table`` quotes each part).

        A raw expression is never quoted — ``*``, ``COUNT(*)`` and anything that
        isn't a plain identifier are passed through untouched, so existing
        hand-written SQL keeps working.
        """
        if not name:
            return name
        open_q, close_q = self.IDENTIFIER_QUOTE
        name = name.strip()
        if name.startswith(open_q) and name.endswith(close_q):
            return name
        if "." in name:
            return ".".join(self.quote_identifier(p) for p in name.split("."))
        # Only quote a plain identifier — leave expressions/wildcards alone.
        if not name.replace("_", "").replace("$", "").isalnum():
            return name
        return f"{open_q}{name.replace(close_q, close_q * 2)}{close_q}"

    #: The engine's parameter marker. Overridden to ``"%s"`` by PostgreSQL,
    #: MySQL and MSSQL; everything else uses the default.
    PARAM_MARKER = "?"

    #: Appended to a single-row INSERT. Only PostgreSQL wants ``RETURNING *``;
    #: it is the one genuinely engine-specific part of building an INSERT.
    INSERT_RETURNING = ""

    def _marked_filter(self, filter_sql: str) -> str:
        """Rewrite a caller's ``?`` placeholders into this engine's marker.

        A caller writes ``"id = ?"`` regardless of engine - that is the
        documented cross-framework filter form. Engines whose marker IS ``?``
        need no rewrite, and running the translator over them anyway would be
        work that can only introduce bugs.
        """
        if self.PARAM_MARKER == "?":
            return filter_sql
        return SQLTranslator.placeholder_style(filter_sql, self.PARAM_MARKER)

    def insert(self, table: str, data: dict | list) -> DatabaseResult:
        """Insert one or more rows.

        Args:
            table: Table name.
            data: A dict (single row) or a list of dicts (multiple rows).
                  List of dicts uses execute_many internally for efficiency.

        Building an INSERT is not engine-specific work. This used to be
        reimplemented in all six SQL adapters, identical except for the
        parameter marker and PostgreSQL's RETURNING - both of which are now
        seams above. MongoDB still overrides it, because it does not build SQL
        at all.
        """
        if isinstance(data, list):
            if not data:
                return DatabaseResult()
            # All dicts must have the same keys
            keys = list(data[0].keys())
            columns = ", ".join(self.quote_identifier(k) for k in keys)
            placeholders = ", ".join([self.PARAM_MARKER] * len(keys))
            sql = f"INSERT INTO {self.quote_identifier(table)} ({columns}) VALUES ({placeholders})"
            params_list = [list(row[k] for k in keys) for row in data]
            return self.execute_many(sql, params_list)

        columns = ", ".join(self.quote_identifier(c) for c in data.keys())
        placeholders = ", ".join([self.PARAM_MARKER] * len(data))
        sql = (
            f"INSERT INTO {self.quote_identifier(table)} "
            f"({columns}) VALUES ({placeholders}){self.INSERT_RETURNING}"
        )
        return self.execute(sql, list(data.values()))

    def update(self, table: str, data: dict,
               filter_sql: str = "", params: list = None) -> DatabaseResult:
        """Update rows matching the filter.

        The SET column names are QUOTED. SQLite already quoted them while
        PostgreSQL, MySQL and MSSQL did not, so a column named after a reserved
        word worked on one engine and failed on three. Quoting is what every
        INSERT in this file already does.
        """
        set_clause = ", ".join(
            f"{self.quote_identifier(k)} = {self.PARAM_MARKER}" for k in data.keys()
        )
        sql = f"UPDATE {self.quote_identifier(table)} SET {set_clause}"
        all_params = list(data.values())

        if filter_sql:
            sql += f" WHERE {self._marked_filter(filter_sql)}"
            all_params += params or []

        return self.execute(sql, all_params)

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
            # Build WHERE from dict. Emits "?" deliberately: the string branch
            # below runs it through _marked_filter, so translating here too
            # would double-translate on a "%s" engine.
            where_parts = [f"{self.quote_identifier(k)} = ?" for k in filter_sql.keys()]
            where_sql = " AND ".join(where_parts)
            return self.delete(table, where_sql, list(filter_sql.values()))

        sql = f"DELETE FROM {self.quote_identifier(table)}"
        if filter_sql:
            sql += f" WHERE {self._marked_filter(filter_sql)}"
        return self.execute(sql, params or [])

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


# SQLTranslator moved to sql_translator.py (feature 3: the adapter module is the
# adapter contract and nothing else). Re-exported here because the sqlite,
# firebird, mssql and odbc adapters import it from this module, and a file move
# is not the place to churn their imports.
from tina4_python.database.sql_translator import SQLTranslator  # noqa: E402,F401
