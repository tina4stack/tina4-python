# Tests for tina4_python.database
import os
import pytest
from tina4_python.database import Database, DatabaseResult


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database for each test — autocommit OFF (default)."""
    db_path = tmp_path / "test.db"
    d = Database(f"sqlite:///{db_path}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    d.commit()  # Explicit commit — no autocommit by default
    yield d
    d.close()


@pytest.fixture
def db_autocommit(tmp_path):
    """Fresh SQLite database with autocommit ON."""
    db_path = tmp_path / "autocommit.db"
    d = Database(f"sqlite:///{db_path}")
    d.autocommit = True
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    yield d
    d.close()


class TestDatabaseResult:
    """Positive tests for DatabaseResult."""

    def test_iterate(self):
        r = DatabaseResult(records=[{"id": 1}, {"id": 2}], count=2)
        assert list(r) == [{"id": 1}, {"id": 2}]

    def test_len(self):
        r = DatabaseResult(records=[{"id": 1}], count=1)
        assert len(r) == 1

    def test_bool_success(self):
        r = DatabaseResult()
        assert bool(r) is True

    def test_bool_error(self):
        r = DatabaseResult(error="Something failed")
        assert bool(r) is False

    def test_to_paginate(self):
        r = DatabaseResult(records=[{"id": 1}], count=50)
        p = r.to_paginate(page=2, per_page=10)
        assert p["total"] == 50
        assert p["page"] == 2
        assert p["total_pages"] == 5
        assert p["has_next"] is True
        assert p["has_prev"] is True


class TestSQLiteAdapter:
    """Positive tests for SQLite database operations (autocommit OFF)."""

    def test_insert_and_fetch_one(self, db):
        db.insert("users", {"name": "Alice", "email": "alice@test.com"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Alice"])
        assert row is not None
        assert row["name"] == "Alice"
        assert row["email"] == "alice@test.com"

    def test_insert_returns_last_id(self, db):
        result = db.insert("users", {"name": "Bob"})
        assert result.last_id == 1
        result2 = db.insert("users", {"name": "Eve"})
        assert result2.last_id == 2
        db.commit()

    def test_fetch_pagination(self, db):
        for i in range(25):
            db.insert("users", {"name": f"User{i}"})
        db.commit()
        result = db.fetch("SELECT * FROM users", limit=10, skip=0)
        assert len(result.records) == 10
        assert result.count == 25

    def test_fetch_page_2(self, db):
        for i in range(25):
            db.insert("users", {"name": f"User{i}"})
        db.commit()
        result = db.fetch("SELECT * FROM users", limit=10, skip=10)
        assert len(result.records) == 10
        assert result.records[0]["name"] == "User10"

    def test_update(self, db):
        db.insert("users", {"name": "Alice"})
        db.commit()
        db.update("users", {"name": "Alice Updated"}, "name = ?", ["Alice"])
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE id = ?", [1])
        assert row["name"] == "Alice Updated"

    def test_delete(self, db):
        db.insert("users", {"name": "ToDelete"})
        db.commit()
        db.delete("users", "name = ?", ["ToDelete"])
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["ToDelete"])
        assert row is None

    def test_table_exists(self, db):
        assert db.table_exists("users") is True

    def test_get_tables(self, db):
        tables = db.get_tables()
        assert "users" in tables

    def test_get_columns(self, db):
        cols = db.get_columns("users")
        names = [c["name"] for c in cols]
        assert "id" in names
        assert "name" in names
        assert "email" in names

    def test_transaction_commit(self, db):
        db.start_transaction()
        db.insert("users", {"name": "Committed"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Committed"])
        assert row is not None

    def test_transaction_rollback(self, db):
        db.insert("users", {"name": "Before"})
        db.commit()
        db.start_transaction()
        db.insert("users", {"name": "RolledBack"})
        db.rollback()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["RolledBack"])
        assert row is None
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Before"])
        assert row is not None

    def test_database_type(self, db):
        assert db.get_database_type() == "sqlite"

    def test_no_autocommit_by_default(self, db):
        """Without autocommit, uncommitted writes are lost on close."""
        assert db.autocommit is False
        db.insert("users", {"name": "Uncommitted"})
        # Don't commit — data should be visible in same connection...
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Uncommitted"])
        assert row is not None  # visible in same transaction
        # ...but the point is: no silent auto-commit happened

    def test_explicit_commit_persists(self, db):
        """Explicit commit() makes data durable."""
        db.insert("users", {"name": "Persisted"})
        db.commit()
        row = db.fetch_one("SELECT * FROM users WHERE name = ?", ["Persisted"])
        assert row is not None


class TestAutocommitEnabled:
    """Tests with autocommit ON (via programmatic toggle)."""

    def test_autocommit_flag(self, db_autocommit):
        assert db_autocommit.autocommit is True

    def test_autocommit_persists_without_explicit_commit(self, db_autocommit):
        db_autocommit.insert("users", {"name": "AutoCommitted"})
        # No explicit commit() call
        row = db_autocommit.fetch_one("SELECT * FROM users WHERE name = ?", ["AutoCommitted"])
        assert row is not None

    def test_autocommit_env_var(self, tmp_path):
        """TINA4_AUTOCOMMIT=true enables autocommit via .env."""
        os.environ["TINA4_AUTOCOMMIT"] = "true"
        try:
            db_path = tmp_path / "env_test.db"
            d = Database(f"sqlite:///{db_path}")
            assert d.autocommit is True
            d.close()
        finally:
            del os.environ["TINA4_AUTOCOMMIT"]


class TestSQLiteAdapterNegative:
    """Negative tests for SQLite database operations."""

    def test_table_not_exists(self, db):
        assert db.table_exists("nonexistent") is False

    def test_fetch_one_no_results(self, db):
        row = db.fetch_one("SELECT * FROM users WHERE id = ?", [9999])
        assert row is None

    def test_fetch_empty_table(self, db):
        result = db.fetch("SELECT * FROM users")
        assert result.count == 0
        assert result.records == []

    def test_invalid_sql(self, db):
        with pytest.raises(Exception):
            db.execute("INVALID SQL STATEMENT")


class TestDatabaseURL:
    """Test DATABASE_URL parsing."""

    def test_sqlite_url(self, tmp_path):
        db_path = tmp_path / "url_test.db"
        db = Database(f"sqlite:///{db_path}")
        db.execute("CREATE TABLE t (id INTEGER)")
        assert db.table_exists("t")
        db.close()

    def test_invalid_driver(self):
        with pytest.raises(ValueError, match="Unknown database driver"):
            Database("fakedb://localhost/test")
