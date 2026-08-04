"""update() matches the primary key in ``data`` case-insensitively.

REGRESSION (2026-08-04). Enabling the live Firebird suite turned up four
failures in the shared write-path contract, all one root cause:

    ValueError: update requires a filter or the complete primary key in the data
    (table='tina4_write_contract', primary key=['ID'], missing from data=['ID'])

The key WAS in the data - as ``id``. Firebird folds an unquoted identifier to
UPPER, so introspection reported ``ID`` while the contract's payload carried
``id``, and the presence check compared the two case-sensitively.

This was never a Firebird bug. PostgreSQL folds to LOWER, so it has the
mirror image for an upper-cased caller key; Firebird only made it visible first,
because the shared fixture happens to write lower-case keys. These tests assert
BOTH directions on real engines, which is the only way to tell a
case-sensitivity bug from an engine quirk.

The fix deliberately does NOT lower-case what introspection returns: that would
special-case one engine and break a genuinely quoted mixed-case table, which is
a real thing on Firebird and is the exact defect already found in PHP's
``tableExists()``. The WHERE clause is built from the ENGINE's column name and
the CALLER's value.

Real engines only - no mocks. SQLite always runs; PostgreSQL and Firebird run
when the lab exports their URLs.
"""
import os

import pytest

from tina4_python.database import Database

TABLE = "tina4_update_key_case"


def _engines():
    """Every engine this run can reach. SQLite is always present."""
    engines = [("sqlite", (None, None, None))]
    postgres = (os.environ.get("TINA4_TEST_PG_URL") or "").strip()
    if postgres:
        engines.append(("postgres", (postgres, "tina4", "tina4")))
    firebird = (os.environ.get("TINA4_TEST_FIREBIRD_URL") or "").strip()
    if firebird:
        engines.append(("firebird", (firebird, "SYSDBA", "masterkey")))
    return engines


ENGINES = _engines()


@pytest.fixture(params=ENGINES, ids=[name for name, _ in ENGINES])
def database(request, tmp_path_factory):
    """A seeded two-row table on a real engine, torn down and CLOSED.

    Every connection is closed explicitly: Firebird takes an exclusive lock for
    DDL, so one leaked handle makes the next DROP TABLE block forever rather
    than fail, and the suite stops dead instead of reporting.
    """
    _, (url, username, password) = request.param
    if url is None:
        url = f"sqlite:///{tmp_path_factory.mktemp('keycase')}/contract.db"
        username = password = ""

    connection = Database(url, username, password)

    def drop():
        try:
            connection.execute(f"DROP TABLE {TABLE}")
            connection.commit()
        except Exception:  # noqa: BLE001 - absent on the first run
            pass

    drop()
    connection.execute(
        f"CREATE TABLE {TABLE} (id INTEGER NOT NULL PRIMARY KEY, qty INTEGER)"
    )
    connection.commit()
    connection.insert(TABLE, {"id": 1, "qty": 10})
    connection.insert(TABLE, {"id": 2, "qty": 20})
    connection.commit()

    try:
        yield connection
    finally:
        drop()
        connection.close()


def _swap_case(name: str) -> str:
    """The spelling a caller would use if they guessed the other convention."""
    return name.lower() if name.isupper() else name.upper()


def _qty_for(database, row_id: int):
    row = database.fetch_one(f"SELECT qty FROM {TABLE} WHERE id = {row_id}")
    assert row is not None, f"row {row_id} vanished"
    return next(value for key, value in row.items() if key.lower() == "qty")


def test_the_engines_really_do_disagree_about_case(database):
    """The premise of the whole fix, asserted rather than assumed.

    If every engine returned the same spelling this bug could not exist and the
    case-insensitive match would be dead code.
    """
    key_columns = database.primary_key(TABLE)
    assert [c.lower() for c in key_columns] == ["id"]


def test_update_accepts_the_primary_key_in_the_other_case(database):
    """POSITIVE - the exact call that raised.

    The caller passes the key spelled the way the OTHER convention would spell
    it, which is what the shared contract does against Firebird.
    """
    key_column = database.primary_key(TABLE)[0]
    caller_key = _swap_case(key_column)

    result = database.update(TABLE, {caller_key: 1, "qty": 55})
    database.commit()

    assert result.affected_rows == 1, (
        f"expected exactly one row updated via {caller_key!r}, "
        f"got {result.affected_rows!r}"
    )
    assert _qty_for(database, 1) == 55, "the update reported success but did not land"
    assert _qty_for(database, 2) == 20, "the update touched a row it should not have"


def test_update_still_accepts_the_engines_own_casing(database):
    """POSITIVE - the case that already worked must keep working.

    Accepting a differently-cased key is strictly MORE permissive; nothing that
    worked before may stop working.
    """
    key_column = database.primary_key(TABLE)[0]

    result = database.update(TABLE, {key_column: 2, "qty": 77})
    database.commit()

    assert result.affected_rows == 1
    assert _qty_for(database, 2) == 77
    assert _qty_for(database, 1) == 10


def test_update_with_no_key_at_all_still_raises(database):
    """NEGATIVE - the data-loss guard must not have been loosened.

    The whole point of the check is that a filterless update never rewrites
    every row. A case-insensitive match must not become a match-anything.
    """
    with pytest.raises(ValueError, match="requires a filter or the complete primary key"):
        database.update(TABLE, {"qty": 99})

    assert _qty_for(database, 1) == 10, "a rejected update must change nothing"
    assert _qty_for(database, 2) == 20


def test_two_keys_differing_only_by_case_are_refused(database):
    """NEGATIVE - ambiguity is refused, never guessed.

    With both ``id`` and ``ID`` present there is no defensible way to choose,
    and choosing wrong writes the WHERE clause of an UPDATE.
    """
    with pytest.raises(ValueError, match="ambiguous"):
        database.update(TABLE, {"id": 1, "ID": 2, "qty": 99})

    assert _qty_for(database, 1) == 10, "a refused update must change nothing"
    assert _qty_for(database, 2) == 20
