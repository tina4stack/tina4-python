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
from tina4_python.orm.fields import Field
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


class ORMMeta(type):
    """Metaclass that collects Field definitions from class body."""

    def __new__(mcs, name, bases, namespace):
        fields = {}
        for key, value in list(namespace.items()):
            if isinstance(value, Field):
                value.name = key
                if value.column is None:
                    value.column = key
                fields[key] = value

        namespace["_fields"] = fields
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
    _db: str | object | None = None  # Per-model database override
    _fields: dict[str, Field] = {}

    def __init__(self, data: dict | str = None, **kwargs):
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
        """Set field values from a dict."""
        for key, value in data.items():
            if key in self._fields:
                field = self._fields[key]
                setattr(self, key, field.validate(value))
            else:
                # Allow extra attributes (from joined queries, etc.)
                setattr(self, key, value)

    @classmethod
    def _get_table(cls) -> str:
        """Get table name — defaults to lowercase class name + 's'."""
        if cls.table_name:
            return cls.table_name
        return cls.__name__.lower() + "s"

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
            raise RuntimeError(
                "No database bound. Call orm_bind(db) before using ORM models."
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
        """Insert or update. Returns self for chaining."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk, None)
        table = self._get_table()

        data = {}
        for name, field in self._fields.items():
            if field.auto_increment and pk_value is None:
                continue  # Skip auto-increment on insert
            value = getattr(self, name)
            if value is not None or not field.auto_increment:
                data[field.column] = value

        if pk_value is not None:
            # Update — use primary key as filter
            update_data = {k: v for k, v in data.items() if k != self._fields[pk].column}
            if update_data:
                db.update(table, update_data, f"{self._fields[pk].column} = ?", [pk_value])
        else:
            # Insert
            result = db.insert(table, data)
            if result.last_id and pk in self._fields:
                setattr(self, pk, result.last_id)

        # Invalidate cached queries for this model
        self.clear_cache()
        return self

    def delete(self):
        """Delete this record (soft or hard)."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        if self.soft_delete and "deleted_at" in self._fields:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            db.update(table, {"deleted_at": now}, f"{self._fields[pk].column} = ?", [pk_value])
            self.deleted_at = now
        else:
            db.delete(table, f"{self._fields[pk].column} = ?", [pk_value])

    def force_delete(self):
        """Hard delete, even if soft delete is enabled."""
        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()

        if pk_value is None:
            raise ValueError("Cannot delete: no primary key value")

        db.delete(table, f"{self._fields[pk].column} = ?", [pk_value])

    def restore(self):
        """Restore a soft-deleted record."""
        if not self.soft_delete:
            raise RuntimeError("Model does not support soft delete")

        db = self._get_db()
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        table = self._get_table()

        db.update(table, {"deleted_at": None}, f"{self._fields[pk].column} = ?", [pk_value])
        self.deleted_at = None

    # ── Finders ─────────────────────────────────────────────────

    @classmethod
    def find(cls, pk_value):
        """Find a single record by primary key. Returns instance or None."""
        db = cls._get_db()
        pk = cls._get_pk()
        table = cls._get_table()
        pk_col = cls._fields[pk].column

        sql = f"SELECT * FROM {table} WHERE {pk_col} = ?"
        if cls.soft_delete:
            sql += " AND deleted_at IS NULL"

        row = db.fetch_one(sql, [pk_value])
        if row is None:
            return None
        return cls(row)

    @classmethod
    def find_or_fail(cls, pk_value):
        """Find by primary key or raise ValueError."""
        result = cls.find(pk_value)
        if result is None:
            raise ValueError(f"{cls.__name__} with {cls._get_pk()}={pk_value} not found")
        return result

    @classmethod
    def all(cls, limit: int = 100, skip: int = 0):
        """Fetch all records (respects soft delete)."""
        db = cls._get_db()
        table = cls._get_table()

        sql = f"SELECT * FROM {table}"
        if cls.soft_delete:
            sql += " WHERE deleted_at IS NULL"

        result = db.fetch(sql, limit=limit, skip=skip)
        return [cls(row) for row in result.records], result.count

    @classmethod
    def select(cls, sql: str, params: list = None, limit: int = 20, skip: int = 0):
        """SQL-first query — you write the SQL, ORM maps results."""
        db = cls._get_db()
        result = db.fetch(sql, params, limit=limit, skip=skip)
        return [cls(row) for row in result.records], result.count

    @classmethod
    def where(cls, filter_sql: str, params: list = None, limit: int = 20, skip: int = 0):
        """Query with WHERE clause shorthand."""
        db = cls._get_db()
        table = cls._get_table()

        sql = f"SELECT * FROM {table} WHERE {filter_sql}"
        if cls.soft_delete:
            sql = f"SELECT * FROM {table} WHERE ({filter_sql}) AND deleted_at IS NULL"

        result = db.fetch(sql, params, limit=limit, skip=skip)
        return [cls(row) for row in result.records], result.count

    @classmethod
    def with_trashed(cls, filter_sql: str = "1=1", params: list = None, limit: int = 20, skip: int = 0):
        """Query including soft-deleted records."""
        db = cls._get_db()
        table = cls._get_table()
        sql = f"SELECT * FROM {table} WHERE {filter_sql}"
        result = db.fetch(sql, params, limit=limit, skip=skip)
        return [cls(row) for row in result.records], result.count

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

    # ── Cached Queries ────────────────────────────────────────

    @classmethod
    def cached(cls, sql: str, params: list = None, ttl: int = 60,
               limit: int = 20, skip: int = 0):
        """SQL query with result caching.

        Usage:
            users, count = User.cached("SELECT * FROM users WHERE active = ?", [1], ttl=120)
        """
        cache_key = f"{cls.__name__}:{Cache.query_key(sql, params)}:{limit}:{skip}"
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return cached

        result = cls.select(sql, params, limit=limit, skip=skip)
        _query_cache.set(cache_key, result, ttl=ttl, tags=[cls.__name__])
        return result

    @classmethod
    def clear_cache(cls):
        """Clear all cached query results for this model."""
        _query_cache.clear_tag(cls.__name__)

    # ── Relationships ───────────────────────────────────────────

    def has_one(self, related_class, foreign_key: str = None):
        """Load a single related record."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        row = self._get_db().fetch_one(sql, [pk_value])
        return related_class(row) if row else None

    def has_many(self, related_class, foreign_key: str = None, limit: int = 100, skip: int = 0):
        """Load multiple related records."""
        pk = self._get_pk()
        pk_value = getattr(self, pk)
        fk = foreign_key or f"{self.__class__.__name__.lower()}_id"
        table = related_class._get_table()

        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        result = self._get_db().fetch(sql, [pk_value], limit=limit, skip=skip)
        return [related_class(row) for row in result.records]

    def belongs_to(self, related_class, foreign_key: str = None):
        """Load the parent record."""
        fk = foreign_key or f"{related_class.__name__.lower()}_id"
        fk_value = getattr(self, fk, None)
        if fk_value is None:
            return None
        return related_class.find(fk_value)

    # ── Scopes ──────────────────────────────────────────────────

    @classmethod
    def scope(cls, name: str, filter_sql: str, params: list = None):
        """Register a reusable query scope on the class.

            User.scope("active", "active = ?", [1])
            users, count = User.active()
        """
        def scope_method(limit: int = 20, skip: int = 0):
            return cls.where(filter_sql, params, limit=limit, skip=skip)

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

    def to_dict(self) -> dict:
        """Convert to dict (field values only)."""
        return {name: getattr(self, name) for name in self._fields}

    def to_object(self) -> dict:
        """Convert to an object/dict (alias for to_dict)."""
        return self.to_dict()

    def to_array(self) -> list:
        """Convert to a list of values."""
        return list(self.to_dict().values())

    def to_list(self) -> list:
        """Convert to a list of values (alias for to_array)."""
        return self.to_array()

    def to_json(self) -> str:
        """Convert to JSON string."""
        import json
        data = self.to_dict()
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
