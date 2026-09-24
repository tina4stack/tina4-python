"""Issue #133 - a write that RETURNS rows must commit through fetch_one()/fetch().

``fetch_one()`` / ``fetch()`` close the implicit transaction a read opens so a
PostgreSQL connection never sits ``idle in transaction`` (#51). They closed it
with a ROLLBACK unconditionally, on the assumption that anything going through
them is a read. ``INSERT/UPDATE/DELETE ... RETURNING`` goes through
``fetch_one()`` naturally - you want the new id - so the caller got the id of a
row that was then rolled back. No error, no warning: silent data loss.
``execute()`` of the same INSERT autocommits and was always fine.

The contract pinned here:
  * a write through fetch_one()/fetch() is committed, exactly like execute();
  * a plain read still ends its implicit transaction (no idle-in-transaction);
  * inside start_transaction() the caller still owns the boundary.

NO MOCKS: a real PostgreSQL, and every visibility check is made from a SECOND
real connection, which is the only thing that can tell committed from not.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
_PARSED = urlparse(PG_URL)
PG_HOST, PG_PORT = _PARSED.hostname or "localhost", _PARSED.port or 5432
TABLE = "issue133_py_note"


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} - skip integration test",
)


def _connect():
    from tina4_python.database import Database
    return Database(PG_URL)


@pytest.fixture
def writer():
    database = _connect()
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.execute(f"CREATE TABLE {TABLE} (id serial PRIMARY KEY, text text NOT NULL)")
    yield database
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.close()


@pytest.fixture
def observer():
    database = _connect()
    yield database
    database.close()


def _visible_rows(observer) -> int:
    return observer.fetch_one(f"SELECT count(*) AS n FROM {TABLE}", [], no_cache=True)["n"]


def _transaction_status(database) -> int:
    """psycopg2's own view of the connection: 0 idle, 2 in transaction."""
    return database._get_adapter()._conn.info.transaction_status


def test_fetch_one_insert_returning_is_committed(writer, observer):
    row = writer.fetch_one(f"INSERT INTO {TABLE} (text) VALUES (?) RETURNING id", ["via fetch_one"])
    assert row and row["id"] == 1
    assert _visible_rows(observer) == 1, (
        "fetch_one() returned the new id, but a second connection cannot see the "
        "row: it was rolled back after the id was handed out (#133)"
    )


def test_fetch_insert_returning_is_committed(writer, observer):
    result = writer.fetch(f"INSERT INTO {TABLE} (text) VALUES (?) RETURNING id", ["via fetch"])
    assert [record["id"] for record in result.records] == [1]
    assert _visible_rows(observer) == 1, "fetch() of an INSERT ... RETURNING was rolled back (#133)"


def test_fetch_one_update_and_delete_returning_are_committed(writer, observer):
    writer.execute(f"INSERT INTO {TABLE} (text) VALUES (?)", ["original"])
    updated = writer.fetch_one(f"UPDATE {TABLE} SET text = ? WHERE id = 1 RETURNING text", ["changed"])
    assert updated == {"text": "changed"}
    assert observer.fetch_one(f"SELECT text FROM {TABLE} WHERE id = 1", [], no_cache=True) == {"text": "changed"}

    deleted = writer.fetch_one(f"DELETE FROM {TABLE} WHERE id = 1 RETURNING id")
    assert deleted == {"id": 1}
    assert _visible_rows(observer) == 0, "fetch_one() of a DELETE ... RETURNING was rolled back (#133)"


def test_fetch_one_data_modifying_cte_is_committed(writer, observer):
    """A WITH whose body writes is a write, even though it ends in SELECT."""
    row = writer.fetch_one(
        f"WITH created AS (INSERT INTO {TABLE} (text) VALUES (?) RETURNING id) SELECT id FROM created",
        ["via cte"],
    )
    assert row == {"id": 1}
    assert _visible_rows(observer) == 1, "a data-modifying CTE through fetch_one() was rolled back"


def test_a_returning_write_is_never_served_from_the_query_cache(writer, observer, monkeypatch):
    """With the request cache on, a repeated INSERT ... RETURNING must insert twice."""
    monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
    cached = _connect()
    try:
        first = cached.fetch_one(f"INSERT INTO {TABLE} (text) VALUES (?) RETURNING id", ["same"])
        second = cached.fetch_one(f"INSERT INTO {TABLE} (text) VALUES (?) RETURNING id", ["same"])
    finally:
        cached.close()
    assert (first, second) == ({"id": 1}, {"id": 2}), "the second INSERT was answered from the query cache"
    assert _visible_rows(observer) == 2


@pytest.mark.parametrize("sql, is_write", [
    ("INSERT INTO t (a) VALUES (1) RETURNING id", True),
    ("  -- a leading comment\n update t SET a = 1 RETURNING a", True),
    ("/* block */ DELETE FROM t RETURNING id", True),
    ("WITH gone AS (DELETE FROM t RETURNING id) SELECT count(*) FROM gone", True),
    ("SELECT * FROM t WHERE note = 'INSERT INTO x'", False),
    ("SELECT id FROM t -- UPDATE later", False),
    ("WITH recent AS (SELECT id FROM t) SELECT * FROM recent", False),
    ("SELECT replace(name, 'a', 'b') AS updated FROM t", False),
])
def test_write_statement_classification(sql, is_write):
    from tina4_python.database.adapter import DatabaseAdapter
    assert DatabaseAdapter._is_write_statement(sql) is is_write


def test_a_plain_read_still_leaves_no_idle_transaction(writer):
    """Negative case: the #51 guarantee must survive the fix."""
    writer.execute(f"INSERT INTO {TABLE} (text) VALUES (?)", ["row"])
    assert writer.fetch_one(f"SELECT text FROM {TABLE} WHERE id = 1") == {"text": "row"}
    assert _transaction_status(writer) == 0, "a read left the connection idle in transaction (#51)"
    assert writer.fetch(f"SELECT text FROM {TABLE}").records == [{"text": "row"}]
    assert _transaction_status(writer) == 0, "fetch() left the connection idle in transaction (#51)"


def test_a_returning_write_inside_an_explicit_transaction_is_still_the_callers(writer, observer):
    """Negative case: inside start_transaction() nothing commits early."""
    writer.start_transaction()
    row = writer.fetch_one(f"INSERT INTO {TABLE} (text) VALUES (?) RETURNING id", ["pending"])
    assert row == {"id": 1}
    assert _visible_rows(observer) == 0, "fetch_one() committed inside the caller's transaction"
    writer.rollback()
    assert _visible_rows(observer) == 0
