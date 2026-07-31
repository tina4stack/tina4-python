"""Regression test — ORM.create_table() on PostgreSQL (doc-verification findings F2/F3).

Three bugs made the documented code-first schema path (ORM.create_table)
silently broken on PostgreSQL:

  1. DateTimeField was emitted as ``DATETIME`` unconditionally. PostgreSQL
     (and Firebird) have no DATETIME type, so CREATE TABLE failed with
     ``type "datetime" does not exist``.
  2. The BooleanField engine check was ``engine == "postgres"`` but
     ``get_database_type()`` returns ``"postgresql"``, so bool columns got
     INTEGER on PG — a Python ``bool`` then couldn't be inserted.
  3. The PG adapter ran ``boolean_to_int`` in _translate_sql, rewriting
     ``DEFAULT FALSE`` -> ``DEFAULT 0`` (and ``= TRUE`` -> ``= 1``), which
     PostgreSQL rejects on a native BOOLEAN column.

On top of that, create_table swallowed the DDL error and returned ``True``,
so callers believed a table was created when none was.

This boots a real PostgreSQL (env-configurable, default localhost:55432) and
skips when unreachable. To run against the doc-test container:
    TINA4_TEST_PG_PORT=5432 TINA4_TEST_PG_DB=tina4_py pytest tests/test_postgres_create_table.py
"""
from __future__ import annotations

import datetime
import os
import socket

import pytest

from tina4_python.database import Database
from tina4_python.orm import bind_database, ORM
from tina4_python.orm.fields import IntegerField, StringField, BooleanField, DateTimeField

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_reachable(), reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (skip)")


class CreateTableWidget(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    active = BooleanField(default=False)
    created = DateTimeField()


@pytest.fixture()
def db():
    conn = Database(f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}", PG_USER, PG_PASS)
    conn.execute("DROP TABLE IF EXISTS createtablewidget")
    conn.commit()
    bind_database(conn)
    yield conn
    conn.execute("DROP TABLE IF EXISTS createtablewidget")
    conn.commit()
    conn.close()


def test_create_table_actually_creates_on_postgres(db):
    """create_table() returns True AND the table really exists (no silent pass)."""
    assert CreateTableWidget.create_table() is True
    assert db.table_exists("createtablewidget") is True


def test_create_table_emits_timestamp_not_datetime(db):
    """DateTimeField -> TIMESTAMP on PG (DATETIME doesn't exist there)."""
    CreateTableWidget.create_table()
    cols = {c["name"]: c for c in db.get_columns("createtablewidget")}
    # PG reports timestamp without time zone as "timestamp..."
    assert "timestamp" in (cols["created"]["type"] or "").lower()


def test_create_table_boolean_is_native(db):
    """BooleanField -> native BOOLEAN on PG, and DEFAULT FALSE survives translation."""
    CreateTableWidget.create_table()
    cols = {c["name"]: c for c in db.get_columns("createtablewidget")}
    assert (cols["active"]["type"] or "").lower() == "boolean"


def test_insert_select_round_trip(db):
    """The full documented round-trip: build the table, insert, read back."""
    CreateTableWidget.create_table()
    w = CreateTableWidget({"name": "alpha", "active": True, "created": "2026-06-15 10:00:00"})
    assert w.save() is not False
    rows = db.fetch("SELECT * FROM createtablewidget ORDER BY id")
    assert rows.count == 1
    row = rows[0]
    assert row["name"] == "alpha"
    assert row["active"] is True                       # native bool, not 1
    assert isinstance(row["created"], datetime.datetime)


def test_where_true_literal_survives(db):
    """boolean_to_int must NOT run on PG: `WHERE active = TRUE` stays valid."""
    CreateTableWidget.create_table()
    CreateTableWidget({"name": "on", "active": True, "created": "2026-06-15 10:00:00"}).save()
    CreateTableWidget({"name": "off", "active": False, "created": "2026-06-15 10:00:00"}).save()
    on = db.fetch("SELECT * FROM createtablewidget WHERE active = TRUE")
    assert on.count == 1
    assert on[0]["name"] == "on"
