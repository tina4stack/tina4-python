"""Lock-in tests for startup auto-migration (v3.13.39).

`_auto_migrate_on_startup()` applies pending migrations on boot when a
`migrations/` folder exists, is gated by TINA4_AUTO_MIGRATE (default on), and is
NON-BREAKING: a failing migration is logged and the service still starts (the
helper must never raise). The explicit `tina4 migrate` CLI stays fail-fast and is
unaffected — covered by test_migration.py.
"""
import os
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


def test_applies_pending_on_startup(project):
    tmp_path, db_path = project
    _migrations(tmp_path, ("000001_items.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY);"))
    _auto_migrate_on_startup()
    assert _table_exists(db_path, "items"), "pending migration should be applied on startup"


def test_disabled_by_env(project):
    tmp_path, db_path = project
    os.environ["TINA4_AUTO_MIGRATE"] = "false"
    _migrations(tmp_path, ("000001_items.sql", "CREATE TABLE items (id INTEGER PRIMARY KEY);"))
    _auto_migrate_on_startup()
    assert not _table_exists(db_path, "items"), "TINA4_AUTO_MIGRATE=false must skip startup migration"


def test_no_folder_is_noop(project):
    # No migrations/ dir at all → silent no-op, never raises.
    _auto_migrate_on_startup()  # must not raise


def test_failure_is_non_breaking(project):
    tmp_path, db_path = project
    # A good migration THEN a broken one — the broken migration must NOT propagate.
    _migrations(
        tmp_path,
        ("000001_ok.sql", "CREATE TABLE ok_tbl (id INTEGER PRIMARY KEY);"),
        ("000002_bad.sql", "CREATE TABLE ;;; not valid sql ((("),
    )
    # The contract: the helper swallows the failure (service still boots).
    _auto_migrate_on_startup()  # must NOT raise despite the bad migration
