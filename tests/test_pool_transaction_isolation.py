# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Real PostgreSQL regressions for exclusive pool leases (issue #145)."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from tina4_python.database import Database


@pytest.fixture
def database():
    url = os.environ.get('TINA4_TEST_PG_URL')
    if not url:
        pytest.skip('[needs:postgres] TINA4_TEST_PG_URL is not configured')
    instances = []
    tables = []

    def make(size):
        db = Database(url, pool=size)
        db.autocommit = True
        instances.append(db)
        return db

    admin = make(0)
    def table():
        name = 'pool145_' + uuid4().hex
        admin.execute(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY)')
        tables.append(name)
        return name

    yield make, table
    for db in instances:
        db.close()
    cleanup = Database(url)
    for name in tables:
        cleanup.execute(f'DROP TABLE IF EXISTS {name}')
    cleanup.close()


def test_pool_transaction_lease_prevents_cross_context_dirty_reads_and_lost_writes(database):
    make, table = database
    db, name = make(4), table()
    db.start_transaction()
    db.execute(f'INSERT INTO {name} VALUES (1)')
    def worker():
        counts = [db.fetch_one(f'SELECT COUNT(*) AS n FROM {name}')["n"] for _ in range(8)]
        for value in range(100, 104):
            db.execute(f'INSERT INTO {name} VALUES (?)', [value])
        return counts
    try:
        with ThreadPoolExecutor(1) as executor:
            counts = executor.submit(worker).result(timeout=10)
    finally:
        db.rollback()
    assert counts == [0] * 8
    assert [row['id'] for row in db.fetch(f'SELECT id FROM {name} ORDER BY id')] == list(range(100, 104))


def test_pool_exhaustion_fails_without_sharing_a_live_transaction(database):
    make, _ = database
    db = make(1)
    db.start_transaction()
    with ThreadPoolExecutor(1) as executor:
        with pytest.raises(RuntimeError, match='pool exhausted'):
            executor.submit(db.fetch_one, 'SELECT 1 AS n').result(timeout=5)
        with pytest.raises(RuntimeError, match='pool exhausted'):
            executor.submit(db.get_adapter).result(timeout=5)
    db.rollback()
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1


def test_explicit_lease_cannot_be_released_by_another_thread(database):
    make, _ = database
    db = make(1)
    adapter = db.checkout()
    try:
        with ThreadPoolExecutor(1) as executor:
            with pytest.raises(RuntimeError, match='owner'):
                executor.submit(db.checkin, adapter).result(timeout=5)
        with pytest.raises(RuntimeError, match='pool exhausted'):
            db.checkout()
    finally:
        db.checkin(adapter)
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1


def test_query_failure_returns_ordinary_lease(database):
    make, _ = database
    db = make(1)
    with pytest.raises(Exception):
        db.execute('SELECT column_that_does_not_exist')
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1


def test_pool_failed_commit_retains_lease_until_rollback(database):
    make, table = database
    db, name = make(1), table()
    # Use a separate deferred column: the primary key itself is immediate.
    db.execute(f'ALTER TABLE {name} ADD COLUMN value INTEGER UNIQUE DEFERRABLE INITIALLY DEFERRED')
    db.start_transaction()
    db.execute(f'INSERT INTO {name} VALUES (1, 7), (2, 7)')
    with pytest.raises(Exception):
        db.commit()
    with ThreadPoolExecutor(1) as executor:
        with pytest.raises(RuntimeError, match='pool exhausted'):
            executor.submit(db.fetch_one, 'SELECT 1 AS n').result(timeout=5)
    db.rollback()
    assert db.fetch_one(f'SELECT COUNT(*) AS n FROM {name}')['n'] == 0
    db.start_transaction()
    db.execute(f'INSERT INTO {name} VALUES (3, 8)')
    db.commit()
    assert db.fetch_one(f'SELECT COUNT(*) AS n FROM {name}')['n'] == 1


def test_ordinary_query_is_exclusively_leased(database):
    import time
    make, _ = database
    db, observer = make(1), make(0)
    marker = 'pool145_sleep_' + uuid4().hex
    with ThreadPoolExecutor(1) as executor:
        query = executor.submit(db.fetch_one, f'SELECT pg_sleep(0.5) /* {marker} */')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            running = observer.fetch_one(
                'SELECT COUNT(*) AS n FROM pg_stat_activity WHERE state = ? '
                'AND query LIKE ? AND pid <> pg_backend_pid()', ['active', '%' + marker + '%'])
            if running['n']:
                break
            time.sleep(0.01)
        else:
            pytest.fail('PostgreSQL did not observe the concurrent query')
        with pytest.raises(RuntimeError, match='pool exhausted'):
            db.fetch_one('SELECT 1 AS n')
        query.result(timeout=5)
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1


def test_failed_begin_discards_connection_and_returns_capacity(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'begin.sqlite'}", pool=1)
    adapter = db.checkout()
    adapter.close()
    db.checkin(adapter)
    with pytest.raises(Exception):
        db.start_transaction()
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1


def test_raw_peek_never_exposes_another_threads_transaction(database):
    make, _ = database
    db = make(2)
    db.start_transaction()
    pinned = db.get_adapter()
    try:
        with ThreadPoolExecutor(1) as executor:
            assert executor.submit(db.get_adapter).result(timeout=5) is not pinned
    finally:
        db.rollback()


def test_failed_rollback_discards_poisoned_connection(database):
    make, _ = database
    db = make(1)
    db.start_transaction()
    # Close the real socket without clearing the adapter's reference: rollback
    # must fail, and the next operation must receive a new live connection.
    db.get_adapter()._conn.close()
    with pytest.raises(Exception):
        db.rollback()
    assert db.fetch_one('SELECT 1 AS n')['n'] == 1
