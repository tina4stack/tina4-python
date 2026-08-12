"""ORM base class contract -- feature 17 (ORM17-DEC-01).

Shared conformance fixture: tina4-documentation/plan/v3/fixtures/ormbase_contract.json

The SAFETY NET for the ORM17-DEC-01 vestigial-state cleanup (remove Node's
`_exists`, PHP's `tableFilter`, and the dead locals in delete/force_delete/
restore). The removal is BEHAVIOUR-PRESERVING, so this real round-trip
(save -> load -> query -> re-save/update -> count -> delete) passes IDENTICALLY
before AND after the removal.

In Python the only removals are the dead locals `table_sql` + `pk_db_col` in
delete/force_delete/restore (plus `pk`/`pk_value` in restore, which has no
null-check) -- unread leftovers from the pk-where refactor. This suite proves
the ORM base lifecycle those methods sit in is untouched.

NO mocks: every case drives a REAL SQLite file with real rows and real ORM
writes. Positive: a save loads back with identical values, count() is the live
total, where() finds by a non-key column, a re-save UPDATEs in place. Negative:
the re-save does not insert a duplicate, and a deleted model is ABSENT from
find() and count().
"""
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, IntegerField, StringField


class BaseWidget(ORM):
    table_name = "basewidget"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    qty = IntegerField()


@pytest.fixture
def db(tmp_path):
    """Fresh real SQLite DB per test, table created."""
    database = Database(f"sqlite:///{tmp_path/'ormbase.db'}")
    bind_database(database)
    BaseWidget.create_table()
    yield database


# ── Invariant: write/read round-trip (positive), no duplicate on re-save ─────

def test_a_saved_model_loads_back_with_identical_values(db):
    widget = BaseWidget(name="alpha", qty=7)
    saved = widget.save()
    assert saved is not False              # save() returns self, never False here
    assert widget.id is not None           # auto-increment PK adopted

    loaded = BaseWidget.find(widget.id)
    assert loaded is not None
    assert loaded.name == "alpha"
    assert loaded.qty == 7


def test_count_returns_the_live_row_total(db):
    # Guards PHP's removed tableFilter read: count() is exactly the row total.
    for i in range(3):
        assert BaseWidget(name=f"w{i}", qty=i).save() is not False
    assert BaseWidget.count() == 3


def test_where_returns_a_row_matched_by_a_non_key_column(db):
    BaseWidget(name="alpha", qty=1).save()
    BaseWidget(name="beta", qty=2).save()

    rows = BaseWidget.where("name = ?", params=["beta"])
    assert len(rows) == 1
    assert rows[0].name == "beta"
    assert rows[0].qty == 2


def test_a_re_saved_model_updates_in_place_not_a_duplicate(db):
    # Guards Node's removed _exists: the insert-vs-update decision never used it.
    BaseWidget(name="alpha", qty=1).save()
    assert BaseWidget.count() == 1

    loaded = BaseWidget.find(1)
    loaded.qty = 99
    assert loaded.save() is not False

    assert BaseWidget.count() == 1         # UPDATE in place, NOT a second INSERT
    assert BaseWidget.find(1).qty == 99    # the change persisted


# ── Invariant: delete removes the row (negative absence) ─────────────────────

def test_a_deleted_model_is_absent_from_find_and_count(db):
    # Guards the dead-local removal in delete().
    BaseWidget(name="alpha", qty=1).save()
    assert BaseWidget.count() == 1

    loaded = BaseWidget.find(1)
    assert loaded.delete() is True

    assert BaseWidget.find(1) is None
    assert BaseWidget.count() == 0


# ── Invariant: save() returns False, never raises, on a real constraint
# violation -- characterises the write-path fail-loud fix's ripple boundary.
# Python's Database.insert() already raises on a driver error (it is a thin
# wrapper over execute(), which never catches), and ORM.save() already wraps
# its insert() call in try/except and converts the raise to False; this pins
# that contract so it can never silently regress into save() raising. ────────

def test_save_on_constraint_violation_returns_false(db):
    db.execute("CREATE UNIQUE INDEX idx_basewidget_name_unique ON basewidget (name)")
    BaseWidget(name="alpha", qty=1).save()
    assert BaseWidget.count() == 1

    duplicate = BaseWidget(name="alpha", qty=2)  # UNIQUE(name) collides
    result = duplicate.save()  # must NOT raise

    assert result is False
    assert BaseWidget.count() == 1            # nothing written
    assert duplicate.get_error() is not None  # cause recorded, not swallowed
