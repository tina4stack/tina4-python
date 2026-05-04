"""Regression test for issue #38 — PG adapter's lastval() probe must not
abort the outer transaction on UUID PK tables.

Before the savepoint wrap in postgres.py, this sequence:

    INSERT INTO uuid_table VALUES (...)
    SELECT * FROM uuid_table

failed on the SELECT with
``psycopg2.errors.InFailedSqlTransaction: current transaction is aborted``,
because the post-INSERT ``SELECT lastval()`` probe raised on the missing
sequence and psycopg2 marked the whole transaction as aborted. The bare
``except: pass`` swallowed the original error and ``last_error`` stayed
``None``, so the symptom was a perfectly valid SELECT failing minutes
later with no useful breadcrumbs.

The test boots a real PostgreSQL (Docker container at localhost:55432),
runs the exact reproduction from the issue, and asserts the SELECT
succeeds. The test is skipped automatically when the container isn't
reachable so CI without postgres just no-ops.
"""
from __future__ import annotations

import os
import socket
import pytest

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USER", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASS", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4")


def _pg_reachable() -> bool:
    """Return True if a postgres server is listening on PG_HOST:PG_PORT."""
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} — skip integration test",
)


@pytest.fixture
def db():
    """A fresh Database connected to the test PG, with a UUID-PK table."""
    from tina4_python.database import Database
    d = Database(
        f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}",
        username=PG_USER, password=PG_PASS,
    )
    # Sanity check — psycopg2 must be available; if not, the import inside
    # Database.connect would have raised already.
    d.execute("DROP TABLE IF EXISTS t4_issue38_uuid")
    d.execute(
        "CREATE TABLE t4_issue38_uuid ("
        "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  name text"
        ")"
    )
    d.commit()
    yield d
    try:
        d.execute("DROP TABLE IF EXISTS t4_issue38_uuid")
        d.commit()
    finally:
        d.close()


class TestIssue38UuidInsertNoTransactionAbort:

    def test_insert_then_select_does_not_raise(self, db):
        """The exact reproduction from the issue. INSERT then SELECT must
        both succeed; before the savepoint fix, the SELECT raised
        InFailedSqlTransaction."""
        result = db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["alice"])
        assert result is not False, f"INSERT failed: {db.get_error()}"
        assert db.get_error() is None, "INSERT should not record an error"

        # The smoking gun — this used to fail with InFailedSqlTransaction.
        row = db.fetch_one("SELECT name FROM t4_issue38_uuid WHERE name = %s", ["alice"])
        assert row is not None
        assert row["name"] == "alice"

    def test_insert_then_multiple_selects(self, db):
        """Pattern: insert one row, do several selects on the same connection."""
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["bob"])
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["carol"])

        rows = db.fetch("SELECT name FROM t4_issue38_uuid ORDER BY name")
        names = [r["name"] for r in rows.records]
        assert names == ["bob", "carol"]

    def test_insert_then_update_then_select(self, db):
        """The savepoint pattern must work for INSERT-UPDATE-SELECT chains."""
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["dave"])
        db.execute("UPDATE t4_issue38_uuid SET name = %s WHERE name = %s",
                   ["dave2", "dave"])
        row = db.fetch_one("SELECT name FROM t4_issue38_uuid")
        assert row["name"] == "dave2"

    def test_explicit_transaction_with_uuid_inserts(self, db):
        """Explicit start_transaction → multiple UUID INSERTs → commit
        must persist all rows (and not silently abort the txn)."""
        db.start_transaction()
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["e1"])
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["e2"])
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["e3"])
        db.commit()

        n = db.fetch_one("SELECT count(*) AS n FROM t4_issue38_uuid")["n"]
        assert n == 3, f"expected 3 rows after commit, got {n}"

    def test_explicit_transaction_with_uuid_then_rollback(self, db):
        """Rollback must drop everything — proves we're really inside one txn."""
        db.start_transaction()
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["x1"])
        db.execute("INSERT INTO t4_issue38_uuid (name) VALUES (%s)", ["x2"])
        db.rollback()

        n = db.fetch_one("SELECT count(*) AS n FROM t4_issue38_uuid")["n"]
        assert n == 0, "rollback did not undo the UUID inserts"

    def test_insert_returning_id_still_works(self, db):
        """The RETURNING path skips the lastval probe entirely; verify it
        still works on a UUID PK."""
        result = db.execute(
            "INSERT INTO t4_issue38_uuid (name) VALUES (%s) RETURNING id",
            ["frank"],
        )
        # RETURNING returns a DatabaseResult with records
        assert result is not False
        # The returned id should be a uuid string (or uuid-like)
        if hasattr(result, "records") and result.records:
            row = result.records[0]
            assert "id" in row
            assert row["id"] is not None
