"""Regression test — the migration runner must work on PostgreSQL.

`_create_v3_table` built its bookkeeping table (`tina4_migration`) with
SQLite-only DDL for every non-Firebird engine: `id INTEGER PRIMARY KEY
AUTOINCREMENT`. On PostgreSQL that throws `syntax error at or near
"AUTOINCREMENT"` from `_ensure_tracking_table`, so `Migration(db).migrate()`
died before any user migration ran -- migrations were entirely unusable on PG
(and MySQL/MSSQL). The fix makes the bookkeeping DDL engine-aware (SERIAL on PG)
mirroring ORM.create_table.

Boots a real PostgreSQL (env-configurable, default localhost:55432) and skips
when unreachable. The MigrationV3 unit tests only use in-memory SQLite, so the
PG path was never exercised -- this is the live-dependency guard for it.
"""
from __future__ import annotations

import os
import socket

import pytest

from tina4_python.database import Database
from tina4_python.migration import Migration

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USER", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASS", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(), reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)"
)


@pytest.fixture()
def pg():
    conn = Database(f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}", PG_USER, PG_PASS)
    for table in ("mig_pg_widget", "tina4_migration"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    yield conn
    for table in ("mig_pg_widget", "tina4_migration"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    conn.close()


def test_migration_runner_works_on_live_postgres(pg, tmp_path):
    """Constructing + running the migration runner on PG creates the engine-aware
    bookkeeping table (SERIAL, not AUTOINCREMENT), then applies a real migration."""
    (tmp_path / "000001_create_widget.sql").write_text(
        "CREATE TABLE mig_pg_widget (id SERIAL PRIMARY KEY, name VARCHAR(50));\n"
        "INSERT INTO mig_pg_widget (name) VALUES ('alpha');"
    )

    # This call used to raise "syntax error at or near AUTOINCREMENT".
    applied = Migration(pg, str(tmp_path)).migrate()

    assert applied == ["000001_create_widget.sql"]
    assert pg.table_exists("tina4_migration"), "bookkeeping table created on PG"
    assert pg.table_exists("mig_pg_widget"), "user migration ran on PG"

    row = pg.fetch_one("SELECT name FROM mig_pg_widget WHERE name = ?", ["alpha"])
    assert row is not None and row["name"] == "alpha"

    # The tracking row carries a SERIAL-assigned id (proves the PK type works,
    # not just that the DDL parsed).
    bk = pg.fetch_one("SELECT id, migration_id FROM tina4_migration ORDER BY id")
    assert bk is not None and int(bk["id"]) >= 1
    assert bk["migration_id"] == "000001_create_widget"


def test_rerun_is_idempotent_on_postgres(pg, tmp_path):
    """A second migrate() applies nothing new and does not re-create the table."""
    (tmp_path / "000001_create_widget.sql").write_text(
        "CREATE TABLE mig_pg_widget (id SERIAL PRIMARY KEY, name VARCHAR(50));"
    )
    assert Migration(pg, str(tmp_path)).migrate() == ["000001_create_widget.sql"]
    # Fresh runner, same folder + same live DB: nothing pending.
    assert Migration(pg, str(tmp_path)).migrate() == []
