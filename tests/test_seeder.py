# Tests for tina4_python.seeder
import pytest
from tina4_python.seeder import Fake, seed_table
from tina4_python.database import Database


@pytest.fixture
def fake():
    return Fake(seed=42)


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
        f1 = Fake(seed=123)
        f2 = Fake(seed=123)
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

        fake = Fake(seed=1)
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

        fake = Fake()
        seed_table(db, "items", 5, {"name": fake.word}, overrides={"active": 1})

        result = db.fetch("SELECT * FROM items WHERE active = 1", limit=100)
        assert result.count == 5
        db.close()
