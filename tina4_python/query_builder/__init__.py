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

    def __init__(self, table: str, db=None, primary_key: str = None):
        """Private-ish constructor. Use from_table() or ORM.query()."""
        self._table = table
        self._db = db
        self._columns: list[str] = ["*"]
        # A selected column can carry bound values too (select_distance binds
        # the reference point). SELECT is the FIRST clause to_sql() emits, so
        # these bind before WHERE, HAVING and ORDER BY.
        self._select_params: list = []
        self._wheres: list[tuple[str, str]] = []
        self._params: list = []
        self._joins: list[str] = []
        self._group_by_cols: list[str] = []
        self._havings: list[str] = []
        self._having_params: list = []
        self._order_by_cols: list[str] = []
        # ORDER BY can carry bound values too (spatial distance ordering binds
        # the reference point). They are appended LAST because ORDER BY is the
        # last clause in to_sql() — placeholder order must match clause order.
        self._order_by_params: list = []
        # The table's primary-key COLUMN, when the builder came from a model.
        # Used as the tie-break that makes distance ordering deterministic.
        self._primary_key: str | None = primary_key
        self._limit_val: int | None = None
        self._offset_val: int | None = None

    @staticmethod
    def from_table(table_name: str, db=None, primary_key: str = None) -> "QueryBuilder":
        """Create a QueryBuilder for a table.

        Args:
            table_name: The database table name.
            db: Optional database connection (Database or adapter).
            primary_key: The table's primary-key column. ``ORM.query()`` fills
                this in; it is what lets ``order_by_distance()`` add a stable
                tie-break so pagination over equidistant rows cannot loop or
                skip. Pass it yourself on a raw builder to get the same
                guarantee.

        Returns:
            A new QueryBuilder instance.
        """
        return QueryBuilder(table_name, db, primary_key)

    def select(self, *columns: str) -> "QueryBuilder":
        """Set the columns to select.

        REPLACES the column list, so any values bound by a previous
        :meth:`select_distance` are discarded with it — an orphaned bound value
        with no placeholder left to fill would silently shift every parameter
        after it. Call ``select()`` first, then ``select_distance()``.

        Args:
            *columns: Column names (default is '*').

        Returns:
            self for chaining.
        """
        if columns:
            self._columns = list(columns)
            self._select_params = []
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

    # ── Spatial predicates ──────────────────────────────────────────
    # These never write PostGIS SQL here. Every fragment comes from the
    # SQLTranslator dialect seam (tina4_python/database/adapter.py), so adding
    # MySQL or MSSQL spatial later touches that file and not this one. Point
    # coordinates and the radius are ALWAYS bound as parameters — no user value
    # is ever formatted into the SQL string.

    def within_distance(self, column: str, point, metres: float) -> "QueryBuilder":
        """Restrict to rows whose point column is within ``metres`` of ``point``.

        Emits ``ST_DWithin(<column>, ST_SetSRID(ST_MakePoint(?, ?), <srid>)::geography, ?)``
        on PostGIS — an index-using predicate, not a distance filter, so the GiST
        index created by ``create_table()`` actually gets used.

            ChargePoint.query().within_distance("location", (18.42, -33.92), 5000).get()

        Args:
            column: The PointField's column name.
            point: A ``Point``, ``(lon, lat)`` tuple, WKT/EWKT string, or GeoJSON
                dict — the same shapes ``PointField`` accepts.
            metres: Radius in metres (the column is ``geography``, so distances
                are metres on the spheroid — no projection needed).

        Returns:
            self for chaining.

        Raises:
            SpatialNotSupportedError: naming the engine, when it has no spatial
                support. Raised HERE, at the call site, rather than at get() —
                so the traceback points at the query you wrote.
        """
        from tina4_python.database.adapter import SQLTranslator
        from tina4_python.orm.point import Point

        location = Point.parse(point)
        radius = float(metres)
        engine = self._engine()
        self._wheres.append(
            ("AND", SQLTranslator.within_distance(engine, column, location.srid))
        )
        self._params.extend([location.lon, location.lat, radius])
        return self

    def intersects(self, column: str, geometry) -> "QueryBuilder":
        """Restrict to rows whose geometry column intersects ``geometry``.

        The geofence predicate — "which devices are inside this zone?" — and
        the general form of :meth:`bbox`. Emits
        ``ST_Intersects(<column>, ST_GeogFromText(?))`` on PostGIS, with the
        whole geometry bound as ONE parameter, so no coordinate is ever
        formatted into the SQL::

            zone = "POLYGON((17.5 -34.5, 19.5 -34.5, 19.5 -33, 17.5 -33, 17.5 -34.5))"
            ChargePoint.query().intersects("location", zone).get()

        Args:
            column: The PointField's column name.
            geometry: A ``Point``, a ``(lon, lat)`` pair, a WKT/EWKT string of
                any geometry type (polygon, multipolygon, line...), or a GeoJSON
                geometry / Feature dict. A GeoJSON dict is bound as JSON and
                parsed by the engine, so there is no client-side WKT writer to
                get wrong.

        Returns:
            self for chaining.

        Raises:
            ValueError: naming the value, when it is not a readable geometry.
            SpatialNotSupportedError: naming the engine, when it has no spatial
                support. Raised HERE, at the call site, not at get().
        """
        from tina4_python.database.adapter import SQLTranslator
        from tina4_python.orm.point import DEFAULT_SRID, geometry_binding

        bound_value, form = geometry_binding(geometry)
        engine = self._engine()
        self._wheres.append(
            ("AND", SQLTranslator.intersects(engine, column, form, DEFAULT_SRID))
        )
        self._params.append(bound_value)
        return self

    def bbox(self, column: str, min_lon: float, min_lat: float,
             max_lon: float, max_lat: float) -> "QueryBuilder":
        """Restrict to rows inside the ``(min_lon, min_lat)``–``(max_lon, max_lat)`` box.

        The map-viewport query. Corners are ``(lon, lat)`` like every other
        coordinate pair in Tina4, south-west corner first::

            ChargePoint.query().bbox("location", 17.5, -34.5, 19.5, -33.0).get()

        All four ordinates are bound as parameters.

        Args:
            column: The PointField's column name.
            min_lon: West edge. min_lat: South edge.
            max_lon: East edge. max_lat: North edge.

        Returns:
            self for chaining.

        Raises:
            ValueError: if an ordinate is not a finite number, is out of the
                WGS 84 range, or if min > max on either axis (an inside-out box
                silently matches nothing, so it fails loud instead). A box that
                crosses the antimeridian cannot be expressed this way — pass
                two boxes, or use :meth:`intersects` with a polygon.
            SpatialNotSupportedError: naming the engine, when it has no spatial
                support.
        """
        import math

        from tina4_python.database.adapter import SQLTranslator
        from tina4_python.orm.point import DEFAULT_SRID

        corners = {
            "min_lon": min_lon, "min_lat": min_lat,
            "max_lon": max_lon, "max_lat": max_lat,
        }
        ordinates = {}
        for label, raw in corners.items():
            try:
                number = float(raw)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"bbox(): {label} must be a number, got {raw!r}"
                ) from e
            if not math.isfinite(number):
                raise ValueError(f"bbox(): {label} must be finite, got {raw!r}")
            bound = 180.0 if label.endswith("lon") else 90.0
            if not -bound <= number <= bound:
                raise ValueError(
                    f"bbox(): {label} {number} is out of range for SRID "
                    f"{DEFAULT_SRID} (-{bound:g}..{bound:g}). Corners are "
                    f"(lon, lat) — did you pass latitude first?"
                )
            ordinates[label] = number

        if ordinates["min_lon"] > ordinates["max_lon"]:
            raise ValueError(
                f"bbox(): min_lon {ordinates['min_lon']} is east of max_lon "
                f"{ordinates['max_lon']}. An inside-out box matches nothing. A "
                f"box crossing the antimeridian must be given as two boxes, or "
                f"as a polygon through intersects()."
            )
        if ordinates["min_lat"] > ordinates["max_lat"]:
            raise ValueError(
                f"bbox(): min_lat {ordinates['min_lat']} is north of max_lat "
                f"{ordinates['max_lat']}. An inside-out box matches nothing."
            )

        engine = self._engine()
        self._wheres.append(("AND", SQLTranslator.bbox(engine, column, DEFAULT_SRID)))
        self._params.extend([
            ordinates["min_lon"], ordinates["min_lat"],
            ordinates["max_lon"], ordinates["max_lat"],
        ])
        return self

    def select_distance(self, column: str, point, alias: str = "metres") -> "QueryBuilder":
        """Also select the distance in metres from ``point`` to each row.

        "How far away is it?" — the value a list of nearby things is usually
        rendered with. Adds ``ST_Distance(<column>, <point>) AS <alias>`` to the
        SELECT list with the coordinates bound, so the number comes back beside
        the row instead of needing a second round trip::

            QueryBuilder.from_table("charge_point", db) \\
                .select_distance("location", (18.42, -33.92)) \\
                .within_distance("location", (18.42, -33.92), 5000) \\
                .order_by_distance("location", (18.42, -33.92)) \\
                .get()
            # rows carry a 'metres' key

        The bound coordinates go into a separate ``_select_params`` list that
        :meth:`_all_params` puts FIRST, because SELECT is the first clause
        ``to_sql()`` emits — placeholder order must match clause order.

        Note ``count()`` is unaffected: it replaces the whole SELECT list with
        ``COUNT(*)``, so it drops these placeholders and their values together.

        Args:
            column: The PointField's column name.
            point: A ``Point``, ``(lon, lat)`` tuple, WKT/EWKT string, or GeoJSON dict.
            alias: Result column name. Validated as a SQL identifier because it
                IS interpolated; the coordinates never are.

        Returns:
            self for chaining.

        Raises:
            ValueError: on a bad point value or an alias that is not a plain
                identifier.
            SpatialNotSupportedError: naming the engine, when it has no spatial
                support.
        """
        from tina4_python.database.adapter import SQLTranslator
        from tina4_python.orm.point import Point

        location = Point.parse(point)
        engine = self._engine()
        expression = SQLTranslator.distance_as(engine, column, alias, location.srid)
        self._columns = self._columns + [expression]
        self._select_params.extend([location.lon, location.lat])
        return self

    def order_by_distance(self, column: str, point, descending: bool = False,
                          tie_break: str | bool = None) -> "QueryBuilder":
        """Order rows by distance from ``point`` (nearest first by default).

        Emits ``ORDER BY ST_Distance(<column>, ST_SetSRID(ST_MakePoint(?, ?), <srid>))``
        on PostGIS, with the coordinates bound as parameters.

            ChargePoint.query().order_by_distance("location", (18.42, -33.92)).limit(5).get()

        **Ties break on a stable key.** Distance alone is not a total order:
        two rows exactly the same distance away can come back in either order,
        and PostgreSQL's sort is not stable — a plain ``UPDATE`` elsewhere in
        the table moves rows in the heap and silently changes the result order.
        Paging over that skips rows and repeats others. So the primary key is
        appended as a secondary sort key whenever the builder knows it
        (``ORM.query()`` always supplies it).

        Args:
            column: The PointField's column name.
            point: A ``Point``, ``(lon, lat)`` tuple, WKT/EWKT string, or GeoJSON dict.
            descending: Furthest first when True (the tie-break follows the
                same direction, so ``descending=True`` is the exact reverse).
            tie_break: Column that breaks exact distance ties. ``None``
                (default) uses the builder's primary key — set for every
                ``ORM.query()``, unset for a bare ``from_table()`` unless you
                pass ``primary_key=``. A column name overrides it; ``False``
                switches the tie-break off and accepts engine-defined order.

        Returns:
            self for chaining.

        Raises:
            SpatialNotSupportedError: naming the engine, when it has no spatial support.
        """
        from tina4_python.database.adapter import SQLTranslator
        from tina4_python.orm.point import Point

        location = Point.parse(point)
        engine = self._engine()
        expression = SQLTranslator.distance(engine, column, location.srid)
        self._order_by_cols.append(f"{expression} DESC" if descending else expression)
        self._order_by_params.extend([location.lon, location.lat])

        key = self._primary_key if tie_break is None else tie_break
        if key:
            key = SQLTranslator.identifier(key, "tie-break column")
            self._order_by_cols.append(f"{key} DESC" if descending else key)
        return self

    def _engine(self) -> str:
        """Resolve the engine name for dialect selection (needs a connection)."""
        self._ensure_db()
        try:
            return self._db.get_database_type() or ""
        except AttributeError:
            return ""

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

        v3.13.39: with no ``.limit()`` set, get() returns ALL matching rows.
        It previously applied a silent default ``LIMIT 100`` — a data-loss-
        on-read footgun where the 101st row vanished without a trace. An
        explicit ``.limit(n)`` is still honoured; ``to_sql()`` never injects
        a default LIMIT either. Pass ``limit=0`` to ``db.fetch`` (its "no
        truncation" sentinel) when no limit was requested.

        Returns:
            DatabaseResult from db.fetch().
        """
        self._ensure_db()
        sql = self.to_sql()
        all_params = self._all_params()

        return self._db.fetch(
            sql,
            all_params or None,
            self._limit_val if self._limit_val is not None else 0,
            self._offset_val if self._offset_val is not None else 0,
        )

    def first(self) -> dict | None:
        """Execute the query and return a single row.

        Returns:
            A dict for the first matching row, or None.
        """
        self._ensure_db()
        sql = self.to_sql()
        all_params = self._all_params()

        return self._db.fetch_one(sql, all_params or None)

    def count(self) -> int:
        """Execute the query and return the row count.

        ORDER BY is dropped for the count: it cannot change ``COUNT(*)``, and
        PostgreSQL/MSSQL reject a non-aggregated ORDER BY expression alongside
        an aggregate — so ``.order_by(...).count()`` used to fail on those
        engines. Dropping it also lets ``.order_by_distance(...).count()`` work.

        Returns:
            Number of matching rows.
        """
        self._ensure_db()

        # Build a count query by replacing columns, without the ORDER BY clause
        # (and therefore without its bound parameters).
        original_columns = self._columns
        original_order = self._order_by_cols
        self._columns = ["COUNT(*) as cnt"]
        self._order_by_cols = []
        try:
            sql = self.to_sql()
        finally:
            self._columns = original_columns
            self._order_by_cols = original_order

        # Only WHERE and HAVING placeholders survive: replacing the SELECT list
        # dropped any select_distance() placeholders, and clearing ORDER BY
        # dropped its own. Binding either here would shift every value.
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

    def to_mongo(self) -> dict:
        """Convert the fluent builder state into a MongoDB-compatible query.

        Returns:
            A dict with keys: filter, projection, sort, limit, skip.
            Only non-empty keys are included.
        """
        result = {}

        # -- projection --
        if self._columns != ["*"]:
            result["projection"] = {col.strip(): 1 for col in self._columns}

        # -- filter --
        if self._wheres:
            param_index = 0
            and_conditions = []
            or_conditions = []

            for i, (connector, condition) in enumerate(self._wheres):
                mongo_cond, param_index = self._parse_condition_to_mongo(
                    condition, param_index
                )
                if i == 0 or connector == "AND":
                    and_conditions.append(mongo_cond)
                else:
                    or_conditions.append(mongo_cond)

            if or_conditions:
                # Merge AND conditions into a single dict, then $or with OR ones
                and_merged = self._merge_mongo_conditions(and_conditions)
                all_branches = [and_merged] + or_conditions
                result["filter"] = {"$or": all_branches}
            else:
                result["filter"] = self._merge_mongo_conditions(and_conditions)

        # -- sort --
        if self._order_by_cols:
            sort_list = []
            for expr in self._order_by_cols:
                parts = expr.strip().split()
                field = parts[0]
                direction = -1 if len(parts) > 1 and parts[1].upper() == "DESC" else 1
                sort_list.append((field, direction))
            result["sort"] = sort_list

        # -- limit / skip --
        if self._limit_val is not None:
            result["limit"] = self._limit_val
        if self._offset_val is not None:
            result["skip"] = self._offset_val

        return result

    def _parse_condition_to_mongo(self, condition: str, param_index: int) -> tuple[dict, int]:
        """Parse a single SQL condition string into a MongoDB filter dict.

        Returns:
            (mongo_filter_dict, updated_param_index)
        """
        import re

        cond = condition.strip()

        # IS NOT NULL
        match = re.match(r"^(\w+)\s+IS\s+NOT\s+NULL$", cond, re.IGNORECASE)
        if match:
            return {match.group(1): {"$exists": True, "$ne": None}}, param_index

        # IS NULL
        match = re.match(r"^(\w+)\s+IS\s+NULL$", cond, re.IGNORECASE)
        if match:
            return {match.group(1): {"$exists": False}}, param_index

        # NOT IN
        match = re.match(r"^(\w+)\s+NOT\s+IN\s*\(\s*\?\s*\)$", cond, re.IGNORECASE)
        if match:
            val = self._params[param_index] if param_index < len(self._params) else []
            values = val if isinstance(val, list) else [val]
            return {match.group(1): {"$nin": values}}, param_index + 1

        # IN
        match = re.match(r"^(\w+)\s+IN\s*\(\s*\?\s*\)$", cond, re.IGNORECASE)
        if match:
            val = self._params[param_index] if param_index < len(self._params) else []
            values = val if isinstance(val, list) else [val]
            return {match.group(1): {"$in": values}}, param_index + 1

        # LIKE
        match = re.match(r"^(\w+)\s+LIKE\s+\?$", cond, re.IGNORECASE)
        if match:
            val = self._params[param_index] if param_index < len(self._params) else ""
            # Convert SQL LIKE pattern to regex: % -> .*, _ -> .
            pattern = str(val).replace("%", ".*").replace("_", ".")
            return {match.group(1): {"$regex": pattern, "$options": "i"}}, param_index + 1

        # Comparison operators: >=, <=, <>, !=, >, <, =
        match = re.match(r"^(\w+)\s*(>=|<=|<>|!=|>|<|=)\s*\?$", cond)
        if match:
            field = match.group(1)
            op = match.group(2)
            val = self._params[param_index] if param_index < len(self._params) else None
            op_map = {
                "=": None,
                "!=": "$ne",
                "<>": "$ne",
                ">": "$gt",
                ">=": "$gte",
                "<": "$lt",
                "<=": "$lte",
            }
            mongo_op = op_map.get(op)
            if mongo_op is None:
                return {field: val}, param_index + 1
            return {field: {mongo_op: val}}, param_index + 1

        # v3.13.39: no silent $where fallback. Previously an unparseable
        # condition was wrapped as ``{'$where': <raw condition string>}`` — a
        # raw-JS sink that is both injection-shaped (the WHERE string runs as
        # JavaScript on the server) and silently different semantics from the
        # SQL the caller wrote. Fail loud instead: name the clause so the
        # caller fixes it rather than shipping a surprise $where.
        raise ValueError(
            f"QueryBuilder.to_mongo(): cannot translate WHERE clause to a "
            f"MongoDB filter: {cond!r}. Supported forms: '<field> <op> ?' "
            f"(=, !=, <>, >, >=, <, <=), '<field> LIKE ?', "
            f"'<field> [NOT] IN (?)', '<field> IS [NOT] NULL'. "
            f"Rewrite the condition in one of those forms (to_mongo() will "
            f"not silently emit a raw $where JavaScript expression)."
        )

    @staticmethod
    def _merge_mongo_conditions(conditions: list[dict]) -> dict:
        """Merge a list of single-field mongo condition dicts into one dict.

        If the same field appears in multiple conditions, wraps them in $and.
        """
        if len(conditions) == 1:
            return conditions[0]

        merged = {}
        conflicts = []
        for cond in conditions:
            for key, val in cond.items():
                if key in merged:
                    conflicts.append(cond)
                    break
                else:
                    merged[key] = val
            else:
                continue
            # If we broke out due to conflict, don't add to merged
            pass

        if conflicts:
            return {"$and": conditions}
        return merged

    # -- Private helpers --

    def _all_params(self) -> list:
        """Bound values in clause order: SELECT, WHERE, HAVING, then ORDER BY.

        Must match the clause order to_sql() emits — a placeholder list out of
        step with the SQL silently binds the wrong values.
        """
        return (
            self._select_params
            + self._params
            + self._having_params
            + self._order_by_params
        )

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
