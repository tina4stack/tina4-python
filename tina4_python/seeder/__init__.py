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


def seed_table(db, table: str, count: int = 10,
               field_map: dict[str, callable] = None,
               overrides: dict = None) -> int:
    """Seed a database table with fake data.

    Args:
        db: Database instance
        table: Table name
        count: Number of rows to insert
        field_map: Dict of column_name → callable that generates a value
        overrides: Static values to set on every row

    Returns:
        Number of rows inserted
    """
    if not field_map:
        return 0

    for i in range(count):
        row = {}
        for col, generator in field_map.items():
            row[col] = generator() if callable(generator) else generator
        if overrides:
            row.update(overrides)
        db.insert(table, row)

    db.commit()
    return count


def seed_orm(orm_class, count: int = 10,
             overrides: dict = None, clear: bool = False,
             seed: int = None) -> int:
    """Seed an ORM model class with auto-generated fake data.

    Args:
        orm_class: ORM subclass with a ``fields`` dict and ``save()`` method.
        count: Number of records to insert.
        overrides: Dict of field overrides — static values or callables
            receiving a FakeData instance.
        clear: If True, delete all existing records before seeding.
        seed: Optional PRNG seed for reproducible output.

    Returns:
        Number of records inserted.
    """
    from tina4_python.debug import Log  # lazy import to avoid circular deps

    fake = FakeData(seed=seed)

    fields = getattr(orm_class, "field_definitions", None) or {}
    if not fields:
        Log.error(f"Seeder: No fields found on {orm_class.__name__}")
        return 0

    if clear:
        try:
            orm_class.delete_all()
        except Exception as exc:
            Log.warning(f"Seeder: Could not clear {orm_class.__name__}: {exc}")

    pk_fields = {
        name for name, opts in fields.items()
        if opts.get("primary_key") and opts.get("auto_increment")
    }

    inserted = 0
    for i in range(count):
        attrs = {}
        for name, field_def in fields.items():
            if name in pk_fields:
                continue
            if overrides and name in overrides:
                val = overrides[name]
                attrs[name] = val(fake) if callable(val) else val
            else:
                attrs[name] = fake.choice([None]) if False else _generate_for_field(fake, field_def, name)
        try:
            obj = orm_class(attrs)
            if obj.save():
                inserted += 1
            else:
                Log.warning(f"Seeder: Insert failed for {orm_class.__name__} row {i + 1}")
        except Exception as exc:
            Log.warning(f"Seeder: Insert failed for {orm_class.__name__} row {i + 1}: {exc}")

    Log.info(f"Seeder: Inserted {inserted}/{count} records into {orm_class.__name__}")
    return inserted


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


__all__ = ["FakeData", "seed_table", "seed_orm"]
