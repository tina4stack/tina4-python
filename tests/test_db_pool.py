"""ADR-0074: the connection pool lends each connection to ONE borrower at a time.

MEASURED on origin/v3: ``ConnectionPool.checkout()`` rotated round-robin and
``checkin()`` was a no-op, so the same adapter was handed to several threads at
once; and the default (``pool=0``) shared ONE connection between every request.
Concurrent requests therefore queued on one connection AND shared its transaction.

Every case runs a real SQLite file database (and PostgreSQL where the property is
engine-specific). No mocks: the "in use" bookkeeping below is the test's own record
of what the REAL pool handed out, checked for overlap.
"""
import asyncio
import os
import threading
import time

import pytest

from tina4_python.database import Database
from tina4_python.database.connection import DatabasePoolExhausted


@pytest.fixture
def sqlite_url(tmp_path):
    return f"sqlite:///{tmp_path / 'pool.db'}"


def _make_table(db):
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
    db.commit()


# ── Sizing ─────────────────────────────────────────────────────────────────────

def test_default_pool_is_bounded_and_larger_than_one(monkeypatch, sqlite_url):
    """The default must let concurrent requests run side by side (ADR-0074: 10)."""
    monkeypatch.delenv("TINA4_DB_POOL", raising=False)
    db = Database(sqlite_url)
    try:
        assert db.pool is not None
        assert db.pool.size == 10
    finally:
        db.close()


def test_pool_zero_means_one_exclusively_lent_connection(monkeypatch, sqlite_url):
    monkeypatch.setenv("TINA4_DB_POOL", "0")
    db = Database(sqlite_url)
    try:
        assert db.pool.size == 1
    finally:
        db.close()


def test_explicit_pool_argument_beats_the_environment(monkeypatch, sqlite_url):
    monkeypatch.setenv("TINA4_DB_POOL", "8")
    db = Database(sqlite_url, pool=3)
    try:
        assert db.pool.size == 3
    finally:
        db.close()


def test_in_memory_sqlite_is_one_connection(monkeypatch):
    """Every sqlite ``:memory:`` connection is a DIFFERENT, empty database, so a
    pool of them would lose the table between two statements."""
    monkeypatch.delenv("TINA4_DB_POOL", raising=False)
    db = Database("sqlite::memory:")
    try:
        assert db.pool.size == 1
        _make_table(db)
        db.insert("items", {"id": 1, "label": "kept"})
        db.commit()

        results = []
        workers = [threading.Thread(target=lambda: results.append(
            db.fetch_one("SELECT label FROM items WHERE id = 1")["label"])) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert results == ["kept"] * 4
    finally:
        db.close()


# ── Exclusive lending ──────────────────────────────────────────────────────────

def test_a_connection_is_never_lent_to_two_borrowers_at_once(sqlite_url):
    db = Database(sqlite_url, pool=3)
    in_use: set[int] = set()
    overlaps: list[int] = []
    guard = threading.Lock()

    def borrow():
        for _ in range(20):
            adapter = db.checkout()
            with guard:
                if id(adapter) in in_use:
                    overlaps.append(id(adapter))
                in_use.add(id(adapter))
            time.sleep(0.002)
            with guard:
                in_use.discard(id(adapter))
            db.checkin(adapter)

    try:
        workers = [threading.Thread(target=borrow) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert overlaps == [], f"an adapter was lent to two borrowers at once {len(overlaps)} times"
        assert db.pool.active_count <= 3
    finally:
        db.close()


def test_every_facade_call_returns_its_connection(sqlite_url):
    db = Database(sqlite_url, pool=2)
    try:
        _make_table(db)
        for n in range(50):
            db.insert("items", {"id": n, "label": "x"})
            db.fetch("SELECT * FROM items", limit=5)
            db.fetch_one("SELECT COUNT(*) AS c FROM items")
        assert db.pool.in_use_count == 0
    finally:
        db.close()


def test_a_transaction_keeps_one_connection_until_commit(sqlite_url):
    db = Database(sqlite_url, pool=3)
    try:
        _make_table(db)
        db.start_transaction()
        assert db.pool.in_use_count == 1
        pinned = db.adapter
        for n in range(5):
            db.insert("items", {"id": n, "label": "tx"})
            assert db.adapter is pinned
        db.commit()
        assert db.pool.in_use_count == 0
        assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 5
    finally:
        db.close()


def test_transactions_on_two_threads_are_isolated(tmp_path):
    """Thread A rolls back while thread B commits; only B's row survives."""
    db = Database(f"sqlite:///{tmp_path / 'iso.db'}", pool=4)
    try:
        _make_table(db)
        a_inserted = threading.Event()

        def thread_a():
            db.start_transaction()
            db.insert("items", {"id": 1, "label": "rolled-back"})
            a_inserted.set()
            time.sleep(0.3)
            db.rollback()

        worker = threading.Thread(target=thread_a)
        worker.start()
        a_inserted.wait(5)
        db.start_transaction()
        db.insert("items", {"id": 2, "label": "committed"})
        db.commit()
        worker.join()
        ids = [r["id"] for r in db.fetch("SELECT id FROM items ORDER BY id").records]
        assert ids == [2]
    finally:
        db.close()


def test_sqlite_standalone_writer_never_deadlocks_an_open_transaction(sqlite_url):
    """A standalone write waiting on a transaction must not block that transaction.

    The standalone writer holds the process write lock while SQLite makes it wait
    for the open transaction. If the transaction's own next write needed that
    lock too, both would stall until busy_timeout (30s).
    """
    db = Database(sqlite_url, pool=3)
    _make_table(db)
    in_transaction = threading.Event()
    errors = []

    def transaction():
        try:
            db.start_transaction()
            db.insert("items", {"id": 1, "label": "first"})
            in_transaction.set()
            time.sleep(0.3)  # the standalone writer is now waiting on us
            db.insert("items", {"id": 2, "label": "second"})
            db.commit()
        except Exception as error:  # noqa: BLE001 - reported below
            errors.append(error)

    def standalone():
        in_transaction.wait(5)
        try:
            db.insert("items", {"id": 3, "label": "standalone"})
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    try:
        workers = [threading.Thread(target=transaction), threading.Thread(target=standalone)]
        started = time.monotonic()
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
        assert time.monotonic() - started < 5, "the writers deadlocked until busy_timeout"
        assert errors == []
        assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 3
    finally:
        db.close()


def test_sqlite_transaction_that_reads_first_can_still_write(sqlite_url):
    """A transaction reads, another connection writes, the transaction then writes.

    A DEFERRED begin fails the last write with "database is locked" (its read
    snapshot is stale). BEGIN IMMEDIATE holds the write lock from the start, so
    the other writer waits for the commit instead.
    """
    db = Database(sqlite_url, pool=3)
    _make_table(db)
    db.insert("items", {"id": 1, "label": "seed"})
    read_done = threading.Event()
    errors = []

    def transaction():
        try:
            db.start_transaction()
            db.fetch_one("SELECT COUNT(*) AS c FROM items")
            read_done.set()
            time.sleep(0.3)
            db.update("items", {"label": "changed"}, "id = ?", [1])
            db.commit()
        except Exception as error:  # noqa: BLE001 - reported below
            errors.append(error)
            db.rollback()

    def other_writer():
        read_done.wait(5)
        db.insert("items", {"id": 2, "label": "other"})

    try:
        workers = [threading.Thread(target=transaction), threading.Thread(target=other_writer)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
        assert errors == [], f"the transaction's write failed: {errors}"
        assert db.fetch_one("SELECT label FROM items WHERE id = 1")["label"] == "changed"
        assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 2
    finally:
        db.close()


def test_checkin_rolls_back_a_transaction_the_borrower_left_open(sqlite_url):
    """A connection must never go back to the pool mid-transaction."""
    db = Database(sqlite_url, pool=1)
    try:
        _make_table(db)
        adapter = db.checkout()
        adapter.start_transaction()
        adapter.execute("INSERT INTO items (id, label) VALUES (1, 'abandoned')")
        db.checkin(adapter)
        assert db.fetch_one("SELECT COUNT(*) AS c FROM items")["c"] == 0
    finally:
        db.close()


# ── Per-request state: get_last_id() / get_error() ─────────────────────────────

def test_get_last_id_is_per_thread_not_shared_between_requests(tmp_path):
    """Thread A inserts, thread B inserts, THEN A reads get_last_id(): A's own id.

    The last id lived on the shared Database object, so a concurrent request's
    insert overwrote it and A read B's row id.
    """
    db = Database(f"sqlite:///{tmp_path / 'lastid.db'}", pool=3)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT)")
    a_inserted, b_inserted = threading.Event(), threading.Event()
    seen = {}

    def request_a():
        db.execute("INSERT INTO items (label) VALUES ('a')")
        a_inserted.set()
        b_inserted.wait(5)
        seen["a"] = db.get_last_id()

    def request_b():
        a_inserted.wait(5)
        db.execute("INSERT INTO items (label) VALUES ('b')")
        seen["b"] = db.get_last_id()
        b_inserted.set()

    try:
        workers = [threading.Thread(target=request_a), threading.Thread(target=request_b)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
        assert seen == {"a": 1, "b": 2}, seen
    finally:
        db.close()


def test_get_last_id_and_get_error_follow_the_async_api(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'lastid_async.db'}", pool=2)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT)")

    async def main():
        await db.execute_async("INSERT INTO items (label) VALUES ('x')")
        first = db.get_last_id()
        with pytest.raises(Exception):
            await db.execute_async("INSERT INTO no_such_table (label) VALUES ('y')")
        return first, db.get_error()

    try:
        last_id, error = asyncio.run(main())
        assert last_id == 1
        assert error and "no_such_table" in error
    finally:
        db.close()


# ── Exhaustion ─────────────────────────────────────────────────────────────────

def test_pool_exhaustion_raises_a_clear_error_naming_tina4_db_pool(monkeypatch, sqlite_url):
    monkeypatch.setenv("TINA4_DB_POOL_TIMEOUT", "0.3")
    db = Database(sqlite_url, pool=1)
    held = db.checkout()
    try:
        started = time.monotonic()
        with pytest.raises(DatabasePoolExhausted) as caught:
            db.fetch_one("SELECT 1 AS one")
        waited = time.monotonic() - started
        message = str(caught.value)
        # Names the variable AND its current value, and the timeout variable.
        assert "TINA4_DB_POOL=1" in message, message
        assert "TINA4_DB_POOL_TIMEOUT=0.3s" in message, message
        assert isinstance(caught.value, TimeoutError)
        assert 0.25 <= waited < 3, f"waited {waited:.2f}s for a 0.3s timeout"
    finally:
        db.checkin(held)
        db.close()


def test_pool_exhaustion_raises_the_same_error_on_the_async_api(monkeypatch, sqlite_url):
    monkeypatch.setenv("TINA4_DB_POOL_TIMEOUT", "0.3")
    db = Database(sqlite_url, pool=1)
    held = db.checkout()
    try:
        with pytest.raises(DatabasePoolExhausted, match=r"TINA4_DB_POOL=1\b"):
            asyncio.run(db.fetch_one_async("SELECT 1 AS one"))
    finally:
        db.checkin(held)
        db.close()


def test_a_waiting_borrower_gets_the_connection_the_moment_it_is_returned(sqlite_url):
    db = Database(sqlite_url, pool=1)
    held = db.checkout()
    got = []
    try:
        waiter = threading.Thread(target=lambda: got.append(db.fetch_one("SELECT 7 AS n")["n"]))
        waiter.start()
        time.sleep(0.2)
        assert got == []
        db.checkin(held)
        waiter.join(5)
        assert got == [7]
    finally:
        db.close()


# ── Async API: task-local transactions, cancellation ───────────────────────────

def test_async_transactions_on_two_tasks_are_isolated(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'aiso.db'}", pool=4)

    async def rolled_back(started):
        try:
            async with db.transaction_async():
                await db.insert_async("items", {"id": 1, "label": "rolled-back"})
                started.set()
                await asyncio.sleep(0.3)
                raise RuntimeError("roll back")
        except RuntimeError:
            pass

    async def committed(started):
        await started.wait()
        async with db.transaction_async():
            await db.insert_async("items", {"id": 2, "label": "committed"})

    async def main():
        started = asyncio.Event()
        await asyncio.gather(rolled_back(started), committed(started))
        return [r["id"] for r in (await db.fetch_async("SELECT id FROM items ORDER BY id")).records]

    try:
        _make_table(db)
        assert asyncio.run(main()) == [2]
        assert db.pool.in_use_count == 0
    finally:
        db.close()


def test_a_cancelled_async_call_still_returns_its_connection(sqlite_url):
    db = Database(sqlite_url, pool=1)
    db.register_function("t4_sleep", 1, lambda s: (time.sleep(s), 1)[1], False)

    async def main():
        task = asyncio.create_task(db.fetch_async("SELECT t4_sleep(0.4) AS s"))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The statement finishes on its worker; the connection must come back.
        return (await db.fetch_one_async("SELECT 3 AS n"))["n"]

    try:
        assert asyncio.run(main()) == 3
        assert db.pool.in_use_count == 0
    finally:
        db.close()


# ── Debug warning: a sync DB call on an event-loop thread ─────────────────────

def _call_sync_api_on_the_loop(db, route_label, times=2):
    from tina4_python.database.connection import current_route

    async def handler():
        token = current_route.set(route_label)
        try:
            for _ in range(times):
                db.fetch_one("SELECT 1 AS one")
        finally:
            current_route.reset(token)

    asyncio.run(handler())


def test_debug_warns_once_per_route_for_a_sync_call_on_the_event_loop(monkeypatch, capsys, sqlite_url):
    monkeypatch.setenv("TINA4_DEBUG", "true")
    db = Database(sqlite_url)
    try:
        capsys.readouterr()
        _call_sync_api_on_the_loop(db, "GET /reports/slow")
        _call_sync_api_on_the_loop(db, "GET /reports/slow")
        out = capsys.readouterr().out
        assert out.count("GET /reports/slow") == 1, out
        assert "fetch_one_async" in out and "def" in out, out
        _call_sync_api_on_the_loop(db, "GET /other")
        assert capsys.readouterr().out.count("GET /other") == 1
    finally:
        db.close()


def test_no_warning_outside_debug_or_off_the_loop(monkeypatch, capsys, sqlite_url):
    db = Database(sqlite_url)
    try:
        monkeypatch.setenv("TINA4_DEBUG", "false")
        capsys.readouterr()
        _call_sync_api_on_the_loop(db, "GET /quiet")
        assert "GET /quiet" not in capsys.readouterr().out

        monkeypatch.setenv("TINA4_DEBUG", "true")

        async def from_a_worker_thread():
            await asyncio.to_thread(db.fetch_one, "SELECT 1 AS one")
            await db.fetch_one_async("SELECT 1 AS one")

        asyncio.run(from_a_worker_thread())
        assert "event loop" not in capsys.readouterr().out
    finally:
        db.close()


# ── PostgreSQL: the engine the report came from ────────────────────────────────

_PG_URL = os.environ.get("TINA4_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not _PG_URL, reason="postgres not configured (set TINA4_TEST_PG_URL)")


@needs_pg
def test_postgres_pooled_connections_are_distinct_server_sessions():
    """Two concurrent borrowers hold two different backend sessions."""
    db = Database(_PG_URL, os.environ.get("TINA4_TEST_PG_USERNAME", ""),
                  os.environ.get("TINA4_TEST_PG_PASSWORD", ""), pool=2)
    pids = []
    barrier = threading.Barrier(2)

    def session_pid():
        db.start_transaction()
        try:
            pids.append(db.fetch_one("SELECT pg_backend_pid() AS pid")["pid"])
            barrier.wait(5)
        finally:
            db.rollback()

    try:
        workers = [threading.Thread(target=session_pid) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert len(set(pids)) == 2, f"both borrowers ran on one backend session: {pids}"
    finally:
        db.close()
