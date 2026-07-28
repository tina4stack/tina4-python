"""Write-path contract: a write with no filter is an error, not a full-table operation.

Audit feature 4 (plan/v3/features/004-sqlite-adapter.md), P1.

The bug these lock in: `db.update(table, data)` with no explicit filter builds
`UPDATE table SET ...` with NO WHERE clause, so it overwrites EVERY row and
reports success. Verified in Python, PHP and Ruby; Node silently changes nothing
instead. Nothing logs, nothing raises, and the only signal is affected_rows.

Real SQLite files under pytest's tmp_path. No mocks - SQLite is free to stand up.
"""

import pytest

from tina4_python.database import Database


@pytest.fixture
def db(tmp_path):
    """A real two-row table, so a full-table write is visible as collateral damage."""
    database = Database(f"sqlite:///{tmp_path}/contract.db")
    database.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    database.insert("t", {"id": 1, "name": "one"})
    database.insert("t", {"id": 2, "name": "two"})
    return database


def rows(database):
    return [dict(r) for r in database.fetch("SELECT * FROM t ORDER BY id").records]


# --- pair 1: keyed update ---------------------------------------------------

def test_update_with_a_primary_key_in_data_updates_only_that_row(db):
    """A PK in the data IS the filter. Row 2 must not be touched."""
    db.update("t", {"id": 1, "name": "CHANGED"})
    assert rows(db) == [
        {"id": 1, "name": "CHANGED"},
        {"id": 2, "name": "two"},
    ], "the primary key in data was not used as the WHERE clause"


def test_negative_update_without_a_filter_or_primary_key_raises(db):
    """THE P1. No filter and no PK must raise, never touch every row.

    Today this returns affected=2 and overwrites the whole table.
    """
    before = rows(db)
    with pytest.raises(ValueError, match="filter"):
        db.update("t", {"name": "NOPK"})
    assert rows(db) == before, (
        "a filterless update modified rows - this is the data-loss bug. "
        f"before={before} after={rows(db)}"
    )


# --- pair 2: no silent no-op ----------------------------------------------

def test_update_reports_the_rows_it_changed(db):
    result = db.update("t", {"name": "X"}, "id = ?", [1])
    assert result.affected_rows == 1


def test_negative_update_never_reports_zero_when_a_matching_row_exists(db):
    """Node's failure mode: affected=0 with a row that plainly matches."""
    result = db.update("t", {"id": 2, "name": "TWO"})
    assert result.affected_rows != 0, (
        "update reported zero affected rows while a matching row existed - "
        "a caller who does not check affected_rows believes the write landed"
    )


# --- pair 3: delete filter forms -----------------------------------------

def test_delete_accepts_a_key_value_filter(db):
    """The form tina4-python/CLAUDE.md documents as THE calling form."""
    db.delete("t", {"id": 2})
    assert rows(db) == [{"id": 1, "name": "one"}]


def test_delete_accepts_a_string_filter_with_params(db):
    db.delete("t", "id = ?", [2])
    assert rows(db) == [{"id": 1, "name": "one"}]


def test_negative_delete_does_not_raise_on_a_key_value_filter(db):
    """The declared type is `str | dict | list`; the dict must not reach the SQL.

    Today: OperationalError 'unrecognized token: "{"' - the annotation promises
    what the code refuses.
    """
    try:
        db.delete("t", {"id": 2})
    except Exception as exc:  # noqa: BLE001 - the point is that NOTHING raises
        pytest.fail(
            f"a declared filter type raised: {type(exc).__name__}: {exc}"
        )


# --- pair 4: no accidental truncate --------------------------------------

def test_truncate_removes_every_row(db):
    """Emptying a table is a real thing to want. It must be spelled out."""
    db.truncate("t")
    assert rows(db) == []


def test_negative_delete_without_a_filter_raises(db):
    before = rows(db)
    with pytest.raises(ValueError, match="filter"):
        db.delete("t")
    assert rows(db) == before, "a filterless delete removed rows"


# --- pair 5: write result contract ---------------------------------------

def test_insert_reports_a_last_id(db):
    result = db.insert("t", {"name": "three"})
    assert result.last_id is not None


def test_negative_update_and_delete_do_not_report_a_last_id(db):
    """last_id is insert-only, per Python's own docs. PHP already does this."""
    updated = db.update("t", {"id": 1, "name": "CHANGED"})
    assert updated.last_id is None, "update reported a last_id"
    deleted = db.delete("t", {"id": 2})
    assert deleted.last_id is None, "delete reported a last_id"
