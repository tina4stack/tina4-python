# Tina4 ORM Fields — Type definitions for model columns.
"""
Fields define column types, constraints, and defaults for ORM models.

    class User(ORM):
        id = Field(int, primary_key=True)
        name = Field(str, required=True, min_length=1, max_length=100)
        email = Field(str, regex=r'^[^@]+@[^@]+\\.[^@]+$')
        role = Field(str, choices=["admin", "user", "guest"])
        active = Field(bool, default=True)
"""
import re as _re
from datetime import datetime


class Field:
    """Generic field descriptor — maps a Python type to a database column."""

    def __init__(
        self,
        field_type: type = str,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        required: bool = False,
        default=None,
        column: str = None,
        min_length: int = None,
        max_length: int = None,
        min_value: float | int = None,
        max_value: float | int = None,
        regex: str = None,
        choices: list = None,
        validator: callable = None,
    ):
        self.field_type = field_type
        self.primary_key = primary_key
        self.auto_increment = auto_increment
        self.required = required
        self.default = default
        self.column = column  # Override DB column name
        self.name = None  # Set by ORM metaclass

        # Validation constraints
        self.min_length = min_length
        self.max_length = max_length
        self.min_value = min_value
        self.max_value = max_value
        self.regex = _re.compile(regex) if regex else None
        self.regex_pattern = regex  # Keep original for error messages
        self.choices = choices
        self.validator = validator  # Custom callable(value) → raises ValueError

    def validate(self, value):
        """Validate and coerce value to the field type."""
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{self.name}' is required")
            return self.default

        # Type coercion
        try:
            if self.field_type == bool and isinstance(value, int):
                value = bool(value)
            else:
                value = self.field_type(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Field '{self.name}': cannot convert {value!r} to {self.field_type.__name__}"
            ) from e

        # String length constraints
        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                raise ValueError(
                    f"Field '{self.name}': minimum length is {self.min_length}, got {len(value)}"
                )
            if self.max_length is not None and len(value) > self.max_length:
                raise ValueError(
                    f"Field '{self.name}': maximum length is {self.max_length}, got {len(value)}"
                )

        # Numeric range constraints
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min_value is not None and value < self.min_value:
                raise ValueError(
                    f"Field '{self.name}': minimum value is {self.min_value}, got {value}"
                )
            if self.max_value is not None and value > self.max_value:
                raise ValueError(
                    f"Field '{self.name}': maximum value is {self.max_value}, got {value}"
                )

        # Regex pattern
        if self.regex and isinstance(value, str):
            if not self.regex.match(value):
                raise ValueError(
                    f"Field '{self.name}': value does not match pattern {self.regex_pattern}"
                )

        # Choices
        if self.choices is not None and value not in self.choices:
            raise ValueError(
                f"Field '{self.name}': must be one of {self.choices}, got {value!r}"
            )

        # Custom validator
        if self.validator is not None:
            self.validator(value)

        return value

    def __repr__(self):
        parts = [self.field_type.__name__]
        if self.primary_key:
            parts.append("pk")
        if self.required:
            parts.append("required")
        if self.max_length:
            parts.append(f"max={self.max_length}")
        if self.choices:
            parts.append(f"choices={self.choices}")
        return f"Field({', '.join(parts)})"


# Convenience aliases — both short and verbose forms supported.
# Verbose is preferred: IntegerField, StringField, BooleanField.
# Short forms (IntField, StrField, BoolField) kept for brevity.

def _make_field(field_type: type, kind: str, **kwargs) -> Field:
    """Create a Field and tag it with a kind name for introspection."""
    f = Field(field_type, **kwargs)
    f.kind = kind  # e.g. "IntegerField", "StringField" — used by GraphQL
    return f

def IntegerField(**kwargs):
    return _make_field(int, "IntegerField", **kwargs)

def StringField(**kwargs):
    return _make_field(str, "StringField", **kwargs)

def BooleanField(**kwargs):
    return _make_field(bool, "BooleanField", **kwargs)

def FloatField(**kwargs):
    return _make_field(float, "FloatField", **kwargs)

def DateTimeField(**kwargs):
    return _make_field(datetime, "DateTimeField", **kwargs)

def TextField(**kwargs):
    return _make_field(str, "TextField", **kwargs)

def BlobField(**kwargs):
    return _make_field(bytes, "BlobField", **kwargs)

def NumericField(**kwargs):
    return _make_field(float, "NumericField", **kwargs)

# Short aliases — kept for backwards compatibility
IntField = IntegerField
StrField = StringField
BoolField = BooleanField


# ── Relationship Descriptors ────────────────────────────────────

class RelationshipDescriptor:
    """Base descriptor for ORM relationships. Lazy-loads on first access."""

    def __init__(self, model_name: str, foreign_key: str = None, rel_type: str = "has_many"):
        self.model_name = model_name
        self.foreign_key = foreign_key
        self.rel_type = rel_type  # "has_many", "has_one", "belongs_to"
        self.attr_name = None  # Set by ORMMeta

    def _resolve_model(self):
        """Resolve the related model class by name from ORM subclasses."""
        from tina4_python.orm.model import ORM
        for cls in ORM.__subclasses__():
            if cls.__name__ == self.model_name:
                return cls
        # Try recursive subclass search
        def _find_subclass(parent):
            for sub in parent.__subclasses__():
                if sub.__name__ == self.model_name:
                    return sub
                found = _find_subclass(sub)
                if found:
                    return found
            return None
        found = _find_subclass(ORM)
        if found:
            return found
        raise ValueError(f"Related model '{self.model_name}' not found")

    def __set_name__(self, owner, name):
        self.attr_name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self  # Class-level access returns the descriptor
        # Check relationship cache
        cache = obj.__dict__.setdefault("_rel_cache", {})
        if self.attr_name in cache:
            return cache[self.attr_name]
        # Load and cache
        result = self._load(obj)
        cache[self.attr_name] = result
        return result

    def __set__(self, obj, value):
        # Allow direct assignment (used by eager loading)
        cache = obj.__dict__.setdefault("_rel_cache", {})
        cache[self.attr_name] = value

    def _load(self, obj):
        """Override in subclasses."""
        raise NotImplementedError


class HasManyDescriptor(RelationshipDescriptor):
    """Lazy-loading descriptor for has_many relationships."""

    def _load(self, obj):
        related_cls = self._resolve_model()
        pk = obj._get_pk()
        pk_value = getattr(obj, pk, None)
        if pk_value is None:
            return []
        fk = self.foreign_key or f"{obj.__class__.__name__.lower()}_id"
        table = related_cls._get_table()
        db = obj._get_db()
        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        result = db.fetch(sql, [pk_value], limit=1000, skip=0)
        return [related_cls(row) for row in result.records]


class HasOneDescriptor(RelationshipDescriptor):
    """Lazy-loading descriptor for has_one relationships."""

    def _load(self, obj):
        related_cls = self._resolve_model()
        pk = obj._get_pk()
        pk_value = getattr(obj, pk, None)
        if pk_value is None:
            return None
        fk = self.foreign_key or f"{obj.__class__.__name__.lower()}_id"
        table = related_cls._get_table()
        db = obj._get_db()
        sql = f"SELECT * FROM {table} WHERE {fk} = ? LIMIT 1"
        row = db.fetch_one(sql, [pk_value])
        return related_cls(row) if row else None


class BelongsToDescriptor(RelationshipDescriptor):
    """Lazy-loading descriptor for belongs_to relationships."""

    def _load(self, obj):
        related_cls = self._resolve_model()
        fk = self.foreign_key or f"{related_cls.__name__.lower()}_id"
        fk_value = getattr(obj, fk, None)
        if fk_value is None:
            return None
        return related_cls.find(fk_value)


def has_many(model_name: str, foreign_key: str = None) -> HasManyDescriptor:
    """Declare a has_many relationship on a model class.

    Usage:
        class User(ORM):
            posts = has_many("Post", foreign_key="user_id")
    """
    return HasManyDescriptor(model_name, foreign_key, "has_many")


def has_one(model_name: str, foreign_key: str = None) -> HasOneDescriptor:
    """Declare a has_one relationship on a model class.

    Usage:
        class User(ORM):
            profile = has_one("Profile", foreign_key="user_id")
    """
    return HasOneDescriptor(model_name, foreign_key, "has_one")


def belongs_to(model_name: str, foreign_key: str = None) -> BelongsToDescriptor:
    """Declare a belongs_to relationship on a model class.

    Usage:
        class Post(ORM):
            user = belongs_to("User", foreign_key="user_id")
    """
    return BelongsToDescriptor(model_name, foreign_key, "belongs_to")
