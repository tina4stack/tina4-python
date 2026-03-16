#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Extensive tests for the Tina4 Seeder module.

Tests cover:
- FakeData generator (all methods, deterministic seeding, edge cases)
- ORM introspection helpers (_get_fields, _get_table_name)
- seed_orm() — ORM-based seeding with overrides, clear, idempotency
- seed_table() — raw table seeding
- Seeder class — builder pattern, topological sort, run()
- seed() — auto-discovery of seed files
- CLI commands — seed:create file generation
"""

import os
import json
import shutil
import tempfile
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from tina4_python.Database import Database
from tina4_python.Migration import migrate
from tina4_python.ORM import ORM, orm
from tina4_python.FieldTypes import (
    IntegerField, StringField, TextField, NumericField,
    DateTimeField, BlobField, JSONBField, ForeignKeyField,
)
from tina4_python.Seeder import (
    FakeData, Seeder, seed_orm, seed_table, seed,
    _get_fields, _get_table_name, _resolve_fk,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dba():
    """Shared SQLite database connection."""
    db_path = "test_seeder.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    connection = Database(f"sqlite3:{db_path}", "", "")
    yield connection
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


# Define ORM classes at module level so they persist across test classes
class SeedUser(ORM):
    __table_name__ = "seed_user"
    id = IntegerField(auto_increment=True, primary_key=True)
    first_name = StringField()
    last_name = StringField()
    email = TextField()
    age = IntegerField()
    balance = NumericField()
    bio = TextField()
    date_created = DateTimeField()


class SeedCategory(ORM):
    __table_name__ = "seed_category"
    id = IntegerField(auto_increment=True, primary_key=True)
    name = StringField()
    description = TextField()


class SeedProduct(ORM):
    __table_name__ = "seed_product"
    id = IntegerField(auto_increment=True, primary_key=True)
    title = StringField()
    price = NumericField()
    category_id = ForeignKeyField(IntegerField("id"), references=SeedCategory())
    status = StringField()


class SeedOrder(ORM):
    __table_name__ = "seed_order"
    id = IntegerField(auto_increment=True, primary_key=True)
    user_id = ForeignKeyField(IntegerField("id"), references=SeedUser())
    product_id = ForeignKeyField(IntegerField("id"), references=SeedProduct())
    quantity = IntegerField()
    total = NumericField()
    date_created = DateTimeField()


@pytest.fixture(scope="module", autouse=True)
def setup_tables(dba):
    """Create test tables and register ORM."""
    for table in ["tina4_migration", "seed_order", "seed_product", "seed_category", "seed_user"]:
        dba.execute(f"DROP TABLE IF EXISTS {table}")
    dba.commit()

    migrate(dba)
    orm(dba)

    # Create tables via raw SQL to ensure they're in the right database
    dba.execute("""CREATE TABLE IF NOT EXISTS seed_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        age INTEGER DEFAULT 0,
        balance REAL DEFAULT 0.0,
        bio TEXT DEFAULT '',
        date_created TEXT
    )""")
    dba.execute("""CREATE TABLE IF NOT EXISTS seed_category (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT DEFAULT '',
        description TEXT DEFAULT ''
    )""")
    dba.execute("""CREATE TABLE IF NOT EXISTS seed_product (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '',
        price REAL DEFAULT 0.0,
        category_id INTEGER,
        status TEXT DEFAULT ''
    )""")
    dba.execute("""CREATE TABLE IF NOT EXISTS seed_order (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        quantity INTEGER DEFAULT 0,
        total REAL DEFAULT 0.0,
        date_created TEXT
    )""")
    dba.commit()

    return {
        "SeedUser": SeedUser,
        "SeedCategory": SeedCategory,
        "SeedProduct": SeedProduct,
        "SeedOrder": SeedOrder,
    }


@pytest.fixture(autouse=True)
def ensure_orm(dba):
    """Re-register ORM before each test to guard against other test modules resetting __dba__."""
    orm(dba)


# ===================================================================
# FakeData Tests
# ===================================================================

class TestFakeData:
    """Tests for the FakeData generator."""

    def test_deterministic_seed(self):
        """Same seed produces identical sequences."""
        a = FakeData(seed=42)
        b = FakeData(seed=42)
        assert a.name() == b.name()
        assert a.email() == b.email()
        assert a.integer() == b.integer()
        assert a.sentence() == b.sentence()

    def test_different_seeds(self):
        """Different seeds produce different data."""
        a = FakeData(seed=1)
        b = FakeData(seed=999)
        # Very unlikely to match
        results_a = [a.name() for _ in range(10)]
        results_b = [b.name() for _ in range(10)]
        assert results_a != results_b

    def test_no_seed_varies(self):
        """Without a seed, data should vary (not guaranteed but statistically certain)."""
        a = FakeData()
        b = FakeData()
        # Generate enough data that collision is near-impossible
        names_a = [a.name() for _ in range(50)]
        names_b = [b.name() for _ in range(50)]
        assert names_a != names_b

    def test_first_name(self):
        fake = FakeData(seed=1)
        name = fake.first_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_last_name(self):
        fake = FakeData(seed=1)
        name = fake.last_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_name(self):
        fake = FakeData(seed=1)
        name = fake.name()
        assert " " in name  # first + last

    def test_email_format(self):
        fake = FakeData(seed=1)
        email = fake.email()
        assert "@" in email
        assert "." in email.split("@")[1]

    def test_email_from_name(self):
        fake = FakeData(seed=1)
        email = fake.email(name="John Smith")
        assert email.startswith("john.smith")
        assert "@" in email

    def test_phone(self):
        fake = FakeData(seed=1)
        phone = fake.phone()
        assert phone.startswith("+1")
        assert "(" in phone and ")" in phone

    def test_sentence(self):
        fake = FakeData(seed=1)
        s = fake.sentence(words=5)
        assert s.endswith(".")
        # First word capitalized
        assert s[0].isupper()

    def test_sentence_word_count(self):
        fake = FakeData(seed=1)
        s = fake.sentence(words=8)
        words = s.rstrip(".").split()
        assert len(words) == 8

    def test_paragraph(self):
        fake = FakeData(seed=1)
        p = fake.paragraph(sentences=3)
        assert isinstance(p, str)
        assert len(p) > 20

    def test_text_max_length(self):
        fake = FakeData(seed=1)
        t = fake.text(max_length=50)
        assert len(t) <= 50

    def test_word(self):
        fake = FakeData(seed=1)
        w = fake.word()
        assert isinstance(w, str)
        assert " " not in w

    def test_slug(self):
        fake = FakeData(seed=1)
        slug = fake.slug(words=3)
        parts = slug.split("-")
        assert len(parts) == 3

    def test_url(self):
        fake = FakeData(seed=1)
        url = fake.url()
        assert url.startswith("https://")

    def test_integer_range(self):
        fake = FakeData(seed=1)
        for _ in range(100):
            val = fake.integer(10, 20)
            assert 10 <= val <= 20

    def test_numeric_range(self):
        fake = FakeData(seed=1)
        for _ in range(100):
            val = fake.numeric(0.0, 10.0, 2)
            assert 0.0 <= val <= 10.0

    def test_numeric_decimals(self):
        fake = FakeData(seed=1)
        val = fake.numeric(0.0, 100.0, 3)
        # Check decimal precision
        str_val = str(val)
        if "." in str_val:
            assert len(str_val.split(".")[1]) <= 3

    def test_boolean(self):
        fake = FakeData(seed=1)
        vals = set(fake.boolean() for _ in range(100))
        assert vals == {0, 1}

    def test_datetime_type(self):
        fake = FakeData(seed=1)
        dt = fake.datetime()
        assert isinstance(dt, datetime)

    def test_datetime_range(self):
        fake = FakeData(seed=1)
        dt = fake.datetime(start_year=2023, end_year=2024)
        assert 2023 <= dt.year <= 2024

    def test_date_format(self):
        fake = FakeData(seed=1)
        d = fake.date()
        parts = d.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # YYYY

    def test_timestamp_format(self):
        fake = FakeData(seed=1)
        ts = fake.timestamp()
        assert " " in ts  # date space time
        date_part, time_part = ts.split(" ")
        assert len(date_part.split("-")) == 3
        assert len(time_part.split(":")) == 3

    def test_blob(self):
        fake = FakeData(seed=1)
        b = fake.blob(32)
        assert isinstance(b, bytes)
        assert len(b) == 32

    def test_json_data_default(self):
        fake = FakeData(seed=1)
        data = fake.json_data()
        assert isinstance(data, dict)
        assert 2 <= len(data) <= 5

    def test_json_data_with_keys(self):
        fake = FakeData(seed=1)
        data = fake.json_data(keys=["name", "value", "score"])
        assert set(data.keys()) == {"name", "value", "score"}

    def test_choice(self):
        fake = FakeData(seed=1)
        items = ["a", "b", "c"]
        val = fake.choice(items)
        assert val in items

    def test_city(self):
        fake = FakeData(seed=1)
        city = fake.city()
        assert isinstance(city, str)
        assert len(city) > 0

    def test_country(self):
        fake = FakeData(seed=1)
        country = fake.country()
        assert isinstance(country, str)
        assert len(country) > 0

    def test_address(self):
        fake = FakeData(seed=1)
        addr = fake.address()
        assert isinstance(addr, str)
        # Should have a number and street type
        parts = addr.split()
        assert len(parts) >= 3

    def test_zip_code(self):
        fake = FakeData(seed=1)
        z = fake.zip_code()
        assert z.isdigit()
        assert len(z) == 5

    def test_company(self):
        fake = FakeData(seed=1)
        c = fake.company()
        assert isinstance(c, str)
        assert " " in c  # "TechGlobal Inc" pattern

    def test_color_hex(self):
        fake = FakeData(seed=1)
        color = fake.color_hex()
        assert color.startswith("#")
        assert len(color) == 7

    def test_uuid_format(self):
        fake = FakeData(seed=1)
        u = fake.uuid()
        parts = u.split("-")
        assert len(parts) == 5
        assert len(u) == 36


# ===================================================================
# FakeData.for_field() Tests
# ===================================================================

class TestFakeDataForField:
    """Test the smart field-to-data mapping."""

    def test_auto_increment_pk_returns_none(self):
        fake = FakeData(seed=1)
        field = IntegerField(primary_key=True, auto_increment=True)
        assert fake.for_field(field, "id") is None

    def test_foreign_key_returns_none(self):
        """FK fields return None (caller resolves)."""
        fake = FakeData(seed=1)

        class DummyORM(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)

        field = ForeignKeyField(IntegerField("id"), references=DummyORM())
        assert fake.for_field(field, "user_id") is None

    def test_integer_field_default(self):
        fake = FakeData(seed=1)
        val = fake.for_field(IntegerField(), "some_count")
        assert isinstance(val, int)

    def test_integer_field_age(self):
        fake = FakeData(seed=1)
        for _ in range(50):
            val = fake.for_field(IntegerField(), "age")
            assert 18 <= val <= 85

    def test_integer_field_year(self):
        fake = FakeData(seed=1)
        val = fake.for_field(IntegerField(), "birth_year")
        assert 1950 <= val <= 2026

    def test_integer_field_boolean(self):
        fake = FakeData(seed=1)
        val = fake.for_field(IntegerField(), "is_active")
        assert val in (0, 1)

    def test_integer_field_rating(self):
        fake = FakeData(seed=1)
        for _ in range(50):
            val = fake.for_field(IntegerField(), "rating")
            assert 1 <= val <= 10

    def test_numeric_field_price(self):
        fake = FakeData(seed=1)
        field = NumericField(decimal_places=2)
        val = fake.for_field(field, "price")
        assert isinstance(val, float)
        assert 0.01 <= val <= 9999.99

    def test_numeric_field_latitude(self):
        fake = FakeData(seed=1)
        field = NumericField()
        val = fake.for_field(field, "latitude")
        assert -90.0 <= val <= 90.0

    def test_numeric_field_longitude(self):
        fake = FakeData(seed=1)
        field = NumericField()
        val = fake.for_field(field, "longitude")
        assert -180.0 <= val <= 180.0

    def test_datetime_field(self):
        fake = FakeData(seed=1)
        val = fake.for_field(DateTimeField(), "created_at")
        assert isinstance(val, str)
        assert " " in val

    def test_blob_field(self):
        fake = FakeData(seed=1)
        val = fake.for_field(BlobField(), "data")
        assert isinstance(val, bytes)

    def test_jsonb_field(self):
        fake = FakeData(seed=1)
        val = fake.for_field(JSONBField(), "metadata")
        assert isinstance(val, dict)

    def test_string_field_email(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "email")
        assert "@" in val

    def test_string_field_name(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "name")
        assert " " in val  # full name

    def test_string_field_first_name(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "first_name")
        assert isinstance(val, str)
        assert " " not in val

    def test_string_field_phone(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "phone")
        assert "+" in val

    def test_string_field_url(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "website")
        assert val.startswith("https://")

    def test_string_field_city(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "city")
        assert isinstance(val, str)

    def test_string_field_country(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "country")
        assert isinstance(val, str)

    def test_string_field_company(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "company")
        assert isinstance(val, str)

    def test_string_field_status(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "status")
        assert val in ["active", "inactive", "pending", "archived"]

    def test_string_field_password(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "password")
        assert len(val) == 16
        assert val.isalnum()

    def test_string_field_uuid(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "uuid")
        assert "-" in val

    def test_string_field_slug(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "slug")
        assert "-" in val

    def test_string_field_title(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "title")
        assert isinstance(val, str)
        assert len(val) > 0

    def test_string_field_description(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "description")
        assert isinstance(val, str)

    def test_string_field_max_length(self):
        fake = FakeData(seed=1)
        field = StringField(field_size=10)
        val = fake.for_field(field, "email")
        assert len(val) <= 10

    def test_string_field_generic_fallback(self):
        fake = FakeData(seed=1)
        val = fake.for_field(StringField(), "some_unknown_column")
        assert isinstance(val, str)
        assert len(val) > 0

    def test_text_field_content(self):
        fake = FakeData(seed=1)
        val = fake.for_field(TextField(), "content")
        assert isinstance(val, str)
        assert len(val) > 10


# ===================================================================
# ORM Introspection Tests
# ===================================================================

class TestIntrospection:
    """Test _get_fields and _get_table_name."""

    def test_get_table_name_explicit(self):
        class MyModel(ORM):
            __table_name__ = "custom_table"
            id = IntegerField(primary_key=True)

        assert _get_table_name(MyModel) == "custom_table"

    def test_get_table_name_auto(self):
        class UserProfile(ORM):
            id = IntegerField(primary_key=True)

        assert _get_table_name(UserProfile) == "user_profile"

    def test_get_table_name_simple(self):
        class User(ORM):
            id = IntegerField(primary_key=True)

        assert _get_table_name(User) == "user"

    def test_get_fields_returns_fields(self):
        class MyModel(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()
            email = TextField()

        fields = _get_fields(MyModel)
        assert "name" in fields or "id" in fields
        # Should contain at least the field types we defined
        field_names = set(fields.keys())
        assert "name" in field_names
        assert "email" in field_names

    def test_get_fields_includes_fk(self):
        class Parent(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)

        class Child(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            parent_id = ForeignKeyField(IntegerField("id"), references=Parent())

        fields = _get_fields(Child)
        assert "parent_id" in fields
        assert isinstance(fields["parent_id"], ForeignKeyField)


# ===================================================================
# seed_orm() Tests
# ===================================================================

class TestSeedOrm:
    """Test ORM-based seeding with actual database."""

    def test_seed_basic(self, dba):
        """Seed 5 users and verify count."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        count = seed_orm(SeedUser, count=5, seed=42)
        assert count == 5

        result = dba.fetch("SELECT count(*) as cnt FROM seed_user")
        assert result.records[0]["cnt"] == 5

    def test_seed_data_quality(self, dba):
        """Verify that generated data matches column heuristics."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        seed_orm(SeedUser, count=3, seed=42)

        result = dba.fetch("SELECT * FROM seed_user")
        for row in result.records:
            assert row["first_name"] is not None
            assert row["last_name"] is not None
            assert "@" in str(row["email"])
            assert isinstance(row["age"], int)

    def test_seed_with_overrides_static(self, dba):
        """Static override values."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        seed_orm(SeedUser, count=3, overrides={"first_name": "TestName"}, seed=42)

        result = dba.fetch("SELECT first_name FROM seed_user")
        for row in result.records:
            assert row["first_name"] == "TestName"

    def test_seed_with_overrides_callable(self, dba):
        """Callable override values."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        seed_orm(SeedUser, count=5, overrides={
            "age": lambda fake: fake.integer(25, 25),
        }, seed=42)

        result = dba.fetch("SELECT age FROM seed_user")
        for row in result.records:
            assert row["age"] == 25

    def test_seed_clear(self, dba):
        """Clear=True removes existing records before seeding."""

        # First seed
        seed_orm(SeedUser, count=10, clear=True, seed=1)
        result = dba.fetch("SELECT count(*) as cnt FROM seed_user")
        assert result.records[0]["cnt"] == 10

        # Second seed with clear
        seed_orm(SeedUser, count=3, clear=True, seed=2)
        result = dba.fetch("SELECT count(*) as cnt FROM seed_user")
        assert result.records[0]["cnt"] == 3

    def test_seed_idempotent(self, dba):
        """Calling seed_orm twice without clear skips if enough records exist."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        count1 = seed_orm(SeedUser, count=5, seed=42)
        assert count1 == 5

        count2 = seed_orm(SeedUser, count=5, seed=99)
        assert count2 == 0  # Skipped because already has >= 5

    def test_seed_no_fields_returns_zero(self):
        """ORM with no fields returns 0."""
        class EmptyOrm(ORM):
            pass

        count = seed_orm(EmptyOrm, count=5)
        assert count == 0

    def test_seed_no_dba_returns_zero(self, dba):
        """ORM without dba returns 0."""
        class NoDbOrm(ORM):
            __dba__ = None
            id = IntegerField(primary_key=True, auto_increment=True)
            name = StringField()

        count = seed_orm(NoDbOrm, count=5)
        assert count == 0

    def test_seed_deterministic(self, dba):
        """Same seed produces same data."""

        dba.execute("DELETE FROM seed_user")
        dba.commit()
        seed_orm(SeedUser, count=3, seed=42)
        result1 = dba.fetch("SELECT first_name, last_name, email FROM seed_user ORDER BY id")

        dba.execute("DELETE FROM seed_user")
        dba.commit()
        seed_orm(SeedUser, count=3, seed=42)
        result2 = dba.fetch("SELECT first_name, last_name, email FROM seed_user ORDER BY id")

        for r1, r2 in zip(result1.records, result2.records):
            assert r1["first_name"] == r2["first_name"]
            assert r1["last_name"] == r2["last_name"]
            assert r1["email"] == r2["email"]


# ===================================================================
# seed_table() Tests
# ===================================================================

class TestSeedTable:
    """Test raw table seeding."""

    def test_seed_table_basic(self, dba):
        """Seed a raw table."""
        dba.execute("DROP TABLE IF EXISTS seed_raw_test")
        dba.execute("CREATE TABLE seed_raw_test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, score INTEGER)")
        dba.commit()

        count = seed_table(dba, "seed_raw_test", {
            "name": "string",
            "score": "integer",
        }, count=10, seed=42)

        assert count == 10
        result = dba.fetch("SELECT count(*) as cnt FROM seed_raw_test")
        assert result.records[0]["cnt"] == 10

        # Cleanup
        dba.execute("DROP TABLE IF EXISTS seed_raw_test")
        dba.commit()

    def test_seed_table_all_types(self, dba):
        """Seed with all supported type strings."""
        dba.execute("DROP TABLE IF EXISTS seed_types_test")
        dba.execute("""CREATE TABLE seed_types_test (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            int_col INTEGER,
            str_col TEXT,
            txt_col TEXT,
            num_col REAL,
            dt_col TEXT,
            json_col TEXT,
            bool_col INTEGER
        )""")
        dba.commit()

        count = seed_table(dba, "seed_types_test", {
            "int_col": "integer",
            "str_col": "string",
            "txt_col": "text",
            "num_col": "numeric",
            "dt_col": "datetime",
            "json_col": "json",
            "bool_col": "boolean",
        }, count=5, seed=42)

        assert count == 5

        result = dba.fetch("SELECT * FROM seed_types_test")
        for row in result.records:
            assert isinstance(row["int_col"], int)
            assert isinstance(row["str_col"], str)
            assert isinstance(row["num_col"], (int, float))
            assert isinstance(row["bool_col"], int)

        dba.execute("DROP TABLE IF EXISTS seed_types_test")
        dba.commit()

    def test_seed_table_with_overrides(self, dba):
        """Overrides work for raw table seeding."""
        dba.execute("DROP TABLE IF EXISTS seed_override_test")
        dba.execute("CREATE TABLE seed_override_test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, status TEXT)")
        dba.commit()

        seed_table(dba, "seed_override_test", {
            "name": "string",
            "status": "string",
        }, count=5, overrides={"status": "active"}, seed=42)

        result = dba.fetch("SELECT status FROM seed_override_test")
        for row in result.records:
            assert row["status"] == "active"

        dba.execute("DROP TABLE IF EXISTS seed_override_test")
        dba.commit()

    def test_seed_table_clear(self, dba):
        """Clear removes existing data."""
        dba.execute("DROP TABLE IF EXISTS seed_clear_test")
        dba.execute("CREATE TABLE seed_clear_test (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
        dba.commit()

        seed_table(dba, "seed_clear_test", {"val": "string"}, count=10, seed=1)
        seed_table(dba, "seed_clear_test", {"val": "string"}, count=3, clear=True, seed=2)

        result = dba.fetch("SELECT count(*) as cnt FROM seed_clear_test")
        assert result.records[0]["cnt"] == 3

        dba.execute("DROP TABLE IF EXISTS seed_clear_test")
        dba.commit()

    def test_seed_table_type_aliases(self, dba):
        """Alternative type strings (int, varchar, float, etc.)."""
        dba.execute("DROP TABLE IF EXISTS seed_alias_test")
        dba.execute("CREATE TABLE seed_alias_test (id INTEGER PRIMARY KEY AUTOINCREMENT, a INTEGER, b TEXT, c REAL, d TEXT)")
        dba.commit()

        count = seed_table(dba, "seed_alias_test", {
            "a": "int",
            "b": "varchar",
            "c": "float",
            "d": "timestamp",
        }, count=3, seed=42)

        assert count == 3

        dba.execute("DROP TABLE IF EXISTS seed_alias_test")
        dba.commit()


# ===================================================================
# Seeder Class Tests
# ===================================================================

class TestSeederClass:
    """Test the builder/runner Seeder class."""

    def test_seeder_single_class(self, dba):
        """Seed a single class via Seeder."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        seeder = Seeder(dba)
        seeder.add(SeedUser, count=7, seed=42)
        results = seeder.run()

        assert results["SeedUser"] == 7
        result = dba.fetch("SELECT count(*) as cnt FROM seed_user")
        assert result.records[0]["cnt"] == 7

    def test_seeder_chaining(self, dba):
        """Method chaining works."""

        dba.execute("DELETE FROM seed_user")
        dba.execute("DELETE FROM seed_category")
        dba.commit()

        results = (
            Seeder(dba)
            .add(SeedUser, count=5, seed=1)
            .add(SeedCategory, count=3, seed=2)
            .run()
        )

        assert results["SeedUser"] == 5
        assert results["SeedCategory"] == 3

    def test_seeder_dependency_order(self, dba):
        """FK dependencies are resolved via topological sort."""

        # Clear in reverse dependency order
        for table in ["seed_order", "seed_product", "seed_category", "seed_user"]:
            dba.execute(f"DELETE FROM {table}")
        dba.commit()

        # Add in wrong order — Seeder should fix it
        seeder = Seeder(dba)
        seeder.add(SeedOrder, count=10, seed=1)
        seeder.add(SeedProduct, count=5, seed=2)
        seeder.add(SeedUser, count=3, seed=3)
        seeder.add(SeedCategory, count=4, seed=4)
        results = seeder.run()

        # All should succeed (parents seeded before children)
        assert results["SeedUser"] == 3
        assert results["SeedCategory"] == 4
        assert results["SeedProduct"] == 5
        assert results["SeedOrder"] == 10

    def test_seeder_clear(self, dba):
        """Seeder.run(clear=True) clears in reverse dependency order."""

        # Pre-populate
        dba.execute("DELETE FROM seed_user")
        dba.execute("DELETE FROM seed_category")
        dba.commit()
        seed_orm(SeedUser, count=20, clear=True, seed=1)
        seed_orm(SeedCategory, count=10, clear=True, seed=2)

        # Now seed with clear
        seeder = Seeder(dba)
        seeder.add(SeedUser, count=3, seed=99)
        seeder.add(SeedCategory, count=2, seed=99)
        results = seeder.run(clear=True)

        assert results["SeedUser"] == 3
        assert results["SeedCategory"] == 2

    def test_seeder_with_overrides(self, dba):
        """Overrides passed through Seeder.add()."""
        dba.execute("DELETE FROM seed_category")
        dba.commit()

        seeder = Seeder(dba)
        seeder.add(SeedCategory, count=5, overrides={"name": "Test Category"}, seed=42)
        seeder.run()

        result = dba.fetch("SELECT name FROM seed_category")
        for row in result.records:
            assert row["name"] == "Test Category"


# ===================================================================
# seed() Auto-Discovery Tests
# ===================================================================

class TestSeedAutoDiscovery:
    """Test the seed() function that discovers seed files."""

    def test_seed_no_folder(self, dba):
        """No seeds folder is handled gracefully."""
        seed(dba, seed_folder="/tmp/nonexistent_seeds_folder")
        # Should not raise

    def test_seed_empty_folder(self, dba):
        """Empty seeds folder is handled gracefully."""
        tmpdir = tempfile.mkdtemp()
        try:
            seed(dba, seed_folder=tmpdir)
        finally:
            shutil.rmtree(tmpdir)

    def test_seed_skips_underscore_files(self, dba):
        """Files starting with _ are skipped."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create an __init__.py and a _helper.py — both should be skipped
            with open(os.path.join(tmpdir, "__init__.py"), "w") as f:
                f.write("")
            with open(os.path.join(tmpdir, "_helper.py"), "w") as f:
                f.write("def seed(dba): raise RuntimeError('Should not be called')")

            seed(dba, seed_folder=tmpdir)
            # No error means the _helper.py was correctly skipped
        finally:
            shutil.rmtree(tmpdir)

    def test_seed_runs_files_alphabetically(self, dba):
        """Seed files run in sorted order."""
        tmpdir = tempfile.mkdtemp()
        tracker_file = os.path.join(tmpdir, "order.txt")

        try:
            for name in ["002_second.py", "001_first.py", "003_third.py"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(f"""
import os
def seed(dba):
    with open(r"{tracker_file}", "a") as f:
        f.write("{name}\\n")
""")

            seed(dba, seed_folder=tmpdir)

            with open(tracker_file) as f:
                order = f.read().strip().split("\n")

            assert order == ["001_first.py", "002_second.py", "003_third.py"]
        finally:
            shutil.rmtree(tmpdir)

    def test_seed_file_without_function(self, dba):
        """Seed file without seed() function is skipped gracefully."""
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "001_no_func.py"), "w") as f:
                f.write("x = 42\n")

            seed(dba, seed_folder=tmpdir)  # Should not raise
        finally:
            shutil.rmtree(tmpdir)

    def test_seed_file_with_error(self, dba):
        """Seed file that raises error is caught and reported."""
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "001_broken.py"), "w") as f:
                f.write("def seed(dba): raise ValueError('test error')\n")

            seed(dba, seed_folder=tmpdir)  # Should not raise
        finally:
            shutil.rmtree(tmpdir)


# ===================================================================
# CLI seed:create Tests
# ===================================================================

class TestCLISeedCreate:
    """Test the create_seed_file CLI function."""

    def test_create_seed_file(self):
        """Creates a seed file with correct naming."""
        from tina4_python.cli import create_seed_file

        tmpdir = tempfile.mkdtemp()
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            os.makedirs("src/seeds", exist_ok=True)
            create_seed_file("users")

            files = sorted(os.listdir(os.path.join(tmpdir, "src", "seeds")))
            # Should have __init__.py and 001_users.py
            assert "__init__.py" in files
            assert "001_users.py" in files

            # Check content
            content = open(os.path.join(tmpdir, "src", "seeds", "001_users.py")).read()
            assert "def seed(dba)" in content
            assert "seed_orm" in content
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(tmpdir)

    def test_create_seed_file_auto_increment(self):
        """Second seed file gets 002_ prefix."""
        from tina4_python.cli import create_seed_file

        tmpdir = tempfile.mkdtemp()
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            os.makedirs("src/seeds", exist_ok=True)
            create_seed_file("users")
            create_seed_file("products")

            files = sorted(os.listdir(os.path.join(tmpdir, "src", "seeds")))
            py_files = [f for f in files if f.endswith(".py") and not f.startswith("_")]
            assert len(py_files) == 2
            assert py_files[0].startswith("001_")
            assert py_files[1].startswith("002_")
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(tmpdir)

    def test_create_seed_file_name_normalization(self):
        """Seed name is normalized to snake_case."""
        from tina4_python.cli import create_seed_file

        tmpdir = tempfile.mkdtemp()
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            os.makedirs("src/seeds", exist_ok=True)
            create_seed_file("User Profiles & Orders")

            files = [f for f in os.listdir(os.path.join(tmpdir, "src", "seeds"))
                     if f.endswith(".py") and not f.startswith("_")]
            assert len(files) == 1
            assert "user_profiles_orders" in files[0]
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(tmpdir)


# ===================================================================
# FK Resolution Tests
# ===================================================================

class TestFKResolution:
    """Test foreign key resolution during seeding."""

    def test_fk_resolved_from_parent(self, dba):
        """Products reference categories that exist."""

        dba.execute("DELETE FROM seed_product")
        dba.execute("DELETE FROM seed_category")
        dba.commit()

        # Seed parents first
        seed_orm(SeedCategory, count=3, clear=True, seed=42)
        seed_orm(SeedProduct, count=10, clear=True, seed=42)

        # Verify products have valid category_ids
        categories = dba.fetch("SELECT id FROM seed_category")
        valid_ids = {row["id"] for row in categories.records}

        products = dba.fetch("SELECT category_id FROM seed_product")
        for row in products.records:
            if row["category_id"] is not None:
                assert row["category_id"] in valid_ids

    def test_seeder_resolves_deep_fk_chain(self, dba):
        """Order → Product → Category chain resolved correctly."""

        for table in ["seed_order", "seed_product", "seed_category", "seed_user"]:
            dba.execute(f"DELETE FROM {table}")
        dba.commit()

        seeder = Seeder(dba)
        seeder.add(SeedUser, count=5, seed=1)
        seeder.add(SeedCategory, count=3, seed=2)
        seeder.add(SeedProduct, count=8, seed=3)
        seeder.add(SeedOrder, count=15, seed=4)
        results = seeder.run()

        assert results["SeedUser"] == 5
        assert results["SeedCategory"] == 3
        assert results["SeedProduct"] == 8
        assert results["SeedOrder"] == 15

        # Verify orders reference valid users and products
        users = {row["id"] for row in dba.fetch("SELECT id FROM seed_user").records}
        products = {row["id"] for row in dba.fetch("SELECT id FROM seed_product").records}
        orders = dba.fetch("SELECT user_id, product_id FROM seed_order")

        for row in orders.records:
            if row["user_id"] is not None:
                assert row["user_id"] in users
            if row["product_id"] is not None:
                assert row["product_id"] in products


# ===================================================================
# Edge Case / Stress Tests
# ===================================================================

class TestEdgeCases:
    """Edge cases and stress tests."""

    def test_seed_zero_count(self, dba):
        """count=0 inserts nothing."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        count = seed_orm(SeedUser, count=0, seed=42)
        assert count == 0

    def test_seed_large_batch(self, dba):
        """Seed 500 records."""
        dba.execute("DELETE FROM seed_user")
        dba.commit()

        count = seed_orm(SeedUser, count=500, seed=42)
        assert count == 500

        result = dba.fetch("SELECT count(*) as cnt FROM seed_user")
        assert result.records[0]["cnt"] == 500

    def test_fake_data_many_calls(self):
        """FakeData should not crash after many calls."""
        fake = FakeData(seed=1)
        for _ in range(1000):
            fake.name()
            fake.email()
            fake.integer()
            fake.sentence()
            fake.json_data()

    def test_fake_data_unique_emails(self):
        """Email generation should have low collision rate."""
        fake = FakeData(seed=42)
        emails = set(fake.email() for _ in range(200))
        # With random suffix numbers, should be very few collisions
        assert len(emails) > 150  # Allow for some collisions

    def test_seed_table_unknown_type_defaults_to_string(self, dba):
        """Unknown type string defaults to StringField."""
        dba.execute("DROP TABLE IF EXISTS seed_unknown_type")
        dba.execute("CREATE TABLE seed_unknown_type (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
        dba.commit()

        count = seed_table(dba, "seed_unknown_type", {
            "val": "unknown_type_xyz",
        }, count=3, seed=42)

        assert count == 3
        result = dba.fetch("SELECT val FROM seed_unknown_type")
        for row in result.records:
            assert isinstance(row["val"], str)

        dba.execute("DROP TABLE IF EXISTS seed_unknown_type")
        dba.commit()
