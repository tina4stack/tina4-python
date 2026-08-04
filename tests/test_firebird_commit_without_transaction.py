"""commit()/rollback() with nothing open are no-ops, not AttributeErrors.

REGRESSION (2026-08-04). Enabling the live Firebird suite on the lab turned up
22 errors in the shared write-path contract, every one of them at fixture setup
and every one the same crash out of the DRIVER, not out of Tina4:

    tina4_python/database/firebird.py:385: in commit
        self._conn.commit()
    firebird/driver/core.py:2694: AttributeError:
        'NoneType' object has no attribute 'commit'

``firebird-driver`` delegates ``Connection.commit()`` to ``main_transaction``,
whose handle is ``None`` until a statement opens a transaction. The legacy
``fdb`` driver started one implicitly -- which is exactly what
``FirebirdAdapter.start_transaction`` still says in its comment -- so the
unconditional ``self._conn.commit()`` was safe when the adapter was written and
became a crash when the preferred driver changed underneath it.

The contract fixture hit it by issuing DDL and then committing: on Firebird the
DDL had already ended the transaction, so there was nothing left to commit.

These tests need a REAL Firebird (no mocks): they are the only way to see this,
because every in-process double would have a ``commit`` attribute and pass.
"""
import os

import pytest

from tina4_python.database import Database

FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not FIREBIRD_URL,
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)

TABLE = "TINA4_COMMIT_NO_TXN"


@pytest.fixture()
def database():
    connection = Database(FIREBIRD_URL, "SYSDBA", "masterkey")
    try:
        connection.execute(f"DROP TABLE {TABLE}")
        connection.commit()
    except Exception:  # noqa: BLE001 - first run against this engine
        pass
    yield connection
    try:
        connection.execute(f"DROP TABLE {TABLE}")
        connection.commit()
    except Exception:  # noqa: BLE001 - teardown must never mask a test failure
        pass


def test_commit_with_no_open_transaction_is_a_no_op(database):
    """NEGATIVE - this is the exact call that raised AttributeError."""
    database.commit()
    database.commit()  # twice: still nothing open, still nothing to do


def test_rollback_with_no_open_transaction_is_a_no_op(database):
    """Same shape as commit(): nothing open means nothing to undo."""
    database.rollback()
    database.rollback()


def test_commit_after_ddl_is_a_no_op_rather_than_a_crash(database):
    """The precise sequence the write-path contract fixture performs.

    Firebird ends the transaction on DDL, so the commit that follows has nothing
    open. Before the fix this raised and took all 22 contract cases with it.
    """
    database.execute(
        f"CREATE TABLE {TABLE} (ID INTEGER NOT NULL PRIMARY KEY, NAME VARCHAR(40))"
    )
    database.commit()


def test_a_committed_write_is_still_really_committed(database):
    """POSITIVE - proves the guard did not turn commit() into a no-op ALWAYS.

    A guard that skipped every commit would make the test above pass while
    silently dropping writes, so this reads the row back over a SEPARATE
    connection, which can only see committed data.
    """
    database.execute(
        f"CREATE TABLE {TABLE} (ID INTEGER NOT NULL PRIMARY KEY, NAME VARCHAR(40))"
    )
    database.commit()

    database.start_transaction()
    database.execute(f"INSERT INTO {TABLE} (ID, NAME) VALUES (1, 'committed')")
    database.commit()

    verifier = Database(FIREBIRD_URL, "SYSDBA", "masterkey")
    row = verifier.fetch_one(f"SELECT NAME FROM {TABLE} WHERE ID = 1")
    assert row is not None, "a committed row was not visible to a second connection"
    assert str(row["NAME"]).strip() == "committed"
