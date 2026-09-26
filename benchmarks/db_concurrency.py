"""Database concurrency probe - ADR-0074.

Boots a REAL Tina4 server (the built-in asyncio server or uvicorn) against a REAL
database and measures what a slow query does to every other request:

  ping      latency of a no-DB request while a slow query runs
  db        latency of a second, fast DB request while a slow query runs
  tx        do two concurrent requests share a transaction? (A rolls back, B commits)
  fetch     how long a fetch() of a 1s statement takes (2s = it ran twice)

Each slow query is started first; the probe fires 0.3s later. The slow query takes
~2s, so a probe that returns in well under a second was NOT blocked by it.

    python benchmarks/db_concurrency.py --engine postgres \
        --url postgresql://localhost:55432/tina4_py --user tina4 --password tina4 \
        --server builtin

Runs against any tina4-python checkout: the async-API rows are reported as "n/a"
when the checkout has no async API (the before-picture). The server is started in
its own process group and killed on exit, including on Ctrl-C.
"""
import argparse
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-engine SQL. "slow" takes ~2s, "fetch1" takes ~1s through fetch().
ENGINE_SQL = {
    "sqlite": {"slow": "SELECT t4_sleep(2) AS s", "fetch1": "SELECT t4_sleep(1) AS s",
               "fast": "SELECT 1 AS one"},
    "postgres": {"slow": "SELECT pg_sleep(2) AS s", "fetch1": "SELECT pg_sleep(1) AS s",
                 "fast": "SELECT 1 AS one"},
    "odbc": {"slow": "SELECT pg_sleep(2) AS s", "fetch1": "SELECT pg_sleep(1) AS s",
             "fast": "SELECT 1 AS one"},
    "mysql": {"slow": "SELECT SLEEP(2) AS s", "fetch1": "SELECT SLEEP(1) AS s",
              "fast": "SELECT 1 AS one"},
    "mssql": {"slow": "EXEC:WAITFOR DELAY '00:00:02'", "fetch1": None,
              "fast": "SELECT 1 AS one"},
    # Firebird has no sleep: the slow statement waits on a row lock the probe
    # holds for 2s from its own connection.
    "firebird": {"slow": "EXEC:UPDATE t4probe_lock SET v = v + 1 WHERE id = 1",
                 "fetch1": None, "fast": "SELECT 1 AS one FROM RDB$DATABASE"},
    "mongodb": {"slow": "MONGO:2000", "fetch1": None,
                "fast": "SELECT * FROM t4probe_tx WHERE id = 999"},
}

ROUTES = r'''
import asyncio, os, time
from tina4_python.core.router import get, noauth
from tina4_python.database import Database

ENGINE = os.environ["PROBE_ENGINE"]
SLOW = os.environ["PROBE_SLOW"]
FETCH1 = os.environ.get("PROBE_FETCH1") or ""
FAST = os.environ["PROBE_FAST"]
db = Database(os.environ["PROBE_URL"], os.environ.get("PROBE_USER", ""), os.environ.get("PROBE_PASSWORD", ""))
HAS_ASYNC = hasattr(db, "fetch_async")

if ENGINE == "sqlite":
    db.register_function("t4_sleep", 1, lambda s: (time.sleep(s), 1)[1], False)

def _slow_sync():
    if SLOW.startswith("EXEC:"):
        db.execute(SLOW[5:]); db.commit()
    elif SLOW.startswith("MONGO:"):
        db.adapter._collection("t4probe_tx").find_one({"$where": f"sleep({SLOW[6:]}) || true"})
    else:
        db.fetch(SLOW)

async def _slow_async():
    if SLOW.startswith("EXEC:"):
        await db.execute_async(SLOW[5:]); await db.commit_async()
    elif SLOW.startswith("MONGO:"):
        await db.run_async(lambda: db.adapter._collection("t4probe_tx").find_one(
            {"$where": f"sleep({SLOW[6:]}) || true"}))
    else:
        await db.fetch_async(SLOW)

@get("/ping")
async def ping(request, response):
    return response({"ok": True})

@get("/slow/async-route-sync-api")
async def slow_a(request, response):
    _slow_sync(); return response({"ok": True})

@get("/slow/def-route-sync-api")
def slow_b(request, response):
    _slow_sync(); return response({"ok": True})

@get("/slow/async-route-async-api")
async def slow_c(request, response):
    if not HAS_ASYNC: return response({"na": True}, 501)
    await _slow_async(); return response({"ok": True})

@get("/fast/def-route-sync-api")
def fast_b(request, response):
    return response({"row": str(db.fetch_one(FAST))})

@get("/fast/async-route-async-api")
async def fast_c(request, response):
    if not HAS_ASYNC: return response({"na": True}, 501)
    return response({"row": str(await db.fetch_one_async(FAST))})

@get("/fetch1")
def fetch1(request, response):
    if not FETCH1: return response({"na": True}, 501)
    started = time.monotonic(); db.fetch(FETCH1)
    return response({"seconds": round(time.monotonic() - started, 3)})

@get("/tx/hold")
def tx_hold(request, response):
    db.start_transaction()
    try:
        db.insert("t4probe_tx", {"id": 1, "label": "A"})
        time.sleep(1.2)
    finally:
        db.rollback()
    return response({"ok": True})

@get("/tx/commit")
def tx_commit(request, response):
    db.insert("t4probe_tx", {"id": 2, "label": "B"}); db.commit()
    return response({"ok": True})

@get("/tx/rows")
def tx_rows(request, response):
    rows = db.fetch("SELECT id, label FROM t4probe_tx", limit=100).records
    return response({"ids": sorted(int(r.get("id", r.get("ID", 0)) or 0) for r in rows)})
'''


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(port: int, path: str, timeout: float = 60.0):
    started = time.monotonic()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        body = res.read().decode(errors="replace")
        return res.status, body, time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - a probe failure is a data point
        return 0, f"{type(exc).__name__}: {exc}", time.monotonic() - started
    finally:
        conn.close()


def _during(port: int, slow_path: str, probe_path: str, lock_holder=None):
    """Latency of probe_path fired 0.3s into slow_path."""
    outcome = {}
    slow = threading.Thread(target=lambda: outcome.setdefault("slow", _get(port, slow_path)))
    if lock_holder:
        lock_holder.start()
        time.sleep(0.2)
    slow.start()
    time.sleep(0.3)
    status, body, seconds = _get(port, probe_path)
    slow.join()
    if lock_holder:
        lock_holder.join()
    if outcome["slow"][0] == 501 or status == 501:
        return "n/a"
    if status != 200 or outcome["slow"][0] != 200:
        return f"ERR {status}/{outcome['slow'][0]}: {(body or outcome['slow'][1])[:80]}"
    return f"{seconds:.2f}s"


def _database(args):
    sys.path.insert(0, str(REPO_ROOT))
    from tina4_python.database import Database
    return Database(args.url, args.user, args.password)


def _prepare(args) -> None:
    db = _database(args)
    for table in ("t4probe_tx", "t4probe_lock"):
        try:
            db.execute(f"DROP TABLE {table}"); db.commit()
        except Exception:  # noqa: BLE001 - first run
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    if args.engine != "mongodb":
        db.execute("CREATE TABLE t4probe_tx (id INTEGER NOT NULL PRIMARY KEY, label VARCHAR(10))")
        db.execute("CREATE TABLE t4probe_lock (id INTEGER NOT NULL PRIMARY KEY, v INTEGER)")
        db.commit()
        db.execute("INSERT INTO t4probe_lock (id, v) VALUES (1, 0)")
        db.commit()
    db.close()


def _lock_holder(args):
    """Hold the Firebird probe row lock for 2s from a separate connection."""
    def hold():
        db = _database(args)
        db.start_transaction()
        db.execute("UPDATE t4probe_lock SET v = v + 1 WHERE id = 1")
        time.sleep(2.0)
        db.rollback()
        db.close()
    return threading.Thread(target=hold)


def _boot(args, root: Path, port: int) -> subprocess.Popen:
    sql = ENGINE_SQL[args.engine]
    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true", "TINA4_NO_BROWSER": "true", "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT), "TINA4_PORT": str(port),
        "TINA4_DEFAULT_WEBSERVER": "true" if args.server == "builtin" else "false",
        "PROBE_ENGINE": args.engine, "PROBE_URL": args.url, "PROBE_USER": args.user or "",
        "PROBE_PASSWORD": args.password or "", "PROBE_SLOW": sql["slow"],
        "PROBE_FETCH1": sql["fetch1"] or "", "PROBE_FAST": sql["fast"],
    })
    proc = subprocess.Popen(
        [sys.executable, "app.py"], cwd=str(root), env=env, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"server died:\n{proc.stdout.read()}")
        status, _, _ = _get(port, "/ping", timeout=1)
        if status == 200:
            return proc
        time.sleep(0.3)
    _stop(proc)
    raise SystemExit("server never answered /ping")


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=sorted(ENGINE_SQL))
    parser.add_argument("--url", required=True)
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--server", default="builtin", choices=("builtin", "uvicorn"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    _prepare(args)
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="t4-dbconc-") as tmp:
        root = Path(tmp)
        (root / "src" / "routes").mkdir(parents=True)
        (root / "src" / "routes" / "probe.py").write_text(ROUTES)
        (root / "app.py").write_text(
            "from tina4_python.core.server import start\n"
            "if __name__ == '__main__':\n"
            f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
        )
        proc = _boot(args, root, port)
        try:
            lock = (lambda: _lock_holder(args)) if args.engine == "firebird" else (lambda: None)
            row = {"engine": args.engine, "server": args.server}
            print(f"[{args.engine}/{args.server}] measuring...", file=sys.stderr, flush=True)
            row["ping|async-route-sync-api"] = _during(port, "/slow/async-route-sync-api", "/ping", lock())
            row["ping|def-route-sync-api"] = _during(port, "/slow/def-route-sync-api", "/ping", lock())
            row["ping|async-route-async-api"] = _during(port, "/slow/async-route-async-api", "/ping", lock())
            row["db|def-route-sync-api"] = _during(port, "/slow/def-route-sync-api", "/fast/def-route-sync-api", lock())
            row["db|async-route-async-api"] = _during(port, "/slow/async-route-async-api", "/fast/async-route-async-api", lock())
            status, body, _ = _get(port, "/fetch1")
            row["fetch(1s stmt)"] = (f"{json.loads(body)['seconds']:.2f}s" if status == 200 else "n/a")
            threads = [threading.Thread(target=_get, args=(port, "/tx/hold"))]
            threads[0].start(); time.sleep(0.3)
            _get(port, "/tx/commit"); threads[0].join()
            status, body, _ = _get(port, "/tx/rows")
            ids = json.loads(body).get("ids", []) if status == 200 else body[:60]
            row["tx isolation"] = "ok" if ids == [2] else f"BROKEN ids={ids}"
        finally:
            _stop(proc)
    print(json.dumps(row) if args.json else "\n".join(f"  {k:28} {v}" for k, v in row.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
