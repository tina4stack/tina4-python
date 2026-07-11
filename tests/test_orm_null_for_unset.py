"""#165 — an INSERT must OMIT a column the caller never assigned so a
``NOT NULL DEFAULT <x>`` column gets its DB default, while still writing NULL
for a field the caller explicitly set to None.

Before the fix, ``ORM.save()`` serialised EVERY declared column on INSERT,
including ones the caller never touched (value None), emitting an explicit
``NULL``. A DB DEFAULT applies only when the column is OMITTED, not when NULL is
passed — so a ``NOT NULL DEFAULT ''`` / ``NOT NULL DEFAULT 0`` column made the
INSERT fail. v2 omitted unset columns; v3 now does too.

The distinction locked in here (positive AND negative):
  * a column left UNSET  -> omitted -> DB default applies  (INSERT succeeds)
  * a column set to None -> written -> explicit NULL       (fails a NOT NULL col)

NOT a mock: real SQLite Database, real DDL with real DEFAULT constraints, real
save()/reload round-trips.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database


# DDL owns the DEFAULT constraints the ORM must respect. label/quantity are
# NOT NULL DEFAULT; note is nullable (to show explicit-None -> NULL is accepted
# where the column allows it).
_DDL = """
CREATE TABLE widget165 (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT    NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 0,
    note     TEXT
)
"""


class Widget165(ORM):
    table_name = "widget165"
    id = IntegerField(primary_key=True, auto_increment=True)
    label = StringField()
    quantity = IntegerField()
    note = StringField()


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite:///{path}")
    database.execute(_DDL)
    database.commit()
    bind_database(database)
    yield database
    try:
        database.close()
    finally:
        os.unlink(path)


# ── Positive: unset columns fall through to the DB default ──────────────

def test_all_columns_unset_inserts_with_db_defaults(db):
    """A model with NOTHING assigned inserts successfully and every column
    shows its DB default (the empty-insert -> DEFAULT VALUES path)."""
    w = Widget165()
    assert w.save() is not False, f"save failed: {w.get_error()!r}"

    row = db.fetch_one("SELECT * FROM widget165 WHERE id = ?", [w.id])
    assert row["label"] == "", "NOT NULL DEFAULT '' should apply to an unset column"
    assert row["quantity"] == 0, "NOT NULL DEFAULT 0 should apply to an unset column"
    assert row["note"] is None


def test_partial_unset_columns_use_db_default(db):
    """Setting only `label` leaves `quantity` unset — it must get the DB
    default 0, not an explicit NULL that violates NOT NULL."""
    w = Widget165(label="hello")
    assert w.save() is not False, f"save failed: {w.get_error()!r}"

    row = db.fetch_one("SELECT * FROM widget165 WHERE id = ?", [w.id])
    assert row["label"] == "hello"
    assert row["quantity"] == 0, "unset NOT NULL DEFAULT column must use its DB default"


# ── Positive: an assigned value is written verbatim ─────────────────────

def test_normal_value_is_written(db):
    w = Widget165(label="widget", quantity=7)
    assert w.save() is not False, f"save failed: {w.get_error()!r}"

    row = db.fetch_one("SELECT * FROM widget165 WHERE id = ?", [w.id])
    assert row["label"] == "widget"
    assert row["quantity"] == 7


# ── Positive: explicit None on a NULLABLE column writes NULL ────────────

def test_explicit_none_on_nullable_column_writes_null(db):
    """`note` is nullable — assigning None explicitly must persist NULL
    (the value IS written, it is not omitted)."""
    w = Widget165(label="x", note=None)
    assert w.save() is not False, f"save failed: {w.get_error()!r}"

    row = db.fetch_one("SELECT * FROM widget165 WHERE id = ?", [w.id])
    assert row["note"] is None


# ── Negative: explicit None IS written (as NULL), so it fails a NOT NULL
#    column — proving the value is not silently swapped for the default ──

def test_explicit_none_on_not_null_column_fails(db):
    """Setting `quantity = None` explicitly (constructor) writes NULL, which a
    NOT NULL column rejects — save() fails loud and no row lands. This is the
    counterpart to the unset case: unset omits (default applies), explicit
    None writes NULL."""
    w = Widget165(label="x", quantity=None)
    assert w.save() is False, "explicit None into a NOT NULL column must fail"
    assert w.get_error() is not None
    assert db.fetch("SELECT * FROM widget165").count == 0, "no row should have landed"


def test_explicit_none_via_attribute_assignment_fails(db):
    """The assignment tracking also covers post-construction attribute sets:
    `w.quantity = None` marks quantity assigned, so it is written as NULL and
    rejected by the NOT NULL column (not omitted)."""
    w = Widget165(label="x")
    w.quantity = None  # explicit — must be tracked as assigned
    assert w.save() is False, "explicit None via attribute must fail on NOT NULL"
    assert db.fetch("SELECT * FROM widget165").count == 0


# ── Regression guard: an ORM-level default (non-None) is still written ──

def test_orm_level_default_is_still_written(db):
    """A field with an ORM default that resolves to a non-None value must
    still be inserted (the omission only targets unset-AND-None columns),
    so callable/static ORM defaults do not regress."""

    class WidgetDefaulted(ORM):
        table_name = "widget165"
        id = IntegerField(primary_key=True, auto_increment=True)
        label = StringField(default="from-orm")   # non-None ORM default
        quantity = IntegerField()
        note = StringField()

    bind_database(db)
    w = WidgetDefaulted()  # label unset by caller, but ORM default is non-None
    assert w.save() is not False, f"save failed: {w.get_error()!r}"

    row = db.fetch_one("SELECT * FROM widget165 WHERE id = ?", [w.id])
    assert row["label"] == "from-orm", "non-None ORM default must be written, not omitted"
