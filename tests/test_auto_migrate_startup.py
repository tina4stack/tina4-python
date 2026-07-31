"""Behavioural tests for startup auto-migration (v3.13.39).

`_auto_migrate_on_startup()` applies pending migrations on boot when a
`migrations/` folder exists, is gated by TINA4_AUTO_MIGRATE (default on), and is
NON-BREAKING: a failing migration is logged and the service still starts (the
helper must never raise). The explicit `tina4 migrate` CLI stays fail-fast and is
unaffected — covered by test_migration.py.

These assert REAL database STATE against a real SQLite db (and, when reachable, a
real PostgreSQL server) — never a mock:
  - flag ON + a real migration present  → the table IS created AND a tina4_migration
    row is recorded.
  - flag OFF                            → NOTHING is created (no table, no row).
  - no migrations/ folder (or empty)    → silent no-op: the db is never even touched.
  - a good migration THEN a broken one  → the good one IS applied + recorded, the
    broken one is NOT, and the helper swallows the failure (no raise).
"""
import os
import socket

import pytest

from tina4_python.core.server import _auto_migrate_on_startup
from tina4_python.database import Database


@pytest.fixture
def project(tmp_path):
    """A temp project: cd in, point TINA4_DATABASE_URL at a temp sqlite, restore after."""
    keys = ("TINA4_DATABASE_URL", "TINA4_AUTO_MIGRATE")
    saved = {k: os.environ.get(k) for k in keys}
    old_cwd = os.getcwd()
    db_path = tmp_path / "app.db"
    os.environ["TINA4_DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ.pop("TINA4_AUTO_MIGRATE", None)
    os.chdir(tmp_path)
    try:
        yield tmp_path, db_path
    finally:
        os.chdir(old_cwd)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _migrations(tmp_path, *files):
    d = tmp_path / "migrations"
    d.mkdir(exist_ok=True)
    for name, sql in files:
        (d / name).write_text(sql, encoding="utf-8")
    return d


def _table_exists(db_path, table):
    db = Database(f"sqlite:///{db_path}")
    try:
        return db.table_exists(table)
    finally:
        db.close()


def _migration_names(db_path):
    """Return the list of recorded migration ids in tina4_migration (empty if none)."""
    db = Database(f"sqlite:///{db_path}")
    try:
        if not db.table_exists("tina4_migration"):
            return []
        rows = db.fetch("SELECT migration_name FROM tina4_migration WHERE passed = 1").records
        return [r["migration_name"] for r in rows]
    finally:
        db.close()


def test_applies_pending_on_startup(project):
    """Flag ON + a real migration → the table IS created AND the run is recorded."""
    tmp_path, db_path = project
    _migrations(tmp_path, ("000001_items.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY);"))

    _auto_migrate_on_startup()

    assert _table_exists(db_path, "items"), "pending migration should be applied on startup"
    # The schema change is not enough — the run must be RECORDED so a re-run skips it.
    assert _migration_names(db_path) == ["000001_items"], (
        "the applied migration must be recorded in tina4_migration"
    )


def test_disabled_by_env(project):
    """Flag OFF → NOTHING is created: no user table, no bookkeeping table, no row."""
    tmp_path, db_path = project
    os.environ["TINA4_AUTO_MIGRATE"] = "false"
    _migrations(tmp_path, ("000001_items.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY);"))

    _auto_migrate_on_startup()

    assert not _table_exists(db_path, "items"), "TINA4_AUTO_MIGRATE=false must skip the migration"
    # Disabled means the runner never ran at all — no bookkeeping table, no row.
    assert not _table_exists(db_path, "tina4_migration"), (
        "disabled startup migration must not even create the tracking table"
    )
    assert _migration_names(db_path) == []


def test_no_folder_is_noop(project):
    """No migrations/ dir at all → silent no-op: the database is never touched."""
    tmp_path, db_path = project

    _auto_migrate_on_startup()  # must not raise

    # The helper returns before opening any connection, so the sqlite file is
    # never even created — the strongest possible "did nothing" assertion.
    assert not db_path.exists(), "no migrations folder must not create/touch the database"


def test_empty_folder_is_noop(project):
    """A migrations/ dir with no .sql files → still a silent no-op (no db touched)."""
    tmp_path, db_path = project
    (tmp_path / "migrations").mkdir()  # exists but empty

    _auto_migrate_on_startup()  # must not raise

    assert not db_path.exists(), "an empty migrations folder must not create/touch the database"


def test_failure_is_non_breaking(project):
    """A good migration THEN a broken one — the broken one must NOT take the app down,
    and must NOT corrupt the good migration's committed state.

    Real-state contract:
      - the helper SWALLOWS the failure (returns normally, service boots);
      - the GOOD migration IS applied AND recorded (committed in its own transaction);
      - the BROKEN migration is NOT applied and NOT recorded.
    """
    tmp_path, db_path = project
    _migrations(
        tmp_path,
        ("000001_ok.sql", "CREATE TABLE ok_tbl (id INTEGER PRIMARY KEY);"),
        ("000002_bad.sql", "CREATE TABLE bad_tbl (;;; not valid sql ((("),
    )

    # The contract: the helper swallows the failure (service still boots).
    _auto_migrate_on_startup()  # must NOT raise despite the bad migration

    # The good migration committed before the bad one failed — its table and its
    # bookkeeping row both survive (proves per-file transactional isolation).
    assert _table_exists(db_path, "ok_tbl"), "the good migration must stay applied"
    # The broken migration left no table and no record behind.
    assert not _table_exists(db_path, "bad_tbl"), "the broken migration must not partially apply"
    assert _migration_names(db_path) == ["000001_ok"], (
        "only the good migration is recorded; the failed one is never recorded as passed"
    )


# ── Live-PostgreSQL behavioural test ─────────────────────────────────────────
# The SQLite cases above prove the contract; this exercises the SAME startup path
# against a REAL PostgreSQL server (the engine-aware bookkeeping DDL + a real
# committed schema change), so the no-mock guarantee holds for a server engine too.
PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture
def pg_project(tmp_path):
    """Point the startup helper at a real PostgreSQL server and clean up the
    test tables before and after."""
    keys = (
        "TINA4_DATABASE_URL",
        "TINA4_DATABASE_USERNAME",
        "TINA4_DATABASE_PASSWORD",
        "TINA4_AUTO_MIGRATE",
    )
    saved = {k: os.environ.get(k) for k in keys}
    old_cwd = os.getcwd()

    def _admin():
        return Database(f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}", PG_USER, PG_PASS)

    def _drop():
        db = _admin()
        for t in ("astartup_pg_items", "tina4_migration"):
            db.execute(f"DROP TABLE IF EXISTS {t}")
            db.commit()
        db.close()

    _drop()
    os.environ["TINA4_DATABASE_URL"] = f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}"
    os.environ["TINA4_DATABASE_USERNAME"] = PG_USER
    os.environ["TINA4_DATABASE_PASSWORD"] = PG_PASS
    os.environ.pop("TINA4_AUTO_MIGRATE", None)
    os.chdir(tmp_path)
    try:
        yield tmp_path, _admin
    finally:
        os.chdir(old_cwd)
        _drop()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.skipif(
    not _pg_reachable(), reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)"
)
def test_applies_pending_on_startup_postgres(pg_project):
    """Flag ON + a real migration → table created + run recorded, on a live PG server."""
    tmp_path, admin = pg_project
    _migrations(
        tmp_path,
        (
            "000001_items.sql",
            "CREATE TABLE astartup_pg_items (id SERIAL PRIMARY KEY, name VARCHAR(20));",
        ),
    )

    _auto_migrate_on_startup()

    db = admin()
    try:
        assert db.table_exists("astartup_pg_items"), "migration applied on live PostgreSQL"
        rows = db.fetch(
            "SELECT migration_name FROM tina4_migration WHERE passed = 1"
        ).records
        assert [r["migration_name"] for r in rows] == ["000001_items"], (
            "the applied migration is recorded in tina4_migration on PG"
        )
    finally:
        db.close()


@pytest.mark.skipif(
    not _pg_reachable(), reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)"
)
def test_disabled_by_env_postgres(pg_project):
    """Flag OFF → NOTHING created on the live PG server (no user table, no tracking table)."""
    tmp_path, admin = pg_project
    os.environ["TINA4_AUTO_MIGRATE"] = "false"
    _migrations(
        tmp_path,
        (
            "000001_items.sql",
            "CREATE TABLE astartup_pg_items (id SERIAL PRIMARY KEY, name VARCHAR(20));",
        ),
    )

    _auto_migrate_on_startup()

    db = admin()
    try:
        assert not db.table_exists("astartup_pg_items"), "disabled flag must skip the PG migration"
        assert not db.table_exists("tina4_migration"), (
            "disabled startup migration must not create the tracking table on PG"
        )
    finally:
        db.close()
