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
from tina4_python.orm.fields import Field, RelationshipDescriptor
from tina4_python.core.cache import Cache

# Module-level query cache — shared across all ORM models
_query_cache = Cache(default_ttl=0, max_size=500)

# Global database reference — set via orm_bind()
_database = None
# Named database connections registry
_databases: dict[str, object] = {}


def orm_bind(db, name: str = None):
    """Bind a Database instance to ORM models.

    Args:
        db: Database instance to bind.
        name: Optional name for the connection (e.g., "audit", "analytics").
              If None, sets the global default used by all models without _db.

    Usage:
        orm_bind(db_main)                    # default for all models
        orm_bind(db_audit, name="audit")     # named connection

        class AuditLog(ORM):
            _db = "audit"  # uses the named connection
    """
    global _database
    if name is None:
        _database = db
    else:
        _databases[name] = db


def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase: 'first_name' -> 'firstName'."""
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

        namespace["_fields"] = fields
        namespace["_relationships"] = relationships
        cls = super().__new__(mcs, name, bases, namespace)
        return cls


class ORM(metaclass=ORMMeta):
    """SQL-first Active Record base class.

    Features:
    - CRUD: save(), load(), delete(), select(), find()
    - Soft delete: deleted_at field, with_trashed(), restore(), force_delete()
    - Scopes: reusable query filters
    - Relationships: has_one(), has_many()
    - Validation from field definitions
    """

    table_name: str = ""
    soft_delete: bool = False  # Set True to enable soft delete
    field_mapping: dict[str, str] = {}  # {"python_attribute": "db_column"}
    auto_map: bool = False  # No-op in Python (snake_case matches DB); exists for cross-language parity
    _db: str | object | None = None  # Per-model database override
    _fields: dict[str, Field] = {}

    def __init__(self, data: dict | str = None, **kwargs):
        # Initialize relationship cache
        self._rel_cache = {}

        # Set defaults from field definitions
        for name, field in self._fields.items():
            setattr(self, name, field.default)

        # Accept JSON string or dict
        if isinstance(data, str):
            import json
            data = json.loads(data)

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
        if os.environ.get("ORM_PLURAL_TABLE_NAMES", "").lower() in ("true", "1", "yes"):
            name += "s"
        return name

    @classmethod
    def _get_db(cls):
        """Get the bound database for this model.

        Resolution order:
        1. cls._db as a Database instance (direct assignment)
        2. cls._db as a string name → look up in _databases registry
        3. Global _database (set via orm_bind(db))
        """
        if cls._db is not None:
            if isinstance(cls._db, str):
                db = _databases.get(cls._db)
                if db is None:
                    raise RuntimeError(
                        f"Named database '{cls._db}' not found. "
                        f"Call orm_bind(db, name='{cls._db}') first."
                    )
                return db
            return cls._db  # Direct Database instance

        if _database is None:
            # Try auto-discovery from DATABASE_URL
            import os
            url = os.environ.get("DATABASE_URL")
            if url:
                from tina4_python.database import Database
                username = os.environ.get("DATABASE_USERNAME", "")
                password = os.environ.get("DATABASE_PASSWORD", "")
                db = Database(url, username, password)
                orm_bind(db)
                return db
            raise RuntimeError(
                "No database bound. Call orm_bind(db) or set DATABASE_URL in .env"
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

    def save(self):
        """Insert or update. Returns self on success, False on failure."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk, None)
        table = self._get_table()
        pk_db_col = self.field_mapping.get(pk, self._fields[pk].column)

        data = {}
        for name, field in self._fields.items():
            if field.auto_increment and pk_value is None:
                continue  # Skip auto-increment on insert
            value = getattr(self, name)
            if value is not None or not field.auto_increment:
                # Use field_mapping for the column name, fall back to field.column
                db_col = self.field_mapping.get(name, field.column)
                data[db_col] = value

        db.start_transaction()
        try:
            if pk_value is not None:
                update_data = {k: v for k, v in data.items() if k != pk_db_col}
                if update_data:
                    db.update(table, update_data, f"{pk_db_col} = ?", [pk_value])
            else:
                result = db.insert(table, data)
                if result.last_id and pk in self._fields:
                    setattr(self, pk, result.last_id)
            db.commit()
        except Exception:
            db.rollback()
            return False

        self.clear_cache()
        self._rel_cache = {}
        self._persisted = True
        return self

    def delete(self):
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
            if self.soft_delete and "deleted_at" in self._fields:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                db.update(table, {"deleted_at": now}, f"{pk_db_col} = ?", [pk_value])
                self.deleted_at = now
            else:
                db.delete(table, f"{pk_db_col} = ?", [pk_value])
            db.commit()
        except Exception:
            db.rollback()
            raise

    def force_delete(self):
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

    def restore(self):
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
            db.update(table, {"deleted_at": None}, f"{pk_db_col} = ?", [pk_value])
            self.deleted_at = None
            db.commit()
        except Exception:
            db.rollback()
            raise

    # ── Finders ─────────────────────────────────────────────────

    @classmethod
    def create(cls, data: dict = None, **kwargs):
        """Create a new instance, save it, and return it.

        Usage:
            user = User.create({"name": "Alice", "email": "alice@example.com"})
            user = User.create(name="Alice", email="alice@example.com")
        """
        instance = cls(data or kwargs)
        instance.save()
        return instance

    @classmethod
    def find_by_id(cls, pk_value, include: list[str] = None):
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
            sql += " AND deleted_at IS NULL"

        return cls.select_one(sql, [pk_value], include=include)

    @classmethod
    def find(cls, pk_value, include: list[str] = None):
        """Alias for find_by_id()."""
        return cls.find_by_id(pk_value, include)

    def load(self, sql: str, params: list = None, include: list[str] = None) -> bool:
        """Load a record into this instance via selectOne.

        Returns True if a record was found and loaded, False otherwise.
        """
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
    def find_or_fail(cls, pk_value):
        """Find by primary key or raise ValueError."""
        result = cls.find_by_id(pk_value)
        if result is None:
            raise ValueError(f"{cls.__name__} with {cls._get_pk()}={pk_value} not found")
        return result

    @classmethod
    def all(cls, limit: int = 100, offset: int = 0, include: list[str] = None):
        """Fetch all records (respects soft delete).

        Args:
            include: List of relationship names to eager-load.
        """
        db = cls._get_db()
        table = cls._get_table()

        sql = f"SELECT * FROM {table}"
        if cls.soft_delete:
            sql += " WHERE deleted_at IS NULL"

        result = db.fetch(sql, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return instances

    @classmethod
    def select(cls, sql: str, params: list = None, limit: int = 20, offset: int = 0,
               include: list[str] = None) -> list:
        """SQL-first query — returns array of ORM objects."""
        db = cls._get_db()
        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return instances

    @classmethod
    def select_one(cls, sql: str, params: list = None, include: list[str] = None):
        """Return a single ORM instance for a raw SQL query, or None if no rows match."""
        instances = cls.select(sql, params, limit=1, offset=0, include=include)
        return instances[0] if instances else None

    @classmethod
    def where(cls, filter_sql: str, params: list = None, limit: int = 20, offset: int = 0,
              include: list[str] = None) -> list:
        """Query with WHERE clause — returns array of ORM objects."""
        db = cls._get_db()
        table = cls._get_table()

        sql = f"SELECT * FROM {table} WHERE {filter_sql}"
        if cls.soft_delete:
            sql = f"SELECT * FROM {table} WHERE ({filter_sql}) AND deleted_at IS NULL"

        result = db.fetch(sql, params, limit=limit, offset=offset)
        instances = [cls(row) for row in result.records]
        if include:
            cls._eager_load(instances, include)
        return instances

    @classmethod
    def with_trashed(cls, filter_sql: str = "1=1", params: list = None, limit: int = 20, offset: int = 0):
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
            where_parts.append("deleted_at IS NULL")
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
            BooleanField → INTEGER
            DateTimeField → DATETIME
            BlobField    → BLOB

        Auto-increment primary keys use engine-appropriate syntax.
        Returns True on success.
        """
        from tina4_python.database.adapter import SQLTranslator

        db = cls._get_db()
        table = cls._get_table()

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
                sql_type = "INTEGER"
            elif kind == "DateTimeField":
                sql_type = "DATETIME"
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
                    sql_type = "INTEGER"
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
                    parts.append(f"DEFAULT {1 if default_val else 0}")
                else:
                    parts.append(f"DEFAULT {default_val}")

            col_defs.append(" ".join(parts))

        sql = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"

        # Translate auto-increment syntax for the current engine
        engine = db.get_database_type()
        sql = SQLTranslator.auto_increment_syntax(sql, engine)

        db.execute(sql)
        db.commit()
        return True

    # ── Cached Queries ────────────────────────────────────────

    @classmethod
    def cached(cls, sql: str, params: list = None, ttl: int = 60,
               limit: int = 20, offset: int = 0):
        """SQL query with result caching. Returns array of ORM objects."""
        cache_key = f"{cls.__name__}:{Cache.query_key(sql, params)}:{limit}:{offset}"
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return cached

        result = cls.select(sql, params, limit=limit, offset=offset)
        _query_cache.set(cache_key, result, ttl=ttl, tags=[cls.__name__])
        return result

    @classmethod
    def clear_cache(cls):
        """Clear all cached query results for this model."""
        _query_cache.clear_tag(cls.__name__)

    # ── Relationships ───────────────────────────────────────────

    def has_one(self, related_class, foreign_key: str = None):
        """Load a single related record (imperative style)."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        row = self._get_db().fetch_one(sql, [pk_value])
        return related_class(row) if row else None

    def has_many(self, related_class, foreign_key: str = None, limit: int = 100, offset: int = 0):
        """Load multiple related records (imperative style)."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        result = self._get_db().fetch(sql, [pk_value], limit=limit, offset=offset)
        return [related_class(row) for row in result.records]

    def belongs_to(self, related_class, foreign_key: str = None):
        """Load the parent record (imperative style)."""
        fk = foreign_key or f"{related_class.__name__.lower()}_id"
        fk_value = getattr(self, fk, None)
        if fk_value is None:
            return None
        return related_class.find(fk_value)

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
    def scope(cls, name: str, filter_sql: str, params: list = None):
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

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self, include: list[str] = None) -> dict:
        """Convert to dict (field values only, optionally with relationships).

        Args:
            include: List of relationship names to include. Supports dot notation
                     for nested relationships (e.g., ["posts.comments"]).
        """
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
                    if related is None:
                        result[rel_name] = None
                    elif isinstance(related, list):
                        result[rel_name] = [
                            r.to_dict(include=nested if nested else None)
                            for r in related
                        ]
                    else:
                        result[rel_name] = related.to_dict(
                            include=nested if nested else None
                        )

        return result

    def to_assoc(self, include: list[str] = None) -> dict:
        """Convert to an associative dict (alias for to_dict)."""
        return self.to_dict(include=include)

    def to_object(self) -> dict:
        """Convert to an object/dict (alias for to_dict)."""
        return self.to_dict()

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
