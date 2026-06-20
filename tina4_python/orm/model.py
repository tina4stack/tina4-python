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
from typing import TYPE_CHECKING, Self
from tina4_python.orm.fields import Field, RelationshipDescriptor
from tina4_python.core.cache import Cache

# Module-level query cache — shared across all ORM models
_query_cache = Cache(default_ttl=0, max_size=500)

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
    # Last save() failure cause (validation message or DB error). None when
    # the most recent save() succeeded. Mirrors db.get_error() so a caller
    # that checks ``if not model.save():`` can still recover the real cause
    # via ``model.get_error()`` / ``model.last_error`` — the failure never
    # vanishes silently.
    last_error: str | None = None

    def __init__(self, data: dict | str = None, **kwargs):
        # Initialize relationship cache
        self._rel_cache = {}

        # Set defaults from field definitions.
        # v3.13.11 (issue #50): callable defaults are evaluated *per
        # instance* so per-row timestamps (e.g. ``default=lambda:
        # datetime.now()``) actually differ. Pre-v3.13.11 the function
        # object reached the driver verbatim and blew up with
        # ``can't adapt type 'function'``.
        for name, field in self._fields.items():
            setattr(self, name, field._resolve_default())

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

    def _populate(self, data: dict):
        """Set field values from a dict.

        Applies reverse field_mapping so DB column names are converted
        to Python attribute names before assignment.
        """
        # Build reverse mapping: db_column -> python_attribute
        reverse = {v: k for k, v in self.field_mapping.items()} if self.field_mapping else {}

        for key, value in data.items():
            # Convert DB column name to Python attribute name if mapped
            attr = reverse.get(key, key)
            if attr in self._fields:
                field = self._fields[attr]
                setattr(self, attr, field.validate(value))
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

        Returns:
            A QueryBuilder instance bound to this model's table and database.
        """
        from tina4_python.query_builder import QueryBuilder
        return QueryBuilder.from_table(cls._get_table(), cls._get_db())

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
        """Get primary key field name."""
        for name, field in cls._fields.items():
            if field.primary_key:
                return name
        return "id"

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
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        data = {}
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
                data[db_col] = value

        # v3.13.11 (issue #50): pick INSERT vs UPDATE on row existence
        # for non-auto-increment PKs. Auto-increment keeps the legacy
        # behaviour (PK is None → INSERT, PK is set → UPDATE).
        is_update = False
        if pk_value is not None:
            if pk_field.auto_increment:
                is_update = True
            else:
                # Natural-key model — check if the row already exists.
                # type(self).exists() handles soft-delete + scope filters
                # the same way the rest of the ORM does.
                try:
                    is_update = type(self).exists(pk_value)
                except Exception:
                    # If we can't tell (e.g. table doesn't exist yet),
                    # fall back to INSERT — the user will see the real
                    # error from the driver instead of a silent no-op.
                    is_update = False

        db.start_transaction()
        try:
            if is_update:
                update_data = {k: v for k, v in data.items() if k != pk_db_col}
                if update_data:
                    db.update(table, update_data, f"{pk_db_col} = ?", [pk_value])
            else:
                db.insert(table, data)
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
            self.last_error = db.get_error() or str(e)
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

    def delete(self) -> bool:
        """Delete this record (soft or hard)."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        db.start_transaction()
        try:
            if self.soft_delete:
                db.update(table, {"is_deleted": 1}, f"{pk_db_col} = ?", [pk_value])
                self.is_deleted = 1
            else:
                db.delete(table, f"{pk_db_col} = ?", [pk_value])
            db.commit()
        except Exception:
            db.rollback()
            raise
        return True

    def force_delete(self) -> bool:
        """Hard delete, even if soft delete is enabled."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        db.start_transaction()
        try:
            db.delete(table, f"{pk_db_col} = ?", [pk_value])
            db.commit()
        except Exception:
            db.rollback()
            raise
        return True

    def restore(self) -> bool:
        """Restore a soft-deleted record."""
        if not self.soft_delete:
            raise RuntimeError("Model does not support soft delete")

        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        db.start_transaction()
        try:
            db.update(table, {"is_deleted": 0}, f"{pk_db_col} = ?", [pk_value])
            self.is_deleted = 0
            db.commit()
        except Exception:
            db.rollback()
            raise
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
        pk_col = cls.field_mapping.get(pk, cls._fields[pk].column)

        sql = f"SELECT * FROM {table} WHERE {pk_col} = ?"
        if cls.soft_delete:
            sql += " AND (is_deleted = 0 OR is_deleted IS NULL)"

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
        conditions = []
        params = []

        if filter:
            for key, value in filter.items():
                col = cls.field_mapping.get(key, key)
                conditions.append(f"{col} = ?")
                params.append(value)

        if cls.soft_delete:
            conditions.append("(is_deleted = 0 OR is_deleted IS NULL)")

        sql = f"SELECT * FROM {table}"
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

        if filter is None:
            # No args — use the primary key value already set
            pk = self._get_pk()
            pk_value = getattr(self, pk, None)
            if pk_value is None:
                return False
            pk_col = self.field_mapping.get(pk, self._fields[pk].column)
            sql = f"SELECT * FROM {table} WHERE {pk_col} = ?"
            params = [pk_value]
        else:
            sql = f"SELECT * FROM {table} WHERE {filter}"

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

        sql = f"SELECT * FROM {table}"
        if cls.soft_delete:
            sql += " WHERE (is_deleted = 0 OR is_deleted IS NULL)"
        if order_by:
            sql += f" ORDER BY {order_by}"

        result = db.fetch(sql, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return instances

    @classmethod
    def select(cls, sql: str = None, params: list = None, limit: int = 20, offset: int = 0,
               include: list[str] = None) -> list[Self]:
        """SQL-first query — returns array of ORM objects.

        When ``sql`` is omitted, defaults to ``SELECT * FROM <table>`` so
        ``Product.select(limit=20)`` works as the scaffolder's CRUD-list
        route expects. Same soft-delete filter as ``where()`` is applied
        when ``cls.soft_delete`` is True.
        """
        db = cls._get_db()
        if not sql:
            table = cls._get_table()
            sql = f"SELECT * FROM {table}"
            if cls.soft_delete:
                sql += " WHERE is_deleted = 0 OR is_deleted IS NULL"
        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return instances

    @classmethod
    def select_one(cls, sql: str, params: list = None, include: list[str] = None) -> Self | None:
        """Return a single ORM instance for a raw SQL query, or None if no rows match."""
        instances = cls.select(sql, params, limit=1, offset=0, include=include)
        return instances[0] if instances else None

    @classmethod
    def where(cls, filter_sql: str, params: list = None, limit: int = 20, offset: int = 0,
              include: list[str] = None, with_count: bool = False):
        """Query with WHERE clause — returns array of ORM objects.

        Two return shapes:

        * ``Model.where("active = ?", [1])``               → ``list[Self]``
        * ``Model.where("active = ?", [1], with_count=True)`` → ``tuple[list[Self], int]``

        The tuple form is for pagination UIs where the total count is
        needed alongside the page slice — saves a second query. Total
        count respects the same filter clause but ignores limit/offset.
        """
        db = cls._get_db()
        table = cls._get_table()

        sql = f"SELECT * FROM {table} WHERE {filter_sql}"
        if cls.soft_delete:
            sql = f"SELECT * FROM {table} WHERE ({filter_sql}) AND (is_deleted = 0 OR is_deleted IS NULL)"

        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)

        if with_count:
            count_sql = f"SELECT COUNT(*) AS n FROM {table} WHERE {filter_sql}"
            if cls.soft_delete:
                count_sql = (
                    f"SELECT COUNT(*) AS n FROM {table} "
                    f"WHERE ({filter_sql}) AND (is_deleted = 0 OR is_deleted IS NULL)"
                )
            count_row = db.fetch_one(count_sql, params)
            total = int(count_row["n"]) if count_row else len(instances)
            return instances, total

        return instances

    @classmethod
    def with_trashed(cls, filter_sql: str = "1=1", params: list = None, limit: int = 20, offset: int = 0) -> list[Self]:
        """Query including soft-deleted records."""
        db = cls._get_db()
        table = cls._get_table()
        sql = f"SELECT * FROM {table} WHERE {filter_sql}"
        result = db.fetch(sql, params, limit=limit, offset=offset)
        return [cls(row) for row in result.records]

    @classmethod
    def count(cls, conditions: str = None, params: list = None) -> int:
        """Count records matching conditions (respects soft delete)."""
        db = cls._get_db()
        table = cls._get_table()

        where_parts = []
        if cls.soft_delete:
            where_parts.append("(is_deleted = 0 OR is_deleted IS NULL)")
        if conditions:
            where_parts.append(f"({conditions})")

        sql = f"SELECT COUNT(*) as cnt FROM {table}"
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
        Returns True on success.
        """
        from tina4_python.database.adapter import SQLTranslator

        db = cls._get_db()
        table = cls._get_table()
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
            elif kind == "BooleanField":
                sql_type = bool_sql
            elif kind == "DateTimeField":
                sql_type = datetime_sql
            elif kind == "BlobField":
                sql_type = "BLOB"
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

            if field_obj.primary_key:
                parts.append("PRIMARY KEY")
            if field_obj.auto_increment:
                parts.append("AUTOINCREMENT")
            if field_obj.required and not field_obj.primary_key:
                parts.append("NOT NULL")
            if field_obj.default is not None and not field_obj.auto_increment:
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

        sql = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"

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
            db.commit()
        except Exception as e:
            from tina4_python.debug import Log
            Log.error(f"create_table failed for {table}: {db.get_error() or e}", sql=sql)
            return False
        return True

    # ── Cached Queries ────────────────────────────────────────

    @classmethod
    def cached(cls, sql: str, params: list = None, ttl: int = 60,
               limit: int = 20, offset: int = 0, include: list = None) -> list[Self]:
        """SQL query with result caching. Returns array of ORM objects."""
        cache_key = f"{cls.__name__}:{Cache.query_key(sql, params)}:{limit}:{offset}"
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return cached

        result = cls.select(sql, params, limit=limit, offset=offset, include=include)
        _query_cache.set(cache_key, result, ttl=ttl, tags=[cls.__name__])
        return result

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached query results for this model."""
        _query_cache.clear_tag(cls.__name__)

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

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        row = self._get_db().fetch_one(sql, [pk_value])
        return related_class(row) if row else None

    def has_many(self, related_class, foreign_key: str = None, limit: int = 100, offset: int = 0) -> list[Self]:
        """Load multiple related records (imperative style)."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        result = self._get_db().fetch(sql, [pk_value], limit=limit, offset=offset)
        return [related_class(row) for row in result.records]

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
                table = related_cls._get_table()
                placeholders = ",".join("?" for _ in pk_values)
                sql = f"SELECT * FROM {table} WHERE {fk} IN ({placeholders})"
                result = db.fetch(sql, pk_values, limit=len(pk_values) * 1000, offset=0)
                related_records = [related_cls(row) for row in result.records]

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
                table = related_cls._get_table()
                placeholders = ",".join("?" for _ in fk_values)
                pk_col = related_cls.field_mapping.get(related_pk, related_cls._fields[related_pk].column)
                sql = f"SELECT * FROM {table} WHERE {pk_col} IN ({placeholders})"
                result = db.fetch(sql, fk_values, limit=len(fk_values) * 10, offset=0)
                related_records = [related_cls(row) for row in result.records]

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
        def scope_method(limit: int = 20, offset: int = 0):
            return cls.where(filter_sql, params, limit=limit, offset=offset)

        setattr(cls, name, staticmethod(scope_method))

    # ── Validation ──────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Validate all fields. Returns list of error messages (empty = valid)."""
        errors = []
        for name, field in self._fields.items():
            value = getattr(self, name)
            try:
                field.validate(value)
            except ValueError as e:
                errors.append(str(e))
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
