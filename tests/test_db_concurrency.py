"""ADR-0074: a slow query never blocks unrelated requests, and concurrent requests
never share a connection or a transaction. On EVERY engine, on BOTH servers.

User report: "psycopg2 is blocking routes". MEASURED on origin/v3 (3.13.x) against
real engines on the built-in asyncio server AND uvicorn (benchmarks/db_concurrency.py):

  * a 2s query in an ``async def`` route made a no-DB /ping wait 3.6-3.8s: the
    sync driver ran ON the event loop, and fetch() ran the statement twice;
  * a 2s query in a ``def`` route made a second DB request wait 1.7-3.8s: the
    default single connection was shared, so requests queued on it;
  * a request that rolled back had its insert COMMITTED by a concurrent request's
    commit: both used the one connection and so the one transaction;
  * MySQL: concurrent use of the shared connection killed the server process;
    MSSQL and Firebird answered 500.

Every case boots a REAL Tina4 server in a subprocess against a REAL engine. The
slow statement is the engine's own sleep (pg_sleep, SLEEP, WAITFOR, a SQLite
function, Mongo's $where sleep); Firebird has none, so its slow statement waits on
a row lock this test holds for 2s from its own connection. No mocks.

Mutation-proof (each goes RED - see plan/db-async-concurrency.md for the record):
  * run the async API on the loop instead of a worker thread -> the async ping case
  * make ConnectionPool.checkout() hand out an adapter already lent out -> the
    rollback-isolation and concurrent-DB cases
  * make Database default to one connection -> the concurrent-DB case
"""
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import free_port
from db_engine_matrix import engines, required_engines_missing

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A probe fired 0.3s into a ~2s slow statement must come back this fast.
UNBLOCKED_SECONDS = 0.5

SLOW = {
    "sqlite": "SELECT t4_sleep(2) AS s",
    "postgres": "SELECT pg_sleep(2) AS s",
    "odbc": "SELECT pg_sleep(2) AS s",
    "mysql": "SELECT SLEEP(2) AS s",
    "mssql": "EXEC:WAITFOR DELAY '00:00:02'",
    "firebird": "EXEC:UPDATE t4conc_lock SET v = v + 1 WHERE id = 1",
    "mongodb": "MONGO:2000",
}
FAST = {
    "firebird": "SELECT 1 AS one FROM RDB$DATABASE",
    "mongodb": "SELECT * FROM t4conc_tx WHERE id = 999",
}

ROUTES = r'''
import asyncio, os, time
from tina4_python.core.router import get
from tina4_python.database import Database

ENGINE = os.environ["CONC_ENGINE"]
SLOW = os.environ["CONC_SLOW"]
FAST = os.environ["CONC_FAST"]
db = Database(os.environ["CONC_URL"], os.environ.get("CONC_USER", ""), os.environ.get("CONC_PASSWORD", ""))
if ENGINE == "sqlite":
    db.register_function("t4_sleep", 1, lambda s: (time.sleep(s), 1)[1], False)

def _mongo_sleep():
    db.adapter._collection("t4conc_tx").find_one({"$where": f"sleep({SLOW[6:]}) || true"})

def _slow_sync():
    if SLOW.startswith("EXEC:"):
        db.execute(SLOW[5:]); db.commit()
    elif SLOW.startswith("MONGO:"):
        _mongo_sleep()
    else:
        db.fetch(SLOW)

async def _slow_async():
    if SLOW.startswith("EXEC:"):
        await db.execute_async(SLOW[5:]); await db.commit_async()
    elif SLOW.startswith("MONGO:"):
        await db.run_async(_mongo_sleep)
    else:
        await db.fetch_async(SLOW)

def _row_id(request):
    return int(request.query.get("id", 0))

@get("/ping")
async def ping(request, response):
    return response({"ok": True})

@get("/slow/sync")
def slow_sync(request, response):
    _slow_sync(); return response({"ok": True})

@get("/slow/async")
async def slow_async(request, response):
    await _slow_async(); return response({"ok": True})

@get("/fast/sync")
def fast_sync(request, response):
    return response({"row": str(db.fetch_one(FAST))})

@get("/fast/async")
async def fast_async(request, response):
    return response({"row": str(await db.fetch_one_async(FAST))})

@get("/tx/hold/sync")
def tx_hold_sync(request, response):
    db.start_transaction()
    try:
        db.insert("t4conc_tx", {"id": _row_id(request), "label": "rolled-back"})
        time.sleep(1.2)
    finally:
        db.rollback()
    return response({"ok": True})

@get("/tx/commit/sync")
def tx_commit_sync(request, response):
    db.start_transaction()
    db.insert("t4conc_tx", {"id": _row_id(request), "label": "committed"})
    db.commit()
    return response({"ok": True})

@get("/tx/hold/async")
async def tx_hold_async(request, response):
    try:
        async with db.transaction_async():
            await db.insert_async("t4conc_tx", {"id": _row_id(request), "label": "rolled-back"})
            await asyncio.sleep(1.2)
            raise RuntimeError("roll this transaction back")
    except RuntimeError:
        pass
    return response({"ok": True})

@get("/tx/commit/async")
async def tx_commit_async(request, response):
    async with db.transaction_async():
        await db.insert_async("t4conc_tx", {"id": _row_id(request), "label": "committed"})
    return response({"ok": True})

@get("/tx/ids")
def tx_ids(request, response):
    rows = db.fetch("SELECT id FROM t4conc_tx", limit=1000).records
    return response({"ids": sorted(int(r.get("id", r.get("ID", 0)) or 0) for r in rows)})
'''


def _database(url, user, password):
    from tina4_python.database import Database
    return Database(url, user, password)


def _prepare(name, url, user, password):
    """Fresh probe tables on the real engine."""
    db = _database(url, user, password)
    try:
        for table in ("t4conc_tx", "t4conc_lock"):
            try:
                db.execute(f"DROP TABLE {table}")
                db.commit()
            except Exception:  # noqa: BLE001 - first run on this engine
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
        if name == "mongodb":
            db.adapter._collection("t4conc_tx").delete_many({})
            db.adapter._collection("t4conc_tx").insert_one({"id": 0, "label": "seed"})
            return
        db.execute("CREATE TABLE t4conc_tx (id INTEGER NOT NULL PRIMARY KEY, label VARCHAR(20))")
        db.execute("CREATE TABLE t4conc_lock (id INTEGER NOT NULL PRIMARY KEY, v INTEGER)")
        db.commit()
        db.execute("INSERT INTO t4conc_lock (id, v) VALUES (1, 0)")
        db.commit()
    finally:
        db.close()


def _get(port, path, timeout=60.0):
    started = time.monotonic()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        return res.status, res.read().decode(errors="replace"), time.monotonic() - started
    finally:
        conn.close()


def _stop(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


def _boot(root, port, server, name, url, user, password):
    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true", "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT), "TINA4_PORT": str(port),
        "TINA4_DEFAULT_WEBSERVER": "true" if server == "builtin" else "false",
        "CONC_ENGINE": name, "CONC_URL": url, "CONC_USER": user, "CONC_PASSWORD": password,
        "CONC_SLOW": SLOW[name], "CONC_FAST": FAST.get(name, "SELECT 1 AS one"),
    })
    env.pop("TINA4_DB_POOL", None)  # the DEFAULT is what is under test
    log = open(root / "server.log", "w")  # noqa: SIM115 - closed with the process
    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=str(root), env=env, start_new_session=True,
        stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"server died:\n{(root / 'server.log').read_text()}")
        try:
            if _get(port, "/ping", timeout=1)[0] == 200:
                return proc
        except OSError:
            pass
        time.sleep(0.2)
    _stop(proc)
    raise AssertionError(f"server never answered:\n{(root / 'server.log').read_text()}")


def _matrix():
    cases = []
    for server in ("builtin", "uvicorn"):
        for name, url, user, password in engines():
            cases.append(pytest.param((server, name, url, user, password), id=f"{name}-{server}"))
    return cases


@pytest.fixture(scope="module", params=_matrix())
def served(request, tmp_path_factory):
    """A real server on a real engine, booted once per (engine, server)."""
    server, name, url, user, password = request.param
    root = tmp_path_factory.mktemp(f"conc-{name}-{server}")
    if name == "sqlite":
        url = f"sqlite:///{root / 'conc.db'}"
    _prepare(name, url, user, password)
    (root / "src" / "routes").mkdir(parents=True)
    (root / "src" / "routes" / "conc.py").write_text(ROUTES)
    port = free_port()
    (root / "app.py").write_text(
        "from tina4_python.core.server import start\n"
        "if __name__ == '__main__':\n"
        f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )
    proc = _boot(root, port, server, name, url, user, password)
    try:
        yield {"port": port, "engine": name, "url": url, "user": user,
               "password": password, "root": root}
    finally:
        _stop(proc)


def _lock_holder(served):
    """Firebird has no sleep: hold the probe row's lock for 2s from our own connection."""
    if served["engine"] != "firebird":
        return None

    def hold():
        db = _database(served["url"], served["user"], served["password"])
        try:
            db.start_transaction()
            db.execute("UPDATE t4conc_lock SET v = v + 1 WHERE id = 1")
            time.sleep(2.0)
            db.rollback()
        finally:
            db.close()
    return threading.Thread(target=hold)


def _probe_during_slow(served, slow_path, probe_path):
    """(probe seconds, slow seconds) for probe_path fired 0.3s into slow_path."""
    port = served["port"]
    outcome = {}
    holder = _lock_holder(served)
    if holder:
        holder.start()
        time.sleep(0.3)
    slow = threading.Thread(target=lambda: outcome.setdefault("slow", _get(port, slow_path)))
    slow.start()
    time.sleep(0.3)
    status, body, seconds = _get(port, probe_path)
    slow.join()
    if holder:
        holder.join()
    slow_status, slow_body, slow_seconds = outcome["slow"]
    assert slow_status == 200, f"{slow_path} failed ({slow_status}): {slow_body[:400]}"
    assert status == 200, f"{probe_path} failed ({status}): {body[:400]}"
    # The slow statement really was slow - otherwise a fast probe proves nothing.
    assert slow_seconds >= 1.5, f"{slow_path} took only {slow_seconds:.2f}s; the probe proves nothing"
    return seconds


def test_every_ci_provisioned_engine_is_in_this_run():
    """Not collected is not the same as passed: a missing engine fails the gate."""
    missing = required_engines_missing()
    assert not missing, f"TINA4_REQUIRE_SERVICES=1 but these engines are not configured: {missing}"


def test_slow_query_through_the_async_api_does_not_block_a_no_db_request(served):
    seconds = _probe_during_slow(served, "/slow/async", "/ping")
    assert seconds < UNBLOCKED_SECONDS, (
        f"{served['engine']}: /ping waited {seconds:.2f}s behind an async-API slow query "
        f"- the event loop was blocked"
    )


def test_slow_query_in_a_def_route_does_not_block_a_no_db_request(served):
    seconds = _probe_during_slow(served, "/slow/sync", "/ping")
    assert seconds < UNBLOCKED_SECONDS, (
        f"{served['engine']}: /ping waited {seconds:.2f}s behind a def-route slow query"
    )


def test_a_concurrent_db_request_does_not_wait_for_the_slow_one_sync_api(served):
    seconds = _probe_during_slow(served, "/slow/sync", "/fast/sync")
    assert seconds < UNBLOCKED_SECONDS, (
        f"{served['engine']}: a fast def-route DB request waited {seconds:.2f}s for the "
        f"slow one - they shared a connection"
    )


def test_a_concurrent_db_request_does_not_wait_for_the_slow_one_async_api(served):
    seconds = _probe_during_slow(served, "/slow/async", "/fast/async")
    assert seconds < UNBLOCKED_SECONDS, (
        f"{served['engine']}: a fast async-API DB request waited {seconds:.2f}s for the "
        f"slow one - they shared a connection"
    )


@pytest.mark.parametrize("api", ["sync", "async"])
def test_rollback_isolation_between_concurrent_requests(served, api):
    """Request A inserts then rolls back; B inserts and commits WHILE A is open.

    With one shared connection, B's commit committed A's insert (A survived its own
    rollback). Only B's row may exist afterwards.
    """
    port = served["port"]
    base = 100 if api == "sync" else 200
    held = threading.Thread(target=_get, args=(port, f"/tx/hold/{api}?id={base + 1}"))
    held.start()
    time.sleep(0.3)
    status, body, _ = _get(port, f"/tx/commit/{api}?id={base + 2}")
    held.join()
    assert status == 200, body[:400]
    status, body, _ = _get(port, "/tx/ids")
    assert status == 200, body[:400]
    ids = [i for i in json.loads(body)["ids"] if base < i < base + 100]
    assert ids == [base + 2], (
        f"{served['engine']}: expected only the committed row {base + 2}, found {ids} - "
        f"the rolled-back request's insert leaked through a shared transaction"
    )
