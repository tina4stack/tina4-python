"""table_exists() finds a Firebird table under either spelling it could be stored as.

REGRESSION (2026-08-04). Firebird's identifier folding is ASYMMETRIC::

    CREATE TABLE foo     ->  stored as FOO   (unquoted folds to UPPER)
    CREATE TABLE "Foo"   ->  stored as Foo   (quoted keeps its case)

The adapter upper-cased the name before querying ``RDB$RELATIONS``. That is
CORRECT for the unquoted case - the common one - and WRONG for a quoted
mixed-case table, which is a real thing on Firebird: the table exists, the
lookup reports it absent, and any CREATE-TABLE idempotency guard built on that
answer never fires. PHP's ``MigrationFootgunsLiveEngineTest`` names exactly this.

Simply dropping the upper-case would not fix it - it would invert which half is
broken. ``table_exists("Foo")`` is genuinely ambiguous, so both spellings are
matched.

Both halves are asserted here on purpose. A fix that only handled quoted names
would pass the mixed-case test while breaking the common unquoted path, and
nothing would catch it.

Real Firebird only - no mocks.
"""
import os

import pytest

from tina4_python.database import Database

FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not FIREBIRD_URL,
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)

UNQUOTED = "tina4_te_plain"
MIXED = "Tina4TeMixed"


@pytest.fixture()
def database():
    connection = Database(FIREBIRD_URL, "SYSDBA", "masterkey")

    def drop(statement):
        try:
            connection.execute(statement)
            connection.commit()
        except Exception:  # noqa: BLE001 - absent on the first run
            pass

    drop(f"DROP TABLE {UNQUOTED}")
    drop(f'DROP TABLE "{MIXED}"')
    try:
        yield connection
    finally:
        drop(f"DROP TABLE {UNQUOTED}")
        drop(f'DROP TABLE "{MIXED}"')
        # Firebird takes an exclusive lock for DDL: a leaked handle makes the
        # next DROP block forever instead of failing.
        connection.close()


def test_an_unquoted_table_is_found(database):
    """POSITIVE - the common path, which must not regress.

    Created unquoted, so Firebird stores it as TINA4_TE_PLAIN while the caller
    asks for the lower-case spelling they typed.
    """
    database.execute(f"CREATE TABLE {UNQUOTED} (id INTEGER NOT NULL PRIMARY KEY)")
    database.commit()

    assert database.table_exists(UNQUOTED) is True
    assert database.table_exists(UNQUOTED.upper()) is True


def test_a_quoted_mixed_case_table_is_found(database):
    """POSITIVE - the case that was broken.

    Created quoted, so Firebird stores it as Tina4TeMixed exactly. Upper-casing
    the lookup asked for TINA4TEMIXED, which does not exist, and the table read
    as absent.
    """
    database.execute(f'CREATE TABLE "{MIXED}" (id INTEGER NOT NULL PRIMARY KEY)')
    database.commit()

    assert database.table_exists(MIXED) is True


def test_a_table_that_does_not_exist_is_still_absent(database):
    """NEGATIVE - matching two spellings must not become matching anything.

    A lookup that answered True for an absent table would make the idempotency
    guard skip a CREATE that was genuinely needed.
    """
    assert database.table_exists("tina4_te_definitely_absent") is False
    assert database.table_exists("Tina4TeDefinitelyAbsent") is False
