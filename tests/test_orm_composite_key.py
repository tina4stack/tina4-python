"""The ORM layer must honour a COMPOSITE primary key (feature 4, open item).

Feature 4 fixed the raw write path: db.update()/delete() take EVERY primary-key
column into the WHERE, because keying on only the first column matches every row
sharing that value. The ORM layer above it was never fixed. It resolves one key
(`_get_pk()` returns the first primary-key field, else "id"), so:

  - `save()` on an existing row keys the UPDATE on ONE column, so it rewrites
    every row sharing that column's value - the exact data-loss shape feature 4
    removed from the layer below.
  - `create_table()` emits an inline `PRIMARY KEY` on EACH key column, which is
    invalid DDL: SQLite/PostgreSQL/MySQL all reject two inline primary keys.

Real SQLite, no mocks - the DDL half only shows up against an engine that
actually parses the statement.
"""
import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, StringField, IntegerField, bind_database


@pytest.fixture
def db():
    path = os.path.join(tempfile.mkdtemp(), "composite.db")
    connection = Database(f"sqlite:///{path}")
    bind_database(connection)
    yield connection
    try:
        connection.close()
    except Exception:
        pass


class Membership(ORM):
    """Two key columns, the shape feature 4's fixture calls composite."""
    __table__ = "membership"
    tenant = StringField(primary_key=True)
    code = StringField(primary_key=True)
    label = StringField()
    seats = IntegerField()


def test_the_model_reports_every_primary_key_column(db):
    """The resolver must return BOTH columns, not just the first."""
    keys = Membership._get_pks()
    assert keys == ["tenant", "code"], f"expected both key columns, got {keys}"


def test_create_table_emits_one_table_level_primary_key(db):
    """Invalid DDL is the giveaway.

    Two inline `PRIMARY KEY` clauses are rejected by SQLite, PostgreSQL and
    MySQL alike. A composite key has to be declared once, at table level.
    """
    assert Membership.create_table() is not False
    ddl = db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='membership'"
    )["sql"]
    assert ddl.upper().count("PRIMARY KEY") == 1, f"expected ONE primary key clause:\n{ddl}"
    assert "PRIMARY KEY" in ddl.upper()
    # Both columns named in the one clause.
    clause = ddl.upper().split("PRIMARY KEY", 1)[1]
    assert "TENANT" in clause and "CODE" in clause, f"both key columns must be in it:\n{ddl}"


def test_save_updates_only_the_row_matching_the_WHOLE_key(db):
    """The data-loss case.

    Two rows share `tenant`. Saving a change to one must not rewrite the other -
    keying on `tenant` alone matches both.
    """
    Membership.create_table()
    Membership(tenant="acme", code="a1", label="first", seats=1).save()
    Membership(tenant="acme", code="a2", label="second", seats=2).save()

    changed = Membership(tenant="acme", code="a1", label="CHANGED", seats=99)
    changed.save()

    rows = {r["code"]: r for r in db.fetch("SELECT * FROM membership ORDER BY code").records}
    assert rows["a1"]["label"] == "CHANGED"
    assert rows["a2"]["label"] == "second", "saving a1 rewrote a2 - the key is being truncated"
    assert rows["a2"]["seats"] == 2


def test_negative_delete_removes_only_the_row_matching_the_WHOLE_key(db):
    """Same hazard on the delete path."""
    Membership.create_table()
    Membership(tenant="acme", code="a1", label="first", seats=1).save()
    Membership(tenant="acme", code="a2", label="second", seats=2).save()

    Membership(tenant="acme", code="a1").delete()

    remaining = db.fetch("SELECT code FROM membership").records
    assert [r["code"] for r in remaining] == ["a2"], (
        "delete removed more than the addressed row - the key is being truncated"
    )


def test_a_single_key_model_is_unaffected(db):
    """The common case must not regress: one key column keeps working."""

    class Widget(ORM):
        __table__ = "widget"
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()

    assert Widget._get_pks() == ["id"]
    Widget.create_table()
    ddl = db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='widget'"
    )["sql"]
    assert ddl.upper().count("PRIMARY KEY") == 1

    w = Widget(name="one")
    w.save()
    assert Widget.find(w.id) is not None


def test_a_model_with_no_declared_key_still_falls_back_to_id(db):
    """Unchanged behaviour for a model that declares no primary key."""

    class Loose(ORM):
        __table__ = "loose"
        name = StringField()

    assert Loose._get_pks() == ["id"]
