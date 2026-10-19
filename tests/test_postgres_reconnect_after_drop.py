# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""PostgreSQL: a connection the server drops is replaced, not reused forever.

A failover, an idle-session reap or ``pg_terminate_backend`` closes the
connection under a running app. The adapter used to keep the dead psycopg2
connection, so every later query raised ``InterfaceError: connection already
closed`` until the process was restarted - while a health check that does not
touch the database kept the process looking healthy.

Now the adapter reconnects from its original connect arguments. The statement
that hit the dropped link is retried once, but only when nothing uncommitted
went down with it. Inside an explicit transaction, or with uncommitted work
pending, the caller sees the error, and the next statement runs on a new
connection. This mirrors the Firebird adapter's dead-connection handling.

NO MOCKS. A real PostgreSQL; the drop is a real ``pg_terminate_backend`` issued
from a second connection, and every assertion reads what the server holds.
"""

import os
import socket
from urllib.parse import urlparse

import pytest

PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
_PARSED = urlparse(PG_URL)
PG_HOST, PG_PORT = _PARSED.hostname or "localhost", _PARSED.port or 5432
TABLE = "reconnect_py_drop"


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


def _connect(**kwargs):
    from tina4_python.database import Database
    return Database(PG_URL, **kwargs)


@pytest.fixture
def observer():
    """A second connection: seeds the table, drops the tested one, reads back."""
    database = _connect()
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.execute(f"CREATE TABLE {TABLE} (id serial PRIMARY KEY, note text)")
    yield database
    database.execute(f"DROP TABLE IF EXISTS {TABLE}")
    database.close()


@pytest.fixture
def tested():
    database = _connect()
    yield database
    database.close()


def _pid(database) -> int:
    return database.fetch_one("SELECT pg_backend_pid() AS pid")["pid"]


def _drop(observer, pid: int):
    row = observer.fetch_one("SELECT pg_terminate_backend(?) AS gone", [pid])
    assert row["gone"] is True


def _notes(observer) -> list:
    return [r["note"] for r in observer.fetch(f"SELECT note FROM {TABLE} ORDER BY id").records]


def test_a_read_after_the_server_drops_the_connection_runs_on_a_new_one(observer, tested):
    before = _pid(tested)
    _drop(observer, before)

    after = _pid(tested)

    assert after != before
    assert _pid(tested) == after


def test_every_read_path_recovers(observer, tested):
    _drop(observer, _pid(tested))
    assert tested.fetch(f"SELECT note FROM {TABLE}").records == []

    _drop(observer, _pid(tested))
    assert tested.fetch_one("SELECT 1 AS one")["one"] == 1


def test_a_write_after_the_drop_lands_exactly_once(observer, tested):
    _drop(observer, _pid(tested))

    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["after-drop"])

    assert _notes(observer) == ["after-drop"]


def test_a_pooled_connection_recovers(observer):
    pooled = _connect(pool=2)
    try:
        _drop(observer, _pid(pooled))
        assert _pid(pooled) > 0
        pooled.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["pooled"])
        assert _notes(observer) == ["pooled"]
    finally:
        pooled.close()


def test_inside_a_transaction_the_drop_surfaces_and_the_next_statement_recovers(observer, tested):
    tested.start_transaction()
    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["in-txn"])
    _drop(observer, _pid(tested))

    with pytest.raises(Exception):
        tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["second"])
    try:
        tested.rollback()
    except Exception:
        pass

    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["next"])
    assert _notes(observer) == ["next"]


def test_with_uncommitted_work_pending_the_statement_is_not_retried_alone(observer, tested):
    tested.adapter.autocommit = False
    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["uncommitted"])
    _drop(observer, _pid_without_ending(tested))

    with pytest.raises(Exception):
        tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["second"])

    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["next"])
    tested.commit()
    assert _notes(observer) == ["next"]


def _pid_without_ending(database) -> int:
    """The backend pid, read on the open transaction without closing it."""
    cursor = database.adapter._conn.cursor()
    cursor.execute("SELECT pg_backend_pid()")
    return cursor.fetchone()[0]


def test_recovers_after_a_failed_reconnect(observer, tested):
    """#242: a failover where the FIRST reconnect cannot reach the new primary.

    ``_reconnect`` closes the dropped link, then ``connect`` fails, leaving a
    CLOSED psycopg2 connection. The next statement built its cursor on that
    link first, so ``self._conn.cursor()`` raised ``InterfaceError: connection
    already closed`` before the reconnect path could run - and the adapter
    stayed wedged there until the process restarted. It must instead keep
    retrying and recover once a reachable server returns.

    NO MOCKS: a real dropped backend, a real failed reconnect (the adapter's own
    connect arguments aimed at a port nothing listens on - what a failover looks
    like before the new primary answers), then a real recovery once the good
    target is restored.
    """
    good = tested.adapter._connect_args
    unreachable = (good[0].replace(f":{PG_PORT}/", ":1/"), good[1], good[2], good[3])
    assert unreachable[0] != good[0], "could not aim the reconnect at a dead port"
    tested.adapter._connect_args = unreachable

    _drop(observer, _pid(tested))
    with pytest.raises(Exception):
        tested.fetch_one("SELECT 1 AS one")   # reconnect to the dead port fails
    with pytest.raises(Exception):
        tested.fetch_one("SELECT 1 AS one")   # still down: retried, never wedged

    tested.adapter._connect_args = good        # the new primary is reachable now
    assert tested.fetch_one("SELECT 1 AS one")["one"] == 1   # recovers
    tested.execute(f"INSERT INTO {TABLE} (note) VALUES (?)", ["after-failed-reconnect"])
    assert _notes(observer) == ["after-failed-reconnect"]
