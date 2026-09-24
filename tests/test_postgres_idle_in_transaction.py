"""Regression test for issue #51 — PostgreSQL idle-in-transaction leak.

The psycopg2 *connection* runs with ``connection.autocommit = False`` so the
framework owns every commit boundary (explicit transactions stay atomic). A
bare ``SELECT`` therefore opens a transaction too; before v3.13.15
``fetch()`` / ``fetch_one()`` never closed it, so the connection sat
``idle in transaction`` for its whole life, holding a pool slot and any locks
it touched. Short-lived boot connections (the migration runner's
``MAX(batch)`` lookup) leaked one each until ``max_connections`` was
exhausted — then autodiscovery failed mid-boot and every route 404'd while
``/health-check`` still passed ("ready but broken").

The fix: after a successful non-transactional read, roll back the implicit
transaction (a SELECT has nothing to persist). Inside an explicit
``start_transaction()`` the caller owns it, so we defer. A write that returns
rows is committed instead (#133, ``test_issue133_fetch_write_commits.py``).

NO MOCKS. This file used to drive a fake connection that counted rollback()
calls; it proved the method was called, never that PostgreSQL agreed. Every
check below asks the SERVER: ``pg_stat_activity.state`` for the tested
connection's own backend, read from a second connection - ``idle`` versus
``idle in transaction`` is exactly the symptom #51 reported.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

from tina4_python.database.postgres import PostgreSQLAdapter

PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
_PARSED = urlparse(PG_URL)
PG_HOST, PG_PORT = _PARSED.hostname or "localhost", _PARSED.port or 5432
TABLE = "issue51_py_idle"


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
def observer():
    """A second connection that reads the server's view of the others."""
    database = _connect()
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.execute(f"CREATE TABLE {TABLE} (id serial PRIMARY KEY, note text)")
    database.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["row"])
    yield database
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.close()


@pytest.fixture
def reader():
    database = _connect()
    yield database
    database.close()


def _server_state(observer, database) -> str:
    """pg_stat_activity.state for ``database``'s own backend, as the server sees it."""
    pid = database._get_adapter()._conn.info.backend_pid
    row = observer.fetch_one("SELECT state FROM pg_stat_activity WHERE pid = ?", [pid], no_cache=True)
    return row["state"]


def test_fetch_one_leaves_the_connection_idle(observer, reader):
    assert reader.fetch_one(f"SELECT note FROM {TABLE} WHERE id = 1", no_cache=True) == {"note": "row"}
    assert _server_state(observer, reader) == "idle", (
        "fetch_one() left the connection 'idle in transaction' (#51)"
    )


def test_fetch_leaves_the_connection_idle(observer, reader):
    assert reader.fetch(f"SELECT note FROM {TABLE}", no_cache=True).records == [{"note": "row"}]
    assert _server_state(observer, reader) == "idle", "fetch() left the connection 'idle in transaction' (#51)"


def test_fetch_one_inside_an_explicit_transaction_leaves_it_open(observer, reader):
    """Negative case: the caller owns an explicit transaction; a read must not end it."""
    reader.start_transaction()
    reader.fetch_one(f"SELECT note FROM {TABLE} WHERE id = 1", no_cache=True)
    assert _server_state(observer, reader) == "idle in transaction"
    reader.rollback()
    assert _server_state(observer, reader) == "idle"


def test_fetch_inside_an_explicit_transaction_leaves_it_open(observer, reader):
    reader.start_transaction()
    reader.fetch(f"SELECT note FROM {TABLE}", no_cache=True)
    assert _server_state(observer, reader) == "idle in transaction"
    reader.commit()
    assert _server_state(observer, reader) == "idle"


def test_short_lived_readers_do_not_leak_open_transactions(observer):
    """The #51 shape: boot-time readers that read once and are never closed."""
    readers = [_connect() for _ in range(5)]
    try:
        for database in readers:
            database.fetch_one(f"SELECT max(id) AS n FROM {TABLE}", no_cache=True)
        states = [_server_state(observer, database) for database in readers]
        assert states == ["idle"] * 5, f"one-shot readers left transactions open: {states}"
    finally:
        for database in readers:
            database.close()


def test_ending_the_read_transaction_without_a_connection_is_safe():
    """Pure: no connection, nothing to close, and no exception."""
    adapter = PostgreSQLAdapter()
    adapter._conn = None
    adapter._end_read_txn()
