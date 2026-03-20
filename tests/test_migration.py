# Tests for tina4_python.migration
import pytest
from pathlib import Path
from tina4_python.database import Database
from tina4_python.migration import migrate, create_migration, rollback


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database."""
    db_path = tmp_path / "migrate_test.db"
    d = Database(f"sqlite:///{db_path}")
    yield d
    d.close()


@pytest.fixture
def mig_dir(tmp_path):
    """Empty migrations directory."""
    d = tmp_path / "migrations"
    d.mkdir()
    return d


# ── migrate() Tests ────────────────────────────────────────────


class TestMigrate:
    """Positive tests for running migrations."""

    def test_run_single_migration(self, db, mig_dir):
        (mig_dir / "000001_create_items.sql").write_text(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_create_items.sql"]
        assert db.table_exists("items")

    def test_run_multiple_in_order(self, db, mig_dir):
        (mig_dir / "000001_create_a.sql").write_text("CREATE TABLE a (id INTEGER);")
        (mig_dir / "000002_create_b.sql").write_text("CREATE TABLE b (id INTEGER);")
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_create_a.sql", "000002_create_b.sql"]
        assert db.table_exists("a")
        assert db.table_exists("b")

    def test_skip_already_executed(self, db, mig_dir):
        (mig_dir / "000001_create_x.sql").write_text("CREATE TABLE x (id INTEGER);")
        migrate(db, str(mig_dir))

        (mig_dir / "000002_create_y.sql").write_text("CREATE TABLE y (id INTEGER);")
        ran = migrate(db, str(mig_dir))
        assert ran == ["000002_create_y.sql"]

    def test_multi_statement_migration(self, db, mig_dir):
        (mig_dir / "000001_multi.sql").write_text(
            "CREATE TABLE t1 (id INTEGER);\n"
            "CREATE TABLE t2 (id INTEGER);"
        )
        ran = migrate(db, str(mig_dir))
        assert len(ran) == 1
        assert db.table_exists("t1")
        assert db.table_exists("t2")

    def test_empty_folder(self, db, mig_dir):
        ran = migrate(db, str(mig_dir))
        assert ran == []

    def test_missing_folder(self, db, tmp_path):
        ran = migrate(db, str(tmp_path / "nonexistent"))
        assert ran == []

    def test_tracking_table_created(self, db, mig_dir):
        (mig_dir / "000001_test.sql").write_text("CREATE TABLE test (id INTEGER);")
        migrate(db, str(mig_dir))
        assert db.table_exists("tina4_migration")

    def test_batch_numbers(self, db, mig_dir):
        (mig_dir / "000001_first.sql").write_text("CREATE TABLE first (id INTEGER);")
        migrate(db, str(mig_dir))

        (mig_dir / "000002_second.sql").write_text("CREATE TABLE second (id INTEGER);")
        migrate(db, str(mig_dir))

        row1 = db.fetch_one("SELECT batch FROM tina4_migration WHERE migration_id = ?", ["000001_first"])
        row2 = db.fetch_one("SELECT batch FROM tina4_migration WHERE migration_id = ?", ["000002_second"])
        assert row1["batch"] == 1
        assert row2["batch"] == 2


    def test_sql_with_line_comments(self, db, mig_dir):
        (mig_dir / "000001_comments.sql").write_text(
            "-- This is a comment\n"
            "CREATE TABLE commented (id INTEGER);\n"
            "-- Another comment\n"
            "INSERT INTO commented (id) VALUES (1); -- inline comment\n"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_comments.sql"]
        assert db.table_exists("commented")
        row = db.fetch_one("SELECT id FROM commented WHERE id = ?", [1])
        assert row is not None

    def test_sql_with_block_comments(self, db, mig_dir):
        (mig_dir / "000001_block.sql").write_text(
            "/* Multi-line\n"
            "   block comment */\n"
            "CREATE TABLE blocked (id INTEGER);\n"
            "/* inline block */ INSERT INTO blocked (id) VALUES (42);\n"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_block.sql"]
        assert db.table_exists("blocked")

    def test_sql_comments_only(self, db, mig_dir):
        (mig_dir / "000001_empty.sql").write_text(
            "-- Just comments\n"
            "-- Nothing to execute\n"
            "/* Also nothing */\n"
        )
        ran = migrate(db, str(mig_dir))
        assert ran == ["000001_empty.sql"]


class TestMigrateNegative:
    """Negative tests for migrations."""

    def test_invalid_sql_rolls_back(self, db, mig_dir):
        (mig_dir / "000001_bad.sql").write_text("THIS IS NOT SQL;")
        with pytest.raises(RuntimeError, match="Migration failed"):
            migrate(db, str(mig_dir))
        # Tracking table should exist but no passed migration
        assert db.table_exists("tina4_migration")
        row = db.fetch_one("SELECT * FROM tina4_migration WHERE migration_id = ?", ["000001_bad"])
        assert row is None

    def test_partial_failure_rolls_back(self, db, mig_dir):
        (mig_dir / "000001_partial.sql").write_text(
            "CREATE TABLE good (id INTEGER);\n"
            "THIS WILL FAIL;"
        )
        with pytest.raises(RuntimeError):
            migrate(db, str(mig_dir))
        # The good table should NOT exist (rolled back)
        assert not db.table_exists("good")


# ── rollback() Tests ───────────────────────────────────────────


class TestRollback:
    """Tests for migration rollback."""

    def test_rollback_last_batch(self, db, mig_dir):
        (mig_dir / "000001_create_r.sql").write_text("CREATE TABLE r (id INTEGER);")
        (mig_dir / "000001_create_r.down.sql").write_text("DROP TABLE r;")
        migrate(db, str(mig_dir))
        assert db.table_exists("r")

        rolled = rollback(db, str(mig_dir))
        assert len(rolled) == 1
        assert not db.table_exists("r")

    def test_rollback_only_last_batch(self, db, mig_dir):
        # Batch 1
        (mig_dir / "000001_a.sql").write_text("CREATE TABLE a (id INTEGER);")
        (mig_dir / "000001_a.down.sql").write_text("DROP TABLE a;")
        migrate(db, str(mig_dir))

        # Batch 2
        (mig_dir / "000002_b.sql").write_text("CREATE TABLE b (id INTEGER);")
        (mig_dir / "000002_b.down.sql").write_text("DROP TABLE b;")
        migrate(db, str(mig_dir))

        rolled = rollback(db, str(mig_dir))
        assert len(rolled) == 1
        assert db.table_exists("a")  # Batch 1 untouched
        assert not db.table_exists("b")  # Batch 2 rolled back

    def test_rollback_nothing_to_rollback(self, db, mig_dir):
        rolled = rollback(db, str(mig_dir))
        assert rolled == []


class TestRollbackNegative:
    """Negative tests for rollback."""

    def test_missing_down_file(self, db, mig_dir):
        (mig_dir / "000001_no_down.sql").write_text("CREATE TABLE nd (id INTEGER);")
        migrate(db, str(mig_dir))

        with pytest.raises(RuntimeError, match="no .down.sql"):
            rollback(db, str(mig_dir))


# ── create_migration() Tests ──────────────────────────────────


class TestCreateMigration:
    """Tests for creating migration files."""

    def test_create_first(self, mig_dir):
        path = create_migration("create users table", str(mig_dir))
        assert "000001_create_users_table.sql" in path
        assert Path(path).exists()
        # Down file also created
        down = Path(path).with_suffix("").with_suffix(".down.sql")
        assert down.exists()

    def test_sequential_numbering(self, mig_dir):
        create_migration("first", str(mig_dir))
        path = create_migration("second", str(mig_dir))
        assert "000002_second.sql" in path

    def test_clean_description(self, mig_dir):
        path = create_migration("Add Email & Phone Fields!", str(mig_dir))
        assert "add_email_phone_fields" in path

    def test_creates_folder(self, tmp_path):
        new_dir = tmp_path / "new_migrations"
        path = create_migration("test", str(new_dir))
        assert new_dir.is_dir()
        assert Path(path).exists()
