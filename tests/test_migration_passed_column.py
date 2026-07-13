# Lock-in suite for the `passed` column semantics on the tina4_migration
# bookkeeping table (parity with tina4-php#129 / #172).
#
# Contract under test (verified against real SQLite — NO mocks):
#   * A fresh v3 tina4_migration table carries the canonical bookkeeping
#     columns, including `passed`.
#   * "Applied" == a row with `passed = 1`; the runner reads `WHERE passed = 1`.
#   * migrate() writes ONLY passed=1 rows. A failed file is rolled back and NO
#     row is written (it is never recorded as passed=0) and the run stops.
#   * The public Migration.record_migration(name, batch, passed=...) API CAN
#     write a passed=0 row. A passed=0 row is NOT counted as applied, so the
#     migration is reported pending — and re-running migrate() applies it
#     cleanly: the success path deletes any leftover row for the migration_name
#     before the passed=1 INSERT, so a stale passed=0 row (a prior failure or a
#     v2 carry-over) is superseded instead of colliding on the UNIQUE
#     migration_name.
#
# Each test drives the real Migration runner against a real temp SQLite
# database. Positive and negative cases are both exercised.
import pytest
from tina4_python.database import Database
from tina4_python.migration import Migration
from tina4_python.migration.runner import _get_executed


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path}/x.db")
    yield d
    d.close()


@pytest.fixture
def mig_dir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    return d


# ── 1. Fresh v3 table exposes the canonical bookkeeping columns ──────────

def test_fresh_v3_table_has_passed_column(db, mig_dir):
    # Constructing a Migration on a fresh DB creates the v3 tracking table.
    Migration(db, str(mig_dir))

    cols = {c["name"].lower() for c in db.get_columns("tina4_migration")}
    expected = {"id", "migration_name", "description", "batch", "executed_at", "passed"}
    assert expected <= cols, (
        f"fresh v3 tina4_migration is missing canonical columns: {expected - cols}"
    )
    # The load-bearing column for this suite.
    assert "passed" in cols, "the `passed` bookkeeping column must exist on a fresh v3 table"


# ── 2. An applied migration is recorded passed=1 and never re-runs ───────

def test_applied_migration_recorded_passed_1_and_not_rerun(db, mig_dir):
    name = "000001_create_widgets"
    (mig_dir / f"{name}.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT);"
    )
    m = Migration(db, str(mig_dir))

    # First run applies the migration.
    ran = m.migrate()
    assert ran == [f"{name}.sql"], f"the migration must apply on the first run: {ran}"
    assert db.table_exists("widgets"), "the migration's CREATE TABLE must have run"

    # It is recorded with passed = 1 (the only value migrate() ever writes).
    row = db.fetch_one(
        "SELECT passed FROM tina4_migration WHERE migration_name = ?", [name]
    )
    assert row is not None, "an applied migration must be recorded in tina4_migration"
    assert row["passed"] == 1, "an applied migration is recorded with passed = 1"

    # Second run: the passed=1 row means it is already applied — not re-run,
    # no double-apply, no error, and the created table survives untouched.
    ran_again = m.migrate()
    assert ran_again == [], f"an already-applied migration must NOT re-run: {ran_again}"
    assert db.table_exists("widgets"), "the created table survives a second migrate()"


# ── 3. A passed=0 row is not applied, and re-running supersedes it cleanly ─

def test_passed_zero_row_is_pending_then_reruns_cleanly(db, mig_dir):
    """passed=0 != applied, and a re-run applies the migration cleanly.

    'Applied' is read as ``WHERE passed = 1``, so a row written with passed=0
    (only reachable via the public ``record_migration(..., passed=0)`` API —
    ``migrate()`` itself never writes passed=0) is invisible to the applied
    set and the migration is reported pending. That is the positive proof that
    passed=0 is not counted as applied.

    Re-runnable lock-in (tina4-php#129 / #172): re-running ``migrate()`` while a
    leftover passed=0 row exists for the SAME name now APPLIES the migration.
    The success path deletes any existing row for the migration_name before the
    passed=1 INSERT, so the stale passed=0 row is superseded instead of
    colliding on the UNIQUE migration_name. Verified against real SQLite; the
    framework source is not modified by this test.
    """
    name = "000001_create_widgets"
    (mig_dir / f"{name}.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT);"
    )
    m = Migration(db, str(mig_dir))

    # A passed=0 tracking row for a migration whose file is on disk.
    m.record_migration(name, 1, passed=0)
    db.commit()

    # Positive: passed=0 is NOT applied -> absent from the applied set, pending.
    assert name not in _get_executed(db), "a passed=0 row must not count as executed"
    applied = {r["migration_name"] for r in m.get_applied()}
    pending = {r["migration_name"] for r in m.get_pending()}
    assert name not in applied, "a passed=0 migration must not appear as applied"
    assert name in pending, "a passed=0 migration must be reported pending (re-runnable)"

    # Re-runnable: migrate() over the leftover passed=0 row now applies the
    # migration cleanly — the CREATE TABLE runs and the run reports it ran.
    ran = m.migrate()
    assert ran == [f"{name}.sql"], f"a previously-failed migration must re-apply cleanly: {ran}"
    assert db.table_exists("widgets"), "the re-run must create the migration's table"

    # The stale passed=0 row is superseded: exactly one row remains for this
    # name, now passed=1.
    rows = db.fetch(
        "SELECT passed FROM tina4_migration WHERE migration_name = ?", [name], limit=10
    ).records
    assert [r["passed"] for r in rows] == [1], (
        "the leftover passed=0 row is superseded by a single passed=1 row"
    )

    # And it is now counted as applied.
    assert name in _get_executed(db), "the re-applied migration must count as executed"


# ── 4. v2 table with a passed=0 row upgrades; applied migration not re-run ─

def test_v2_table_with_passed0_row_upgrades_and_applied_not_rerun(db, mig_dir):
    # Build the Python v2 shape: `description`-keyed, no migration_name/batch/
    # executed_at columns. `passed` was already present in v2.
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

    # An APPLIED (passed=1) migration whose file exists on disk AND whose effect
    # (the users table) already exists — exactly the state after a real v2 apply.
    (mig_dir / "000001_create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY);"
    )
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db.commit()
    db.execute(
        "INSERT INTO tina4_migration (description, content, passed) VALUES (?, ?, 1)",
        ["create_users", b""],
    )
    # A second, failed (passed=0) legacy row with NO matching file on disk, so
    # its (acceptable) re-run is a no-op — there is nothing to apply and no error.
    db.execute(
        "INSERT INTO tina4_migration (description, content, passed) VALUES (?, ?, 0)",
        ["orphan_failed_no_file", b""],
    )
    db.commit()

    # Constructing Migration triggers the in-place v2 -> v3 upgrade.
    m = Migration(db, str(mig_dir))

    cols = {c["name"].lower() for c in db.get_columns("tina4_migration")}
    for col in ("migration_name", "batch", "executed_at"):
        assert col in cols, f"the v2 -> v3 upgrade must add the {col} column"

    # The already-applied migration must NOT re-run, and NO exception is raised.
    ran = m.migrate()
    assert "000001_create_users.sql" not in ran, (
        "the already-applied (passed=1, backfilled) migration must not re-run"
    )
    assert ran == [], f"nothing should re-run (orphan passed=0 row has no file): {ran}"

    # Positive: the backfilled passed=1 row is seen as applied after the upgrade.
    applied = {r["migration_name"] for r in m.get_applied()}
    assert "000001_create_users" in applied, (
        "the backfilled passed=1 legacy row is applied after the upgrade"
    )
    assert db.table_exists("users"), "the already-applied table stays in place"
