"""Issue #145 regression: the connection pool must isolate a transaction to the
one connection its thread pinned, on a REAL PostgreSQL, with pool=4.

The bug (round-robin pool, pre-ADR-0074): ``start_transaction()`` did not lease a
connection exclusively, so a concurrent thread's plain operation could land on the
SAME connection the open transaction was using. Two consequences, both data loss:

  * the concurrent thread ran INSIDE the open transaction and could read its
    uncommitted rows;
  * the concurrent thread's own autocommit write was rolled back when the
    unrelated transaction rolled back (its ``rollback()`` reached the shared
    connection).

ADR-0074 makes every ``start_transaction()`` check out a connection EXCLUSIVELY
and pin it to the calling context (a ``contextvars`` borrow), releasing it only on
commit()/rollback(). A second thread borrows a DIFFERENT connection from the pool.

Exact repro from the report, on real PostgreSQL, pool=4:
  1. Thread A: start_transaction() + INSERT (uncommitted).
  2. Thread B (a plain pooled fetch): must NOT see A's uncommitted row, and must
     NOT be running inside A's transaction.
  3. Thread B's own autocommit write must SURVIVE A's later rollback.

No mocks: a live PostgreSQL, its own MVCC (READ COMMITTED) provides the isolation
the pool must not defeat by sharing a connection.

Mutation-proof: make ``ConnectionPool.checkout()`` hand back a connection already
leased (or drop the transaction pin) and thread B lands on A's connection — it
then sees A's uncommitted row (assertion 1 goes RED) and its own write vanishes on
A's rollback (assertion 3 goes RED). Proven RED against that mutation.
"""
import os
import threading

import pytest

from db_engine_matrix import required_engines_missing
from tina4_python.database import Database


def _pg():
    url = os.environ.get("TINA4_TEST_PG_URL")
    if not url:
        if "postgres" in required_engines_missing():
            pytest.fail("TINA4_REQUIRE_SERVICES=1 but TINA4_TEST_PG_URL is unset")
        pytest.skip("[needs:service=postgres] TINA4_TEST_PG_URL not set")
    return url, os.environ.get("TINA4_TEST_PG_USERNAME", ""), os.environ.get("TINA4_TEST_PG_PASSWORD", "")


def test_issue145_open_transaction_does_not_leak_to_a_concurrent_pooled_thread():
    url, user, password = _pg()
    db = Database(url, user, password, pool=4)

    db.execute("DROP TABLE IF EXISTS t4_issue145")
    db.execute("CREATE TABLE t4_issue145 (id INTEGER PRIMARY KEY, who VARCHAR(32))")

    a_inserted = threading.Event()   # A has INSERTed inside its transaction (uncommitted)
    b_done = threading.Event()       # B has finished its checks + its own write
    observed = {}

    def thread_a():
        db.start_transaction()
        db.execute("INSERT INTO t4_issue145 (id, who) VALUES (1, 'A-uncommitted')")
        a_inserted.set()
        # Hold the transaction open until B has read and written on its own
        # connection, then roll back — A's row must never land.
        b_done.wait(timeout=30)
        db.rollback()

    def thread_b():
        a_inserted.wait(timeout=30)
        # B borrows a DIFFERENT pooled connection. Under READ COMMITTED it must
        # not see A's uncommitted row, and it must NOT be inside A's transaction.
        rows = db.fetch("SELECT id FROM t4_issue145").records
        observed["ids_seen_by_b"] = sorted(r["id"] for r in rows)
        # B's own autocommit write on its own connection.
        db.execute("INSERT INTO t4_issue145 (id, who) VALUES (2, 'B-autocommit')")
        b_done.set()

    a = threading.Thread(target=thread_a)
    b = threading.Thread(target=thread_b)
    a.start(); b.start()
    a.join(timeout=60); b.join(timeout=60)
    assert not a.is_alive() and not b.is_alive(), "threads deadlocked (pool starvation?)"

    # 1 + 2: B never saw A's uncommitted row, so B was not sharing A's connection
    # or its transaction.
    assert observed.get("ids_seen_by_b") == [], (
        f"thread B saw {observed.get('ids_seen_by_b')!r} while A's transaction was "
        "open — the pool leaked A's connection into B (issue #145)"
    )

    # 3: A rolled back, so id=1 is gone; B's autocommit write (id=2) survived A's
    # rollback because it ran on its own connection.
    final = sorted(r["id"] for r in db.fetch("SELECT id FROM t4_issue145").records)
    assert 1 not in final, "A's rolled-back row survived — transaction was not isolated"
    assert final == [2], (
        f"expected only B's committed row [2], got {final!r} — B's write was rolled "
        "back with A's transaction (issue #145)"
    )

    db.execute("DROP TABLE IF EXISTS t4_issue145")
    db.close()
