# Regression suite for tina4-python's v2 -> v3 tina4_migration auto-upgrade.
#
# Ports the PHP Issue 115 fix shipped in tina4-php 3.12.12 to Python.
# Same intent, adapted to the Python v2/v3 column shapes.
#
# Python v2 tracked migrations with `description` as the identifier and had no
# `migration_name`, `batch`, or `executed_at` columns. Python v3 added those.
# When a project upgrades from v2 to v3, the existing tina4_migration table
# must be upgraded in place; already-applied migrations must not re-run.
#
# These ten tests pin the contract.
import pytest
from pathlib import Path
from tina4_python.database import Database
from tina4_python.migration import Migration


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "v2up.db"
    d = Database(f"sqlite:///{db_path}")
    yield d
    d.close()


@pytest.fixture
def mig_dir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def _create_v2_table(db):
    """Recreate a Python-v2-shaped tina4_migration table.

    v2 had `description` as the identifier and no migration_name/batch/executed_at
    columns. `passed` was already present.
    """
    db.execute(
        """
        CREATE TABLE tina4_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            content BLOB,
            passed INTEGER DEFAULT 0
        )
        """
    )
    db.commit()


def _insert_v2_row(db, description, passed=1):
    db.execute(
        "INSERT INTO tina4_migration (description, content, passed) VALUES (?, ?, ?)",
        [description, b"", passed],
    )
    db.commit()


def _column_names(db):
    return [c["name"].lower() for c in db.get_columns("tina4_migration")]


# ── 1. v2 schema detected and upgraded ──────────────────────────────

def test_v2_schema_detected_and_upgraded(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "000001_create_users")

    Migration(db, str(mig_dir))

    cols = _column_names(db)
    assert "migration_name" in cols, "v3 migration_name column must be added"
    assert "batch" in cols, "v3 batch column must be added"
    assert "executed_at" in cols, "v3 executed_at column must be added"


# ── 2. Legacy v2 row matched to a file on disk ───────────────────────

def test_v2_row_matched_to_file_on_disk(db, mig_dir):
    _create_v2_table(db)
    # v2 stored the bare description (no prefix)
    _insert_v2_row(db, "create_users")

    # The real file on disk has a sequence prefix
    (mig_dir / "000001_create_users.sql").write_text("SELECT 1;")

    Migration(db, str(mig_dir))

    rows = db.fetch("SELECT migration_name FROM tina4_migration", limit=10).records
    ids = [r["migration_name"] for r in rows]
    assert "000001_create_users" in ids, (
        "Backfill must match the v2 description to the matching file's stem"
    )


# ── 3. No file match → fallback keeps the v2 description ─────────────

def test_v2_row_without_matching_file_falls_back_to_description(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "orphan_no_file_anywhere")

    Migration(db, str(mig_dir))

    rows = db.fetch("SELECT migration_name FROM tina4_migration", limit=10).records
    ids = [r["migration_name"] for r in rows]
    assert ids, "backfilled rows must have a migration_name"
    assert "orphan_no_file_anywhere" in ids[0], (
        "Fallback must keep the v2 description as the v3 identifier"
    )


# ── 4. Already-applied v2 migration does NOT re-run after upgrade ───

def test_applied_v2_migration_does_not_rerun_after_upgrade(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "create_users")

    # The file exists on disk and v2 already applied it
    (mig_dir / "000001_create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);"
    )
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db.commit()

    m = Migration(db, str(mig_dir))
    ran = m.migrate()

    assert ran == [], (
        "Already-applied v2 migration must NOT re-run after the upgrade"
    )


# ── 5. v3 schema left untouched ──────────────────────────────────────

def test_v3_schema_untouched(db, mig_dir):
    Migration(db, str(mig_dir))  # initialise as v3
    # Insert a v3-shaped row directly
    db.execute(
        "INSERT INTO tina4_migration (migration_name, description, batch, executed_at, passed) "
        "VALUES (?, ?, ?, ?, 1)",
        ["x", "x", 1, "now"],
    )
    db.commit()

    # Second construction must not corrupt the v3 data
    Migration(db, str(mig_dir))

    rows = db.fetch("SELECT migration_name FROM tina4_migration", limit=10).records
    assert len(rows) == 1
    assert rows[0]["migration_name"] == "x"


# ── 6. Empty v2 table upgrades cleanly ───────────────────────────────

def test_empty_v2_table_upgrades_cleanly(db, mig_dir):
    _create_v2_table(db)
    # No rows inserted

    Migration(db, str(mig_dir))

    cols = _column_names(db)
    assert "migration_name" in cols
    assert "batch" in cols
    assert "executed_at" in cols

    rows = db.fetch("SELECT * FROM tina4_migration", limit=10).records
    assert rows == []


# ── 7. Multiple v2 rows backfilled ───────────────────────────────────

def test_multiple_v2_rows_backfilled(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "create_users")
    _insert_v2_row(db, "create_orders")
    _insert_v2_row(db, "add_index")

    (mig_dir / "000001_create_users.sql").write_text("SELECT 1;")
    (mig_dir / "000002_create_orders.sql").write_text("SELECT 1;")

    Migration(db, str(mig_dir))

    rows = db.fetch("SELECT migration_name FROM tina4_migration", limit=10).records
    assert len(rows) == 3, "All v2 rows must be backfilled"

    ids = {r["migration_name"] for r in rows}
    # Two have files on disk, third falls back to its description
    assert "000001_create_users" in ids
    assert "000002_create_orders" in ids
    assert "add_index" in ids


# ── 8. v2 row with passed=0 also backfilled ──────────────────────────

def test_failed_v2_entries_also_backfilled(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "create_users", passed=1)
    _insert_v2_row(db, "create_orders", passed=0)

    Migration(db, str(mig_dir))

    rows = db.fetch("SELECT migration_name, passed FROM tina4_migration", limit=10).records
    assert len(rows) == 2, "Both passed=1 and passed=0 rows must be backfilled"
    for r in rows:
        assert r["migration_name"], "Every row gets a non-empty migration_name"


# ── 9. status() lists backfilled legacy migrations ───────────────────

def test_status_lists_backfilled_legacy_migrations(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "create_users")

    (mig_dir / "000001_create_users.sql").write_text("SELECT 1;")

    m = Migration(db, str(mig_dir))
    status = m.status()

    completed_ids = [c["migration_name"] for c in status["completed"]]
    assert "000001_create_users" in completed_ids, (
        "status()['completed'] must include the backfilled legacy migration"
    )
    assert status["pending"] == [], (
        "No pending — the legacy row was matched to the only file"
    )


# ── 10. New migrations after upgrade run normally ────────────────────

def test_new_migrations_after_upgrade_run_normally(db, mig_dir):
    _create_v2_table(db)
    _insert_v2_row(db, "create_users")
    (mig_dir / "000001_create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);"
    )
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db.commit()

    m = Migration(db, str(mig_dir))

    # New migration added after the upgrade
    (mig_dir / "20260101000000_create_orders.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY);"
    )

    ran = m.migrate()

    assert ran == ["20260101000000_create_orders.sql"], (
        "Only the new migration runs — the legacy one was matched and skipped"
    )
    assert db.table_exists("orders")


# ── old-v3 (migration_id) table renames to migration_name, no re-run ─

def test_old_v3_migration_id_column_renamed_to_migration_name(db, mig_dir):
    """A table created by v3 <= 3.13.54 used `migration_id` as the name column.
    The 3.13.55 canonical name is `migration_name`. The in-place upgrade must add
    migration_name and copy the values, so already-applied migrations are still
    seen as applied (not re-run)."""
    db.execute(
        """
        CREATE TABLE tina4_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id VARCHAR(500) NOT NULL UNIQUE,
            description VARCHAR(500),
            batch INTEGER NOT NULL DEFAULT 1,
            executed_at VARCHAR(50) NOT NULL,
            passed INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    db.execute(
        "INSERT INTO tina4_migration (migration_id, description, batch, executed_at, passed) "
        "VALUES (?, ?, 1, 'legacy', 1)",
        ["000001_create_users", ""],   # v3 stores the file STEM (no .sql)
    )
    db.commit()
    (mig_dir / "000001_create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);"
    )
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db.commit()

    m = Migration(db, str(mig_dir))

    cols = _column_names(db)
    assert "migration_name" in cols, "old-v3 table must gain the migration_name column"
    rows = db.fetch("SELECT migration_name FROM tina4_migration", limit=10).records
    assert rows[0]["migration_name"] == "000001_create_users", (
        "migration_name must be copied from the old migration_id column"
    )

    ran = m.migrate()
    assert ran == [], "an already-applied migration must NOT re-run after the rename upgrade"


# ── issue #93: a PENDING migration must APPLY on a legacy (migration_id) table ─
#
# The test above only proves the READ side: it asserts an already-applied
# migration does NOT re-run, so _record_applied() is never called and the
# bookkeeping INSERT is never exercised against the legacy shape. That blind
# spot let #93 ship: `migration_id` is NOT NULL on a v3 <= 3.13.54 table and the
# insert never wrote it, so EVERY new migration died on a not-null violation and
# no further migration could ever apply to that database. Fresh tables have no
# such column, which is why CI never saw it. These pin the WRITE side.


def _create_old_v3_table(db, with_migration_name=False):
    """Recreate the tina4_migration table exactly as v3 <= 3.13.54 created it.

    `migration_id` is NOT NULL UNIQUE there. With with_migration_name=True this
    is the post-rename-compat shape (both columns, NOT NULL still on the old
    one) - a database that has already booted a >= 3.13.55 framework once.
    """
    extra = ", migration_name VARCHAR(500)" if with_migration_name else ""
    db.execute(
        f"""
        CREATE TABLE tina4_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id VARCHAR(500) NOT NULL UNIQUE,
            description VARCHAR(500),
            batch INTEGER NOT NULL DEFAULT 1,
            executed_at VARCHAR(50) NOT NULL,
            passed INTEGER NOT NULL DEFAULT 1{extra}
        )
        """
    )
    db.commit()


@pytest.mark.parametrize("with_migration_name", [False, True], ids=["old_v3", "old_v3_compat"])
def test_issue_93_pending_migration_applies_on_legacy_migration_id_table(db, mig_dir, with_migration_name):
    """A pending migration must apply on a table created by v3 <= 3.13.54.

    Both legacy variants must work: one the new runner has never touched, and
    one that already ran the rename compat path (both columns present, the old
    one still NOT NULL). The fix must not live in the rename branch - that fires
    once and would never reach the second case.
    """
    _create_old_v3_table(db, with_migration_name)
    (mig_dir / "000001_smoke.sql").write_text("CREATE TABLE smoke_check (id INTEGER);")

    ran = Migration(db, str(mig_dir)).migrate()

    assert ran == ["000001_smoke.sql"], "the pending migration must apply, not die on migration_id NOT NULL"
    assert db.table_exists("smoke_check"), "the migration's own DDL must have run"
    row = db.fetch_one("SELECT migration_name, migration_id, passed FROM tina4_migration")
    assert row["migration_name"] == "000001_smoke"
    assert row["passed"] == 1
    assert row["migration_id"] == "000001_smoke", (
        "the legacy NOT NULL column must be populated, mirroring migration_name"
    )


def test_issue_93_legacy_table_migration_reruns_without_unique_collision(db, mig_dir):
    """Re-recording the same migration must replace its row, not collide.

    `migration_id` is UNIQUE on the legacy table, so writing it back is only safe
    because the delete-before-insert removes this migration's own row first.
    """
    _create_old_v3_table(db)
    (mig_dir / "000001_smoke.sql").write_text("CREATE TABLE smoke_check (id INTEGER);")
    m = Migration(db, str(mig_dir))
    m.migrate()

    # Force a re-record of the same name — this is what would trip the UNIQUE.
    m.record_migration("000001_smoke", 2, passed=0)
    m.record_migration("000001_smoke", 3, passed=1)

    rows = db.fetch("SELECT migration_name, migration_id, batch FROM tina4_migration", limit=10).records
    assert len(rows) == 1, "at most one row per migration_name — latest state wins"
    assert rows[0]["batch"] == 3
    assert rows[0]["migration_id"] == "000001_smoke"


def test_issue_93_fresh_v3_table_still_inserts_only_canonical_columns(db, mig_dir):
    """Control: a fresh table has no migration_id, and must not gain one.

    Guards the fix against over-reach — the column list is built from the table's
    real columns, so a canonical table inserts only the six canonical ones.
    """
    (mig_dir / "000001_smoke.sql").write_text("CREATE TABLE smoke_check (id INTEGER);")

    ran = Migration(db, str(mig_dir)).migrate()

    assert ran == ["000001_smoke.sql"]
    cols = _column_names(db)
    assert "migration_id" not in cols, "a fresh v3 table must never grow the legacy column"
    assert db.fetch_one("SELECT migration_name FROM tina4_migration")["migration_name"] == "000001_smoke"
