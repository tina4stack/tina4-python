# Tina4 Seeder — Fake data generation and database seeding, zero dependencies.
"""
Generate realistic fake data for testing and development.

    from tina4_python.seeder import FakeData, seed_table

    fake = FakeData()
    fake.name()      # "Alice Johnson"
    fake.email()     # "alice.johnson@example.com"

    seed_table(db, "users", 50, {"name": fake.name, "email": fake.email})
"""
import random
import string
import hashlib
from datetime import datetime as _datetime, timedelta, timezone

# Word banks for generating realistic data
_FIRST_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Henry",
    "Ivy", "Jack", "Kate", "Leo", "Mia", "Noah", "Olivia", "Pete",
    "Quinn", "Rose", "Sam", "Tina", "Uma", "Vince", "Wendy", "Xander",
    "Yara", "Zane", "Anna", "Ben", "Chloe", "Dan", "Emma", "Felix",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Clark", "Lewis", "Young",
]
_DOMAINS = ["example.com", "test.org", "demo.net", "mail.dev", "inbox.io"]
_WORDS = [
    "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore",
    "magna", "aliqua", "enim", "minim", "veniam", "quis", "nostrud",
    "exercitation", "ullamco", "laboris", "nisi", "aliquip", "commodo",
]
_CITIES = [
    "New York", "London", "Tokyo", "Paris", "Sydney", "Berlin", "Toronto",
    "Cape Town", "Mumbai", "Singapore", "Dubai", "Amsterdam", "Seoul",
]
_COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Australia", "Germany",
    "France", "Japan", "Brazil", "India", "South Africa", "Nigeria",
    "Egypt", "Kenya", "Mexico", "Argentina", "Chile", "Colombia", "Spain",
    "Italy", "Netherlands", "Sweden", "Norway", "Denmark", "Finland",
    "Switzerland", "Belgium", "Austria", "New Zealand", "Singapore",
    "South Korea", "Thailand", "Indonesia", "Philippines", "Vietnam",
    "Malaysia", "United Arab Emirates", "Saudi Arabia", "Turkey", "Poland",
]
_COMPANY_WORDS = [
    "Tech", "Global", "Apex", "Nova", "Core", "Prime", "Next", "Blue",
    "Bright", "Smart", "Swift", "Peak", "Fusion", "Pulse", "Vertex",
]
_COMPANY_SUFFIXES = ["Inc", "Corp", "Ltd", "LLC", "Group", "Solutions", "Systems", "Labs"]
_STREETS = [
    "Main St", "Oak Ave", "Park Rd", "Cedar Ln", "Elm St", "Pine Dr",
    "Maple Way", "River Rd", "Lake Blvd", "Hill Ct", "Valley View",
]
_JOB_TITLES = [
    "Software Engineer", "Product Manager", "Designer", "Data Analyst",
    "DevOps Engineer", "CEO", "CTO", "Sales Manager", "Marketing Lead",
    "Accountant", "Operations Manager", "QA Engineer", "UX Researcher",
    "Support Specialist", "HR Manager", "Technical Writer",
]
_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "ZAR", "INR", "CNY"]
_CREDIT_CARD_PREFIXES = ["4111", "4242", "5500", "5105"]


class FakeData:
    """Fake data generator with deterministic seeding."""

    def __init__(self, seed: int = None):
        self._rng = random.Random(seed)

    @classmethod
    def seed(cls, seed: int) -> "FakeData":
        """Static factory — create a seeded FakeData instance.

            fake = FakeData.seed(42)
            fake.name()  # deterministic
        """
        return cls(seed)

    def run(self, fn, count: int = 1) -> list:
        """Run a generator function `count` times and return the results."""
        return [fn() for _ in range(count)]

    def seed_dir(self, seed_folder: str = "seeds") -> list:
        """Run all Python seed files in the given folder (sorted, skipping
        files starting with ``_``). Returns the list of files executed."""
        import os
        import importlib.util

        if not os.path.isdir(seed_folder):
            return []
        files = sorted(
            f for f in os.listdir(seed_folder)
            if f.endswith(".py") and not f.startswith("_")
        )
        executed: list = []
        for name in files:
            path = os.path.join(seed_folder, name)
            try:
                spec = importlib.util.spec_from_file_location(name[:-3], path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                executed.append(path)
            except Exception:
                pass
        return executed

    def name(self) -> str:
        return f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"

    def first_name(self) -> str:
        return self._rng.choice(_FIRST_NAMES)

    def last_name(self) -> str:
        return self._rng.choice(_LAST_NAMES)

    def email(self) -> str:
        first = self._rng.choice(_FIRST_NAMES).lower()
        last = self._rng.choice(_LAST_NAMES).lower()
        domain = self._rng.choice(_DOMAINS)
        return f"{first}.{last}@{domain}"

    def phone(self) -> str:
        area = self._rng.randint(200, 999)
        mid = self._rng.randint(100, 999)
        end = self._rng.randint(1000, 9999)
        return f"+1 ({area}) {mid}-{end}"

    def integer(self, min_val: int = 0, max_val: int = 10000) -> int:
        return self._rng.randint(min_val, max_val)

    def decimal(self, min_val: float = 0.0, max_val: float = 1000.0, decimals: int = 2) -> float:
        return round(self._rng.uniform(min_val, max_val), decimals)

    def boolean(self) -> bool:
        return self._rng.choice([True, False])

    def word(self) -> str:
        return self._rng.choice(_WORDS)

    def sentence(self, words: int = 8) -> str:
        s = " ".join(self._rng.choice(_WORDS) for _ in range(words))
        return s.capitalize() + "."

    def paragraph(self, sentences: int = 4) -> str:
        return " ".join(self.sentence(self._rng.randint(5, 12)) for _ in range(sentences))

    def text(self, paragraphs: int = 3) -> str:
        return "\n\n".join(self.paragraph() for _ in range(paragraphs))

    def date(self, start_year: int = 2020, end_year: int = 2025) -> str:
        start = _datetime(start_year, 1, 1, tzinfo=timezone.utc)
        end = _datetime(end_year, 12, 31, tzinfo=timezone.utc)
        delta = (end - start).days
        d = start + timedelta(days=self._rng.randint(0, delta))
        return d.strftime("%Y-%m-%d")

    def datetime_iso(self) -> str:
        d = self.date()
        h = self._rng.randint(0, 23)
        m = self._rng.randint(0, 59)
        s = self._rng.randint(0, 59)
        return f"{d}T{h:02d}:{m:02d}:{s:02d}Z"

    def uuid(self) -> str:
        hex_str = hashlib.md5(
            str(self._rng.random()).encode()
        ).hexdigest()
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:]}"

    def url(self) -> str:
        domain = self._rng.choice(_DOMAINS)
        path = "/".join(self._rng.choice(_WORDS) for _ in range(2))
        return f"https://{domain}/{path}"

    def address(self) -> str:
        num = self._rng.randint(1, 999)
        street = self._rng.choice(_STREETS)
        city = self._rng.choice(_CITIES)
        return f"{num} {street}, {city}"

    def company(self) -> str:
        w1 = self._rng.choice(_COMPANY_WORDS)
        w2 = self._rng.choice(_COMPANY_WORDS)
        suffix = self._rng.choice(_COMPANY_SUFFIXES)
        return f"{w1}{w2} {suffix}"

    def city(self) -> str:
        return self._rng.choice(_CITIES)

    def country(self) -> str:
        return self._rng.choice(_COUNTRIES)

    def zip_code(self) -> str:
        return str(self._rng.randint(10000, 99999))

    def numeric(self, min_val: float = 0.0, max_val: float = 1000.0, decimals: int = 2) -> float:
        return self.decimal(min_val, max_val, decimals)

    def datetime(self, start_year: int = 2020, end_year: int = 2025) -> str:
        start = _datetime(start_year, 1, 1, tzinfo=timezone.utc)
        end = _datetime(end_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        delta = int((end - start).total_seconds())
        d = start + timedelta(seconds=self._rng.randint(0, delta))
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")

    def for_field(self, field_def: dict, column_name: str = None):
        """Generate a fake value from a field definition dict and optional column name.

        Args:
            field_def: Dict with keys like type, primary_key, auto_increment, max_length, min, max.
            column_name: Optional column name string for heuristic matching.

        Returns:
            A generated value, or None if the field is a primary key with auto_increment.
        """
        if field_def.get("primary_key") and field_def.get("auto_increment"):
            return None
        col = (column_name or "").lower()
        ftype = (field_def.get("type") or "string").lower()

        # Column name heuristics (checked before type fallback)
        if col:
            if "email" in col:
                return self.email()
            if "phone" in col or "tel" in col or "mobile" in col:
                return self.phone()
            if col in ("full_name", "fullname", "name"):
                return self.name()
            if "first_name" in col or ("first" in col and "name" in col):
                return self.first_name()
            if "last_name" in col or ("last" in col and "name" in col):
                return self.last_name()
            if "address" in col or "street" in col:
                return self.address()
            if "city" in col or "town" in col:
                return self.city()
            if "country" in col:
                return self.country()
            if "zip" in col or "postal" in col:
                return self.zip_code()
            if "company" in col or "org" in col:
                return self.company()
            if "url" in col or "website" in col or "link" in col:
                return self.url()
            if "uuid" in col or "guid" in col:
                return self.uuid()

        # Field type fallback
        if ftype in ("string", "text"):
            return self.sentence()
        if ftype == "integer":
            return self.integer(
                field_def.get("min", 0),
                field_def.get("max", 10000),
            )
        if ftype in ("numeric", "float", "decimal"):
            return self.numeric(
                field_def.get("min", 0.0),
                field_def.get("max", 1000.0),
            )
        if ftype == "boolean":
            return self.boolean()
        if ftype == "datetime":
            return self.datetime()
        if ftype == "date":
            return self.date()

        return self.word()

    def color_hex(self) -> str:
        return f"#{self._rng.randint(0, 0xFFFFFF):06x}"

    def job_title(self) -> str:
        return self._rng.choice(_JOB_TITLES)

    def currency(self) -> str:
        return self._rng.choice(_CURRENCIES)

    def ip_address(self) -> str:
        return (
            f"{self._rng.randint(1, 255)}.{self._rng.randint(0, 255)}."
            f"{self._rng.randint(0, 255)}.{self._rng.randint(1, 254)}"
        )

    def credit_card(self) -> str:
        """Generate a fake credit card number (test numbers only, e.g. 4111...)."""
        prefix = self._rng.choice(_CREDIT_CARD_PREFIXES)
        rest = "".join(str(self._rng.randint(0, 9)) for _ in range(12))
        return prefix + rest

    def choice(self, items: list):
        return self._rng.choice(items)

    def sample(self, items: list, k: int) -> list:
        return self._rng.sample(items, min(k, len(items)))

    def alphanumeric(self, length: int = 10) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(self._rng.choice(chars) for _ in range(length))


class SeedSummary(int):
    """Result of a seed run — ``{seeded, failed, errors}``.

    Subclasses ``int`` so its integer value is ``seeded``. This keeps the
    pre-overhaul contract intact: callers doing ``count = seed_table(...)``
    and ``assert count == 10`` still pass, while new callers can inspect
    ``summary.seeded`` / ``summary.failed`` / ``summary.errors`` or treat it
    as a dict (``summary["failed"]``, ``dict(summary)``, ``summary.to_dict()``).

    ``errors`` is a list of ``{"row": <0-based index>, "message": <str>}``
    dicts describing every skipped row.
    """

    def __new__(cls, seeded: int = 0, failed: int = 0, errors: list = None):
        obj = super().__new__(cls, seeded)
        obj.seeded = int(seeded)
        obj.failed = int(failed)
        obj.errors = errors if errors is not None else []
        return obj

    def to_dict(self) -> dict:
        return {"seeded": self.seeded, "failed": self.failed, "errors": self.errors}

    # Dict-style read access so callers can use summary["seeded"] / dict(summary).
    def __getitem__(self, key):
        if isinstance(key, str):
            return {"seeded": self.seeded, "failed": self.failed, "errors": self.errors}[key]
        raise TypeError("SeedSummary keys are 'seeded', 'failed', 'errors'")

    def keys(self):
        return ("seeded", "failed", "errors")

    def __iter__(self):
        return iter(self.keys())

    def __repr__(self):
        return f"SeedSummary(seeded={self.seeded}, failed={self.failed}, errors={self.errors!r})"


def _generator_for_column(fake: "FakeData", name: str, col_type: str):
    """Pick a FakeData generator for one column from its name + type.

    The shared heuristic behind :func:`auto_field_map`, so the dev-admin
    seeding endpoint and the MCP ``seed_table`` dev tool auto-generate
    identical column data. Falls back to a sentence for anything unrecognised.
    """
    name_lower = (name or "").lower()
    col_type = (col_type or "").upper()
    if "email" in name_lower:
        return fake.email
    if "name" in name_lower and "user" in name_lower:
        return fake.name
    if "first" in name_lower and "name" in name_lower:
        return fake.first_name
    if "last" in name_lower and "name" in name_lower:
        return fake.last_name
    if "name" in name_lower:
        return fake.name
    if "phone" in name_lower or "tel" in name_lower:
        return fake.phone
    if "url" in name_lower or "link" in name_lower:
        return fake.url
    if "address" in name_lower:
        return fake.address
    if "date" in name_lower or "time" in name_lower or "created" in name_lower:
        return fake.datetime_iso
    if "desc" in name_lower or "body" in name_lower or "content" in name_lower:
        return fake.paragraph
    if "title" in name_lower or "subject" in name_lower:
        return fake.sentence
    if "active" in name_lower or "enabled" in name_lower or "done" in name_lower:
        return fake.boolean
    if "INT" in col_type or "SERIAL" in col_type:
        return lambda: fake.integer(1, 10000)
    if any(t in col_type for t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")):
        return lambda: fake.decimal(0, 1000)
    if "BOOL" in col_type:
        return fake.boolean
    return fake.sentence


def auto_field_map(db, table: str, fake: "FakeData" = None) -> dict:
    """Introspect ``table``'s columns and build a column->generator field_map
    for :func:`seed_table`, skipping auto-increment / ``id`` primary keys.

    This is the "seed a table I did not hand-write generators for" convenience
    that both the dev-admin seeding endpoint and the MCP ``seed_table`` dev tool
    need. ``seed_table`` itself stays explicit (no field_map = no rows); this
    helper is how a caller opts into automatic generation. Returns an empty dict
    when the table has no columns, so ``seed_table`` then seeds nothing rather
    than crashing.
    """
    fake = fake or FakeData()
    columns = db.get_columns(table) or []
    field_map: dict[str, callable] = {}
    for col in columns:
        name = col.get("name", col.get("column_name", ""))
        col_type = str(col.get("type", col.get("data_type", "")) or "").upper()
        is_pk = col.get("primary_key", col.get("pk", False))
        if is_pk and ("AUTO" in col_type or "SERIAL" in col_type or name.lower() == "id"):
            continue
        field_map[name] = _generator_for_column(fake, name, col_type)
    return field_map


def seed_table(db, table: str, count: int = 10,
               field_map: dict[str, callable] = None,
               overrides: dict = None, clear: bool = False,
               seed: int = None, strict: bool = False) -> SeedSummary:
    """Seed a database table with fake data.

    Visible-but-resilient: each row is wrapped. On a row failure the cause is
    logged (with the row index) and the row is skipped — unless ``strict=True``,
    in which case the first failure RE-RAISES. At the end a one-line summary is
    logged ("seeded N, M failed").

    Args:
        db: Database instance.
        table: Table name.
        count: Number of rows to insert.
        field_map: Dict of column_name → callable that generates a value
            (or a static value).
        overrides: Static values to set on every row.
        clear: If True, delete every existing row in ``table`` before seeding
            so re-runs don't duplicate rows or trip unique-PK violations (P2).
        seed: Optional PRNG seed — seeds the FakeData RNG used for any
            ``FakeData`` instance the caller passes through ``field_map``. Has
            no effect unless the caller's generators read from a shared
            ``FakeData(seed=...)``; provided for signature parity with
            ``seed_orm`` and so the dev-admin endpoint can pass it through.
        strict: If True, re-raise on the first failed row instead of skipping.

    Returns:
        A :class:`SeedSummary` (``{seeded, failed, errors}``) — also usable as
        the int row-count for backward compatibility.
    """
    from tina4_python.debug import Log  # lazy import to avoid circular deps

    if not field_map:
        return SeedSummary(0, 0, [])

    if clear:
        _clear_table(db, table)

    seeded = 0
    failed = 0
    errors: list = []

    for i in range(count):
        try:
            row = {}
            for col, generator in field_map.items():
                row[col] = generator() if callable(generator) else generator
            if overrides:
                row.update(overrides)
            db.insert(table, row)
            seeded += 1
        except Exception as exc:
            if strict:
                # Surface the failure with row context, but still raise.
                Log.error(f"Seeder: row {i} failed seeding '{table}' (strict): {exc}")
                raise
            failed += 1
            errors.append({"row": i, "message": str(exc)})
            Log.warning(f"Seeder: row {i} failed seeding '{table}', skipped: {exc}")

    try:
        db.commit()
    except Exception:
        # Autocommit-on engines / pooled standalone writes may not need an
        # explicit commit; never let the summary itself crash.
        pass

    Log.info(f"Seeder: '{table}' — seeded {seeded}, {failed} failed")
    return SeedSummary(seeded, failed, errors)


def seed_orm(orm_class, count: int = 10,
             overrides: dict = None, clear: bool = False,
             seed: int = None, strict: bool = False) -> SeedSummary:
    """Seed an ORM model class with auto-generated fake data.

    Visible-but-resilient: each row is wrapped. On a row failure the cause is
    logged (with the row index) and the row is skipped — unless ``strict=True``,
    in which case the first failure RE-RAISES. A one-line summary is logged at
    the end.

    Args:
        orm_class: ORM subclass with ``_fields`` and a ``save()`` method.
        count: Number of records to insert.
        overrides: Dict of field overrides — static values or callables
            receiving a FakeData instance.
        clear: If True, delete all existing records before seeding (P2).
        seed: Optional PRNG seed for reproducible output (P3).
        strict: If True, re-raise on the first failed row instead of skipping.

    Returns:
        A :class:`SeedSummary` (``{seeded, failed, errors}``) — also usable as
        the int row-count for backward compatibility.
    """
    from tina4_python.debug import Log  # lazy import to avoid circular deps

    fake = FakeData(seed=seed)

    fields = getattr(orm_class, "_fields", None) or {}
    if not fields:
        Log.error(f"Seeder: No fields found on {orm_class.__name__}")
        return SeedSummary(0, 0, [])

    if clear:
        _clear_orm(orm_class)

    pk_fields = {
        name for name, field in fields.items()
        if getattr(field, "primary_key", False) and getattr(field, "auto_increment", False)
    }

    # P4a — resolve FK columns to REAL parent PKs so a child row references an
    # existing parent. Snapshotted once (parents are seeded first by
    # seed_models's topo-sort, so the table is populated by now).
    fk_pools = _foreign_key_pools(orm_class, fields)

    seeded = 0
    failed = 0
    errors: list = []
    for i in range(count):
        try:
            attrs = {}
            for name, field in fields.items():
                if name in pk_fields:
                    continue
                if overrides and name in overrides:
                    val = overrides[name]
                    attrs[name] = val(fake) if callable(val) else val
                elif name in fk_pools and fk_pools[name]:
                    attrs[name] = fake.choice(fk_pools[name])
                else:
                    attrs[name] = _generate_for_field(fake, _field_meta(field), name)
            _validate_types(fields, attrs, orm_class.__name__, Log)
            obj = orm_class(attrs)
            if obj.save():
                seeded += 1
            else:
                raise RuntimeError(f"save() returned falsy for {orm_class.__name__}")
        except Exception as exc:
            if strict:
                Log.error(
                    f"Seeder: row {i} failed seeding {orm_class.__name__} "
                    f"(strict): {exc}"
                )
                raise
            failed += 1
            errors.append({"row": i, "message": str(exc)})
            Log.warning(
                f"Seeder: row {i} failed seeding {orm_class.__name__}, skipped: {exc}"
            )

    Log.info(f"Seeder: {orm_class.__name__} — seeded {seeded}, {failed} failed")
    return SeedSummary(seeded, failed, errors)


def seed_models(orm_classes: list, count: int = 10,
                overrides: dict = None, clear: bool = False,
                seed: int = None, strict: bool = False) -> dict:
    """Batch-seed several ORM models, ordering by their ForeignKeyField
    dependency graph (P4a).

    Parent tables seed before children (topological sort over
    ``ForeignKeyField.references``); when ``clear=True`` the clear runs in the
    REVERSE order so children are removed before parents — no FK violations
    regardless of the order the caller lists the models in.

    Args:
        orm_classes: List of ORM subclasses to seed.
        count: Rows per model.
        overrides: Per-model overrides as ``{ModelClass: {field: value}}`` or a
            single flat dict applied to every model.
        clear: Clear each table first (reverse-topo order).
        seed: PRNG seed (P3) — applied per model.
        strict: Re-raise on the first failed row.

    Returns:
        ``{ModelClass.__name__: SeedSummary}`` for each model seeded.
    """
    ordered = _topo_sort_models(orm_classes)

    if clear:
        for model in reversed(ordered):
            _clear_orm(model)

    results: dict = {}
    for model in ordered:
        model_overrides = overrides
        if isinstance(overrides, dict) and model in overrides:
            model_overrides = overrides[model]
        results[model.__name__] = seed_orm(
            model, count=count, overrides=model_overrides,
            clear=False, seed=seed, strict=strict,
        )
    return results


def _field_meta(field) -> dict:
    """Normalise an ORM Field object into the small dict shape
    ``_generate_for_field`` expects (``{type, scale}``)."""
    kind = getattr(field, "kind", "") or ""
    type_map = {
        "IntegerField": "integer",
        "ForeignKeyField": "integer",
        "FloatField": "float",
        "NumericField": "numeric",
        "BooleanField": "boolean",
        "DateTimeField": "datetime",
        "StringField": "string",
        "TextField": "text",
        "BlobField": "blob",
    }
    ftype = type_map.get(kind, "string")
    meta = {"type": ftype}
    scale = getattr(field, "scale", None)
    if scale is not None:
        meta["scale"] = scale
    return meta


def _validate_types(fields: dict, attrs: dict, model_name: str, Log) -> None:
    """P4c — when a generated value's Python type clearly mismatches the
    target column's field type, LOG a warning (never hard-fail)."""
    py_type = {
        "IntegerField": int, "ForeignKeyField": int,
        "FloatField": float, "NumericField": float,
        "BooleanField": bool,
    }
    for name, value in attrs.items():
        if value is None:
            continue
        field = fields.get(name)
        if field is None:
            continue
        expected = py_type.get(getattr(field, "kind", "") or "")
        if expected is None:
            continue
        # bool is an int subclass — an int landing in a bool column is fine,
        # but a non-numeric in an int column (or vice-versa) is suspicious.
        if expected in (int, float) and isinstance(value, bool):
            continue
        if not isinstance(value, expected):
            Log.warning(
                f"Seeder: {model_name}.{name} expected {expected.__name__} "
                f"but generated {type(value).__name__} ({value!r}) — inserting anyway"
            )


def _clear_table(db, table: str) -> None:
    """Delete every row in ``table``. Tolerant — logs and continues on error."""
    from tina4_python.debug import Log
    try:
        db.delete(table, "1=1")
    except Exception as exc:
        Log.warning(f"Seeder: could not clear '{table}': {exc}")


def _clear_orm(orm_class) -> None:
    """Delete every row backing an ORM model. Tolerant — logs and continues."""
    from tina4_python.debug import Log
    try:
        db = orm_class._get_db()
        db.delete(orm_class._get_table(), "1=1")
    except Exception as exc:
        Log.warning(f"Seeder: could not clear {orm_class.__name__}: {exc}")


def _foreign_key_pools(orm_class, fields: dict) -> dict:
    """For each ForeignKeyField on the model, fetch the existing primary-key
    values of the referenced table so seeded child rows reference a real
    parent (P4a). Returns ``{fk_field_name: [pk_value, ...]}``; columns with
    no resolvable / empty parent table are omitted (the generic generator
    then fills them, and the row may fail loudly — never silently).
    """
    from tina4_python.orm.fields import ForeignKeyField
    from tina4_python.debug import Log

    pools: dict = {}
    for name, field in fields.items():
        if not isinstance(field, ForeignKeyField) or field.references is None:
            continue
        ref = field.references
        try:
            if hasattr(ref, "_get_table"):          # ORM class reference
                target = ref
            else:
                # String reference — resolve against ORM subclasses.
                from tina4_python.orm.model import ORM as _ORM
                target = next(
                    (s for s in _all_subclasses(_ORM)
                     if s.__name__ == str(ref)), None
                )
            if target is None:
                continue
            db = target._get_db()
            pk = target._get_pk()
            rows = db.fetch(f"SELECT {pk} FROM {target._get_table()}", limit=100000)
            values = [r[pk] for r in rows.records if r.get(pk) is not None]
            if values:
                pools[name] = values
        except Exception as exc:
            Log.warning(f"Seeder: could not resolve FK pool for {name}: {exc}")
    return pools


def _all_subclasses(cls) -> list:
    """Recursively collect all subclasses of cls."""
    out = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(_all_subclasses(sub))
    return out


def _topo_sort_models(orm_classes: list) -> list:
    """Topologically sort ORM models so parents (referenced tables) come
    before children (tables with a ForeignKeyField pointing at them).

    Uses the ORM's existing ``ForeignKeyField.references`` metadata. Models
    not in the input list are ignored as dependencies (you only seed what you
    pass). Cycles fall back to the caller's declared order for the remainder.
    """
    from tina4_python.orm.fields import ForeignKeyField

    in_set = list(dict.fromkeys(orm_classes))  # dedupe, preserve order
    name_to_model = {m.__name__: m for m in in_set}

    def _deps(model) -> set:
        deps = set()
        for field in getattr(model, "_fields", {}).values():
            if isinstance(field, ForeignKeyField) and field.references is not None:
                ref = field.references
                ref_name = ref.__name__ if hasattr(ref, "__name__") else str(ref)
                target = name_to_model.get(ref_name)
                if target is not None and target is not model:
                    deps.add(target)
        return deps

    deps_map = {m: _deps(m) for m in in_set}

    ordered: list = []
    placed: set = set()
    # Stable topo: repeatedly emit models whose deps are all placed.
    remaining = list(in_set)
    progressed = True
    while remaining and progressed:
        progressed = False
        still: list = []
        for model in remaining:
            if deps_map[model] <= placed:
                ordered.append(model)
                placed.add(model)
                progressed = True
            else:
                still.append(model)
        remaining = still
    # Cycle / unresolved deps — append in declared order so we never drop a model.
    ordered.extend(remaining)
    return ordered


def _generate_for_field(fake: FakeData, field_def: dict, col: str):
    """Generate a fake value for an ORM field definition + column name."""
    col = col.lower()
    ftype = field_def.get("type", "string")

    if ftype == "integer":
        if "age" in col:
            return fake.integer(18, 85)
        if "year" in col:
            return fake.integer(1950, 2025)
        return fake.integer(1, 10000)

    if ftype in ("float", "decimal", "numeric"):
        decimals = field_def.get("scale", 2)
        return fake.decimal(0.01, 9999.99, decimals)

    if ftype == "date":
        return fake.date()

    if ftype in ("datetime", "timestamp"):
        return fake.datetime()

    if ftype == "boolean":
        return fake.boolean()

    if ftype in ("string", "text"):
        if "email" in col:
            return fake.email()
        if col in ("name", "full_name", "fullname"):
            return fake.name()
        if "first" in col and "name" in col:
            return fake.first_name()
        if "last" in col and "name" in col:
            return fake.last_name()
        if any(x in col for x in ("phone", "tel", "mobile")):
            return fake.phone()
        if any(x in col for x in ("url", "website", "link")):
            return fake.url()
        if any(x in col for x in ("address", "street")):
            return fake.address()
        if any(x in col for x in ("city", "town")):
            return fake.city()
        if "country" in col:
            return fake.country()
        if any(x in col for x in ("zip", "postal")):
            return fake.zip_code()
        if any(x in col for x in ("company", "org")):
            return fake.company()
        if any(x in col for x in ("color", "colour")):
            return fake.color_hex()
        if any(x in col for x in ("uuid", "guid")):
            return fake.uuid()
        if any(x in col for x in ("description", "summary", "bio", "about", "content", "body")):
            return fake.paragraph()
        return fake.sentence()

    return fake.word()


__all__ = ["FakeData", "SeedSummary", "seed_table", "seed_orm", "seed_models",
           "auto_field_map"]
