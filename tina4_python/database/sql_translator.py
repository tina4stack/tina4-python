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


class SpatialNotSupportedError(NotImplementedError):
    """The selected database engine cannot honor the GIS contract."""


class SQLTranslator:
    """Cross-engine SQL translator.

    Each database adapter calls the rules it needs. Rules are composable
    and stateless — just string transforms.
    """

    SPATIAL_ENGINES = ("postgres", "postgresql")
    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

    @classmethod
    def supports_spatial(cls, engine: str) -> bool:
        """Return whether Tina4 has a spatial provider for ``engine``."""
        name = (engine or "").lower()
        name = cls.ENGINE_ALIASES.get(name, name)
        return name in cls.SPATIAL_ENGINES

    @classmethod
    def require_spatial(cls, engine: str, feature: str) -> str:
        """Return the normalized spatial engine or fail with an actionable error."""
        name = (engine or "unknown").lower()
        name = cls.ENGINE_ALIASES.get(name, name)
        if cls.supports_spatial(name):
            return name
        raise SpatialNotSupportedError(
            f"{feature} is not supported on the '{name}' database engine. "
            "Tina4 GIS support is PostGIS-first: use PostgreSQL with the "
            "PostGIS extension (CREATE EXTENSION postgis). Tina4 will not "
            "replace a spatial query with an approximate latitude/longitude query. "
            "If the application needs storage only and no GIS behavior, declare "
            "separate longitude and latitude FloatField columns instead."
        )

    @classmethod
    def identifier(cls, name: str, what: str = "column") -> str:
        """Validate an identifier before placing it in spatial SQL."""
        if not isinstance(name, str) or not cls._IDENTIFIER.fullmatch(name):
            raise ValueError(
                f"Spatial {what} name {name!r} is not a valid SQL identifier"
            )
        return name

    @staticmethod
    def _srid(srid) -> int:
        """Coerce the interpolated SRID to an integer."""
        if isinstance(srid, bool):
            raise ValueError(f"Spatial SRID must be an integer, got {srid!r}")
        try:
            value = int(srid)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Spatial SRID must be an integer, got {srid!r}") from error
        if value <= 0:
            raise ValueError(f"Spatial SRID must be positive, got {value}")
        return value

    @classmethod
    def point_column_type(cls, engine: str, srid: int = 4326) -> str:
        """Return PostGIS geography Point DDL."""
        cls.require_spatial(engine, "PointField")
        return f"geography(Point,{cls._srid(srid)})"

    @classmethod
    def spatial_index(cls, engine: str, table: str, column: str) -> str:
        """Return idempotent PostGIS GiST-index DDL."""
        cls.require_spatial(engine, "spatial index creation")
        table = cls.identifier(table, "table")
        column = cls.identifier(column)
        index = f"{table.replace('.', '_')}_{column}_gist"
        return f"CREATE INDEX IF NOT EXISTS {index} ON {table} USING GIST ({column})"

    @classmethod
    def point_literal(cls, engine: str, srid: int = 4326) -> str:
        """Return a bound PostGIS point expression in longitude/latitude order."""
        cls.require_spatial(engine, "spatial predicates")
        return f"ST_SetSRID(ST_MakePoint(?, ?), {cls._srid(srid)})::geography"

    @classmethod
    def within_distance(cls, engine: str, column: str, srid: int = 4326) -> str:
        """Return a bound radius predicate whose distance uses metres."""
        cls.require_spatial(engine, "within_distance()")
        column = cls.identifier(column)
        return f"ST_DWithin({column}, {cls.point_literal(engine, srid)}, ?)"

    @classmethod
    def distance(cls, engine: str, column: str, srid: int = 4326) -> str:
        """Return a bound spheroid-distance expression in metres."""
        cls.require_spatial(engine, "order_by_distance()")
        column = cls.identifier(column)
        return f"ST_Distance({column}, {cls.point_literal(engine, srid)})"

    @classmethod
    def distance_as(cls, engine: str, column: str, alias: str, srid: int = 4326) -> str:
        """Return an aliased bound distance expression for a SELECT list."""
        alias = cls.identifier(alias, "result alias")
        return f"{cls.distance(engine, column, srid)} AS {alias}"

    @classmethod
    def geometry_literal(cls, engine: str, form: str = "ewkt", srid: int = 4326) -> str:
        """Return a one-parameter PostGIS geometry expression."""
        cls.require_spatial(engine, "spatial predicates")
        if form == "ewkt":
            return "ST_GeogFromText(?)"
        if form == "geojson":
            return f"ST_SetSRID(ST_GeomFromGeoJSON(?), {cls._srid(srid)})::geography"
        raise ValueError(
            f"Spatial geometry form {form!r} is not supported; use 'ewkt' or 'geojson'"
        )

    @classmethod
    def intersects(cls, engine: str, column: str, form: str = "ewkt",
                   srid: int = 4326) -> str:
        """Return a bound PostGIS intersection predicate."""
        column = cls.identifier(column)
        return f"ST_Intersects({column}, {cls.geometry_literal(engine, form, srid)})"

    @classmethod
    def bbox(cls, engine: str, column: str, srid: int = 4326) -> str:
        """Return a bound PostGIS bounding-box predicate."""
        cls.require_spatial(engine, "bbox()")
        column = cls.identifier(column)
        return (
            f"ST_Intersects({column}, "
            f"ST_MakeEnvelope(?, ?, ?, ?, {cls._srid(srid)})::geography)"
        )

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

    # ── Literal-safe rewriting ──────────────────────────────────────
    #
    # A dialect rewrite (|| -> CONCAT, TRUE -> 1, ILIKE -> LOWER LIKE) must NEVER
    # touch text inside a string literal, a quoted identifier or a comment: a
    # column value of 'a||b', a label 'TRUE', or a LIKE pattern that mentions
    # ILIKE is DATA, not SQL. Each transform masks every literal/identifier/
    # comment to an opaque token, rewrites the masked SQL, then restores the
    # tokens, so the rewrite only ever sees real SQL structure. This is the same
    # guarantee the placeholder path already had; it now covers concat/bool/ilike.

    _MASK_RE = re.compile(r"\x00(\d+)\x00")

    @staticmethod
    def _mask_literals(sql: str):
        """Replace string literals, quoted identifiers and comments with opaque
        ``\\x00N\\x00`` tokens. Returns ``(masked_sql, literals)`` where
        ``literals[N]`` is the original text. Doubled-quote escapes (``''`` ``""``
        `````` `` ``````) are handled, so an embedded quote never ends the span early.
        """
        out = []
        literals = []
        i, n = 0, len(sql)
        while i < n:
            ch = sql[i]
            nxt = sql[i + 1] if i + 1 < n else ""
            if ch in ("'", '"', "`"):
                start = i
                i += 1
                while i < n:
                    if sql[i] == ch:
                        if i + 1 < n and sql[i + 1] == ch:
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                out.append(f"\x00{len(literals)}\x00")
                literals.append(sql[start:i])
                continue
            if ch == "-" and nxt == "-":
                start = i
                while i < n and sql[i] != "\n":
                    i += 1
                out.append(f"\x00{len(literals)}\x00")
                literals.append(sql[start:i])
                continue
            if ch == "/" and nxt == "*":
                start = i
                i += 2
                while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                    i += 1
                i = min(i + 2, n)
                out.append(f"\x00{len(literals)}\x00")
                literals.append(sql[start:i])
                continue
            out.append(ch)
            i += 1
        return "".join(out), literals

    @staticmethod
    def _restore_literals(masked: str, literals) -> str:
        """Inverse of :meth:`_mask_literals`."""
        return SQLTranslator._MASK_RE.sub(lambda m: literals[int(m.group(1))], masked)

    # A concat/ilike operand: a masked literal-or-identifier token, a simple
    # function call, a (qualified) identifier, a placeholder, or a number. The
    # function-call args exclude ``|`` so a nested ``||`` never splits the chain.
    _CONCAT_PRIMARY = (
        r"(?:\x00\d+\x00"
        r"|[A-Za-z_][\w$]*\s*\([^()|]*\)"
        r"|[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*"
        r"|:[A-Za-z_]\w*|\$\d+|\?|%s"
        r"|\d+(?:\.\d+)?)"
    )
    _CONCAT_CHAIN = re.compile(
        _CONCAT_PRIMARY + r"(?:\s*\|\|\s*" + _CONCAT_PRIMARY + r")+"
    )
    _ILIKE_RE = re.compile(
        r"(" + _CONCAT_PRIMARY + r")\s+ILIKE\s+(" + _CONCAT_PRIMARY + r")",
        re.IGNORECASE,
    )

    @staticmethod
    def concat_pipes_to_func(sql: str) -> str:
        """Convert ``||`` string concatenation to ``CONCAT(...)`` for MySQL/MSSQL.

        Rewrites ONLY ``||`` operators joining expression operands OUTSIDE any
        string literal or comment, and only the operand chain — never the whole
        statement::

            SELECT a || b FROM t   ->  SELECT CONCAT(a, b) FROM t
            WHERE data = 'a||b'    ->  WHERE data = 'a||b'   (literal untouched)
        """
        if "||" not in sql:
            return sql
        masked, literals = SQLTranslator._mask_literals(sql)
        if "||" not in masked:
            return sql  # every || was inside a literal or comment
        rewritten = SQLTranslator._CONCAT_CHAIN.sub(
            lambda m: "CONCAT(" + ", ".join(re.split(r"\s*\|\|\s*", m.group(0))) + ")",
            masked,
        )
        return SQLTranslator._restore_literals(rewritten, literals)

    @staticmethod
    def boolean_to_int(sql: str) -> str:
        """Convert bare ``TRUE``/``FALSE`` to ``1``/``0`` for engines without a
        boolean type. A ``TRUE``/``FALSE`` INSIDE a string literal is data and is
        left untouched (``WHERE label = 'TRUE'`` is preserved)."""
        if not re.search(r"\b(?:TRUE|FALSE)\b", sql, re.IGNORECASE):
            return sql
        masked, literals = SQLTranslator._mask_literals(sql)
        masked = re.sub(r"\bTRUE\b", "1", masked, flags=re.IGNORECASE)
        masked = re.sub(r"\bFALSE\b", "0", masked, flags=re.IGNORECASE)
        return SQLTranslator._restore_literals(masked, literals)

    @staticmethod
    def ilike_to_like(sql: str) -> str:
        """Convert ``col ILIKE pattern`` to ``LOWER(col) LIKE LOWER(pattern)`` for
        engines without ``ILIKE``. The pattern operand is captured whole (a
        multi-word ``'%two words%'`` survives), and an ``ILIKE`` INSIDE a string
        literal is left untouched."""
        if "ilike" not in sql.lower():
            return sql
        masked, literals = SQLTranslator._mask_literals(sql)
        rewritten = SQLTranslator._ILIKE_RE.sub(
            lambda m: f"LOWER({m.group(1)}) LIKE LOWER({m.group(2)})", masked
        )
        return SQLTranslator._restore_literals(rewritten, literals)

    @staticmethod
    def auto_increment_syntax(sql: str, engine: str) -> str:
        """Translate AUTOINCREMENT across engines in DDL."""
        if engine == "mysql":
            return sql.replace("AUTOINCREMENT", "AUTO_INCREMENT")
        if engine == "postgresql":
            # INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
            # BIGINT  PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
            # A 64-bit key needs BIGSERIAL: a plain BIGINT with the keyword merely
            # stripped has no sequence and cannot auto-increment (an insert with no
            # id then fails the NOT NULL primary key).
            sql = re.sub(
                r"\bBIGINT\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                "BIGSERIAL PRIMARY KEY",
                sql, flags=re.IGNORECASE,
            )
            sql = re.sub(
                r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                "SERIAL PRIMARY KEY",
                sql, flags=re.IGNORECASE,
            )
            # Any leftover AUTOINCREMENT is not valid PostgreSQL syntax.
            sql = re.sub(r"\s*\bAUTOINCREMENT\b", "", sql, flags=re.IGNORECASE)
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

    # Hard per-statement bind-parameter ceiling per engine. 0 means "never
    # collapse a batch on this engine". See tests/fixtures/batch_write_contract.json,
    # which is byte-identical in all four frameworks and is the source of these
    # numbers.
    MAX_BIND_PARAMS = {
        "sqlite": 999,
        "postgres": 65535,
        "mysql": 65535,
        "mssql": 2100,
        "firebird": 0,
        "odbc": 0,
        "mongodb": 0,
    }

    # The four frameworks do not agree on what an engine calls itself - Python
    # and PHP report "postgresql", Ruby and Node report "postgres". Without
    # normalising, the cap lookup misses and the collapse silently does nothing
    # on the engine with the largest win. Caught by a live run, not by reading.
    ENGINE_ALIASES = {
        "postgresql": "postgres",
        "pgsql": "postgres",
        "sqlite3": "sqlite",
        "sqlserver": "mssql",
        "sqlsrv": "mssql",
        "mariadb": "mysql",
    }

    _INSERT_VALUES = re.compile(
        r"^\s*INSERT\s+INTO\s+.+?\s+VALUES\s*\((?P<values>[^()]*)\)\s*$",
        re.IGNORECASE | re.DOTALL,
    )

    # Engines whose LAST_INSERT_ID() reports the FIRST generated id of a
    # multi-row INSERT rather than the last. Verified live, not assumed: a
    # 3-row insert into a fresh MySQL table reports 1 while MAX(id) is 3.
    # SQLite (last_insert_rowid), PostgreSQL (lastval) and MSSQL already report
    # the last, so collapsing a batch does not change them.
    FIRST_ID_ENGINES = ("mysql",)

    @staticmethod
    def batch_last_id(reported_id, rows_in_chunk, engine):
        """Normalise a collapsed batch's last id to the LAST row's id.

        A row-at-a-time batch reports the last row's id simply because the last
        statement inserted the last row. Collapsing rows into one statement
        changes that on any engine that reports the FIRST generated id, so this
        restores the contract instead of quietly redefining it.

        The ids generated by a single multi-row INSERT are consecutive, so the
        last is ``first + rows - 1``. (With a non-default
        ``auto_increment_increment`` they are not, which is why this is applied
        only to the engines that actually need it rather than everywhere.)
        """
        name = (engine or "").lower()
        name = SQLTranslator.ENGINE_ALIASES.get(name, name)
        if name not in SQLTranslator.FIRST_ID_ENGINES:
            return reported_id
        try:
            return int(reported_id) + max(int(rows_in_chunk), 1) - 1
        except (TypeError, ValueError):
            return reported_id

    @staticmethod
    def build_batch_inserts(sql, params_list, engine):
        """Collapse a row-at-a-time INSERT batch into chunked multi-row VALUES.

        A batch that loops one INSERT per row pays a full network round-trip per
        row, and the round-trip - not SQL building - is the entire cost of a
        batch write. Measured over 500 rows: PostgreSQL 9848ms row-at-a-time
        against 15.8ms as a single multi-row statement (625x), MySQL 216x,
        MSSQL 121x.

        Returns a list of ``(sql, params)`` statements to run INSTEAD of the
        loop, or an EMPTY list meaning "not collapsible - keep looping". Empty
        is always a correct answer, so anything unrecognised falls back to the
        behaviour that was already there rather than guessing.

        Pure: no I/O, no engine contact. The chunking rules are therefore
        checkable without a database, and the live-engine runners prove the
        rows land correctly.
        """
        rows = params_list or []
        if len(rows) < 2:
            return []

        name = (engine or "").lower()
        name = SQLTranslator.ENGINE_ALIASES.get(name, name)
        cap = SQLTranslator.MAX_BIND_PARAMS.get(name, 0)
        if cap <= 0:
            # Firebird has no multi-row VALUES syntax; ODBC's real ceiling
            # depends on the driver behind it. Emitting SQL the engine cannot
            # parse to save a round-trip is not a trade worth making.
            return []

        upper = sql.upper()
        # A collapsed statement returns N rows where the caller expects one, and
        # conflict arbitration changes once rows share a statement.
        if "RETURNING" in upper or "ON CONFLICT" in upper or "ON DUPLICATE KEY" in upper:
            return []

        match = SQLTranslator._INSERT_VALUES.match(sql)
        if match is None:
            return []

        values = match.group("values")
        # Every slot must be a bare placeholder. `now()` repeated per row inside
        # one statement is not the same write as `now()` evaluated per statement.
        slots = [slot.strip() for slot in values.split(",")]
        if not slots or any(slot != "?" for slot in slots):
            return []

        columns = len(slots)
        if any(len(params) != columns for params in rows):
            return []

        chunk_rows = max(1, cap // columns)
        if chunk_rows < 2:
            return []

        head = sql[: match.start("values") - 1].rstrip()
        one_row = "(" + ", ".join(["?"] * columns) + ")"

        statements = []
        for start in range(0, len(rows), chunk_rows):
            chunk = rows[start:start + chunk_rows]
            flat = []
            for params in chunk:
                flat.extend(params)
            statements.append((head + " " + ", ".join([one_row] * len(chunk)), flat))
        return statements


# QueryCache lives in tina4_python.core.cache (as ``Cache``). Re-exported here
# under the QueryCache alias for cross-framework naming parity with PHP/Ruby/Node.
from tina4_python.core.cache import Cache as QueryCache  # noqa: E402,F401
