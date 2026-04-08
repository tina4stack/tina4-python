"""Tests for the Migration class (OOP wrapper around migration runner functions)."""
import os
import tempfile
import pytest
from tina4_python.database import Database
from tina4_python.migration import Migration


@pytest.fixture()
def db_and_dir():
    """Provide a fresh SQLite DB and temporary migrations directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        migrations_dir = os.path.join(tmpdir, "migrations")
        os.makedirs(migrations_dir)
        db = Database(f"sqlite:///{tmpdir}/test.db")
        yield db, migrations_dir
        db.close()


def write_migration(migrations_dir: str, name: str, up_sql: str, down_sql: str = ""):
    """Helper to write .sql and .down.sql files."""
    up_path = os.path.join(migrations_dir, name)
    down_path = os.path.join(migrations_dir, name.replace(".sql", ".down.sql"))
    with open(up_path, "w") as f:
        f.write(up_sql)
    with open(down_path, "w") as f:
        f.write(down_sql or f"-- rollback {name}\n")
    return up_path


class TestMigrationClass:

    def test_instantiation(self, db_and_dir):
        db, mdir = db_and_dir
        m = Migration(db, mdir)
        assert m is not None

    def test_migrate_empty_directory(self, db_and_dir):
        db, mdir = db_and_dir
        m = Migration(db, mdir)
        result = m.migrate()
        assert result == []

    def test_migrate_applies_pending(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        applied = m.migrate()
        assert "000001_create_users.sql" in applied

    def test_migrate_skips_already_applied(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        m.migrate()
        # Second run — nothing new
        applied = m.migrate()
        assert applied == []

    def test_rollback_last_batch(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        m.migrate()
        rolled = m.rollback()
        assert len(rolled) >= 1

    def test_rollback_steps(self, db_and_dir):
        db, mdir = db_and_dir
        # Two separate batches
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        m.migrate()

        write_migration(mdir, "000002_add_email.sql",
                        "ALTER TABLE users ADD COLUMN email TEXT;",
                        "-- no-op")
        m.migrate()

        # Roll back both batches
        rolled = m.rollback(steps=2)
        assert len(rolled) >= 1

    def test_rollback_empty_returns_empty(self, db_and_dir):
        db, mdir = db_and_dir
        m = Migration(db, mdir)
        rolled = m.rollback()
        assert rolled == []

    def test_status_structure(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        m.migrate()

        s = m.status()
        assert "completed" in s
        assert "pending" in s
        assert len(s["completed"]) == 1
        assert len(s["pending"]) == 0

    def test_get_applied_returns_list(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        m.migrate()
        applied = m.get_applied()
        assert isinstance(applied, list)
        assert len(applied) == 1

    def test_get_pending_returns_list(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
                        "DROP TABLE users;")
        m = Migration(db, mdir)
        pending = m.get_pending()
        assert isinstance(pending, list)
        assert len(pending) == 1

    def test_get_files_returns_sorted_sql_files(self, db_and_dir):
        db, mdir = db_and_dir
        write_migration(mdir, "000001_create_users.sql",
                        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        write_migration(mdir, "000002_add_email.sql",
                        "ALTER TABLE users ADD COLUMN email TEXT;")
        m = Migration(db, mdir)
        files = m.get_files()
        assert "000001_create_users.sql" in files
        assert "000002_add_email.sql" in files
        # .down.sql files must NOT appear
        for f in files:
            assert not f.endswith(".down.sql")
        # Sorted order
        assert files == sorted(files)

    def test_create_scaffolds_files(self, db_and_dir):
        db, mdir = db_and_dir
        m = Migration(db, mdir)
        up_path = m.create("add products table")
        assert os.path.exists(up_path)
        # .down.sql must also exist
        down_path = up_path.replace(".sql", ".down.sql")
        assert os.path.exists(down_path)
        # Filename must contain description
        assert "add_products_table" in os.path.basename(up_path)

    def test_create_then_migrate(self, db_and_dir):
        db, mdir = db_and_dir
        m = Migration(db, mdir)
        up_path = m.create("create test table")
        # Fill the up migration with actual SQL
        with open(up_path, "w") as f:
            f.write("CREATE TABLE test_table (id INTEGER PRIMARY KEY);")
        applied = m.migrate()
        assert len(applied) == 1

    def test_default_migrations_dir(self, db_and_dir):
        db, _ = db_and_dir
        # Should instantiate without error even if dir doesn't exist
        m = Migration(db)
        assert m is not None
        result = m.migrate()  # nonexistent dir returns empty
        assert result == []
