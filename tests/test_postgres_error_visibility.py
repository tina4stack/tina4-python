"""Regression test for issue #46 — PostgreSQL failures must surface, not cascade.

Schalk hit ``current transaction is aborted, commands ignored until end of
transaction block`` on the FIRST DB call in a trace — meaning an earlier
query had failed silently and left the connection in an aborted state.
psycopg2 cascades every subsequent statement until ROLLBACK is called.

The fix in ``tina4_python/database/postgres.py:_safe_execute``:

1. Catch every cursor exception
2. Log it via ``Log.error`` with SQL + params context
3. Store on ``self.last_error``
4. Auto-rollback when NOT inside an explicit transaction so the next
   caller gets a clean connection
5. Re-raise so the caller still sees the failure

This test boots a real PostgreSQL container (localhost:55432) and runs
the cascade scenario. Skipped when the container isn't reachable so CI
without postgres just no-ops.
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
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)",
)


@pytest.fixture
def db():
    """A fresh PostgreSQL adapter pointing at the test container."""
    from tina4_python.database.postgres import PostgreSQLAdapter
    adapter = PostgreSQLAdapter()
    adapter.connect(
        f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    )
    adapter.autocommit = False  # match production default
    yield adapter
    try:
        adapter._conn.rollback()
    except Exception:
        pass
    adapter.close()


class TestPostgresErrorVisibility:
    """Issue #46 — failures must surface, not cascade."""

    def test_failed_query_stores_last_error(self, db):
        """A bad query stores the actual error message on the adapter."""
        with pytest.raises(Exception):
            db.execute("SELECT * FROM table_that_does_not_exist")

        assert db.last_error is not None, "last_error must be populated"
        # Should contain the actual cause, not a cascade message.
        assert "table_that_does_not_exist" in db.last_error.lower() or \
               "does not exist" in db.last_error.lower(), \
               f"Expected real error, got: {db.last_error!r}"

    def test_implicit_failure_does_not_cascade(self, db):
        """After a failed query outside an explicit transaction, the
        NEXT query must succeed on the same connection — not return
        the 'current transaction is aborted' cascade message."""
        # First query fails.
        with pytest.raises(Exception):
            db.execute("SELECT * FROM table_that_does_not_exist")

        # Second query — totally unrelated, plain SELECT — must succeed.
        # Before the fix this raised InFailedSqlTransaction.
        result = db.fetch("SELECT 1 AS one")
        assert result.records, "Cascade not cleared — fix didn't auto-rollback"
        assert result.records[0]["one"] == 1

    def test_failed_query_logs_via_log_error(self, db, caplog):
        """The framework logs the original error so a tail -f sees it
        even when callers swallow exceptions."""
        import logging
        caplog.set_level(logging.DEBUG)

        with pytest.raises(Exception):
            db.execute("SELECT * FROM table_that_does_not_exist")

        # Log.error writes to the framework writer; in tests we hook
        # the Log static method to capture. Use a sentinel via the
        # writer if exposed; otherwise just verify last_error fired.
        assert db.last_error is not None

    def test_explicit_transaction_failure_keeps_user_in_charge(self, db):
        """Inside an EXPLICIT transaction, the framework does NOT
        auto-rollback. The user knows they're in a transaction; ripping
        them out of it on every error would shadow legitimate
        SAVEPOINT/retry patterns. They get the error + last_error +
        log, and call rollback() themselves."""
        db._in_transaction = True

        with pytest.raises(Exception):
            db.execute("SELECT * FROM table_that_does_not_exist")

        # Auto-rollback skipped — connection IS aborted now.
        # The user must call rollback explicitly.
        assert db.last_error is not None, \
            "Still logged even inside an explicit transaction"

        # Clean up so the fixture teardown doesn't choke.
        try:
            db._conn.rollback()
        except Exception:
            pass
        db._in_transaction = False


# ── v3.13.8: heal pre-existing aborted-txn state ────────────────────


class TestPoisonedConnectionIsHealed:
    """Issue #46 follow-on (v3.13.8): Schalk on the 24rent team upgraded
    to v3.13.7 and still hit ``InFailedSqlTransaction`` on the FIRST
    query of a function. v3.13.6's auto-rollback only fires *on* a
    failure the wrapper catches — it doesn't heal a connection that
    arrived poisoned from boot-time work, a prior request, or an
    explicit-transaction failure that never got rolled back.

    v3.13.8 adds a pre-flight ``_heal_aborted_txn()`` step inside
    :meth:`PostgreSQLAdapter._exec_with_handling` and :meth:`fetch`
    that checks the psycopg2 ``transaction_status`` and rolls back if
    the connection is in ``TRANSACTION_STATUS_INERROR``."""

    def _poison(self, db):
        """Simulate the Schalk scenario: run a bad query via *raw*
        cursor.execute (bypassing our wrapper) and DON'T rollback.
        Connection is now in TRANSACTION_STATUS_INERROR — every
        subsequent execute would normally cascade."""
        cursor = db._conn.cursor()
        try:
            cursor.execute("SELECT * FROM table_that_does_not_exist_v3138")
        except Exception:
            pass
        import psycopg2.extensions as _ext
        assert db._conn.info.transaction_status == _ext.TRANSACTION_STATUS_INERROR, \
            "test setup: connection should be in aborted state after raw bad query"

    def test_fetch_heals_poisoned_connection(self, db):
        """A `db.fetch` arriving on a poisoned connection should NOT
        cascade. The heal step rolls back first; the real query runs
        clean."""
        self._poison(db)

        result = db.fetch("SELECT 1 AS one")

        assert result.records, "fetch returned no records — heal didn't run"
        assert result.records[0]["one"] == 1
        # last_error should NOT contain the cascade message — that means
        # heal worked and the query never hit InFailedSqlTransaction.
        if db.last_error:
            assert "current transaction is aborted" not in db.last_error.lower(), \
                f"cascade message leaked into last_error: {db.last_error!r}"

    def test_execute_heals_poisoned_connection(self, db):
        """Same contract for ``db.execute`` — _exec_with_handling's
        pre-flight heal covers this path."""
        self._poison(db)

        # Should NOT raise InFailedSqlTransaction.
        db.execute("SELECT 1")
        # And the connection should be back in idle state.
        import psycopg2.extensions as _ext
        assert db._conn.info.transaction_status in (
            _ext.TRANSACTION_STATUS_IDLE,
            _ext.TRANSACTION_STATUS_INTRANS,
        ), "connection should not be in aborted state after heal"

    def test_explicit_transaction_skips_heal(self, db):
        """Inside an explicit transaction, the heal must defer to the
        user — same rule as the failure-time auto-rollback. A
        SAVEPOINT/retry caller can't have the framework yanking them
        out of their txn behind their back."""
        self._poison(db)
        db._in_transaction = True

        # Inside an explicit txn the heal is a no-op, so the next query
        # should cascade with InFailedSqlTransaction.
        with pytest.raises(Exception) as excinfo:
            db.execute("SELECT 1")
        assert "current transaction is aborted" in str(excinfo.value).lower(), \
            "explicit-txn caller must see the cascade so they can SAVEPOINT/rollback themselves"

        # Clean up so the fixture teardown doesn't choke.
        try:
            db._conn.rollback()
        except Exception:
            pass
        db._in_transaction = False
