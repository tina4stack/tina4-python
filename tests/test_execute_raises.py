"""Database.execute() must FAIL LOUD — raise on a SQL error, never silently
return False.

Pre-3.13.x ``Database.execute()`` caught the driver exception and returned
``False`` (storing the cause on ``last_error``). Almost no caller checks a
boolean after every write, so a failed ``INSERT``/``UPDATE``/``DELETE`` looked
like success while the row never landed — a silent partial-write footgun. It now
raises (mirroring ``fetch()``), while still capturing the cause on
``last_error`` / ``get_error()``.

Engine-agnostic — runs on SQLite, so it executes locally and in CI with no
database server.
"""
from __future__ import annotations

import pytest

from tina4_python.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path}/raise.db")
    database.execute(
        "CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
    )
    database.commit()
    yield database
    database.close()


def test_execute_raises_on_bad_sql(db):
    """A statement against a missing table raises — it does NOT return False."""
    with pytest.raises(Exception):
        db.execute("INSERT INTO no_such_table (x) VALUES (1)")
    # The cause is still readable through the public API after the raise.
    assert db.get_error() is not None
    assert db.get_error() == db.last_error


def test_execute_raises_on_constraint_violation(db):
    """A NOT NULL violation must surface as an exception, and the row must
    NOT exist — the write genuinely failed, it wasn't swallowed."""
    with pytest.raises(Exception):
        db.execute("INSERT INTO widget (id, name) VALUES (1, NULL)")
    assert db.fetch("SELECT * FROM widget").count == 0


def test_execute_success_returns_truthy_and_clears_error(db):
    """The success contract is unchanged: a good write returns truthy
    (True / DatabaseResult, never False) and clears last_error."""
    result = db.execute("INSERT INTO widget (id, name) VALUES (1, 'ok')")
    db.commit()
    assert result is not False and result is not None
    assert db.get_error() is None
    assert db.fetch("SELECT * FROM widget").count == 1
