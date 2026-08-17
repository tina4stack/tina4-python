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
import copy as _copy
import json as _json
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

    # ── v3.13.11 (issue #50): callable-default resolution ──────────────
    #
    # Pre-v3.13.11 a callable default (e.g. ``DateTimeField(default=lambda:
    # datetime.now())``) reached the driver verbatim and blew up with
    # ``can't adapt type 'function'``. Now we evaluate the callable at the
    # point of use, so every instance gets a freshly computed value (per-row
    # timestamps actually differ). Types are excluded — ``default=int`` is
    # almost never intended to mean "call int()".
    def _resolve_default(self):
        d = self.default
        if callable(d) and not isinstance(d, type):
            return d()
        return d

    def _coerce_type(self, value):
        """Cast a non-None *value* to the field's declared Python type.

        Drivers return values in different shapes per engine:

          engine        datetime column     bool column    numeric column
          --------      ----------------    -----------    --------------
          SQLite        str                 int (0/1)      float / int
          PostgreSQL    datetime            bool           Decimal
          MySQL         datetime            int (0/1)      Decimal
          MSSQL         datetime            bool           Decimal
          Firebird      datetime            int (0/1)      Decimal

        So the rule is: if the driver already handed us the right type,
        accept it as-is. Otherwise coerce. This avoids the classic crash
        `datetime(datetime_instance)` that hit every PostgreSQL ORM read.

        Care is needed around `bool` being a subclass of `int` in Python —
        we handle those two paths explicitly before the generic fast path.

        Shared by :meth:`validate` (write path) and :meth:`coerce` (read
        path) — the SAME type coercion applies to both; only business-rule
        enforcement (required/length/range/regex/choices/custom validator)
        differs between them (LOAD-DEC-01).
        """
        try:
            # BooleanField receiving an int (e.g. SQLite 0/1) → cast to bool
            if self.field_type is bool and isinstance(value, int) and not isinstance(value, bool):
                value = bool(value)
            # IntegerField receiving a bool → cast to int (preserve legacy behaviour
            # where True/False round-trip as 1/0 in numeric columns)
            elif self.field_type is int and isinstance(value, bool):
                value = int(value)
            # DateTimeField receiving an ISO-8601 string (SQLite default) → parse
            elif self.field_type is datetime and isinstance(value, str):
                value = datetime.fromisoformat(value)
            # Fast path: driver already handed us the correct type. Don't re-coerce —
            # `datetime(datetime_instance)` etc. raises TypeError otherwise.
            elif isinstance(value, self.field_type):
                pass
            else:
                value = self.field_type(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Field '{self.name}': cannot convert {value!r} to {self.field_type.__name__}"
            ) from e
        return value

    def coerce(self, value):
        """Type-coerce *value* for HYDRATION (the read path) — LOAD-DEC-01.

        Runs the same type coercion as :meth:`validate` (str -> datetime,
        int -> bool, JSON parse via subclass overrides, ...) but never
        re-enforces business constraints: required/length/range/regex/
        choices/a custom validator. Those are write-path rules (feature 19);
        re-running them on every read meant a stored row that violated a
        constraint — or one TIGHTENED after the row was written — raised out
        of ``cls(row)`` and aborted the entire ``select()``, not just the
        offending row. A finder must always be able to read what a previous,
        looser write already persisted.
        """
        if value is None:
            return self._resolve_default()

        if callable(value) and not isinstance(value, type):
            value = value()
            if value is None:
                return None

        return self._coerce_type(value)

    def validate(self, value):
        """Validate and coerce value to the field type — the WRITE path.

        Re-enforces every business constraint (required/length/range/regex/
        choices/custom validator) in addition to type coercion. Used by
        ``save()`` (via :meth:`validate_value`'s sibling enforcement) and by
        any caller assigning a NEW value to a field (e.g. AutoCrud's PUT
        handler). For hydrating a row already in the database, use
        :meth:`coerce` instead (LOAD-DEC-01) — re-validating on every read is
        what made a stored row unreadable the moment a constraint tightened.
        """
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{self.name}' is required")
            return self._resolve_default()

        # v3.13.11 (issue #50): if the user stored a callable as the field
        # value (e.g. ``default=lambda: datetime.now()`` reached us without
        # being resolved on instance init), evaluate it now so the driver
        # gets a real value, not the function object. Types are excluded —
        # ``default=int`` is almost never intended to mean "call int()".
        if callable(value) and not isinstance(value, type):
            value = value()
            if value is None:
                return None

        value = self._coerce_type(value)

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

    def validate_value(self, name: str, value) -> list[str]:
        """Collect canonical constraint-violation messages for *value* (empty = valid).

        Feature 19 (VALID-TWO-MESSAGES): this is the ENFORCEMENT surface that
        ``ORM.validate()``/``save()`` use. It emits the SAME field-prefixed
        wording as the request-body ``Validator`` -- "<field> is required",
        "<field> must be at most N characters", "<field> does not match the
        required format" -- so a client keying on a message matches either
        validator. It never coerces and never raises: the coercion-oriented
        :meth:`validate` above is the read-path type-normaliser and is unchanged.
        """
        errors: list[str] = []
        blank = value is None or (isinstance(value, str) and value.strip() == "")
        # required short-circuits -- no other rule adds signal on a missing value
        # (parity with the request Validator's early continue and PHP/Ruby ORM).
        if self.required and self.default is None and blank:
            errors.append(f"{name} is required")
            return errors
        if value is None:
            return errors

        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                errors.append(f"{name} must be at least {self.min_length} characters")
            if self.max_length is not None and len(value) > self.max_length:
                errors.append(f"{name} must be at most {self.max_length} characters")
            if self.regex is not None and not self.regex.match(value):
                errors.append(f"{name} does not match the required format")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min_value is not None and value < self.min_value:
                errors.append(f"{name} must be at least {self.min_value}")
            if self.max_value is not None and value > self.max_value:
                errors.append(f"{name} must be at most {self.max_value}")

        if self.choices is not None and value not in self.choices:
            allowed_json = _json.dumps(self.choices, separators=(",", ":"))
            errors.append(f"{name} must be one of {allowed_json}")

        return errors

    def to_db(self, value):
        """Serialize an in-memory value to the form the driver should store.

        Identity by default — the value already round-trips through the driver
        as-is. Overridden by fields whose Python representation differs from
        their column representation (e.g. ``JSONField`` stores a JSON string).
        Called by ``ORM.save()`` when building the row for INSERT/UPDATE.
        """
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

def DecimalField(*, precision: int = 10, scale: int = 2, **kwargs):
    """A fixed-precision numeric column that emits a real ``DECIMAL(p, s)``.

    ``FloatField`` / ``NumericField`` map to the engine's floating type
    (``REAL``) — fast, but binary floating point cannot represent every
    decimal fraction exactly, so they are the wrong choice for MONEY. Reach for
    ``DecimalField`` when the column must keep an exact scale: it emits a real
    ``DECIMAL(precision, scale)`` column (identical on PostgreSQL, MySQL, MSSQL,
    Firebird and SQLite), so the database stores the value at the declared
    scale instead of a floating approximation.

    The in-memory Python representation is a ``float`` (the documented default —
    it round-trips through every driver and binds on SQLite, which cannot bind a
    ``Decimal``); the fixed scale lives in the COLUMN. For end-to-end exact
    arithmetic, store the amount in minor units (an ``IntegerField`` of cents)
    or hand the column a ``str``/``Decimal`` your driver accepts.

        class Invoice(ORM):
            id     = IntegerField(primary_key=True, auto_increment=True)
            amount = DecimalField(precision=12, scale=4)   # DECIMAL(12,4)
    """
    f = _make_field(float, "DecimalField", **kwargs)
    f.precision = precision
    f.scale = scale
    return f

class JSONField(Field):
    """A column that stores a JSON document (a ``dict`` or a ``list``).

    You work with a plain Python ``dict``/``list``; the ORM serializes it to a
    JSON string on save and parses it back on load. The column DDL is
    engine-aware (see :meth:`ORM.create_table`): ``JSONB`` on PostgreSQL,
    ``JSON`` on MySQL, ``NVARCHAR(MAX)`` on MSSQL, ``TEXT`` on SQLite/ODBC,
    ``BLOB SUB_TYPE TEXT`` on Firebird.

    Read normalization: a native-JSON driver (PostgreSQL JSONB, MySQL JSON) may
    hand back an already-parsed object, while a string-backed engine (SQLite)
    hands back a JSON string. :meth:`validate` normalizes both to a Python
    object, so ``model.data`` is always a ``dict``/``list`` regardless of engine.

    Usage::

        class Event(ORM):
            id      = IntegerField(primary_key=True, auto_increment=True)
            payload = JSONField()

        Event({"payload": {"type": "click", "tags": ["a", "b"]}}).save()
        e = Event.find(1)
        e.payload["type"]   # "click"  — a real dict, not a string
    """

    def __init__(self, **kwargs):
        super().__init__(dict, **kwargs)
        self.kind = "JSONField"

    def _resolve_default(self):
        # Deep-copy a mutable JSON default (``default={}`` / ``default=[]``) so
        # separate instances never alias the same object — the classic
        # shared-default footgun. This runs on BOTH the __init__ default path
        # (which calls _resolve_default directly) and the validate() None path.
        d = super()._resolve_default()
        return _copy.deepcopy(d) if isinstance(d, (dict, list)) else d

    def _parse_json(self, value):
        """Normalize a driver JSON string/bytes (or an already-parsed
        dict/list from a native-JSON engine) to a Python object. Shared by
        :meth:`coerce` (read path) and :meth:`validate` (write path) —
        JSON parsing is type coercion, not a business constraint, so it runs
        on BOTH paths (LOAD-DEC-01/LOAD-JSON-ONLY)."""
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if isinstance(value, str):
            try:
                value = _json.loads(value)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Field '{self.name}': value is not valid JSON") from e
        if not isinstance(value, (dict, list)):
            raise ValueError(
                f"Field '{self.name}': expected a dict or list, got {type(value).__name__}"
            )
        return value

    def coerce(self, value):
        """Read-path hydration (LOAD-DEC-01): parse JSON, skip the custom
        validator and the required check — a stored row must still hydrate
        even if a constraint was tightened after it was written."""
        if value is None:
            return self._resolve_default()
        return self._parse_json(value)

    def validate(self, value):
        # None -> required check + default (mirrors base Field).
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{self.name}' is required")
            return self._resolve_default()

        # A driver returns a JSON string (SQLite/TEXT) or an already-parsed
        # dict/list (PostgreSQL JSONB, MySQL JSON). Normalize to a Python object.
        value = self._parse_json(value)
        if self.validator is not None:
            self.validator(value)
        return value

    def to_db(self, value):
        # Serialize to a JSON string for the driver. A TEXT column stores it
        # verbatim; a native JSON column (JSONB/JSON) casts the string literal.
        if value is None:
            return None
        if isinstance(value, str):
            return value  # already serialized (defensive)
        try:
            return _json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Field '{self.name}': value is not JSON-serializable") from e


class PointField(Field):
    """A column that stores a single geographic point, SRID-aware.

    You work with a :class:`~tina4_python.orm.point.Point` value object; the ORM
    writes EWKT on save and parses the engine's (HEX)EWKB back into a ``Point``
    on load, so ``model.location.lat`` always works regardless of engine wire
    format.

    Assignment accepts any of these and normalises to ``Point``::

        site.location = (18.4241, -33.9249)                            # (lon, lat) tuple
        site.location = "POINT(18.4241 -33.9249)"                       # WKT
        site.location = "SRID=4326;POINT(18.4241 -33.9249)"             # EWKT
        site.location = {"type": "Point", "coordinates": [18.42, -33.9]}  # GeoJSON

    Reading it back gives the value object::

        site.location.lon       # 18.4241
        site.location.lat       # -33.9249
        site.location.wkt       # 'POINT(18.4241 -33.9249)'
        site.location.geojson   # {'type': 'Point', 'coordinates': [18.4241, -33.9249]}

    ``to_dict()`` / ``to_json()`` / ``response()`` emit the GeoJSON form, so a
    map front end consumes a Tina4 route with no translation layer.

    **Engine support is PostGIS-first and never silently wrong.** The column DDL
    is ``geography(Point,<srid>)`` on PostgreSQL, and
    :meth:`~tina4_python.orm.model.ORM.create_table` also creates a GiST index
    for it. On any engine without spatial support, ``create_table()`` raises
    :class:`~tina4_python.database.adapter.SpatialNotSupportedError` naming that
    engine rather than creating a wrong column type.

    Usage::

        class ChargePoint(ORM):
            id       = IntegerField(primary_key=True, auto_increment=True)
            name     = StringField()
            location = PointField()          # geography(Point,4326) + GiST index

        ChargePoint({"name": "V&A", "location": (18.4241, -33.9249)}).save()

        near = ChargePoint.query() \\
            .within_distance("location", (18.42, -33.92), 5000) \\
            .order_by_distance("location", (18.42, -33.92)) \\
            .get()

    Args:
        srid: Spatial reference id for the column. Defaults to 4326 (WGS 84).
        spatial_index: Create the engine's spatial index for this column in
            ``create_table()``. Defaults to True — a radius query without one
            is a full table scan.
    """

    def __init__(self, srid: int = None, spatial_index: bool = True, **kwargs):
        from tina4_python.orm.point import DEFAULT_SRID, Point
        super().__init__(Point, **kwargs)
        self.kind = "PointField"
        self.srid = DEFAULT_SRID if srid is None else int(srid)
        self.spatial_index = spatial_index

    def _resolve_default(self):
        # ORM.__init__ seeds attributes straight from _resolve_default (it does
        # not route through validate), so coerce here too — otherwise a
        # ``default=(lon, lat)`` would leave ``model.location`` as a raw tuple on
        # an unsaved instance and ``.lat`` would fail.
        from tina4_python.orm.point import Point

        default = super()._resolve_default()
        if default is None:
            return default
        return self._parse_point(default)

    def _parse_point(self, value):
        from tina4_python.orm.point import Point

        try:
            point = Point.parse(value, self.srid)
        except ValueError as e:
            raise ValueError(f"Field '{self.name}': {e}") from e
        if point.srid != self.srid:
            raise ValueError(
                f"Field '{self.name}' expects SRID {self.srid}; received {point.srid}. "
                "Tina4 never silently reprojects or restamps spatial data."
            )
        return point

    def coerce(self, value):
        """Hydrate/assign through the Point parser, not ``Point(value)``."""
        return None if value is None else self._parse_point(value)

    def validate(self, value):
        """Coerce any supported point representation into a ``Point``.

        Runs on BOTH the write path (tuple / WKT / GeoJSON from a route) and the
        read path (the engine's HEXEWKB), which is what makes the column
        round-trip identically no matter how it was assigned.
        """
        from tina4_python.orm.point import Point

        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{self.name}' is required")
            default = self._resolve_default()
            return None if default is None else Point.parse(default, self.srid)

        point = self._parse_point(value)

        if self.validator is not None:
            self.validator(point)
        return point

    def to_db(self, value):
        """Serialise to EWKT — ``SRID=4326;POINT(lon lat)``.

        EWKT carries the SRID with the geometry, so the engine never has to
        assume one, and it is accepted verbatim by PostGIS geography input. The
        value is bound as a normal parameter; it is never formatted into SQL.
        """
        from tina4_python.orm.point import Point

        if value is None:
            return None
        return self._parse_point(value).ewkt


class ForeignKeyField(Field):
    """Integer field that references another model's primary key.

    Declaring this field automatically wires up both sides of the relationship:
    - ``belongs_to`` on the model that owns the FK
    - ``has_many``   on the referenced model

    Relationships are READ-SIDE-ONLY (REL-DEC-01): declaring a ``ForeignKeyField``
    wires up traversal accessors, but the framework emits NO DB-level
    ``REFERENCES`` / ``ON DELETE`` clause. Referential integrity is the
    migration/DDL's job (consistent with the no-foreign-key Firebird rule), so
    deleting a parent does NOT cascade to children at the engine level — enforce
    that with hand-written DDL if you need it.

    Args:
        to:           The referenced model class (or its name as a string for
                      forward references).  Required.
        related_name: Name for the ``has_many`` accessor on the referenced model.
                      Defaults to ``<owning_model_lower>s``
                      (e.g. Post → ``posts``).

    Usage::

        class Post(ORM):
            user_id = ForeignKeyField(to=User)
            # Automatically creates:
            #   post.user        → User instance  (belongs_to)
            #   user.posts       → [Post, ...]    (has_many)

        class Comment(ORM):
            post_id = ForeignKeyField(to=Post, related_name="comments")
            # Automatically creates:
            #   comment.post     → Post instance
            #   post.comments    → [Comment, ...]
    """

    def __init__(self, to=None, related_name: str = None, **kwargs):
        # REL-DEC-01: relationships are READ-SIDE-ONLY. The framework emits no
        # DB-level FK / ON DELETE clause, so the old ``on_delete=`` parameter
        # silently did NOTHING (a phantom API). It is dropped: passing it now
        # fails loudly instead of implying a cascade that never happens. Enforce
        # referential integrity in your migration DDL instead.
        if "on_delete" in kwargs:
            raise ValueError(
                "ForeignKeyField no longer accepts on_delete: Tina4 relationships "
                "are read-side-only and emit no ON DELETE / REFERENCES clause. "
                "Enforce referential integrity in your migration DDL instead."
            )
        super().__init__(int, **kwargs)
        self.references = to            # model class or string name
        self.related_name = related_name
        self.kind = "ForeignKeyField"


# Short aliases — kept for backwards compatibility
IntField = IntegerField
StrField = StringField
BoolField = BooleanField


# ── Relationship Descriptors ────────────────────────────────────

# REL-EAGER-UNBOUNDED: lazy has_many pages through children in blocks of this
# size so a parent with more than one page of children never loses the tail.
# Before, the lazy load passed a silent ``limit=1000`` and truncated with no
# signal; now it pages until a short block, so every child is reachable.
_LAZY_PAGE_SIZE = 1000


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
        where = f"{fk} = ?"
        # REL-SOFTDELETE-TRAVERSAL: a soft-deleted child must not surface through
        # parent.children, consistent with the finders' default exclusion.
        if getattr(related_cls, "soft_delete", False):
            where += f" AND {related_cls._soft_delete_filter()}"
        # Order by the child PK so OFFSET paging is stable across pages.
        order_col = related_cls.field_mapping.get(
            related_cls._get_pk(), related_cls._fields[related_cls._get_pk()].column
        )
        sql = f"SELECT * FROM {table} WHERE {where} ORDER BY {order_col}"
        # REL-EAGER-UNBOUNDED: page through ALL children rather than silently
        # truncating at a fixed cap.
        records = []
        offset = 0
        while True:
            result = db.fetch(sql, [pk_value], limit=_LAZY_PAGE_SIZE, offset=offset)
            batch = result.records
            records.extend(batch)
            if len(batch) < _LAZY_PAGE_SIZE:
                break
            offset += _LAZY_PAGE_SIZE
        return [related_cls(row) for row in records]


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
        sql = f"SELECT * FROM {table} WHERE {fk} = ?"
        # REL-SOFTDELETE-TRAVERSAL: exclude a soft-deleted related row.
        if getattr(related_cls, "soft_delete", False):
            sql += f" AND {related_cls._soft_delete_filter()}"
        sql += " LIMIT 1"
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
        return related_cls.find_by_id(fk_value)


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
