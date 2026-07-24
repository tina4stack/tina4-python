"""Lock-in for the SQLite row-hydration contract (fetch-path audit).

fetch() was changed to hydrate rows from a tuple cursor + a column list
computed once, instead of dict(sqlite3.Row) per row (which allocates a Row
object AND a dict per row). These tests pin the OUTPUT so that optimisation --
and any future one -- cannot quietly change what callers receive: plain dicts
keyed by column name, NULL as None, aliased JOIN columns keyed by their alias,
and an empty list for a no-match query. Real SQLite, no doubles.
"""
import tempfile
import shutil

import pytest

from tina4_python.database import Database


@pytest.fixture
def db():
    tmp = tempfile.mkdtemp()
    database = Database(f"sqlite:///{tmp}/hydration.db")
    database.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, active INTEGER, note TEXT)"
    )
    database.execute("INSERT INTO users VALUES (1, 'Alice', 1, 'x')")
    database.execute("INSERT INTO users VALUES (2, NULL, 0, NULL)")
    database.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT)")
    database.execute("INSERT INTO posts VALUES (10, 1, 'Hi')")
    database.commit()
    yield database
    database.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_rows_are_plain_dicts_keyed_by_column(db):
    rows = db.fetch("SELECT * FROM users WHERE id = 1").records
    assert rows == [{"id": 1, "name": "Alice", "active": 1, "note": "x"}]
    assert type(rows[0]) is dict  # a real dict, not a sqlite3.Row proxy


def test_null_becomes_none(db):
    rows = db.fetch("SELECT * FROM users WHERE id = 2").records
    assert rows == [{"id": 2, "name": None, "active": 0, "note": None}]


def test_empty_result_is_empty_list(db):
    result = db.fetch("SELECT * FROM users WHERE id = 999")
    assert result.records == []


def test_aliased_join_columns_keyed_by_alias(db):
    rows = db.fetch(
        "SELECT u.id AS uid, p.id AS pid, u.name, p.title "
        "FROM users u JOIN posts p ON p.user_id = u.id"
    ).records
    assert rows == [{"uid": 1, "pid": 10, "name": "Alice", "title": "Hi"}]


def test_every_row_has_the_same_keys(db):
    rows = db.fetch("SELECT * FROM users ORDER BY id", limit=1000).records
    assert [list(r.keys()) for r in rows] == [
        ["id", "name", "active", "note"],
        ["id", "name", "active", "note"],
    ]


def test_count_is_still_populated(db):
    # The COUNT(*) probe must keep working alongside the new hydration.
    result = db.fetch("SELECT * FROM users", limit=1)
    assert result.count == 2
    assert len(result.records) == 1


def test_fetch_one_unchanged(db):
    assert db.fetch_one("SELECT * FROM users WHERE id = 1") == {
        "id": 1,
        "name": "Alice",
        "active": 1,
        "note": "x",
    }
