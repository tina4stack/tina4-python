# Tests for tina4_python.seeder
import pytest
from tina4_python.seeder import FakeData, seed_table
from tina4_python.database import Database


@pytest.fixture
def fake():
    return FakeData(seed=42)


class TestFake:
    def test_name(self, fake):
        name = fake.name()
        assert " " in name
        assert len(name) > 3

    def test_email(self, fake):
        email = fake.email()
        assert "@" in email
        assert "." in email

    def test_phone(self, fake):
        phone = fake.phone()
        assert phone.startswith("+1")

    def test_integer(self, fake):
        n = fake.integer(1, 100)
        assert 1 <= n <= 100

    def test_decimal(self, fake):
        d = fake.decimal(0, 100, 2)
        assert 0 <= d <= 100

    def test_boolean(self, fake):
        assert isinstance(fake.boolean(), bool)

    def test_sentence(self, fake):
        s = fake.sentence()
        assert s.endswith(".")
        assert len(s) > 5

    def test_date(self, fake):
        d = fake.date()
        assert len(d) == 10
        assert "-" in d

    def test_uuid(self, fake):
        u = fake.uuid()
        assert len(u) == 36
        assert u.count("-") == 4

    def test_url(self, fake):
        url = fake.url()
        assert url.startswith("https://")

    def test_address(self, fake):
        addr = fake.address()
        assert "," in addr

    def test_deterministic(self):
        f1 = FakeData(seed=123)
        f2 = FakeData(seed=123)
        assert f1.name() == f2.name()
        assert f1.email() == f2.email()

    def test_choice(self, fake):
        result = fake.choice(["a", "b", "c"])
        assert result in ["a", "b", "c"]

    def test_alphanumeric(self, fake):
        s = fake.alphanumeric(20)
        assert len(s) == 20


class TestSeedTable:
    def test_seed(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seed.db'}")
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)")
        db.commit()

        fake = FakeData(seed=1)
        count = seed_table(db, "users", 10, {
            "name": fake.name,
            "email": fake.email,
        })
        assert count == 10

        result = db.fetch("SELECT * FROM users", limit=100)
        assert result.count == 10
        db.close()

    def test_seed_with_overrides(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seed2.db'}")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, active INTEGER)")
        db.commit()

        fake = FakeData()
        seed_table(db, "items", 5, {"name": fake.word}, overrides={"active": 1})

        result = db.fetch("SELECT * FROM items WHERE active = 1", limit=100)
        assert result.count == 5
        db.close()

    def test_seed_zero_rows(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seed0.db'}")
        db.execute("CREATE TABLE things (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()

        fake = FakeData()
        count = seed_table(db, "things", 0, {"name": fake.name})
        assert count == 0
        db.close()

    def test_seed_no_field_map(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seedn.db'}")
        db.execute("CREATE TABLE things (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()

        count = seed_table(db, "things", 10)
        assert count == 0
        db.close()

    def test_seed_empty_field_map(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seede.db'}")
        db.execute("CREATE TABLE things (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        db.commit()

        count = seed_table(db, "things", 10, field_map={})
        assert count == 0
        db.close()

    def test_seed_static_values_in_field_map(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seeds.db'}")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, status TEXT)")
        db.commit()

        seed_table(db, "items", 3, {"name": "static_name", "status": "active"})

        result = db.fetch("SELECT * FROM items", limit=100)
        assert result.count == 3
        for row in result:
            assert row["name"] == "static_name"
            assert row["status"] == "active"
        db.close()

    def test_seed_multiple_columns(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'seedm.db'}")
        db.execute(
            "CREATE TABLE people (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT, email TEXT, phone TEXT, age INTEGER)"
        )
        db.commit()

        fake = FakeData(seed=42)
        count = seed_table(db, "people", 20, {
            "name": fake.name,
            "email": fake.email,
            "phone": fake.phone,
            "age": lambda: fake.integer(18, 90),
        })
        assert count == 20

        result = db.fetch("SELECT * FROM people", limit=100)
        assert result.count == 20
        for row in result:
            assert "@" in row["email"]
            assert row["phone"].startswith("+1")
        db.close()


class TestFakeNames:
    def test_first_name(self, fake):
        first = fake.first_name()
        assert isinstance(first, str)
        assert len(first) > 0
        assert " " not in first

    def test_last_name(self, fake):
        last = fake.last_name()
        assert isinstance(last, str)
        assert len(last) > 0
        assert " " not in last

    def test_name_is_first_plus_last(self, fake):
        name = fake.name()
        parts = name.split(" ")
        assert len(parts) == 2


class TestFakeText:
    def test_word_no_spaces(self, fake):
        w = fake.word()
        assert " " not in w
        assert len(w) > 0

    def test_sentence_word_count(self, fake):
        s = fake.sentence(words=5)
        # sentence has ~5 words + period
        word_count = len(s.rstrip(".").split())
        assert word_count == 5

    def test_sentence_capitalized(self, fake):
        s = fake.sentence()
        assert s[0].isupper()

    def test_paragraph_has_multiple_sentences(self, fake):
        p = fake.paragraph(sentences=3)
        # Should contain at least 3 periods
        assert p.count(".") >= 3

    def test_text_has_paragraphs(self, fake):
        t = fake.text(paragraphs=2)
        assert "\n\n" in t


class TestFakeNumeric:
    def test_integer_min_equals_max(self, fake):
        n = fake.integer(5, 5)
        assert n == 5

    def test_decimal_precision(self, fake):
        d = fake.decimal(0, 100, 3)
        # Should have at most 3 decimal places
        s = str(d)
        if "." in s:
            assert len(s.split(".")[1]) <= 3

    def test_integer_negative_range(self, fake):
        n = fake.integer(-100, -1)
        assert -100 <= n <= -1


class TestFakeIdentifiers:
    def test_uuid_format(self, fake):
        u = fake.uuid()
        parts = u.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    def test_uuid_uniqueness(self, fake):
        uuids = {fake.uuid() for _ in range(50)}
        assert len(uuids) == 50

    def test_url_format(self, fake):
        url = fake.url()
        assert url.startswith("https://")
        assert "/" in url[8:]

    def test_color_hex_format(self, fake):
        c = fake.color_hex()
        assert c.startswith("#")
        assert len(c) == 7
        # All chars after # should be hex digits
        int(c[1:], 16)


class TestFakeContact:
    def test_email_format(self, fake):
        email = fake.email()
        assert "@" in email
        local, domain = email.split("@")
        assert len(local) > 0
        assert "." in domain

    def test_phone_format(self, fake):
        phone = fake.phone()
        assert phone.startswith("+1 (")
        assert ")" in phone
        assert "-" in phone

    def test_address_has_number_and_street(self, fake):
        addr = fake.address()
        parts = addr.split(",")
        assert len(parts) >= 2
        # First part should have a number and street
        assert any(c.isdigit() for c in parts[0])


class TestFakeMisc:
    def test_sample(self, fake):
        items = [1, 2, 3, 4, 5]
        s = fake.sample(items, 3)
        assert len(s) == 3
        assert all(x in items for x in s)

    def test_sample_larger_than_list(self, fake):
        items = [1, 2]
        s = fake.sample(items, 10)
        assert len(s) == 2

    def test_alphanumeric_default_length(self, fake):
        s = fake.alphanumeric()
        assert len(s) == 10

    def test_alphanumeric_chars(self, fake):
        s = fake.alphanumeric(50)
        assert all(c.isalnum() for c in s)

    def test_date_format(self, fake):
        d = fake.date()
        parts = d.split("-")
        assert len(parts) == 3
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        assert 2020 <= year <= 2025
        assert 1 <= month <= 12
        assert 1 <= day <= 31

    def test_date_range(self, fake):
        d = fake.date(start_year=2023, end_year=2023)
        assert d.startswith("2023-")

    def test_datetime_iso_format(self, fake):
        dt = fake.datetime_iso()
        assert "T" in dt
        assert dt.endswith("Z")
        # Check date part
        assert len(dt.split("T")[0]) == 10

    def test_boolean_type(self, fake):
        results = {fake.boolean() for _ in range(100)}
        assert True in results
        assert False in results

    def test_choice_from_list(self, fake):
        items = ["a", "b", "c"]
        for _ in range(20):
            assert fake.choice(items) in items

    def test_seed_factory(self):
        f = FakeData.seed(42)
        assert isinstance(f, FakeData)
        name = f.name()
        assert isinstance(name, str)
        assert " " in name
