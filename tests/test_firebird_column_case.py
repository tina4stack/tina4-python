"""Firebird column names fold back only when Firebird folded them.

Firebird's identifier folding is ASYMMETRIC::

    SELECT 1 AS x        ->  stored X       (unquoted folds to UPPER)
    SELECT 1 AS "MyCol"  ->  stored MyCol   (quoted keeps its case)

Every other engine Tina4 supports gives ``x`` for the first form -- PostgreSQL
folds to lower, MySQL/SQLite/MSSQL preserve -- so portable code reading
``row["x"]`` broke on Firebird alone. The driver now folds an all-uppercase name
back to lowercase and leaves anything else alone.

BOTH halves are asserted on purpose. A blanket ``.lower()`` passes the first
test and fails the second, and that is exactly what this driver used to do:
``AS "MyCol"`` came back ``mycol``, so a mixed-case key was unreachable. A fix
that only stopped lowercasing would pass the second and fail the first.

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


@pytest.fixture()
def database():
    connection = Database(FIREBIRD_URL, "SYSDBA", "masterkey")
    yield connection
    connection.close()


def test_unquoted_name_comes_back_lowercase(database):
    row = database.fetch_one("SELECT 1 AS x FROM rdb$database")
    assert list(row.keys()) == ["x"], "an unquoted alias must read like every other engine"
    assert row["x"] == 1


def test_quoted_mixed_case_name_keeps_its_case(database):
    row = database.fetch_one('SELECT 1 AS "MyCol" FROM rdb$database')
    assert list(row.keys()) == ["MyCol"], "a quoted alias was cased deliberately; do not fold it"
    assert row["MyCol"] == 1
