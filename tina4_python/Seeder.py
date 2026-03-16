#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Data seeder for Tina4 Python.

Generates realistic fake data and seeds database tables via ORM introspection
or raw table definitions. Zero external dependencies — uses Python's built-in
``random`` module with embedded word/name lists.

Typical usage::

    from tina4_python.Seeder import seed_orm, FakeData

    # Seed 50 users with auto-generated data
    seed_orm(User, count=50)

    # Seed with overrides
    seed_orm(Order, count=200, overrides={
        "status": lambda fake: fake.choice(["pending", "shipped", "delivered"]),
    })

    # Use FakeData standalone
    fake = FakeData(seed=42)
    print(fake.name())       # "Sarah Johnson"
    print(fake.email())      # "sarah.johnson@example.com"
"""

__all__ = ["FakeData", "Seeder", "seed_orm", "seed_table"]

import os
import random
import string
from datetime import datetime, timedelta
from tina4_python import Debug
from tina4_python.FieldTypes import (
    BaseField, IntegerField, NumericField, StringField, TextField,
    DateTimeField, BlobField, JSONBField, ForeignKeyField,
)

# ---------------------------------------------------------------------------
# Embedded data pools (zero external dependencies)
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Dorothy", "Paul", "Kimberly", "Andrew", "Emily", "Joshua", "Donna",
    "Kenneth", "Michelle", "Kevin", "Carol", "Brian", "Amanda", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Andre", "Aisha", "Wei", "Yuki", "Carlos", "Fatima", "Raj", "Priya",
    "Mohammed", "Sophia", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Mia",
    "Lucas", "Isabella", "Mason", "Charlotte", "Logan", "Amelia", "Aiden", "Harper",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward",
    "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel",
    "Van Zuydam", "Müller", "Nakamura", "Singh", "Chen", "Silva", "Ali", "Okafor",
]

_WORDS = [
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "I",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see", "other",
    "than", "then", "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first", "well", "way",
    "even", "new", "want", "because", "any", "these", "give", "day", "most", "us",
    "great", "small", "large", "every", "found", "still", "between", "name", "should", "home",
    "big", "end", "along", "each", "much", "both", "help", "line", "turn", "move",
    "thing", "right", "same", "old", "better", "point", "long", "real", "system", "data",
    "report", "order", "product", "service", "customer", "account", "payment", "record", "total", "status",
    "market", "world", "company", "project", "team", "value", "process", "business", "group", "result",
    "information", "development", "management", "quality", "performance", "technology", "support", "research",
    "design", "program", "network", "building", "community", "education", "experience", "environment",
    "government", "industry", "health", "security", "position", "standard", "material", "investment",
    "production", "structure", "activity", "analysis", "practice", "resource", "strategy", "training",
    "international", "national", "political", "economic", "social", "important", "different", "available",
]

_CITIES = [
    "New York", "London", "Tokyo", "Paris", "Berlin", "Sydney", "Toronto", "Mumbai",
    "São Paulo", "Cairo", "Lagos", "Dubai", "Singapore", "Hong Kong", "Seoul",
    "Mexico City", "Bangkok", "Istanbul", "Moscow", "Rome", "Barcelona", "Amsterdam",
    "Nairobi", "Cape Town", "Johannesburg", "Buenos Aires", "Lima", "Santiago",
    "Jakarta", "Manila", "Kuala Lumpur", "Auckland", "Vancouver", "Chicago",
    "San Francisco", "Los Angeles", "Miami", "Boston", "Seattle", "Denver",
]

_COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Australia", "Germany", "France",
    "Japan", "Brazil", "India", "South Africa", "Nigeria", "Egypt", "Kenya",
    "Mexico", "Argentina", "Chile", "Colombia", "Spain", "Italy", "Netherlands",
    "Sweden", "Norway", "Denmark", "Finland", "Switzerland", "Belgium", "Austria",
    "New Zealand", "Singapore", "South Korea", "Thailand", "Indonesia", "Philippines",
    "Vietnam", "Malaysia", "United Arab Emirates", "Saudi Arabia", "Turkey", "Poland",
    "Portugal", "Ireland", "Czech Republic", "Romania", "Greece", "Israel",
]

_DOMAINS = [
    "example.com", "test.org", "sample.net", "demo.io", "mail.com",
    "inbox.org", "webmail.net", "company.com", "corp.io", "biz.net",
]

_STREETS = [
    "Main", "Oak", "Pine", "Maple", "Cedar", "Elm", "Park", "Lake",
    "Hill", "River", "Church", "Market", "King", "Queen", "High",
    "Bridge", "Station", "Garden", "Mill", "Spring", "Valley", "Forest",
]

_STREET_TYPES = ["Street", "Avenue", "Road", "Drive", "Lane", "Boulevard", "Way", "Place"]

_COMPANY_WORDS = [
    "Tech", "Global", "Apex", "Nova", "Core", "Prime", "Next", "Blue",
    "Bright", "Smart", "Swift", "Peak", "Fusion", "Pulse", "Vertex",
    "Alpha", "Sigma", "Delta", "Omega", "Quantum", "Solar", "Cyber",
    "Cloud", "Data", "Logic", "Wave", "Link", "Flow", "Net", "Hub",
]

_COMPANY_SUFFIXES = ["Inc", "Corp", "Ltd", "LLC", "Group", "Solutions", "Systems", "Labs"]


# ---------------------------------------------------------------------------
# FakeData generator
# ---------------------------------------------------------------------------

class FakeData:
    """Deterministic fake data generator with zero external dependencies.

    Uses Python's built-in ``random`` module with embedded word/name lists.
    Each instance uses its own ``random.Random`` to avoid polluting global state.

    Args:
        seed: Optional seed for reproducible data generation.

    Example::

        fake = FakeData(seed=42)
        fake.name()       # "Sarah Johnson"
        fake.email()      # "sarah.johnson@example.com"
        fake.integer(1, 100)
        fake.sentence()
    """

    def __init__(self, seed=None):
        self._rng = random.Random(seed)

    def first_name(self):
        """Random first name."""
        return self._rng.choice(_FIRST_NAMES)

    def last_name(self):
        """Random last name."""
        return self._rng.choice(_LAST_NAMES)

    def name(self):
        """Random full name (first + last)."""
        return f"{self.first_name()} {self.last_name()}"

    def email(self, name=None):
        """Random email address, optionally based on a name."""
        if name:
            parts = name.lower().split()
            local = ".".join(parts)
        else:
            local = f"{self.first_name().lower()}.{self.last_name().lower()}"
        # Add a random number to reduce collisions
        local += str(self._rng.randint(1, 999))
        return f"{local}@{self._rng.choice(_DOMAINS)}"

    def phone(self):
        """Random phone number."""
        area = self._rng.randint(200, 999)
        mid = self._rng.randint(100, 999)
        end = self._rng.randint(1000, 9999)
        return f"+1 ({area}) {mid}-{end}"

    def sentence(self, words=6):
        """Random sentence with the given number of words."""
        w = [self._rng.choice(_WORDS) for _ in range(words)]
        w[0] = w[0].capitalize()
        return " ".join(w) + "."

    def paragraph(self, sentences=3):
        """Random paragraph with the given number of sentences."""
        return " ".join(self.sentence(self._rng.randint(5, 12)) for _ in range(sentences))

    def text(self, max_length=200):
        """Random text, truncated to max_length."""
        t = self.paragraph(2)
        return t[:max_length] if len(t) > max_length else t

    def word(self):
        """Single random word."""
        return self._rng.choice(_WORDS)

    def slug(self, words=3):
        """URL-friendly slug."""
        return "-".join(self._rng.choice(_WORDS) for _ in range(words))

    def url(self):
        """Random URL."""
        return f"https://{self._rng.choice(_DOMAINS)}/{self.slug()}"

    def integer(self, min_val=0, max_val=10000):
        """Random integer in range."""
        return self._rng.randint(min_val, max_val)

    def numeric(self, min_val=0.0, max_val=1000.0, decimals=2):
        """Random float in range, rounded to decimal places."""
        return round(self._rng.uniform(min_val, max_val), decimals)

    def boolean(self):
        """Random boolean (as 0 or 1 for SQL compatibility)."""
        return self._rng.choice([0, 1])

    def datetime(self, start_year=2020, end_year=2026):
        """Random datetime between start_year and end_year."""
        start = datetime(start_year, 1, 1)
        end = datetime(end_year, 12, 31)
        delta = (end - start).days
        random_days = self._rng.randint(0, max(1, delta))
        random_seconds = self._rng.randint(0, 86399)
        return start + timedelta(days=random_days, seconds=random_seconds)

    def date(self, start_year=2020, end_year=2026):
        """Random date string (YYYY-MM-DD)."""
        return self.datetime(start_year, end_year).strftime("%Y-%m-%d")

    def timestamp(self, start_year=2020, end_year=2026):
        """Random timestamp string (YYYY-MM-DD HH:MM:SS)."""
        return self.datetime(start_year, end_year).strftime("%Y-%m-%d %H:%M:%S")

    def blob(self, size=64):
        """Random bytes."""
        return os.urandom(size)

    def json_data(self, keys=None):
        """Random dict suitable for JSONB fields."""
        if keys:
            return {k: self.word() for k in keys}
        n = self._rng.randint(2, 5)
        return {self.word(): self.word() for _ in range(n)}

    def choice(self, items):
        """Random choice from a list."""
        return self._rng.choice(items)

    def city(self):
        """Random city name."""
        return self._rng.choice(_CITIES)

    def country(self):
        """Random country name."""
        return self._rng.choice(_COUNTRIES)

    def address(self):
        """Random street address."""
        num = self._rng.randint(1, 9999)
        street = self._rng.choice(_STREETS)
        st_type = self._rng.choice(_STREET_TYPES)
        return f"{num} {street} {st_type}"

    def zip_code(self):
        """Random ZIP/postal code."""
        return str(self._rng.randint(10000, 99999))

    def company(self):
        """Random company name."""
        w1 = self._rng.choice(_COMPANY_WORDS)
        w2 = self._rng.choice(_COMPANY_WORDS)
        suffix = self._rng.choice(_COMPANY_SUFFIXES)
        return f"{w1}{w2} {suffix}"

    def color_hex(self):
        """Random hex color code."""
        return "#{:06x}".format(self._rng.randint(0, 0xFFFFFF))

    def uuid(self):
        """Random UUID-like string (not RFC 4122 compliant but unique enough for seeding)."""
        h = "".join(self._rng.choices("0123456789abcdef", k=32))
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    def for_field(self, field, column_name=None):
        """Generate appropriate fake data based on a field definition and column name.

        This is the key method that ties FakeData to ORM introspection.
        It uses the field type for the base data type, then refines based
        on the column name for contextually appropriate values.

        Args:
            field: A BaseField or ForeignKeyField instance.
            column_name: The column name (used for smart heuristics).

        Returns:
            An appropriate fake value for the field.
        """
        col = (column_name or "").lower()

        # Skip auto-increment primary keys — let the DB handle them
        if isinstance(field, BaseField) and field.primary_key and field.auto_increment:
            return None

        # ForeignKeyField — handled separately by the seeder (needs DB query)
        if isinstance(field, ForeignKeyField):
            return None  # sentinel: caller resolves FK

        # IntegerField
        if isinstance(field, IntegerField):
            if "age" in col:
                return self.integer(18, 85)
            if "year" in col:
                return self.integer(1950, 2026)
            if "quantity" in col or "qty" in col or "count" in col:
                return self.integer(1, 100)
            if "active" in col or "enabled" in col or "visible" in col or "is_" in col:
                return self.boolean()
            if "sort" in col or "order" in col or "position" in col or "rank" in col:
                return self.integer(1, 1000)
            if "rating" in col or "score" in col:
                return self.integer(1, 10)
            return self.integer(1, 10000)

        # NumericField
        if isinstance(field, NumericField):
            decimals = field.decimal_places or 2
            if "price" in col or "cost" in col or "amount" in col or "total" in col or "fee" in col:
                return self.numeric(0.01, 9999.99, decimals)
            if "rate" in col or "percent" in col or "ratio" in col:
                return self.numeric(0.0, 100.0, decimals)
            if "lat" in col:
                return self.numeric(-90.0, 90.0, 6)
            if "lon" in col or "lng" in col:
                return self.numeric(-180.0, 180.0, 6)
            if "weight" in col or "height" in col:
                return self.numeric(0.1, 500.0, decimals)
            return self.numeric(0.0, 10000.0, decimals)

        # DateTimeField
        if isinstance(field, DateTimeField):
            return self.timestamp()

        # BlobField
        if isinstance(field, BlobField):
            return self.blob(64)

        # JSONBField
        if isinstance(field, JSONBField):
            return self.json_data()

        # StringField / TextField — column name heuristics
        if isinstance(field, (StringField, TextField)):
            max_len = field.field_size or 255

            if "email" in col:
                return self.email()[:max_len]
            if col in ("name", "full_name", "fullname", "display_name"):
                return self.name()[:max_len]
            if "first" in col and "name" in col:
                return self.first_name()[:max_len]
            if "last" in col and "name" in col:
                return self.last_name()[:max_len]
            if "surname" in col or "family_name" in col:
                return self.last_name()[:max_len]
            if "phone" in col or "tel" in col or "mobile" in col or "cell" in col:
                return self.phone()[:max_len]
            if "url" in col or "website" in col or "link" in col or "href" in col:
                return self.url()[:max_len]
            if "address" in col or "street" in col:
                return self.address()[:max_len]
            if "city" in col or "town" in col:
                return self.city()[:max_len]
            if "country" in col:
                return self.country()[:max_len]
            if "zip" in col or "postal" in col:
                return self.zip_code()[:max_len]
            if "company" in col or "organization" in col or "org" in col:
                return self.company()[:max_len]
            if "color" in col or "colour" in col:
                return self.color_hex()[:max_len]
            if "uuid" in col or "guid" in col:
                return self.uuid()[:max_len]
            if "slug" in col:
                return self.slug()[:max_len]
            if "title" in col or "subject" in col or "heading" in col:
                return self.sentence(self._rng.randint(3, 6)).rstrip(".")[:max_len]
            if "description" in col or "summary" in col or "bio" in col or "about" in col:
                return self.text(max_len)
            if "content" in col or "body" in col or "text" in col or "note" in col or "comment" in col:
                return self.paragraph(2)[:max_len]
            if "status" in col:
                return self.choice(["active", "inactive", "pending", "archived"])[:max_len]
            if "type" in col or "category" in col or "kind" in col:
                return self.choice(["standard", "premium", "basic", "enterprise", "custom"])[:max_len]
            if "tag" in col or "label" in col:
                return self.word()[:max_len]
            if "password" in col or "pass" in col or "secret" in col:
                return "".join(self._rng.choices(string.ascii_letters + string.digits, k=min(16, max_len)))
            if "token" in col or "key" in col or "hash" in col:
                return "".join(self._rng.choices(string.ascii_letters + string.digits, k=min(32, max_len)))
            if "username" in col or "user_name" in col or "login" in col:
                return (self.first_name().lower() + str(self._rng.randint(1, 99)))[:max_len]
            # Generic string fallback
            return self.sentence(self._rng.randint(2, 5)).rstrip(".")[:max_len]

        # Unknown field type — generic string
        return self.word()


# ---------------------------------------------------------------------------
# ORM introspection helpers
# ---------------------------------------------------------------------------

def _get_fields(orm_class):
    """Extract field definitions from an ORM class.

    Creates a temporary instance and reads its ``__field_definitions__`` dict.
    Returns ``{field_name: field_instance}`` excluding methods and builtins.
    """
    try:
        instance = orm_class.__new__(orm_class)
        # Manually trigger __init__ without DB check issues
        instance.__field_definitions__ = {}
        instance.__table_name__ = None
        instance.__dba__ = None

        for key in dir(orm_class):
            if (not key.startswith('__') and not key.startswith('_')
                    and key not in ['save', 'load', 'delete', 'to_json',
                                    'to_dict', 'create_table', 'select',
                                    'fetch', 'fetch_one']):
                attr = getattr(orm_class, key)
                if isinstance(attr, (BaseField, ForeignKeyField)):
                    instance.__field_definitions__[key] = attr

        return instance.__field_definitions__
    except Exception as e:
        Debug.error(f"Seeder: Failed to introspect {orm_class.__name__}: {e}")
        return {}


def _get_table_name(orm_class):
    """Get the table name for an ORM class."""
    if hasattr(orm_class, '__table_name__') and orm_class.__table_name__:
        return orm_class.__table_name__
    # Snake case conversion (same logic as ORM.__get_snake_case_name__)
    name = orm_class.__name__
    result = [name[0].lower()]
    for char in name[1:]:
        if char.isupper():
            result.append('_')
        result.append(char.lower())
    return "".join(result)


def _resolve_fk(dba, field, fake):
    """Resolve a ForeignKeyField by querying existing IDs from the referenced table."""
    try:
        ref_table = _get_table_name(field.references_table)
        ref_col = field.references_column
        result = dba.fetch(f"SELECT {ref_col} FROM {ref_table}")
        if result and result.records:
            ids = [row[ref_col] for row in result.records]
            return fake.choice(ids)
    except Exception as e:
        Debug.warning(f"Seeder: Could not resolve FK to {field.references_table}: {e}")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_orm(orm_class, count=10, overrides=None, clear=False, seed=None):
    """Seed a single ORM class with auto-generated fake data.

    Introspects the ORM class fields, generates appropriate data for each
    column based on its type and name, and inserts ``count`` records.

    Args:
        orm_class: An ORM subclass (e.g. ``User``, ``Product``).
        count: Number of records to insert (default 10).
        overrides: Dict of ``{field_name: value_or_callable}``.
            Static values are used directly. Callables receive a
            ``FakeData`` instance and should return a value.
        clear: If True, deletes all existing records before seeding.
        seed: Optional random seed for reproducible data.

    Returns:
        int: Number of records inserted.

    Example::

        seed_orm(User, count=50)
        seed_orm(Order, count=200, overrides={
            "status": lambda fake: fake.choice(["pending", "shipped"]),
            "country": "ZA",
        })
    """
    if overrides is None:
        overrides = {}

    fake = FakeData(seed=seed)
    fields = _get_fields(orm_class)
    table_name = _get_table_name(orm_class)

    if not fields:
        Debug.error(f"Seeder: No fields found on {orm_class.__name__}")
        return 0

    dba = orm_class.__dba__
    if dba is None:
        Debug.error(f"Seeder: No database connection on {orm_class.__name__}. Call orm(db) first.")
        return 0

    # Check idempotency
    if not clear:
        try:
            result = dba.fetch_one(f"SELECT count(*) as count_records FROM {table_name}")
            if result and result.get("count_records", 0) >= count:
                Debug.info(f"Seeder: {table_name} already has {result['count_records']} records, skipping (use clear=True to reseed)")
                return 0
        except Exception:
            pass  # Table might not exist yet

    # Clear if requested
    if clear:
        try:
            dba.execute(f"DELETE FROM {table_name}")
            Debug.info(f"Seeder: Cleared {table_name}")
        except Exception as e:
            Debug.warning(f"Seeder: Could not clear {table_name}: {e}")

    # Identify fields to populate
    insert_fields = {}
    pk_field = None
    fk_fields = {}

    for name, field in fields.items():
        if isinstance(field, BaseField) and field.primary_key and field.auto_increment:
            pk_field = name
            continue  # Skip auto-increment PKs
        if isinstance(field, ForeignKeyField):
            fk_fields[name] = field
            continue
        insert_fields[name] = field

    # Insert records
    inserted = 0
    for i in range(count):
        row = {}

        # Generate values for regular fields
        for name, field in insert_fields.items():
            if name in overrides:
                val = overrides[name]
                row[name] = val(fake) if callable(val) else val
            else:
                row[name] = fake.for_field(field, name)

        # Resolve foreign keys
        for name, field in fk_fields.items():
            if name in overrides:
                val = overrides[name]
                row[name] = val(fake) if callable(val) else val
            else:
                resolved = _resolve_fk(dba, field, fake)
                if resolved is not None:
                    row[name] = resolved

        # Insert via ORM
        try:
            obj = orm_class(row)
            obj.save()
            inserted += 1
        except Exception as e:
            Debug.warning(f"Seeder: Insert failed for {table_name} row {i + 1}: {e}")

    Debug.info(f"Seeder: Inserted {inserted}/{count} records into {table_name}")
    return inserted


def seed_table(dba, table_name, columns, count=10, overrides=None, clear=False, seed=None):
    """Seed a raw database table (no ORM class needed).

    Args:
        dba: A Database instance.
        table_name: Name of the table to seed.
        columns: Dict of ``{column_name: type_string}``.
            Supported types: "integer", "string", "text", "numeric", "float",
            "datetime", "date", "blob", "json", "jsonb", "boolean".
        count: Number of records to insert (default 10).
        overrides: Dict of ``{column_name: value_or_callable}``.
        clear: If True, deletes all existing records before seeding.
        seed: Optional random seed for reproducible data.

    Returns:
        int: Number of records inserted.

    Example::

        seed_table(dba, "audit_log", {
            "action": "string",
            "created_at": "datetime",
            "payload": "json",
        }, count=100)
    """
    if overrides is None:
        overrides = {}

    fake = FakeData(seed=seed)

    # Type string to field class mapping
    type_map = {
        "integer": IntegerField,
        "int": IntegerField,
        "string": StringField,
        "varchar": StringField,
        "text": TextField,
        "numeric": NumericField,
        "float": NumericField,
        "decimal": NumericField,
        "datetime": DateTimeField,
        "date": DateTimeField,
        "timestamp": DateTimeField,
        "blob": BlobField,
        "binary": BlobField,
        "json": JSONBField,
        "jsonb": JSONBField,
        "boolean": IntegerField,
        "bool": IntegerField,
    }

    if clear:
        try:
            dba.execute(f"DELETE FROM {table_name}")
            Debug.info(f"Seeder: Cleared {table_name}")
        except Exception as e:
            Debug.warning(f"Seeder: Could not clear {table_name}: {e}")

    inserted = 0
    for i in range(count):
        row = {}
        for col_name, type_str in columns.items():
            if col_name in overrides:
                val = overrides[col_name]
                row[col_name] = val(fake) if callable(val) else val
            else:
                field_class = type_map.get(type_str.lower(), StringField)
                field = field_class()
                field.column_name = col_name
                row[col_name] = fake.for_field(field, col_name)

        try:
            dba.insert(table_name, row)
            inserted += 1
        except Exception as e:
            Debug.warning(f"Seeder: Insert failed for {table_name} row {i + 1}: {e}")

    Debug.info(f"Seeder: Inserted {inserted}/{count} records into {table_name}")
    return inserted


class Seeder:
    """Programmatic seeder builder with relationship/dependency support.

    Resolves foreign key dependencies automatically via topological sort,
    ensuring parent tables are seeded before child tables.

    Example::

        seeder = Seeder(dba)
        seeder.add(User, count=20)
        seeder.add(Order, count=100, overrides={"status": "pending"})
        seeder.run(clear=True)
    """

    def __init__(self, dba=None):
        self._dba = dba
        self._tasks = []

    def add(self, orm_class, count=10, overrides=None, seed=None):
        """Register an ORM class to seed.

        Args:
            orm_class: An ORM subclass.
            count: Number of records to generate.
            overrides: Dict of ``{field_name: value_or_callable}``.
            seed: Optional random seed for this class.

        Returns:
            self (for chaining).
        """
        self._tasks.append({
            "orm_class": orm_class,
            "count": count,
            "overrides": overrides or {},
            "seed": seed,
        })
        return self

    def _resolve_order(self):
        """Topological sort of tasks based on ForeignKeyField references.

        Uses Kahn's algorithm. Classes with FK references to other seeded
        classes are moved after their dependencies.
        """
        # Build class-to-task mapping
        class_map = {}
        for task in self._tasks:
            class_map[task["orm_class"]] = task

        # Build adjacency list
        in_degree = {task["orm_class"]: 0 for task in self._tasks}
        graph = {task["orm_class"]: [] for task in self._tasks}

        for task in self._tasks:
            fields = _get_fields(task["orm_class"])
            for name, field in fields.items():
                if isinstance(field, ForeignKeyField):
                    ref = field.references_table
                    if ref in class_map and ref != task["orm_class"]:
                        graph[ref].append(task["orm_class"])
                        in_degree[task["orm_class"]] += 1

        # Kahn's algorithm
        queue = [cls for cls, deg in in_degree.items() if deg == 0]
        ordered = []

        while queue:
            cls = queue.pop(0)
            ordered.append(class_map[cls])
            for dependent in graph.get(cls, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Add any remaining (circular deps) at the end
        seen = {t["orm_class"] for t in ordered}
        for task in self._tasks:
            if task["orm_class"] not in seen:
                ordered.append(task)

        return ordered

    def run(self, clear=False):
        """Execute all seed tasks in dependency order.

        Args:
            clear: If True, clears tables before seeding (in reverse order).

        Returns:
            dict: ``{class_name: records_inserted}`` for each seeded class.
        """
        ordered = self._resolve_order()
        results = {}

        # If clearing, delete in reverse order (children first)
        if clear:
            for task in reversed(ordered):
                table = _get_table_name(task["orm_class"])
                try:
                    if self._dba:
                        self._dba.execute(f"DELETE FROM {table}")
                    elif task["orm_class"].__dba__:
                        task["orm_class"].__dba__.execute(f"DELETE FROM {table}")
                    Debug.info(f"Seeder: Cleared {table}")
                except Exception as e:
                    Debug.warning(f"Seeder: Could not clear {table}: {e}")

        for task in ordered:
            n = seed_orm(
                task["orm_class"],
                count=task["count"],
                overrides=task["overrides"],
                clear=False,  # Already cleared above if needed
                seed=task["seed"],
            )
            results[task["orm_class"].__name__] = n

        return results


# ---------------------------------------------------------------------------
# Auto-discovery: run seed files from src/seeds/
# ---------------------------------------------------------------------------

def seed(dba, seed_folder="src/seeds", clear=False):
    """Run all seed files in the given folder.

    Discovers ``*.py`` files in ``seed_folder``, sorted alphabetically,
    and calls their ``seed(dba)`` function.

    Args:
        dba: A Database instance.
        seed_folder: Path to the seeds directory (default "src/seeds").
        clear: Passed to each seed file's ``seed()`` function.

    Example seed file (``src/seeds/001_users.py``)::

        from src.orm.User import User
        from tina4_python.Seeder import seed_orm

        def seed(dba):
            seed_orm(User, count=50)
    """
    import importlib.util

    if not os.path.isdir(seed_folder):
        Debug.info(f"Seeder: No seeds folder found at {seed_folder}")
        return

    files = sorted([
        f for f in os.listdir(seed_folder)
        if f.endswith(".py") and not f.startswith("_")
    ])

    if not files:
        Debug.info(f"Seeder: No seed files found in {seed_folder}")
        return

    Debug.info(f"Seeder: Found {len(files)} seed file(s) in {seed_folder}")

    for filename in files:
        filepath = os.path.join(seed_folder, filename)
        module_name = f"seeds.{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "seed") and callable(module.seed):
                Debug.info(f"Seeder: Running {filename}...")
                module.seed(dba)
                Debug.info(f"Seeder: Completed {filename}")
            else:
                Debug.warning(f"Seeder: {filename} has no seed(dba) function, skipping")

        except Exception as e:
            Debug.error(f"Seeder: Failed to run {filename}: {e}")
