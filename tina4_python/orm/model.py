# Tina4 ORM Model — SQL-first Active Record.
"""
The ORM base class. Models inherit from ORM and define fields.
SQL-first: you write the queries, ORM maps and manages the data.

    class User(ORM):
        table_name = "users"
        id = Field(int, primary_key=True)
        name = Field(str, required=True)
        email = Field(str)
"""
from __future__ import annotations
import re
from typing import TYPE_CHECKING, Self
from tina4_python.orm.fields import Field, RelationshipDescriptor
from tina4_python.orm.collection import ModelCollection
from tina4_python.core.cache import Cache

# Module-level query cache — shared across ALL ORM models, so a write on one
# model busts a cross-table query cached on another (CACHE-DEC-01).
_query_cache = Cache(default_ttl=0, max_size=500)

# Identifier after a FROM / JOIN keyword (optionally schema-qualified and quoted).
# Used to tag a cached query by every table it touches so a write to any of them
# busts it (CACHE-DEC-01). An alias after the table name is deliberately ignored.
_CACHE_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+([`"\[]?[A-Za-z_][\w$]*[`"\]]?(?:\.[`"\[]?[A-Za-z_][\w$]*[`"\]]?)?)',
    re.IGNORECASE,
)


def _tables_in_sql(sql: str) -> set[str]:
    """Table names a query reads FROM / JOINs — lowercased, schema-stripped.

    Best-effort: for each FROM/JOIN keyword it takes the following identifier,
    drops any quoting (backticks, double quotes, square brackets) and schema
    prefix (public.users -> users), and ignores the alias. A cached query is
    tagged with these tables so a write to any one of them invalidates it.
    """
    tables: set[str] = set()
    for match in _CACHE_TABLE_RE.finditer(sql or ""):
        name = match.group(1).strip('`"[]')
        if "." in name:
            name = name.rsplit(".", 1)[-1].strip('`"[]')
        if name:
            tables.add(name.lower())
    return tables

# Global database reference — set via bind_database()
_database = None
# Named database connections registry
_databases: dict[str, object] = {}


def bind_database(db, name: str = None):
    """Bind a Database instance to ORM models.

    Args:
        db: Database instance to bind.
        name: Optional name for the connection (e.g., "audit", "analytics").
              If None, sets the global default used by all models without _db.

    Usage:
        bind_database(db_main)                    # default for all models
        bind_database(db_audit, name="audit")     # named connection

        # Decorator style — class is returned unchanged:
        @bind_database(db)
        class User(ORM):
            ...

        class AuditLog(ORM):
            _db = "audit"  # uses the named connection
    """
    global _database
    if name is None:
        _database = db
    else:
        _databases[name] = db

    # Return a pass-through decorator so @bind_database(db) syntax works.
    # Without this the decorator would set the class to None.
    def _decorator(cls):
        return cls

    return _decorator


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase: 'first_name' -> 'firstName'."""
    name = name.lower()
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case: 'firstName' -> 'first_name'."""
    result = []
    for c in name:
        if c.isupper() and result:
            result.append("_")
        result.append(c.lower())
    return "".join(result)


# REL-EAGER-UNBOUNDED: the eager loader builds one placeholder per parent PK in
# the ``WHERE fk IN (...)`` list. Split the parent PKs into chunks of this size
# so a very large parent set never yields an unbounded IN list (a query-size /
# driver parameter-limit risk); each chunk is one query. It is comfortably under
# SQLite's default 999-variable limit while leaving room for other bound params.
_EAGER_IN_CHUNK = 500
# Rows fetched per page when reading a relation's rows, so no relation is ever
# silently truncated at a fixed cap.
_EAGER_PAGE_SIZE = 1000


def _chunk_list(seq: list, size: int):
    """Yield successive ``size``-length slices of ``seq``."""
    for start in range(0, len(seq), size):
        yield seq[start:start + size]


class ORMMeta(type):
    """Metaclass that collects Field definitions and relationship descriptors."""

    def __new__(mcs, name, bases, namespace):
        from tina4_python.orm.fields import (
            ForeignKeyField, BelongsToDescriptor, HasManyDescriptor,
        )

        fields = {}
        relationships = {}
        for key, value in list(namespace.items()):
            if isinstance(value, Field):
                value.name = key
                if value.column is None:
                    value.column = key
                fields[key] = value
            elif isinstance(value, RelationshipDescriptor):
                value.attr_name = key
                relationships[key] = value

        # ── Auto-wire ForeignKeyField relationships ─────────────────
        # For each ForeignKeyField, create:
        #   1. belongs_to on this model  (e.g. user_id → self.user)
        #   2. has_many   on the referenced model  (e.g. User.posts)
        for key, field in list(fields.items()):
            if not isinstance(field, ForeignKeyField) or field.references is None:
                continue

            # Derive belongs_to accessor name: "user_id" → "user", "post" → "post"
            belongs_name = key[:-3] if key.endswith("_id") else key
            if belongs_name not in namespace and belongs_name not in relationships:
                model_ref = (
                    field.references.__name__
                    if hasattr(field.references, "__name__")
                    else str(field.references)
                )
                bt = BelongsToDescriptor(model_ref, foreign_key=key)
                bt.attr_name = belongs_name
                relationships[belongs_name] = bt
                namespace[belongs_name] = bt

            # Register has_many on the referenced model (class reference only;
            # string references require the target to already exist in globals).
            target = None
            if hasattr(field.references, "_fields"):        # already an ORM class
                target = field.references
            elif isinstance(field.references, str):
                # Try to find the named model in existing ORM subclasses
                from tina4_python.orm.model import ORM as _ORM  # noqa: forward-ref guard
                def _find(model_name):
                    for sub in _ORM.__subclasses__():
                        if sub.__name__ == model_name:
                            return sub
                    return None
                target = _find(field.references)

            if target is not None:
                hm_name = field.related_name or (name.lower() + "s")
                if not hasattr(target, hm_name):
                    hm = HasManyDescriptor(name, foreign_key=key)
                    hm.attr_name = hm_name
                    setattr(target, hm_name, hm)
                    if hasattr(target, "_relationships"):
                        target._relationships[hm_name] = hm

        namespace["_fields"] = fields
        namespace["_relationships"] = relationships
        # Spatial (PointField) attribute names, resolved once at class creation.
        # to_dict() and create_table() branch on this, so a model with no
        # geometry pays a single falsy check and nothing else.
        namespace["_spatial_fields"] = tuple(
            key for key, f in fields.items() if getattr(f, "kind", None) == "PointField"
        )
        cls = super().__new__(mcs, name, bases, namespace)

        # Auto-register for CRUD if flagged
        if namespace.get("auto_crud", False) and name != "ORM":
            try:
                from tina4_python.crud import AutoCrud
                AutoCrud.register(cls)
            except ImportError:
                pass

        return cls


class ORM(metaclass=ORMMeta):
    """SQL-first Active Record base class.

    Features:
    - CRUD: save(), load(), delete(), select(), find()
    - Soft delete: is_deleted field (0/1), with_trashed(), restore(), force_delete()
    - Scopes: reusable query filters
    - Relationships: has_one(), has_many()
    - Validation from field definitions
    """

    table_name: str = ""
    soft_delete: bool = False  # Set True to enable soft delete
    field_mapping: dict[str, str] = {}  # {"python_attribute": "db_column"}
    auto_map: bool = True  # No-op in Python (snake_case matches DB); exists for cross-language parity
    auto_crud: bool = False  # Set True to auto-register CRUD routes
    _db: str | object | None = None  # Per-model database override
    _fields: dict[str, Field] = {}
    # PointField attribute names on this model, filled by ORMMeta. Empty for
    # every non-spatial model, which is what keeps the spatial branches free.
    _spatial_fields: tuple[str, ...] = ()
    # Last save() failure cause (validation message or DB error). None when
    # the most recent save() succeeded. Mirrors db.get_error() so a caller
    # that checks ``if not model.save():`` can still recover the real cause
    # via ``model.get_error()`` / ``model.last_error`` — the failure never
    # vanishes silently.
    last_error: str | None = None

    def __init__(self, data: dict | str = None, **kwargs):
        # Initialize relationship cache
        self._rel_cache = {}

        # #165: track which fields the caller EXPLICITLY assigned (via
        # constructor data/kwargs, _populate, or ``model.field = x``). save()
        # uses this to OMIT an unset column from an INSERT — so a NOT NULL
        # DEFAULT column gets its DB default instead of an explicit NULL —
        # while still writing NULL for a field the caller set to None. The
        # defaults seeded below go through object.__setattr__ so they are NOT
        # counted as caller assignments.
        self._assigned_fields = set()

        # Set defaults from field definitions.
        # v3.13.11 (issue #50): callable defaults are evaluated *per
        # instance* so per-row timestamps (e.g. ``default=lambda:
        # datetime.now()``) actually differ. Pre-v3.13.11 the function
        # object reached the driver verbatim and blew up with
        # ``can't adapt type 'function'``.
        for name, field in self._fields.items():
            object.__setattr__(self, name, field._resolve_default())

        # Accept JSON string or dict
        if isinstance(data, str):
            import json
            data = json.loads(data)

        # A single model is one record — reject a list/array with a clear
        # message instead of a cryptic "'list' object has no attribute 'items'".
        if data is not None and not isinstance(data, dict):
            raise TypeError(
                f"{type(self).__name__}() expects a dict, a JSON object string, or "
                f"keyword args for one record — got {type(data).__name__}. To build "
                f"many records, map over the list: "
                f"[{type(self).__name__}(row) for row in rows]."
            )

        # Populate from dict or kwargs
        if data:
            self._populate(data)
        if kwargs:
            self._populate(kwargs)

    def __setattr__(self, name, value):
        """Set an attribute, recording explicit assignment to declared fields.

        #165: ``save()`` reads ``_assigned_fields`` to tell a column the caller
        actually assigned (write it — an explicit ``None`` becomes ``NULL``)
        from one left at its default (OMIT from the INSERT so a
        ``NOT NULL DEFAULT`` column gets its DB default rather than an explicit
        ``NULL``). ``__init__`` seeds field defaults with ``object.__setattr__``,
        so only genuine caller assignments are tracked here. Non-field attrs
        (``last_error``, ``_rel_cache``, relationships, …) are never recorded.
        """
        assigned = self.__dict__.get("_assigned_fields")
        if assigned is not None and name in type(self)._fields:
            assigned.add(name)
        object.__setattr__(self, name, value)

    def _populate(self, data: dict):
        """Set field values from a dict — the READ/hydration path.

        Applies reverse field_mapping so DB column names are converted
        to Python attribute names before assignment. Uses ``field.coerce()``
        (type coercion + JSON parse only), NOT ``field.validate()`` — a row
        already persisted must always hydrate, even if it violates a
        business constraint (required/length/range/regex/choices) or one
        was tightened after the row was written (LOAD-PY-REVALIDATE /
        LOAD-DEC-01). Business-constraint enforcement stays on the write
        path (``ORM.validate()`` / ``save()``, feature 19) — unaffected.
        """
        # Build reverse mapping: db_column -> python_attribute
        reverse = {v: k for k, v in self.field_mapping.items()} if self.field_mapping else {}

        for key, value in data.items():
            # Convert DB column name to Python attribute name if mapped
            attr = reverse.get(key, key)
            if attr in self._fields:
                field = self._fields[attr]
                setattr(self, attr, field.coerce(value))
            else:
                # Allow extra attributes (from joined queries, etc.)
                setattr(self, attr, value)

    def _get_db_column(self, prop: str) -> str:
        """Get the DB column name for a Python attribute.

        Uses field_mapping if defined, otherwise returns the property name as-is.
        """
        return self.field_mapping.get(prop, prop)

    def _get_db_data(self) -> dict:
        """Convert all field data using field_mapping.

        Returns a dict with DB column names as keys and current attribute values.
        """
        data = {}
        for name, field in self._fields.items():
            db_col = self.field_mapping.get(name, field.column)
            data[db_col] = getattr(self, name)
        return data

    @classmethod
    def query(cls) -> "QueryBuilder":
        """Create a fluent QueryBuilder pre-configured for this model's table and database.

        Usage:
            results = User.query().where("active = ?", [1]).order_by("name").get()

        The model's primary-key column travels with the builder so
        ``order_by_distance()`` can break exact distance ties on it — without a
        tie-break the row order for equidistant rows is engine-defined and
        pagination can skip or repeat rows.

        Returns:
            A QueryBuilder instance bound to this model's table and database.
        """
        from tina4_python.query_builder import QueryBuilder
        return QueryBuilder.from_table(
            cls._get_table(), cls._get_db(), cls._get_pk_column()
        )

    @classmethod
    def _get_table(cls) -> str:
        """Get table name — defaults to lowercase class name.

        Set ORM_PLURAL_TABLE_NAMES=true in .env to restore the old
        behaviour that appended 's' (e.g. Contact → contacts).
        """
        if cls.table_name:
            return cls.table_name
        import os
        name = cls.__name__.lower()
        if os.environ.get("TINA4_ORM_PLURAL_TABLE_NAMES", "").lower() in ("true", "1", "yes"):
            name += "s"
        return name

    @classmethod
    def _get_table_sql(cls) -> str:
        """Table name QUOTED for the bound dialect — use this in SQL.

        ``_get_table()`` stays the raw name (needed for metadata lookups like
        ``table_exists``); this is what goes into a statement, so a reserved
        word such as ``table_name = "order"`` works instead of being a syntax
        error. Falls back to the raw name when no database is bound yet.
        """
        table = cls._get_table()
        try:
            db = cls._get_db()
            quote = getattr(db, "quote_identifier", None)
            if quote:
                return quote(table)
        except Exception:  # noqa: BLE001 — quoting must never break a query
            pass
        return table

    @classmethod
    def _get_db(cls):
        """Get the bound database for this model.

        Resolution order:
        1. cls._db as a Database instance (direct assignment)
        2. cls._db as a string name → look up in _databases registry
        3. Global _database (set via bind_database(db))
        """
        if cls._db is not None:
            if isinstance(cls._db, str):
                db = _databases.get(cls._db)
                if db is None:
                    raise RuntimeError(
                        f"Named database '{cls._db}' not found. "
                        f"Call bind_database(db, name='{cls._db}') first."
                    )
                return db
            return cls._db  # Direct Database instance

        if _database is None:
            # Try auto-discovery from TINA4_DATABASE_URL
            import os
            url = os.environ.get("TINA4_DATABASE_URL")
            if url:
                from tina4_python.database import Database
                username = os.environ.get("TINA4_DATABASE_USERNAME", "")
                password = os.environ.get("TINA4_DATABASE_PASSWORD", "")
                db = Database(url, username, password)
                bind_database(db)
                return db
            raise RuntimeError(
                "No database bound. Call bind_database(db) or set TINA4_DATABASE_URL in .env"
            )
        return _database

    @classmethod
    def _get_pk(cls) -> str:
        """The FIRST primary-key field name (or "id").

        Kept for the auto-increment paths, which are single-column by
        definition. Anything that ADDRESSES a row must use :meth:`_get_pks`:
        keying on one column of a composite key matches every row sharing that
        column's value, which is the data-loss shape feature 4 removed from the
        raw write path below this layer.
        """
        for name, field in cls._fields.items():
            if field.primary_key:
                return name
        return "id"

    @classmethod
    def _get_pks(cls) -> list[str]:
        """EVERY primary-key field name, in declaration order.

        A key may span several columns. Returns ["id"] when a model declares no
        primary key, matching the previous fallback.
        """
        keys = [name for name, field in cls._fields.items() if field.primary_key]
        return keys or ["id"]

    def _pk_where(self) -> tuple[str, list]:
        """A WHERE clause naming EVERY primary-key column, and its params.

        Addressing a row by one column of a composite key matches every row
        sharing that value. Feature 4 removed that from the raw write path; this
        is the same rule for the ORM above it.
        """
        cls = type(self)
        clauses, params = [], []
        for name in cls._get_pks():
            if name not in cls._fields:
                continue
            column = cls.field_mapping.get(name, cls._fields[name].column)
            clauses.append(f"{column} = ?")
            params.append(getattr(self, name, None))
        return " AND ".join(clauses), params

    @classmethod
    def _get_pk_column(cls) -> str:
        """Database COLUMN name of the primary key (field_mapping aware).

        ``_get_pk()`` returns the attribute name; SQL needs the column it maps
        to. QueryBuilder uses this as the stable ORDER BY tie-break.
        """
        pk = cls._get_pk()
        field = cls._fields.get(pk)
        return cls.field_mapping.get(pk, (field.column if field else None) or pk)

    # ── CRUD ────────────────────────────────────────────────────

    def save(self) -> Self | bool:
        """Insert or update. Returns self on success, False on failure.

        Fails loud, never silent (the same principle ``db.execute()``
        follows). On *any* failure path save() returns ``False`` — keeping
        the contract callers rely on (``if not model.save(): ...``) — but it
        also (a) logs the real cause via ``Log.error`` with model/table
        context and (b) records the cause on ``self.last_error`` so a caller
        can recover it after the fact via :meth:`get_error` / ``last_error``.
        It never raises and never changes the ``self | False`` return shape.

        Two distinct failure paths, both loud:

        * **Validation** (v3.13.39): :meth:`validate` runs FIRST. If it
          returns errors, save() logs them, records them on ``last_error``,
          and returns ``False`` WITHOUT touching the database — an invalid
          model never reaches the driver.
        * **Database** (v3.13.39): a driver error (NOT NULL, duplicate PK,
          missing table, …) is rolled back, logged with the underlying cause,
          recorded on ``last_error`` (mirroring ``db.get_error()``), and
          returns ``False`` — the cause is no longer swallowed silently.

        v3.13.11 (issue #50): for non-auto-increment primary keys (e.g.
        user-supplied string IDs like ``"GC-100"``), the decision between
        INSERT and UPDATE is made on whether the row *exists*, not on
        whether the PK is set. Pre-v3.13.11 a natural-key save() always
        chose UPDATE — matched zero rows — and silently returned success
        without inserting anything.

        Auto-increment behaviour is unchanged: ``pk_value is None`` means
        "new row, let the engine assign an ID" and we still INSERT.
        """
        from tina4_python.debug import Log

        # ── Change 2: validate() is enforced. An invalid model never
        # reaches the driver — fail loud (log + last_error), return False. ──
        errors = self.validate()
        if errors:
            self.last_error = "; ".join(errors)
            Log.error(
                f"{type(self).__name__}.save() refused: validation failed — "
                f"{self.last_error}"
            )
            return False

        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk, None)
        pk_field = self._fields[pk]
        table = self._get_table()
        table_sql = self._get_table_sql()
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        data = {}
        # #165: db columns to OMIT from an INSERT — those the caller never
        # assigned AND whose value is None. Omitting them lets the DB DEFAULT
        # apply (e.g. NOT NULL DEFAULT '') instead of emitting an explicit NULL
        # that violates the constraint. Unused on the UPDATE path.
        insert_omit = set()
        # A field's to_db() serialization can fail loud — the commonest case is a
        # JSONField handed a value that is not JSON-serializable (a set, a custom
        # object). The write-path contract, identical in all four frameworks, is:
        # save() returns False + logs the cause (never raises out of save(), never
        # silently persists a bad row). So a serialization error while BUILDING the
        # row is caught here, recorded on last_error, logged, and turned into a
        # False return before any transaction is opened.
        try:
            for name, field in self._fields.items():
                if field.auto_increment and pk_value is None:
                    continue  # Skip auto-increment on insert
                value = getattr(self, name)
                # v3.13.11 (issue #50): resolve callable values at write time
                # too, in case the user set ``self.created_at = lambda: ...``
                # directly. Defensive — Field.validate() already handles this
                # for the normal __init__ + _populate paths.
                if callable(value) and not isinstance(value, type):
                    value = value()
                if value is not None or not field.auto_increment:
                    # Use field_mapping for the column name, fall back to field.column
                    db_col = self.field_mapping.get(name, field.column)
                    # Serialize to the column's storage form: identity for most
                    # fields, JSON string for JSONField (see Field.to_db).
                    data[db_col] = field.to_db(value)
                    # #165: a None value the caller never assigned is an UNSET
                    # column — omit it from the INSERT so the DB DEFAULT applies.
                    # A resolved ORM default (non-None) is still written; a value
                    # the caller explicitly set to None is still written as NULL
                    # (its field name is in _assigned_fields).
                    if value is None and name not in self._assigned_fields:
                        insert_omit.add(db_col)
        except (ValueError, TypeError) as exc:
            self.last_error = str(exc)
            Log.error(f"{type(self).__name__}.save() refused: {exc}")
            return False

        # v3.13.11 (issue #50): pick INSERT vs UPDATE on row existence
        # for non-auto-increment PKs. Auto-increment keeps the legacy
        # behaviour (PK is None → INSERT, PK is set → UPDATE).
        is_update = False
        if pk_value is not None:
            if pk_field.auto_increment:
                is_update = True
            else:
                # Natural-key model — check if THIS row already exists.
                #
                # This asked exists(pk_value), which tests only the FIRST key
                # column. On a composite key that is true for any row sharing
                # that column, so inserting a genuinely new row was decided to
                # be an UPDATE and silently OVERWROTE a different row: saving
                # (acme, a2) rewrote (acme, a1). The check has to name the whole
                # key, exactly like the write that follows it.
                try:
                    where, where_params = self._pk_where()
                    if where:
                        found = db.fetch_one(
                            f"SELECT 1 AS present FROM {table_sql} WHERE {where}", where_params
                        )
                        is_update = found is not None
                    else:
                        is_update = type(self).exists(pk_value)
                except Exception:
                    # If we can't tell (e.g. table doesn't exist yet),
                    # fall back to INSERT — the user will see the real
                    # error from the driver instead of a silent no-op.
                    is_update = False

        db.start_transaction()
        try:
            if is_update:
                pk_columns = {
                    self.field_mapping.get(n, self._fields[n].column)
                    for n in self._get_pks()
                    if n in self._fields
                }
                update_data = {k: v for k, v in data.items() if k not in pk_columns}
                where, where_params = self._pk_where()
                if update_data and where:
                    db.update(table, update_data, where, where_params)
            else:
                # #165: drop unset-None columns so the DB DEFAULT applies.
                insert_data = {c: v for c, v in data.items() if c not in insert_omit}
                if insert_data:
                    db.insert(table, insert_data)
                else:
                    # Every insertable column was left unset — let the DB
                    # apply ALL its column defaults rather than emitting
                    # explicit NULLs. DEFAULT VALUES is valid on SQLite /
                    # PostgreSQL / MSSQL / Firebird; MySQL spells it () VALUES ().
                    if db.get_database_type() == "mysql":
                        db.execute(f"INSERT INTO {table_sql} () VALUES ()")
                    else:
                        db.execute(f"INSERT INTO {table_sql} DEFAULT VALUES")
                # Only adopt the engine-assigned ID for auto-increment PKs.
                # Natural-key PKs were already set by the caller; don't
                # overwrite them with the driver's last_id (which on PG
                # may be a sequence value that doesn't apply here).
                if pk_field.auto_increment:
                    last_id = db.get_last_id()
                    if last_id and pk in self._fields:
                        setattr(self, pk, last_id)
            db.commit()
        except Exception as e:
            db.rollback()
            # ── Change 1: fail loud, never silent. Keep the False return
            # contract, but capture the REAL cause (prefer db.get_error(),
            # which db.execute()/insert()/update() populate, falling back to
            # the exception text) on self.last_error so it survives, and log
            # it with model/table context. ──
            cause = db.get_error() or str(e)
            # ── DX hint (v3.13.60): turn a bare driver error into an
            # actionable fix for the two commonest ORM write footguns. Match
            # the message case-insensitively (SQLite says "no such table" /
            # "no such column: is_deleted" / "has no column named is_deleted";
            # Postgres/MySQL say "does not exist" / "doesn't exist"). Any
            # OTHER error keeps its raw cause untouched so we never mask an
            # unrelated failure (e.g. a NOT NULL / duplicate-PK violation). ──
            low = cause.lower()
            if self.soft_delete and "is_deleted" in low and (
                "no such column" in low or "has no column" in low
                or "does not exist" in low or "doesn't exist" in low
                or "unknown column" in low
            ):
                cause += (
                    " — soft_delete=True requires an is_deleted column; declare "
                    "it (is_deleted = IntegerField(default=0)) or add a migration"
                )
            elif "no such table" in low or (
                ("does not exist" in low or "doesn't exist" in low)
                # exclude a column-not-found (e.g. Postgres 'column "x" does not exist')
                # so a genuine missing-column error never gets a spurious table hint
                and "column" not in low
            ):
                cause += (
                    f" — table '{table}' does not exist; call "
                    f"{type(self).__name__}.create_table() or run a migration"
                )
            self.last_error = cause
            Log.error(
                f"{type(self).__name__}.save() failed for table "
                f"'{table}': {self.last_error}"
            )
            return False

        self.last_error = None
        self.clear_cache()
        self._rel_cache = {}
        self._persisted = True
        return self

    @classmethod
    def _soft_delete_column(cls) -> str:
        """DB column backing the soft-delete flag, honouring ``field_mapping``.

        The soft-delete finder filter and the ``delete``/``restore`` writes must
        address the SAME column. ``field_mapping`` remaps a Python attribute to
        its DB column (SOFTDEL-PY-FILTER-MAPPING), so a model that remaps
        ``is_deleted`` filters and writes on the mapped column, not the literal.
        Defaults to ``is_deleted`` when unmapped, so ordinary models are
        unaffected.
        """
        return cls.field_mapping.get("is_deleted", "is_deleted")

    @classmethod
    def _soft_delete_filter(cls) -> str:
        """SQL predicate that excludes soft-deleted rows (``field_mapping``-aware)."""
        col = cls._soft_delete_column()
        return f"({col} = 0 OR {col} IS NULL)"

    def delete(self) -> bool:
        """Delete this record (soft or hard)."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        db.start_transaction()
        try:
            if self.soft_delete:
                where, where_params = self._pk_where()
                db.update(table, {self._soft_delete_column(): 1}, where, where_params)
                self.is_deleted = 1
            else:
                where, where_params = self._pk_where()
                db.delete(table, where, where_params)
            db.commit()
        except Exception:
            db.rollback()
            raise
        # Bust cached reads of any table this write touched (CACHE-DEC-01).
        self.clear_cache()
        return True

    def force_delete(self) -> bool:
        """Hard delete, even if soft delete is enabled."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        db.start_transaction()
        try:
            where, where_params = self._pk_where()
            db.delete(table, where, where_params)
            db.commit()
        except Exception:
            db.rollback()
            raise
        # Bust cached reads of any table this write touched (CACHE-DEC-01).
        self.clear_cache()
        return True

    def restore(self) -> bool:
        """Restore a soft-deleted record."""
        if not self.soft_delete:
            raise RuntimeError("Model does not support soft delete")

        db = self._get_db()
        table = self._get_table()

        db.start_transaction()
        try:
            where, where_params = self._pk_where()
            db.update(table, {self._soft_delete_column(): 0}, where, where_params)
            self.is_deleted = 0
            db.commit()
        except Exception:
            db.rollback()
            raise
        # Bust cached reads of any table this write touched (CACHE-DEC-01).
        self.clear_cache()
        return True

    # ── Finders ─────────────────────────────────────────────────

    @classmethod
    def create(cls, data: dict = None, **kwargs) -> Self | bool:
        """Create a new instance, save it, and return it.

        Returns the saved instance on success. v3.13.39: if the underlying
        :meth:`save` fails (validation errors or a driver error), create()
        returns ``False`` — it does NOT hand back a possibly-unsaved
        instance, so a failed insert can never masquerade as a success. The
        failure cause is logged and available on the (discarded) instance's
        ``get_error()`` via the same path save() uses.

        Usage:
            user = User.create({"name": "Alice", "email": "alice@example.com"})
            user = User.create(name="Alice", email="alice@example.com")
            if not User.create(name=None):   # save() failed -> False
                ...
        """
        instance = cls(data or kwargs)
        if instance.save() is False:
            return False
        return instance

    @classmethod
    def find_by_id(cls, pk_value, include: list[str] = None) -> Self | None:
        """Find a single record by primary key. Returns instance or None.

        Args:
            pk_value: Primary key value.
            include: List of relationship names to eager-load.
        """
        pk = cls._get_pk()
        table = cls._get_table()
        table_sql = cls._get_table_sql()
        pk_col = cls.field_mapping.get(pk, cls._fields[pk].column)

        sql = f"SELECT * FROM {table_sql} WHERE {pk_col} = ?"
        if cls.soft_delete:
            sql += f" AND {cls._soft_delete_filter()}"

        return cls.select_one(sql, [pk_value], include=include)

    @classmethod
    def find(cls, filter=None, limit: int = 100, offset: int = 0, order_by: str = None, include: list[str] = None):
        """Find record(s) by primary key, filter dict, or all.

        Overloaded on the first argument:

        * ``int | str`` — primary-key lookup, returns a single instance
          (or ``None``). Equivalent to ``find_by_id(pk)``.
        * ``dict`` — filter as before, returns ``list[Self]``.
        * omitted — returns ``list[Self]`` of all records (subject to
          ``limit`` / ``offset`` / ``order_by``).

        Usage:
            User.find(1)                           → User | None  (PK lookup)
            User.find({"name": "Alice"})           → [User, ...]
            User.find({"age": 18}, limit=10)       → [User, ...]
            User.find(order_by="name ASC")          → [User, ...]
            User.find()                             → all records

        Args:
            filter: ``int``/``str`` primary-key value OR dict of
                {column: value} pairs (AND-ed) OR ``None``.
            limit: Max records to return (filter/all variants only).
            offset: Starting offset (filter/all variants only).
            order_by: ORDER BY clause (e.g. "name ASC").
            include: Relationship names to eager-load.
        """
        # PK lookup — int/str routes to find_by_id. Active Record convention
        # (Django Model.objects.get(pk=1), SQLAlchemy session.get(M, 1),
        # Ruby Model.find(1)). Docs have always promised this; we deliver.
        if isinstance(filter, (int, str)) and not isinstance(filter, bool):
            return cls.find_by_id(filter, include=include)

        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()
        conditions = []
        params = []

        if filter:
            for key, value in filter.items():
                col = cls.field_mapping.get(key, key)
                conditions.append(f"{col} = ?")
                params.append(value)

        if cls.soft_delete:
            conditions.append(cls._soft_delete_filter())

        sql = f"SELECT * FROM {table_sql}"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if order_by:
            sql += f" ORDER BY {order_by}"

        return cls.select(sql, params, limit=limit, offset=offset, include=include)

    def load(self, filter: str = None, params: list = None, include: list[str] = None) -> bool:
        """Load a record into this instance.

        Usage:
            orm.id = 1; orm.load()          — uses PK already set
            orm.load("id = ?", [1])         — filter with params
            orm.load("id = 1")              — filter string

        Returns True if a record was found and loaded, False otherwise.
        """
        db = self._get_db()
        table = self._get_table()
        table_sql = self._get_table_sql()

        if filter is None:
            # No args — use the primary key value already set
            pk = self._get_pk()
            pk_value = getattr(self, pk, None)
            if pk_value is None:
                return False
            pk_col = self.field_mapping.get(pk, self._fields[pk].column)
            sql = f"SELECT * FROM {table_sql} WHERE {pk_col} = ?"
            params = [pk_value]
        else:
            sql = f"SELECT * FROM {table_sql} WHERE {filter}"

        cls = type(self)
        result = cls.select_one(sql, params, include=include)
        if result is None:
            return False
        for key, value in result.to_dict().items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._persisted = True
        return True

    @classmethod
    def find_or_fail(cls, pk_value) -> Self:
        """Find by primary key or raise ValueError."""
        result = cls.find_by_id(pk_value)
        if result is None:
            raise ValueError(f"{cls.__name__} with {cls._get_pk()}={pk_value} not found")
        return result

    @classmethod
    def exists(cls, pk_value) -> bool:
        """Return True if a record with the given primary key exists."""
        return cls.find_by_id(pk_value) is not None

    @classmethod
    def all(cls, limit: int = 100, offset: int = 0, include: list[str] = None, order_by: str = None) -> list[Self]:
        """Fetch all records (respects soft delete).

        Args:
            limit: Max records to return.
            offset: Starting offset.
            include: List of relationship names to eager-load.
            order_by: ORDER BY clause (e.g. "name ASC").
        """
        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()

        sql = f"SELECT * FROM {table_sql}"
        if cls.soft_delete:
            sql += f" WHERE {cls._soft_delete_filter()}"
        if order_by:
            sql += f" ORDER BY {order_by}"

        result = db.fetch(sql, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return ModelCollection(instances, total=result.count, limit=limit, offset=offset)

    @classmethod
    def select(cls, sql: str = None, params: list = None, limit: int = 100, offset: int = 0,
               include: list[str] = None) -> ModelCollection:
        """SQL-first query — returns array of ORM objects.

        When ``sql`` is omitted, defaults to ``SELECT * FROM <table>`` so
        ``Product.select(limit=20)`` works as the scaffolder's CRUD-list
        route expects. Same soft-delete filter as ``where()`` is applied
        when ``cls.soft_delete`` is True.

        The default ``limit`` is 100, the one row cap the whole family shares
        (``all``/``find``/``where``/``with_trashed``/``cached``/``scope``/
        ``db.fetch``). Pagination is a default, not an opt-in: pass a bigger
        ``limit`` to reach past it.
        """
        db = cls._get_db()
        if not sql:
            table = cls._get_table()
            table_sql = cls._get_table_sql()
            sql = f"SELECT * FROM {table_sql}"
            if cls.soft_delete:
                sql += f" WHERE {cls._soft_delete_filter()}"
        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return ModelCollection(instances, total=result.count, limit=limit, offset=offset)

    @classmethod
    def select_one(cls, sql: str, params: list = None, include: list[str] = None) -> Self | None:
        """Return a single ORM instance for a raw SQL query, or None if no rows match."""
        instances = cls.select(sql, params, limit=1, offset=0, include=include)
        return instances[0] if instances else None

    @classmethod
    def where(cls, filter_sql: str, params: list = None, limit: int = 100, offset: int = 0,
              include: list[str] = None, order_by: str = None) -> ModelCollection:
        """Query with a WHERE clause -- returns a ModelCollection of ORM objects.

        The result IS a list (iterate / index / ``len`` / slice all unchanged) and
        also carries the total rows matching ``filter_sql``, independent of
        ``limit`` / ``offset``, via ``get_total_records()`` and ``to_paginate()``
        (ADR-0064). So a caller reading a 20-row page still learns there are 250
        matching rows.

        The total is free: the ``db.fetch()`` below already ran a ``COUNT(*)``
        probe for the same filter and returns it on ``result.count`` -- no second
        query.

        Args:
            order_by: ORDER BY clause (e.g. "name ASC"). Applied to the page rows
                only; the total ignores ordering (COUNT is order-independent).
        """
        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()

        sql = f"SELECT * FROM {table_sql} WHERE {filter_sql}"
        if cls.soft_delete:
            sql = f"SELECT * FROM {table_sql} WHERE ({filter_sql}) AND {cls._soft_delete_filter()}"
        if order_by:
            sql += f" ORDER BY {order_by}"

        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return ModelCollection(instances, total=result.count, limit=limit, offset=offset)

    @classmethod
    def with_trashed(cls, filter_sql: str = "1=1", params: list = None, limit: int = 100, offset: int = 0) -> ModelCollection:
        """Query including soft-deleted records -- returns a ModelCollection.

        Like ``where()``, the result carries the total matching rows (soft-deleted
        included) via ``get_total_records()`` / ``to_paginate()`` (ADR-0064).
        """
        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()
        sql = f"SELECT * FROM {table_sql} WHERE {filter_sql}"
        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        return ModelCollection(instances, total=result.count, limit=limit, offset=offset)

    @classmethod
    def count(cls, conditions: str = None, params: list = None) -> int:
        """Count records matching conditions (respects soft delete)."""
        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()

        where_parts = []
        if cls.soft_delete:
            where_parts.append(cls._soft_delete_filter())
        if conditions:
            where_parts.append(f"({conditions})")

        sql = f"SELECT COUNT(*) as cnt FROM {table_sql}"
        if where_parts:
            sql += f" WHERE {' AND '.join(where_parts)}"

        row = db.fetch_one(sql, params or [])
        return row["cnt"] if row else 0

    # ── Table Creation ──────────────────────────────────────────

    @classmethod
    def create_table(cls) -> bool:
        """Generate and execute CREATE TABLE DDL from the model's field definitions.

        Field type to SQL type mapping:
            IntegerField → INTEGER
            StringField  → VARCHAR(255)
            TextField    → TEXT
            NumericField/FloatField → REAL
            BooleanField → engine-aware (see below)
            DateTimeField → DATETIME
            BlobField    → BLOB

        v3.13.11 BooleanField mapping (engine-aware):
            SQLite    → INTEGER    (no native bool — historic convention)
            PostgreSQL → BOOLEAN   (native type; psycopg2 binds Python
                                    ``bool`` as BOOLEAN, so INTEGER columns
                                    caused ``operator does not exist:
                                    boolean = integer``)
            MySQL     → BOOLEAN    (synonym for TINYINT(1))
            MSSQL     → BIT        (the SQL Server bool type)
            Firebird  → INTEGER    (driver round-trip is uneven; integer
                                    is the safer choice on Firebird)

        Auto-increment primary keys use engine-appropriate syntax.

        Returns:
            True on success, False if the DDL failed (the cause is logged).

        Raises:
            SpatialNotSupportedError: **narrowed contract — a spatial model on
                a non-spatial engine RAISES, it does not return False.** Every
                other failure here is recoverable and reported as ``False``,
                but there is no safe fallback column type for geometry: a
                ``TEXT`` stand-in would accept writes, return rows, and be
                silently wrong for every distance query afterwards. The
                exception names the engine and the alternative. It is resolved
                BEFORE the ``table_exists`` short-circuit, so the refusal never
                depends on whether the table happens to exist yet, and it fires
                on the engine — not on the field — so a PointField model is
                portable source that simply cannot be deployed onto an engine
                that would lie about it.

                Mirrors (PHP / Ruby / Node) must THROW here too. Returning
                false would collapse "this engine cannot do spatial" into the
                same signal as "the DDL failed", and the caller would create
                the table by hand and carry on.
        """
        from tina4_python.database.adapter import SQLTranslator

        db = cls._get_db()
        table = cls._get_table()
        table_sql = cls._get_table_sql()
        engine = (db.get_database_type() or "").lower()

        # v3.13.11: BooleanField now uses each engine's native type
        # where it's reliable. SQLite and Firebird stay on INTEGER —
        # SQLite has no native bool, and Firebird's driver round-trip
        # for native BOOLEAN is uneven across versions.
        # v3.13.16: db.get_database_type() returns "postgresql" (with the -ql),
        # so the old `== "postgres"` check never matched and BooleanField got
        # INTEGER on PG — which then can't accept a Python bool on insert.
        if engine in ("postgres", "postgresql"):
            bool_sql = "BOOLEAN"
        elif engine == "mysql":
            bool_sql = "BOOLEAN"  # MySQL alias for TINYINT(1)
        elif engine == "mssql":
            bool_sql = "BIT"
        else:
            # sqlite, firebird, odbc, anything else
            bool_sql = "INTEGER"

        # v3.13.16: DateTimeField was emitted as "DATETIME" unconditionally,
        # but PostgreSQL and Firebird have no DATETIME type — CREATE TABLE blew
        # up with `type "datetime" does not exist`. Emit each engine's real
        # timestamp type. (MySQL/MSSQL/SQLite keep DATETIME: it's valid there,
        # and on MySQL it avoids TIMESTAMP's auto-update + 2038 surprises.)
        if engine in ("postgres", "postgresql", "firebird"):
            datetime_sql = "TIMESTAMP"
        else:
            datetime_sql = "DATETIME"

        # JSONField -> the engine's native JSON type where it has one, else a
        # text column. PostgreSQL JSONB (binary, indexable, canonical form);
        # MySQL JSON; MSSQL has no JSON type so NVARCHAR(MAX) (its documented
        # JSON storage); SQLite/ODBC TEXT; Firebird has no TEXT/JSON type so
        # BLOB SUB_TYPE TEXT. The ORM stores a JSON string in every case, so a
        # text-backed column round-trips identically to a native one.
        if engine in ("postgres", "postgresql"):
            json_sql = "JSONB"
        elif engine == "mysql":
            json_sql = "JSON"
        elif engine == "mssql":
            json_sql = "NVARCHAR(MAX)"
        elif engine == "firebird":
            json_sql = "BLOB SUB_TYPE TEXT"
        else:
            json_sql = "TEXT"

        # PointField -> the engine's spatial type via the SQLTranslator dialect
        # seam (``geography(Point,<srid>)`` on PostGIS). Resolved BEFORE the
        # table_exists short-circuit so a spatial model on a non-spatial engine
        # ALWAYS raises SpatialNotSupportedError naming that engine — a wrong
        # column type is never created, and the error does not depend on whether
        # the table happens to exist yet. This is the loud-not-silent contract:
        # unlike the other type mappings there is no safe fallback for geometry.
        point_sql: dict[str, str] = {}
        for name, field_obj in cls._fields.items():
            if getattr(field_obj, "kind", None) != "PointField":
                continue
            col_name = cls.field_mapping.get(name, field_obj.column or name)
            point_sql[col_name] = SQLTranslator.point_column_type(
                engine, getattr(field_obj, "srid", 4326)
            )

        # Don't recreate if table already exists
        if db.table_exists(table):
            return True

        col_defs = []
        for name, field_obj in cls._fields.items():
            col_name = cls.field_mapping.get(name, field_obj.column or name)
            kind = getattr(field_obj, "kind", None)

            # Map field kind to SQL type
            sql_type = "TEXT"
            if kind == "IntegerField":
                sql_type = "INTEGER"
            elif kind == "StringField":
                max_len = getattr(field_obj, "max_length", None) or 255
                sql_type = f"VARCHAR({max_len})"
            elif kind == "TextField":
                sql_type = "TEXT"
            elif kind in ("NumericField", "FloatField"):
                sql_type = "REAL"
            elif kind == "DecimalField":
                # A fixed-precision column: emit a real DECIMAL(p, s) so the
                # engine keeps the declared scale instead of a floating
                # approximation. Valid syntax on PG/MySQL/MSSQL/Firebird/SQLite.
                precision = getattr(field_obj, "precision", 10)
                scale = getattr(field_obj, "scale", 2)
                sql_type = f"DECIMAL({precision},{scale})"
            elif kind == "BooleanField":
                sql_type = bool_sql
            elif kind == "DateTimeField":
                sql_type = datetime_sql
            elif kind == "BlobField":
                sql_type = "BLOB"
            elif kind == "JSONField":
                sql_type = json_sql
            elif kind == "PointField":
                sql_type = point_sql[col_name]
            else:
                # Fallback based on field_type
                ft = field_obj.field_type
                if ft == int:
                    sql_type = "INTEGER"
                elif ft == float:
                    sql_type = "REAL"
                elif ft == bool:
                    sql_type = bool_sql
                elif ft == bytes:
                    sql_type = "BLOB"

            parts = [col_name, sql_type]

            # A COMPOSITE key is declared once, at table level (below). Emitting
            # an inline PRIMARY KEY per column is invalid DDL - SQLite,
            # PostgreSQL and MySQL all reject two of them in one table.
            if field_obj.primary_key and len(cls._get_pks()) == 1:
                parts.append("PRIMARY KEY")
            if field_obj.auto_increment:
                parts.append("AUTOINCREMENT")
            if field_obj.required and not field_obj.primary_key:
                parts.append("NOT NULL")
            # Callable defaults (e.g. DateTimeField(default=lambda: datetime.now())) are
            # resolved per-row at insert time (_resolve_default, issue #50); they must NOT
            # be emitted into the CREATE TABLE DDL, where they stringify to an invalid
            # `DEFAULT <function ...>` and silently fail table creation.
            if field_obj.default is not None and not field_obj.auto_increment \
                    and kind != "JSONField" and not callable(field_obj.default):
                default_val = field_obj.default
                if isinstance(default_val, str):
                    parts.append(f"DEFAULT '{default_val}'")
                elif isinstance(default_val, bool):
                    # v3.13.16: a native BOOLEAN column (PG/MySQL) needs
                    # TRUE/FALSE; INTEGER- and BIT-backed bools (SQLite,
                    # Firebird, MSSQL) need 1/0. `DEFAULT 0` on a PG BOOLEAN
                    # raises "default expression is of type integer".
                    if bool_sql == "BOOLEAN":
                        parts.append(f"DEFAULT {'TRUE' if default_val else 'FALSE'}")
                    else:
                        parts.append(f"DEFAULT {1 if default_val else 0}")
                else:
                    parts.append(f"DEFAULT {default_val}")

            col_defs.append(" ".join(parts))

        # SOFTDEL-DEC-02: a soft_delete model needs an is_deleted flag column,
        # but create_table only knew about DECLARED fields — so a
        # soft_delete=True model that never declared is_deleted built a table
        # with NO such column, and every soft-delete read/write then errored on
        # the missing column. Inject it here (INTEGER 0/1, default 0),
        # field_mapping-aware, unless the model already declares it, so the
        # generated schema always matches the soft-delete behaviour.
        if cls.soft_delete:
            sd_col = cls._soft_delete_column()
            declared_cols = {
                cls.field_mapping.get(name, fo.column or name)
                for name, fo in cls._fields.items()
            }
            if sd_col not in declared_cols:
                col_defs.append(f"{sd_col} INTEGER DEFAULT 0")

        # A COMPOSITE key is declared ONCE, at table level. Per-column inline
        # PRIMARY KEY (above) is suppressed when the key spans more than one
        # column, because two inline primary keys is invalid DDL on every engine.
        pks = cls._get_pks()
        if len(pks) > 1:
            pk_cols = [cls.field_mapping.get(k, cls._fields[k].column) for k in pks if k in cls._fields]
            if pk_cols:
                col_defs.append(f"PRIMARY KEY ({', '.join(pk_cols)})")

        # MSSQL and Firebird reject `IF NOT EXISTS` on CREATE TABLE (a syntax
        # error). The `db.table_exists(table)` guard above already returns early
        # when the table is present, so `IF NOT EXISTS` is pure redundancy on
        # every engine and simply omitted where it does not parse.
        if_not_exists = "" if engine in ("mssql", "sqlserver", "firebird") else "IF NOT EXISTS "
        sql = f"CREATE TABLE {if_not_exists}{table_sql} ({', '.join(col_defs)})"

        # Translate auto-increment syntax for the current engine
        engine = db.get_database_type()
        sql = SQLTranslator.auto_increment_syntax(sql, engine)

        # Don't claim success when the DDL failed. execute() now RAISES on a
        # bad type / any DDL error (it used to swallow it into get_error() and
        # return False). Keep create_table()'s bool contract by catching the
        # error and returning False with the cause logged, rather than letting
        # it propagate out of create_table().
        try:
            db.execute(sql)
            # A spatial predicate without a spatial index is a full table scan,
            # so the index ships WITH the column rather than as a thing the
            # developer must remember. IF NOT EXISTS keeps it idempotent.
            for name, field_obj in cls._fields.items():
                if getattr(field_obj, "kind", None) != "PointField":
                    continue
                if not getattr(field_obj, "spatial_index", True):
                    continue
                col_name = cls.field_mapping.get(name, field_obj.column or name)
                db.execute(SQLTranslator.spatial_index(engine, table, col_name))
            db.commit()
        except Exception as e:
            from tina4_python.debug import Log
            Log.error(f"create_table failed for {table}: {db.get_error() or e}", sql=sql)
            return False
        return True

    # ── Cached Queries ────────────────────────────────────────

    @classmethod
    def _cache_tags(cls, sql: str = None) -> list[str]:
        """Every table a cached query touches: this model's table plus every
        FROM/JOIN table in ``sql`` (see :func:`_tables_in_sql`). A write to any
        of these busts the entry, so a cross-table JOIN cached here is
        invalidated when the OTHER table's model writes (CACHE-DEC-01)."""
        tags = {cls._get_table().lower()}
        tags |= _tables_in_sql(sql)
        return list(tags)

    @classmethod
    def cached(cls, sql: str, params: list = None, ttl: int = 60,
               limit: int = 100, offset: int = 0, include: list = None) -> list[Self]:
        """SQL query with result caching. Returns array of ORM objects.

        Invalidation (CACHE-DEC-01): the entry is tagged by every table the query
        touches (this model's table plus any FROM/JOIN tables), so a write through
        the ORM (save/delete/force_delete/restore) to ANY of those tables busts
        it. ``ttl <= 0`` means NO-CACHE — the query runs and the rows are returned
        but nothing is stored, so every read hits the database (it is NOT an
        infinite-lived entry)."""
        # ttl <= 0 is NO-CACHE: run it live, store nothing, read nothing.
        if ttl <= 0:
            return cls.select(sql, params, limit=limit, offset=offset, include=include)

        cache_key = f"{cls.__name__}:{Cache.query_key(sql, params)}:{limit}:{offset}"
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return cached

        result = cls.select(sql, params, limit=limit, offset=offset, include=include)
        _query_cache.set(cache_key, result, ttl=ttl, tags=cls._cache_tags(sql))
        return result

    @classmethod
    def clear_cache(cls) -> None:
        """Invalidate every cached query that touches this model's table.

        Tag-scoped in the ORM layer (a cached JOIN on another model that reads
        this table is busted too because it carries this table's tag; a query
        that never touches this table is left intact), then cascaded to the
        DB layer on this model's bound connection so an out-of-band write /
        deliberate refresh / race-with-another-process cannot leave stale rows
        in db.fetch()'s persistent cache. Called after every ORM write
        (save/delete/force_delete/restore) so a read-after-write never serves
        a stale/deleted row (CACHE-DEC-01). PY-06-22 (3.13.105) added the
        DB-layer cascade -- previously the two cache layers disagreed
        under TINA4_AUTO_CACHING=true + TINA4_DB_CACHE=true."""
        _query_cache.clear_tag(cls._get_table().lower())
        try:
            cls._get_db().cache_clear()
        except Exception:
            # A resolvable DB is not guaranteed at every clear_cache call
            # site (module-import time in odd bootstraps, tests that mutate
            # bindings); never let a cache-clear crash a save/delete.
            pass

    @classmethod
    def clear_rel_cache(cls) -> None:
        """Clear the relationship cache on this class.

        Useful when you know relationships have changed and want to force
        re-fetching on the next attribute access.
        """
        if hasattr(cls, "_rel_cache"):
            cls._rel_cache = {}

    @classmethod
    def get_db(cls):
        """Return the database connection bound to this model.

        Resolution order matches _get_db():
        1. cls._db as a Database instance
        2. cls._db as a named string → registry lookup
        3. Global default set via bind_database()
        """
        return cls._get_db()

    @classmethod
    def get_db_column(cls, prop: str) -> str:
        """Map a Python property/field name to its database column name.

        Uses field_mapping first, then falls back to the Field's own column
        attribute, and finally the property name itself.

        Args:
            prop: Python attribute name (e.g. "first_name").

        Returns:
            The corresponding database column name (e.g. "firstName").
        """
        if prop in cls.field_mapping:
            return cls.field_mapping[prop]
        field = cls._fields.get(prop)
        if field is not None and field.column:
            return field.column
        return prop

    @classmethod
    def eager_load(cls, instances: list, include_list: list[str]) -> None:
        """Eagerly load relationships for a list of ORM instances.

        This is the public equivalent of _eager_load — it exposes the same
        batch-loading behaviour so callers can trigger eager loading on an
        already-fetched list of instances without re-querying.

        Args:
            instances: List of ORM instances (must all be the same model class).
            include_list: Relationship names to load, optionally dot-separated
                          for nesting (e.g. ["posts", "posts.comments"]).
        """
        cls._eager_load(instances, include_list)

    # ── Relationships ───────────────────────────────────────────

    def has_one(self, related_class, foreign_key: str = None) -> Self | None:
        """Load a single related record (imperative style)."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()
        table_sql = related_class._get_table_sql()

        sql = f"SELECT * FROM {table_sql} WHERE {fk} = ?"
        row = self._get_db().fetch_one(sql, [pk_value])
        return related_class(row) if row else None

    def has_many(self, related_class, foreign_key: str = None, limit: int = None, offset: int = 0) -> list[Self]:
        """Load multiple related records (imperative style).

        IMPREL-PY-CAP: with no explicit ``limit`` this returns the WHOLE set,
        paging in blocks exactly like the lazy descriptor (feature 21) instead of
        the old silent 100-row cap -- so the same relationship yields the same
        row count whether accessed imperatively or lazily. An explicit ``limit``
        still pages (explicit, never silent).
        """
        from tina4_python.orm.fields import _LAZY_PAGE_SIZE
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table_sql = related_class._get_table_sql()
        # Order by the child PK so OFFSET paging is stable across pages (parity
        # with the lazy descriptor's SQL).
        order_col = related_class.field_mapping.get(
            related_class._get_pk(), related_class._fields[related_class._get_pk()].column
        )
        sql = f"SELECT * FROM {table_sql} WHERE {fk} = ? ORDER BY {order_col}"
        db = self._get_db()

        if limit is not None:
            result = db.fetch(sql, [pk_value], limit=limit, offset=offset)
            return [related_class(row) for row in result.records]

        # No explicit limit -> page through ALL rows (uncapped, parity with lazy).
        records = []
        page_offset = offset
        while True:
            result = db.fetch(sql, [pk_value], limit=_LAZY_PAGE_SIZE, offset=page_offset)
            batch = result.records
            records.extend(batch)
            if len(batch) < _LAZY_PAGE_SIZE:
                break
            page_offset += _LAZY_PAGE_SIZE
        return [related_class(row) for row in records]

    def belongs_to(self, related_class, foreign_key: str = None) -> Self | None:
        """Load the parent record (imperative style)."""
        fk = foreign_key or f"{related_class.__name__.lower()}_id"
        fk_value = getattr(self, fk, None)
        if fk_value is None:
            return None
        return related_class.find_by_id(fk_value)

    @classmethod
    def _eager_load(cls, instances: list, include: list[str]):
        """Eager-load relationships for a list of instances (prevents N+1).

        Args:
            instances: List of model instances.
            include: List of relationship names, optionally dot-separated for nesting
                     (e.g., ["posts", "posts.comments"]).
        """
        if not instances:
            return

        from tina4_python.orm.fields import (
            HasManyDescriptor, HasOneDescriptor, BelongsToDescriptor,
        )

        # Group includes: top-level and nested
        top_level = {}
        for inc in include:
            parts = inc.split(".", 1)
            rel_name = parts[0]
            if rel_name not in top_level:
                top_level[rel_name] = []
            if len(parts) > 1:
                top_level[rel_name].append(parts[1])

        for rel_name, nested in top_level.items():
            descriptor = cls._relationships.get(rel_name)
            if descriptor is None:
                continue

            related_cls = descriptor._resolve_model()
            pk = cls._get_pk()
            db = cls._get_db()

            if isinstance(descriptor, (HasManyDescriptor, HasOneDescriptor)):
                # Collect all PKs from instances
                pk_values = [getattr(inst, pk) for inst in instances if getattr(inst, pk) is not None]
                if not pk_values:
                    continue

                fk = descriptor.foreign_key or f"{cls.__name__.lower()}_id"
                table_sql = related_cls._get_table_sql()
                # REL-SOFTDELETE-TRAVERSAL: a soft-deleted child must not surface
                # through eager traversal either (parity with lazy + the finders).
                soft = (
                    f" AND {related_cls._soft_delete_filter()}"
                    if getattr(related_cls, "soft_delete", False)
                    else ""
                )
                order_col = related_cls.field_mapping.get(
                    related_cls._get_pk(), related_cls._fields[related_cls._get_pk()].column
                )
                # REL-EAGER-UNBOUNDED: chunk the parent PKs so the IN list stays
                # bounded, and page each chunk so no relation is truncated.
                related_records = []
                for chunk in _chunk_list(pk_values, _EAGER_IN_CHUNK):
                    placeholders = ",".join("?" for _ in chunk)
                    sql = (
                        f"SELECT * FROM {table_sql} WHERE {fk} IN ({placeholders})"
                        f"{soft} ORDER BY {order_col}"
                    )
                    offset = 0
                    while True:
                        result = db.fetch(sql, list(chunk), limit=_EAGER_PAGE_SIZE, offset=offset)
                        batch = result.records
                        related_records.extend(related_cls(row) for row in batch)
                        if len(batch) < _EAGER_PAGE_SIZE:
                            break
                        offset += _EAGER_PAGE_SIZE

                # Eager load nested relationships on related records
                if nested:
                    related_cls._eager_load(related_records, nested)

                # Group by foreign key and assign
                grouped = {}
                for record in related_records:
                    fk_val = getattr(record, fk, None)
                    if fk_val not in grouped:
                        grouped[fk_val] = []
                    grouped[fk_val].append(record)

                for inst in instances:
                    pk_val = getattr(inst, pk)
                    records = grouped.get(pk_val, [])
                    if isinstance(descriptor, HasOneDescriptor):
                        inst._rel_cache[rel_name] = records[0] if records else None
                    else:
                        inst._rel_cache[rel_name] = records

            elif isinstance(descriptor, BelongsToDescriptor):
                fk = descriptor.foreign_key or f"{related_cls.__name__.lower()}_id"
                fk_values = list({
                    getattr(inst, fk) for inst in instances
                    if getattr(inst, fk, None) is not None
                })
                if not fk_values:
                    continue

                related_pk = related_cls._get_pk()
                table_sql = related_cls._get_table_sql()
                pk_col = related_cls.field_mapping.get(related_pk, related_cls._fields[related_pk].column)
                # REL-SOFTDELETE-TRAVERSAL: a soft-deleted parent is excluded from
                # belongs_to traversal too (parity with find_by_id).
                soft = (
                    f" AND {related_cls._soft_delete_filter()}"
                    if getattr(related_cls, "soft_delete", False)
                    else ""
                )
                # REL-EAGER-UNBOUNDED: chunk the FK values so the IN list stays bounded.
                related_records = []
                for chunk in _chunk_list(fk_values, _EAGER_IN_CHUNK):
                    placeholders = ",".join("?" for _ in chunk)
                    sql = f"SELECT * FROM {table_sql} WHERE {pk_col} IN ({placeholders}){soft}"
                    result = db.fetch(sql, list(chunk), limit=len(chunk), offset=0)
                    related_records.extend(related_cls(row) for row in result.records)

                if nested:
                    related_cls._eager_load(related_records, nested)

                lookup = {getattr(r, related_pk): r for r in related_records}
                for inst in instances:
                    fk_val = getattr(inst, fk, None)
                    inst._rel_cache[rel_name] = lookup.get(fk_val)

    # ── Scopes ──────────────────────────────────────────────────

    @classmethod
    def scope(cls, name: str, filter_sql: str, params: list = None) -> None:
        """Register a reusable query scope on the class.

            User.scope("active", "active = ?", [1])
            users, count = User.active()
        """
        def scope_method(limit: int = 100, offset: int = 0):
            return cls.where(filter_sql, params, limit=limit, offset=offset)

        setattr(cls, name, staticmethod(scope_method))

    # ── Validation ──────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Validate all fields. Returns list of error messages (empty = valid).

        Feature 19: each message uses the canonical request-Validator vocabulary
        ("<field> is required", "<field> must be at most N characters", ...) via
        ``Field.validate_value`` so the ORM validator and the request-body
        ``Validator`` speak ONE message language (VALID-TWO-MESSAGES). An invalid
        model never reaches the driver -- ``save()`` enforces this list.
        """
        errors = []
        for name, field in self._fields.items():
            value = getattr(self, name)
            errors.extend(field.validate_value(name, value))
        return errors

    def get_error(self) -> str | None:
        """Return the cause of the most recent failed :meth:`save`, or None.

        Mirrors ``db.get_error()``. After ``save()`` returns ``False`` —
        whether from validation or a driver error — the real cause is
        retrievable here (and on ``self.last_error``) so a caller using the
        ``if not model.save():`` contract can still surface it. Cleared to
        ``None`` on a successful save.
        """
        return self.last_error

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self, include: list[str] = None, case: str = "snake") -> dict:
        """Convert to dict (field values only, optionally with relationships).

        Args:
            include: List of relationship names to include. Supports dot notation
                     for nested relationships (e.g., ["posts.comments"]).
            case: Key casing — 'snake' (default for Python), 'camel' (matches PHP).
        """
        if case == "camel":
            result = {snake_to_camel(name): getattr(self, name) for name in self._fields}
        else:
            result = {name: getattr(self, name) for name in self._fields}

        # Spatial fields serialise as GeoJSON geometry, so to_dict() / to_json()
        # / response() all emit map-ready output from one place. `_spatial_fields`
        # is empty for every non-spatial model, so this costs one falsy check.
        if self._spatial_fields:
            for name in self._spatial_fields:
                key = snake_to_camel(name) if case == "camel" else name
                point = result.get(key)
                if point is not None:
                    result[key] = point.geojson

        if include:
            # Group includes: top-level and nested
            top_level = {}
            for inc in include:
                parts = inc.split(".", 1)
                rel_name = parts[0]
                if rel_name not in top_level:
                    top_level[rel_name] = []
                if len(parts) > 1:
                    top_level[rel_name].append(parts[1])

            for rel_name, nested in top_level.items():
                if rel_name in self._relationships:
                    # Access the relationship (triggers lazy load if not cached)
                    related = getattr(self, rel_name)
                    key = snake_to_camel(rel_name) if case == "camel" else rel_name
                    if related is None:
                        result[key] = None
                    elif isinstance(related, list):
                        result[key] = [
                            r.to_dict(include=nested if nested else None, case=case)
                            for r in related
                        ]
                    else:
                        result[key] = related.to_dict(
                            include=nested if nested else None, case=case
                        )

        return result

    def to_assoc(self, include: list[str] = None, case: str = "snake") -> dict:
        """Convert to an associative dict (alias for to_dict)."""
        return self.to_dict(include=include, case=case)

    def to_object(self, case: str = "snake") -> dict:
        """Convert to an object/dict (alias for to_dict)."""
        return self.to_dict(case=case)

    def to_array(self) -> list:
        """Convert to a list of values."""
        return list(self.to_dict().values())

    def to_list(self) -> list:
        """Convert to a list of values (alias for to_array)."""
        return self.to_array()

    def to_feature(self, geometry_field: str = None, include: list[str] = None) -> dict:
        """Convert to an RFC 7946 GeoJSON ``Feature``.

        The model's point field becomes the feature ``geometry``; every other
        field becomes a ``properties`` entry, with the primary key also lifted to
        the feature ``id`` (where GIS clients look for it).

            ChargePoint.find(1).to_feature()
            # {"type": "Feature", "id": 1,
            #  "geometry": {"type": "Point", "coordinates": [18.4241, -33.9249]},
            #  "properties": {"name": "V&A"}}

        Args:
            geometry_field: Which PointField to use as the geometry. Required
                only when the model declares more than one.
            include: Relationships to include in ``properties`` (as for
                :meth:`to_dict`).

        Raises:
            ValueError: if the model has no PointField, if ``geometry_field`` is
                not one, or if it is ambiguous with several point fields.
        """
        if not self._spatial_fields:
            raise ValueError(
                f"{type(self).__name__}.to_feature(): the model has no PointField, "
                f"so it has no geometry. Add a PointField, or use to_dict()."
            )
        if geometry_field is None:
            if len(self._spatial_fields) > 1:
                raise ValueError(
                    f"{type(self).__name__}.to_feature(): the model has several "
                    f"point fields {list(self._spatial_fields)} — pass "
                    f"geometry_field= to choose one."
                )
            geometry_field = self._spatial_fields[0]
        elif geometry_field not in self._spatial_fields:
            raise ValueError(
                f"{type(self).__name__}.to_feature(): {geometry_field!r} is not a "
                f"PointField on this model. Point fields: "
                f"{list(self._spatial_fields)}."
            )

        properties = self.to_dict(include=include)
        geometry = properties.pop(geometry_field, None)
        feature = {"type": "Feature", "geometry": geometry, "properties": properties}
        pk = self._get_pk()
        pk_value = properties.get(pk)
        if pk_value is not None:
            feature["id"] = pk_value
        return feature

    def to_json(self, include: list[str] = None) -> str:
        """Convert to JSON string."""
        import json
        data = self.to_dict(include=include)
        # Handle non-serializable types
        for key, value in data.items():
            if hasattr(value, "isoformat"):
                data[key] = value.isoformat()
            elif isinstance(value, bytes):
                import base64
                data[key] = base64.b64encode(value).decode()
        return json.dumps(data)

    def __repr__(self):
        pk = self._get_pk()
        pk_val = getattr(self, pk, None)
        return f"<{self.__class__.__name__} {pk}={pk_val}>"


def feature_collection(models, geometry_field: str = None, include: list[str] = None) -> dict:
    """Wrap models with a PointField into an RFC 7946 ``FeatureCollection``.

    This is the shape a map front end (Leaflet, MapLibre, OpenLayers, tina4-js on
    a map) consumes directly, so a route becomes a one-liner::

        from tina4_python.orm import feature_collection

        @get("/api/charge-points.geojson")
        async def charge_points(request, response):
            return response(feature_collection(ChargePoint.all()))

    ``response()`` then serialises the returned dict as JSON exactly as it does
    any other dict — nothing new on the response path.

    It is deliberately **explicit** rather than an automatic transform of
    ``response(list_of_models)``: a list of models always serialises to a JSON
    array, and silently switching that to a FeatureCollection because a field
    type is present would be exactly the kind of magic Tina4 avoids.

    Args:
        models: An ORM instance or an iterable of them — e.g. ``Model.all()``,
            ``Model.where(...)``, ``Model.select(...)``.
        geometry_field: Which PointField supplies the geometry (only needed when
            a model declares more than one).
        include: Relationships to include in each feature's ``properties``.

    Returns:
        ``{"type": "FeatureCollection", "features": [...]}`` — an empty
        ``features`` list for empty input, never None.

    Raises:
        TypeError: naming what it got, if any element is not an ORM model
            (``QueryBuilder.get()`` returns raw row dicts, which carry no field
            definitions and therefore no geometry — use ``Model.where()`` /
            ``Model.select()`` for GeoJSON output).
    """
    if models is None:
        rows = []
    elif isinstance(models, ORM):
        rows = [models]
    else:
        rows = models
    features = []
    for row in rows:
        if not isinstance(row, ORM):
            raise TypeError(
                f"feature_collection(): expected ORM model instances, got "
                f"{type(row).__name__}. Pass Model.all() / Model.where(...) / a "
                f"list of models — a raw row dict has no field definitions, so "
                f"there is no geometry field to find."
            )
        features.append(row.to_feature(geometry_field=geometry_field, include=include))
    return {"type": "FeatureCollection", "features": features}
