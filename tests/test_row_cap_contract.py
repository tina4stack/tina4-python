# The raw-fetch row cap, pinned as its own file so it can never stop running.
#
# WHY THIS FILE EXISTS
#
# tina4-php carried this exact test as a SECOND PHPUnit TestCase class inside
# tests/DevAdminTest.php. PHPUnit loads one test class per file, so the second
# class was never collected and the test NEVER RAN -- it sat in the repo looking
# like coverage for releases on end. When it was finally lifted into its own file
# and executed, it FAILED: it asserted a default cap of 10. That 10 came from the
# V2 documentation and had survived into v3 in two separate places. A test that
# does not run cannot tell you its own assertion has gone stale, so the stale
# number and the dead test protected each other.
#
# Two habits come out of that, and this file is built on both:
#
#   1. One file, one contract, collected by the runner's ordinary discovery.
#      Nothing here hides behind another module's collection rules.
#   2. THE FIXTURE MUST HOLD MORE ROWS THAN THE CAP. The PHP version created 30
#      rows and asserted 30 -- which is exactly what you get whether the cap is
#      100, or 1000, or there is no cap at all. It could only ever have failed on
#      a cap BELOW 30. A fixture smaller than the cap proves nothing about the
#      cap, so this one holds 150 against a cap of 100 and every assertion below
#      is a number the wrong implementation cannot also produce.
#
# THE CONTRACT
#
#   * fetch() with NO limit argument returns at most 100 rows.
#   * An explicit limit overrides that default IN BOTH DIRECTIONS -- 25 gives 25,
#     and 120 gives 120 even though 120 is larger than the cap. The cap is a
#     default, not a ceiling; without the upward case a hardcoded `LIMIT 100`
#     would satisfy every other assertion here.
#   * SQL that already carries its own LIMIT must NOT get a second one appended.
#
# BOTH LAYERS, EVERY ASSERTION
#
# Python writes the default 100 down TWICE: in Database.fetch's signature
# (database/connection.py) and again in SQLiteAdapter.fetch's signature
# (database/sqlite.py), which is also where the already-has-a-LIMIT check lives.
# Either can drift alone, and the wrapper's own default masks the adapter's, so
# every case below runs against BOTH -- see the `layer` fixture.
#
# Real SQLite on disk throughout, no doubles: `db._get_adapter()` hands back the
# very SQLiteAdapter the wrapper delegates to.
#
# A weaker sibling of this test lives on in tests/test_dev_admin.py
# (TestSQLiteLimitDedup, 30 rows asserting 30). It is deliberately NOT deleted --
# a bug test is never lost, only superseded. This file is the strong one.
import pytest

from tina4_python.database import Database

ROWS = 150          # MORE than the cap, on purpose. See the header.
CAP = 100
UNDER_CAP = 25
OVER_CAP = 120      # > CAP and < ROWS, so "120" cannot be confused with either.


@pytest.fixture
def db(tmp_path):
    """A real SQLite database file holding MORE rows than the cap."""
    d = Database(f"sqlite:///{tmp_path / 'row_cap_contract.db'}")
    d.execute("CREATE TABLE cap_rows (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT)")
    d.execute_many(
        "INSERT INTO cap_rows (label) VALUES (?)",
        [[f"row{i}"] for i in range(ROWS)],
    )
    d.commit()
    # If this is ever wrong the whole file is meaningless, so prove the premise
    # before asserting anything about truncation.
    assert d.fetch_one("SELECT COUNT(*) AS c FROM cap_rows")["c"] == ROWS
    yield d
    d.close()


@pytest.fixture(params=["wrapper", "adapter"])
def layer(request, db):
    """The same contract asserted at BOTH layers that cap.

    "wrapper" is Database.fetch; "adapter" is the REAL SQLiteAdapter underneath
    it (not a stand-in -- _get_adapter() returns the object the wrapper calls).
    The layer shows up in the test id, so a red run names which one drifted.
    """
    return db.fetch if request.param == "wrapper" else db._get_adapter().fetch


def rows(result):
    """Row COUNT of what came back.

    `.records`, never `.count` -- `count` is the total matching rows (150 here,
    what pagination needs) and stays 150 no matter what the cap does. Asserting
    `.count` would test nothing about truncation.
    """
    return len(result.records)


class TestNoLimitArgumentCapsAtOneHundred:
    """The default. 150 rows are available; 100 come back."""

    def test_fetch_with_no_limit_returns_the_cap(self, layer):
        assert rows(layer("SELECT * FROM cap_rows")) == CAP

    def test_the_cap_truncates_rather_than_reporting_a_smaller_table(self, layer):
        # The rows are capped but the total is still honest. This is the pair the
        # 30-row fixture could never separate: a broken cap and a small table look
        # identical when the fixture is smaller than the cap.
        result = layer("SELECT * FROM cap_rows")
        assert rows(result) == CAP
        assert result.count == ROWS


class TestAnExplicitLimitOverridesInBothDirections:
    """The cap is a DEFAULT, not a ceiling."""

    def test_a_smaller_limit_is_honoured(self, layer):
        assert rows(layer("SELECT * FROM cap_rows", limit=UNDER_CAP)) == UNDER_CAP

    def test_a_limit_larger_than_the_cap_is_honoured(self, layer):
        # The half that catches a hardcoded `LIMIT 100`: 120 > 100, and all 120
        # rows must come back. Only possible because the fixture holds 150.
        assert rows(layer("SELECT * FROM cap_rows", limit=OVER_CAP)) == OVER_CAP

    def test_a_limit_of_every_row_returns_every_row(self, layer):
        assert rows(layer("SELECT * FROM cap_rows", limit=ROWS)) == ROWS


class TestSqlThatAlreadyHasALimitIsLeftAlone:
    """No second LIMIT appended -- not a truncating one, not a syntax error."""

    def test_an_explicit_limit_in_the_sql_above_the_cap_survives(self, layer):
        # The strong case. A LIMIT of 130 in the SQL is ABOVE the default cap, so
        # appending `LIMIT 100` would truncate to 100 and appending anything at
        # all would be a SQLite syntax error. 130 rows back means neither
        # happened. (The old 30-row/`LIMIT 3` version sat below the cap, where a
        # wrongly-appended cap changes nothing observable.)
        assert rows(layer("SELECT * FROM cap_rows LIMIT 130")) == 130

    def test_an_explicit_limit_in_the_sql_below_the_cap_survives(self, layer):
        assert rows(layer("SELECT * FROM cap_rows LIMIT 7")) == 7

    def test_the_sqls_own_limit_wins_over_the_limit_argument(self, layer):
        # Both are present. The SQL already says 130, so the argument must not be
        # appended on top of it -- one LIMIT reaches SQLite, and it is the one in
        # the statement.
        assert rows(layer("SELECT * FROM cap_rows LIMIT 130", limit=UNDER_CAP)) == 130
