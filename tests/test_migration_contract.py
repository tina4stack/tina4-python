"""Shared migration contract -- feature 15 (OWNER-DECISIONS.md Batch 4,
feature doc 015-migrations.md, MIG-DEC-01/02/03).

Real engines only (SQLite, PostgreSQL, MySQL, MSSQL, Firebird 5) -- no mocks,
no fakes. The SAME case names are proven in all four frameworks; the shared
fixture is tina4-documentation/plan/v3/fixtures/migrations_contract.json.

MIG-DEC-01: `tina4 migrate:status` used to raise KeyError (`_migrate_status`
read `m['migration_id']` but `Migration.status()` keys its dicts
`migration_name`) the moment there was at least one completed or pending
migration -- untested until now. `migrate_status_prints_without_crashing`
drives the REAL CLI entry point (a subprocess running the installed
`tina4python migrate:status` console-script code path) against a real
migrated SQLite database and asserts the printed output.

MIG-DEC-02: rollback is fail-safe -- Python is the REFERENCE model the other
three frameworks were aligned to this release (a missing/failed `.down.sql`
RAISES rather than silently dropping the ledger row).
`failed_or_missing_down_does_not_drop_ledger` proves the row survives the
raise (the existing `test_missing_down_file` in test_migration.py only
asserted the raise itself, not the ledger's post-raise state).

MIG-DEC-03: `firebird_mssql_create_add_idempotency_real` proves the
CREATE TABLE (Firebird + MSSQL) and ALTER TABLE ADD (Firebird) idempotency
skips against REAL engines -- Python was never flagged as a mock violator
(its footgun-guard unit tests exercise a pure function via a tiny two-method
stand-in, not an end-to-end "against a live engine" claim), but this shared
fixture proves it for real for the first time, matching PHP's
MigrationFootgunsLiveEngineTest ("NO DOUBLES") as the model.

`ledger_row_commits_atomically_with_ddl` and
`midfile_failure_rolls_back_on_transactional_ddl` prove the crash-safety
design from opposite angles: the former shows the ledger write NEVER lands
out of step with the DDL loop (even on MySQL, whose DDL auto-commits and so
CANNOT be rolled back -- the ledger row still never appears for a file that
failed); the latter shows PostgreSQL's transactional DDL rolls back an
EARLIER already-executed statement in the same file when a LATER one fails
(no partial apply at all, not even the DDL).

Env contract (identical to the write-path/pgprovider/mysqlprovider/
mssqlprovider/firebirdprovider runners): TINA4_TEST_PG_HOST/_PORT/_USERNAME/
_PASSWORD/_DB (default 127.0.0.1:55432, tina4/tina4); TINA4_TEST_MYSQL_HOST/
_PORT/_USERNAME/_PASSWORD/_DB (default 127.0.0.1:3306, tina4/tina4);
TINA4_TEST_MSSQL_HOST/_PORT/_USERNAME/_PASSWORD/_DB (default 127.0.0.1:1433,
sa/TinaSQL123!Secure); TINA4_TEST_FIREBIRD_URL (a live Firebird 5 URL; unset
means the Firebird cases skip locally -- the lab gate's own preflight FATALs
if it is unreachable there, a skipped required engine is a ghost).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

from tina4_python.database import Database
from tina4_python.migration import Migration
from tina4_python.migration.runner import _should_skip_create_table, _should_skip_for_firebird

# ── Real-engine connection coordinates (env-overridable) ────────────────────

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4_py")

MYSQL_HOST = os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("TINA4_TEST_MYSQL_USERNAME", "tina4")
MYSQL_PASS = os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4")
MYSQL_DB = os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test")

MSSQL_HOST = os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1")
MSSQL_PORT = int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433"))
MSSQL_USER = os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa")
MSSQL_PASS = os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure")
MSSQL_DB = os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test")

FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


needs_pg = pytest.mark.skipif(
    not _reachable(PG_HOST, PG_PORT),
    reason=f"no reachable PostgreSQL at {PG_HOST}:{PG_PORT} (set TINA4_TEST_PG_*)",
)
needs_mysql = pytest.mark.skipif(
    not _reachable(MYSQL_HOST, MYSQL_PORT),
    reason=f"no reachable MySQL at {MYSQL_HOST}:{MYSQL_PORT} (set TINA4_TEST_MYSQL_*)",
)
needs_mssql = pytest.mark.skipif(
    not _reachable(MSSQL_HOST, MSSQL_PORT),
    reason=f"no reachable MSSQL at {MSSQL_HOST}:{MSSQL_PORT} (set TINA4_TEST_MSSQL_*)",
)
needs_firebird = pytest.mark.skipif(
    not FIREBIRD_URL, reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)"
)


def _pg() -> Database:
    return Database(f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}", PG_USER, PG_PASS)


def _mysql() -> Database:
    return Database(f"mysql://{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}", MYSQL_USER, MYSQL_PASS)


def _mssql() -> Database:
    return Database(f"mssql://{MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DB}", MSSQL_USER, MSSQL_PASS)


def _firebird() -> Database:
    return Database(FIREBIRD_URL)


# ── ledger-row-commits-atomically-with-ddl ──────────────────────────────────


class TestLedgerRowCommitsAtomicallyWithDdl:
    def test_ledger_row_commits_atomically_with_ddl(self, tmp_path):
        """SQLite: the happy path -- DDL and the ledger row land TOGETHER."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_create_widgets.sql").write_text(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);"
        )
        db = Database(f"sqlite:///{tmp_path / 'ledger.db'}")
        try:
            applied = Migration(db, str(mig_dir)).migrate()
            assert applied == ["000001_create_widgets.sql"]
            assert db.table_exists("widgets"), "DDL did not apply"
            row = db.fetch_one(
                "SELECT migration_name, batch FROM tina4_migration WHERE migration_name = ?",
                ["000001_create_widgets"],
            )
            assert row is not None, "ledger row was not written alongside the DDL"
            assert row["batch"] == 1
        finally:
            db.close()

    @needs_mysql
    def test_ledger_row_never_precedes_or_survives_a_failed_ddl_on_mysql(self, tmp_path):
        """MySQL auto-commits DDL (cannot roll back), so this proves the
        NARROWER claim: the ledger write -- coded strictly AFTER the
        statement loop -- never lands for a file that failed, even though
        the engine itself cannot undo the DDL it already committed. Loud
        proof that atomicity holds for the write ORDER, independent of
        whether the engine's own DDL is transactional."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_mysql_atomic.sql").write_text(
            "CREATE TABLE mig_mysql_atomic (id INT PRIMARY KEY);\n"
            "THIS IS NOT VALID SQL;"
        )
        db = _mysql()
        db.execute("DROP TABLE IF EXISTS mig_mysql_atomic")
        db.execute("DELETE FROM tina4_migration WHERE migration_name = '000001_mysql_atomic'")
        db.commit()
        try:
            with pytest.raises(RuntimeError):
                Migration(db, str(mig_dir)).migrate()

            # MySQL committed the CREATE TABLE immediately (non-transactional DDL) --
            # the table IS there, proving this is a genuine non-rollback-capable engine.
            assert db.table_exists("mig_mysql_atomic"), (
                "precondition: MySQL DDL auto-commits, the table must exist"
            )
            # But the ledger write is coded strictly after the statement loop, so it
            # never ran for this failed file -- no row, at any batch, ever.
            row = db.fetch_one(
                "SELECT 1 FROM tina4_migration WHERE migration_name = ?",
                ["000001_mysql_atomic"],
            )
            assert row is None, (
                "the ledger row must never be written for a migration whose "
                "statement loop failed, even on a non-transactional-DDL engine"
            )
        finally:
            db.execute("DROP TABLE IF EXISTS mig_mysql_atomic")
            db.execute("DELETE FROM tina4_migration WHERE migration_name = '000001_mysql_atomic'")
            db.commit()
            db.close()


# ── midfile-failure-rolls-back-on-transactional-ddl ─────────────────────────


class TestMidfileFailureRollsBackOnTransactionalDdl:
    @needs_pg
    def test_midfile_failure_rolls_back_on_transactional_ddl(self, tmp_path):
        """PostgreSQL: a multi-statement file whose FIRST statement (a real
        CREATE TABLE) succeeds and whose SECOND fails rolls back the WHOLE
        file, including the already-executed CREATE TABLE -- no partial
        apply, no ledger row. Proves PostgreSQL's transactional DDL, not
        merely "the ledger write didn't happen" (MySQL already proves that
        narrower claim without transactional DDL)."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_pg_midfile.sql").write_text(
            "CREATE TABLE mig_pg_midfile (id SERIAL PRIMARY KEY, name VARCHAR(50));\n"
            "THIS IS NOT VALID SQL;"
        )
        db = _pg()
        db.execute("DROP TABLE IF EXISTS mig_pg_midfile")
        db.execute("DELETE FROM tina4_migration WHERE migration_name = '000001_pg_midfile'")
        db.commit()
        try:
            with pytest.raises(RuntimeError):
                Migration(db, str(mig_dir)).migrate()

            assert not db.table_exists("mig_pg_midfile"), (
                "PostgreSQL DDL is transactional -- the earlier CREATE TABLE in "
                "the same failed file must be rolled back too, not left applied"
            )
            row = db.fetch_one(
                "SELECT 1 FROM tina4_migration WHERE migration_name = ?",
                ["000001_pg_midfile"],
            )
            assert row is None, "no ledger row for a fully-rolled-back file"
        finally:
            db.execute("DROP TABLE IF EXISTS mig_pg_midfile")
            db.execute("DELETE FROM tina4_migration WHERE migration_name = '000001_pg_midfile'")
            db.commit()
            db.close()


# ── migrate-status-prints-without-crashing ──────────────────────────────────

# A fresh interpreter that runs the REAL CLI `main` with `migrate:status` as
# the command -- the identical code path (main -> COMMANDS dispatch ->
# _migrate_status) the installed `tina4python migrate:status` console-script
# takes. Mirrors tests/test_cli_test_exit_code.py's proven pattern.
_RUN_CLI_STATUS = (
    "import sys; "
    "from tina4_python.cli import main; "
    "sys.argv = ['tina4python', 'migrate:status']; "
    "main()"
)


def _run_migrate_status_cli(project_dir, db_url):
    env = dict(os.environ)
    env["TINA4_DATABASE_URL"] = db_url
    env.pop("TINA4_AUTO_MIGRATE", None)
    return subprocess.run(
        [sys.executable, "-c", _RUN_CLI_STATUS],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestMigrateStatusPrintsWithoutCrashing:
    def test_migrate_status_prints_without_crashing(self, tmp_path):
        """MIG-CLI-STATUS-BROKEN regression: `tina4 migrate:status` used to
        raise KeyError('migration_id') the moment ANY migration existed
        (completed OR pending). Real end-to-end: a real migrated SQLite DB,
        a real subprocess running the real CLI entry point, real stdout."""
        db_path = tmp_path / "status.db"
        db_url = f"sqlite:///{db_path}"
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_create_accounts.sql").write_text(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);"
        )
        (mig_dir / "000002_add_index.sql").write_text(
            "CREATE INDEX idx_accounts_name ON accounts (name);"
        )

        # Apply ONLY the first migration up front (in-process, real DB) so the
        # status print has to show one COMPLETED and one PENDING migration --
        # exercising BOTH of the CLI's broken code paths (completed AND
        # pending both read `m['migration_id']` before the fix).
        db = Database(db_url)
        try:
            (mig_dir / "000002_add_index.sql").rename(tmp_path / "000002_add_index.sql.hold")
            Migration(db, str(mig_dir)).migrate()
        finally:
            db.close()
        (tmp_path / "000002_add_index.sql.hold").rename(mig_dir / "000002_add_index.sql")

        result = _run_migrate_status_cli(tmp_path, db_url)

        assert result.returncode == 0, (
            f"migrate:status must exit 0 against a real migrated DB.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "KeyError" not in result.stderr, f"the migration_id KeyError regressed:\n{result.stderr}"
        assert "Traceback" not in result.stderr, f"migrate:status crashed:\n{result.stderr}"

        assert "Completed migrations" in result.stdout
        assert "000001_create_accounts" in result.stdout, result.stdout
        assert "Pending migrations" in result.stdout
        assert "000002_add_index" in result.stdout, result.stdout
        assert "1 completed, 1 pending" in result.stdout, result.stdout

    def test_migrate_status_prints_without_crashing_when_nothing_applied_yet(self, tmp_path):
        """The all-pending case (no completed migrations at all) must also
        print cleanly -- guards the pending-only branch independently."""
        db_path = tmp_path / "status_empty.db"
        db_url = f"sqlite:///{db_path}"
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_never_applied.sql").write_text(
            "CREATE TABLE never_applied (id INTEGER PRIMARY KEY);"
        )

        result = _run_migrate_status_cli(tmp_path, db_url)

        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "KeyError" not in result.stderr
        assert "No completed migrations" in result.stdout
        assert "000001_never_applied" in result.stdout, result.stdout
        assert "0 completed, 1 pending" in result.stdout, result.stdout


# ── failed-or-missing-down-does-not-drop-ledger ─────────────────────────────


class TestFailedOrMissingDownDoesNotDropLedger:
    def test_failed_or_missing_down_does_not_drop_ledger(self, tmp_path):
        """MIG-ROLLBACK-DROPS-LEDGER (Python is the reference model): a
        migration with NO .down.sql file must RAISE on rollback(), and the
        tina4_migration row must SURVIVE the raise -- the schema stays
        tracked rather than silently forgotten. Extends the existing
        test_missing_down_file (which only asserted the raise) with the
        row-survives assertion the shared fixture names."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_no_down.sql").write_text("CREATE TABLE nd (id INTEGER);")
        db = Database(f"sqlite:///{tmp_path / 'nodown.db'}")
        try:
            m = Migration(db, str(mig_dir))
            m.migrate()

            row_before = db.fetch_one(
                "SELECT migration_name FROM tina4_migration WHERE migration_name = ?",
                ["000001_no_down"],
            )
            assert row_before is not None, "precondition: the migration must be recorded"

            with pytest.raises(RuntimeError, match="no .py or .down.sql"):
                m.rollback()

            row_after = db.fetch_one(
                "SELECT migration_name FROM tina4_migration WHERE migration_name = ?",
                ["000001_no_down"],
            )
            assert row_after is not None, (
                "a missing .down.sql must RAISE, never silently drop the ledger row "
                "-- the schema is still there and must stay tracked"
            )
            # The user table itself is untouched (nothing to reverse).
            assert db.table_exists("nd")
        finally:
            db.close()

    def test_failed_down_statement_does_not_drop_ledger(self, tmp_path):
        """A .down.sql that EXISTS but whose SQL fails must also RAISE and
        leave the ledger row in place (not just the missing-file case)."""
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "000001_bad_down.sql").write_text("CREATE TABLE bd (id INTEGER);")
        (mig_dir / "000001_bad_down.down.sql").write_text("THIS IS NOT VALID SQL;")
        db = Database(f"sqlite:///{tmp_path / 'baddown.db'}")
        try:
            m = Migration(db, str(mig_dir))
            m.migrate()

            with pytest.raises(RuntimeError):
                m.rollback()

            row_after = db.fetch_one(
                "SELECT migration_name FROM tina4_migration WHERE migration_name = ?",
                ["000001_bad_down"],
            )
            assert row_after is not None, (
                "a FAILING down statement must also RAISE, never silently drop "
                "the ledger row"
            )
        finally:
            db.close()


# ── firebird-mssql-create-add-idempotency-real ──────────────────────────────


class TestFirebirdMssqlCreateAddIdempotencyReal:
    """NO DOUBLES. Drives the REAL Firebird 5 / real MSSQL idempotency skips
    directly against the live engines -- the same model as PHP's
    MigrationFootgunsLiveEngineTest. A real table on a real server makes the
    guard fire; a really-absent table proves the negative control."""

    @needs_mssql
    def test_mssql_create_table_skipped_when_table_really_exists(self, tmp_path):
        db = _mssql()
        table = "nomock_mig_py_users"
        db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")
        db.commit()
        try:
            db.execute(f"CREATE TABLE {table} (id INT)")
            db.commit()
            assert db.table_exists(table), "precondition: the real engine must report the table"

            reason = _should_skip_create_table(db, f"CREATE TABLE {table} (id INT)")
            assert reason is not None, "a really-existing MSSQL table must make CREATE TABLE skip"
            assert table in reason
        finally:
            db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")
            db.commit()
            db.close()

    @needs_mssql
    def test_mssql_create_table_not_skipped_when_table_really_absent(self, tmp_path):
        db = _mssql()
        table = "nomock_mig_py_absent"
        db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")
        db.commit()
        try:
            assert not db.table_exists(table), "precondition: the table must really be absent"
            reason = _should_skip_create_table(db, f"CREATE TABLE {table} (id INT)")
            assert reason is None, "an absent table must NOT be skipped -- the migration has to run"
        finally:
            db.close()

    @needs_firebird
    def test_firebird_create_table_skipped_when_table_really_exists(self, tmp_path):
        db = _firebird()
        table = "NOMOCK_MIG_PY_USERS"
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:
            pass
        try:
            db.execute(f"CREATE TABLE {table} (id INTEGER)")
            db.commit()
            assert db.table_exists(table), "precondition: the real engine must report the folded table"

            reason = _should_skip_create_table(db, f"CREATE TABLE {table} (id INTEGER)")
            assert reason is not None, "a really-existing Firebird table must make CREATE TABLE skip"
            assert table in reason
        finally:
            try:
                db.execute(f"DROP TABLE {table}")
                db.commit()
            except Exception:
                pass
            db.close()

    @needs_firebird
    def test_firebird_create_table_not_skipped_when_table_really_absent(self, tmp_path):
        db = _firebird()
        table = "NOMOCK_MIG_PY_ABSENT"
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:
            pass
        try:
            assert not db.table_exists(table), "precondition: the table must really be absent"
            reason = _should_skip_create_table(db, f"CREATE TABLE {table} (id INTEGER)")
            assert reason is None, "an absent table must NOT be skipped -- the migration has to run"
        finally:
            db.close()

    @needs_firebird
    def test_firebird_alter_add_skipped_when_column_really_exists(self, tmp_path):
        """ALTER TABLE ... ADD idempotency (Firebird has no IF NOT EXISTS for
        it): a REAL column on a REAL table makes the guard fire."""
        db = _firebird()
        table = "NOMOCK_MIG_PY_ADDCOL"
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:
            pass
        try:
            db.execute(f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY)")
            db.commit()
            db.execute(f"ALTER TABLE {table} ADD extra_col VARCHAR(50)")
            db.commit()

            reason = _should_skip_for_firebird(db, f"ALTER TABLE {table} ADD extra_col VARCHAR(50)")
            assert reason is not None, "a really-existing Firebird column must make ALTER ADD skip"
            assert "extra_col" in reason
        finally:
            try:
                db.execute(f"DROP TABLE {table}")
                db.commit()
            except Exception:
                pass
            db.close()

    @needs_firebird
    def test_firebird_alter_add_not_skipped_when_column_really_absent(self, tmp_path):
        db = _firebird()
        table = "NOMOCK_MIG_PY_ADDCOL2"
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:
            pass
        try:
            db.execute(f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY)")
            db.commit()

            reason = _should_skip_for_firebird(db, f"ALTER TABLE {table} ADD extra_col VARCHAR(50)")
            assert reason is None, "an absent column must NOT be skipped -- the ADD has to run"
        finally:
            try:
                db.execute(f"DROP TABLE {table}")
                db.commit()
            except Exception:
                pass
            db.close()
