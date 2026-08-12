"""Race-safe get_next_id() contract - feature 16 (nextid_contract.json).

Two duplicate-id bugs are locked out here, against REAL databases with REAL
concurrency (no mocks):

  * NEXTID-GENERIC-TOCTOU + NEXTID-PG-FIRSTUSE: the generic sequence fallback did
    an UPDATE then a SEPARATE SELECT (a TOCTOU: two concurrent callers read the
    same post-increment value and returned a DUPLICATE id), and the PostgreSQL
    first-use path let two concurrent first-callers each CREATE a separate
    sequence so the loser fell to that racy table and drew a duplicate from a
    second counter. Fixed: a single atomic ``UPDATE ... RETURNING`` in the
    fallback, and ``CREATE SEQUENCE IF NOT EXISTS`` + always-draw-from-nextval so
    every caller shares ONE counter.

  * NEXTID-MONGO-BROKEN: MongoDB now has a DEDICATED atomic path
    (``findOneAndUpdate($inc)`` keyed by ``_id``), monotonic and
    concurrency-safe, instead of falling through the relational path whose
    arithmetic ``+ 1`` UPDATE has no Mongo translation (the increment was
    dropped, so every call returned the same id).

Real services on the .99 lab: PostgreSQL :55432 (tina4/tina4), MySQL :3306
(tina4/tina4 -> tina4_test), MongoDB :27017. Under TINA4_REQUIRE_SERVICES a skip
here is a hard failure - these MUST run.

Mutation-proof: revert the fallback to UPDATE-then-separate-SELECT and
"concurrent generic sequence next id yields distinct ids" goes RED (a duplicate
under concurrency); revert the Mongo path to the non-incrementing relational
fallback and "mongo next id increments monotonically" goes RED (id2 == id1).
"""
import os
import socket
import threading
import uuid

import pytest

from tina4_python.database import Database

# ── real-service connection coordinates (the canonical TINA4_TEST_* convention) ──
_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)
_MYSQL = dict(
    host=os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306")),
    user=os.environ.get("TINA4_TEST_MYSQL_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test"),
)
_MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI", "mongodb://127.0.0.1:27017")
_MONGO_DB = "tina4_nextid_py"

_CONCURRENCY = 24


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _pg_url() -> str:
    return f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}"


def _mysql_url() -> str:
    return f"mysql://{_MYSQL['host']}:{_MYSQL['port']}/{_MYSQL['db']}"


def _mongo_url() -> str:
    base = _MONGO_URI.split("://", 1)[-1]
    scheme = _MONGO_URI.split("://", 1)[0]
    host = base.split("?", 1)[0].split("/", 1)[0]
    query = ("?" + _MONGO_URI.split("?", 1)[1]) if "?" in _MONGO_URI else ""
    return f"{scheme}://{host}/{_MONGO_DB}{query}"


def _mongo_reachable() -> bool:
    try:
        import pymongo  # noqa: F401
    except ImportError:
        return False
    host = _MONGO_URI.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    port = int((_MONGO_URI.split("://", 1)[-1].split("/", 1)[0].split(":") + ["27017"])[1])
    return _reachable(host, port)


needs_pg = pytest.mark.skipif(
    not _reachable(_PG["host"], _PG["port"]),
    reason=f"no reachable postgres at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)",
)
needs_mysql = pytest.mark.skipif(
    not _reachable(_MYSQL["host"], _MYSQL["port"]),
    reason=f"no reachable mysql at {_MYSQL['host']}:{_MYSQL['port']} (set TINA4_TEST_MYSQL_*)",
)
needs_mongo = pytest.mark.skipif(
    not _mongo_reachable(),
    reason=f"no reachable mongodb at {_MONGO_URI} (set TINA4_TEST_MONGO_URI)",
)


def _close(db) -> None:
    try:
        db.close()
    except Exception:
        try:
            db._get_adapter().close()
        except Exception:
            pass


def _hammer(make_call, n=_CONCURRENCY):
    """Run ``make_call()`` on n threads released together by a barrier, so the
    race window is as wide as possible. Returns (results, errors)."""
    results, errors = [], []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker():
        try:
            barrier.wait(timeout=15)
            value = make_call()
            with lock:
                results.append(value)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


# ── PostgreSQL: public get_next_id first-use + the direct generic fallback ──────

@needs_pg
def test_concurrent_get_next_id_on_a_fresh_table_yields_distinct_ids():
    """N concurrent get_next_id() on a FRESH postgres table (each caller its own
    connection) return N DISTINCT ids. Exercises the first-use sequence-create
    race: pre-fix the loser fell to a second counter and drew a duplicate."""
    table = f"nextid_fresh_{uuid.uuid4().hex[:10]}"
    admin = Database(_pg_url(), _PG["user"], _PG["pwd"])
    try:
        admin.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v VARCHAR(20))")
        admin.commit()

        def call():
            db = Database(_pg_url(), _PG["user"], _PG["pwd"])
            try:
                return db.get_next_id(table)
            finally:
                _close(db)

        results, errors = _hammer(call)
        assert errors == [], f"get_next_id raised under concurrency: {errors[:3]}"
        assert len(results) == _CONCURRENCY
        assert len(set(results)) == _CONCURRENCY, (
            f"DUPLICATE ids under concurrency: {sorted(results)}"
        )
    finally:
        try:
            admin.execute(f"DROP TABLE IF EXISTS {table}")
            admin.execute(f"DROP SEQUENCE IF EXISTS {table}_id_seq")
            admin.commit()
        except Exception:
            pass
        _close(admin)


@needs_pg
def test_concurrent_generic_sequence_next_id_yields_distinct_ids():
    """The generic sequence fallback (UPDATE ... RETURNING) is atomic: N
    concurrent callers against real postgres return N DISTINCT ids. This is the
    TOCTOU mutation target - reverting to UPDATE-then-separate-SELECT turns it
    RED. On postgres, Database._sequence_next() routes to the generic path."""
    seq = f"gen.{uuid.uuid4().hex[:10]}"
    admin = Database(_pg_url(), _PG["user"], _PG["pwd"])
    try:
        # Seed the tina4_sequences row once so every worker hits the atomic
        # increment (not a concurrent first-insert), isolating the TOCTOU.
        admin._sequence_next(seq, table=None, pk_column="id")

        def call():
            db = Database(_pg_url(), _PG["user"], _PG["pwd"])
            try:
                return db._sequence_next(seq, table=None, pk_column="id")
            finally:
                _close(db)

        results, errors = _hammer(call)
        assert errors == [], f"generic next-id raised under concurrency: {errors[:3]}"
        assert len(results) == _CONCURRENCY
        assert len(set(results)) == _CONCURRENCY, (
            f"DUPLICATE ids from the generic fallback under concurrency: {sorted(results)}"
        )
    finally:
        try:
            admin.execute("DELETE FROM tina4_sequences WHERE seq_name = ?", [seq])
            admin.commit()
        except Exception:
            pass
        _close(admin)


# ── MySQL: the tina4_sequences LAST_INSERT_ID path, under real concurrency ──────

@needs_mysql
def test_concurrent_get_next_id_on_mysql_yields_distinct_ids():
    """N concurrent get_next_id() on real MySQL (each caller its own connection)
    return N DISTINCT ids - proving the per-connection LAST_INSERT_ID sequence
    path is race-safe (previously only ever exercised on SQLite)."""
    table = f"nextid_my_{uuid.uuid4().hex[:8]}"
    admin = Database(_mysql_url(), _MYSQL["user"], _MYSQL["pwd"])
    try:
        admin.execute(f"DROP TABLE IF EXISTS {table}")
        admin.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v VARCHAR(20))")
        admin.commit()
        # Pre-create tina4_sequences + the row so workers race the increment,
        # not a concurrent CREATE TABLE.
        admin.get_next_id(table)

        def call():
            db = Database(_mysql_url(), _MYSQL["user"], _MYSQL["pwd"])
            try:
                return db.get_next_id(table)
            finally:
                _close(db)

        results, errors = _hammer(call)
        assert errors == [], f"get_next_id raised under concurrency: {errors[:3]}"
        assert len(results) == _CONCURRENCY
        assert len(set(results)) == _CONCURRENCY, (
            f"DUPLICATE ids under concurrency (mysql): {sorted(results)}"
        )
    finally:
        try:
            admin.execute("DELETE FROM tina4_sequences WHERE seq_name = ?", [f"{table}.id"])
            admin.execute(f"DROP TABLE IF EXISTS {table}")
            admin.commit()
        except Exception:
            pass
        _close(admin)


# ── MongoDB: the dedicated atomic findOneAndUpdate($inc) counter ────────────────

@needs_mongo
def test_mongo_next_id_increments_monotonically():
    """MongoDB get_next_id() ADVANCES: id2 > id1 across sequential calls. The
    strict '>' is the no-increment mutation target - the pre-fix relational
    fallback dropped the '+ 1' so every call returned the SAME id (id2 == id1)."""
    db = Database(_mongo_url())
    table = f"mono_{uuid.uuid4().hex[:10]}"
    try:
        id1 = db.get_next_id(table)
        id2 = db.get_next_id(table)
        id3 = db.get_next_id(table)
        assert id2 > id1, f"mongo next-id did not advance: id1={id1} id2={id2}"
        assert id3 > id2, f"mongo next-id did not advance: id2={id2} id3={id3}"
        assert len({id1, id2, id3}) == 3
    finally:
        try:
            db.execute(f"DROP TABLE {table}")
        except Exception:
            pass
        _close(db)


@needs_mongo
def test_concurrent_mongo_next_id_yields_distinct_ids():
    """N concurrent MongoDB get_next_id() calls (one shared client, as in
    production) return N DISTINCT ids - the atomic $inc counter is
    concurrency-safe."""
    db = Database(_mongo_url())
    table = f"conc_{uuid.uuid4().hex[:10]}"
    try:
        db.get_next_id(table)  # seed the counter once

        def call():
            return db.get_next_id(table)

        results, errors = _hammer(call)
        assert errors == [], f"mongo get_next_id raised under concurrency: {errors[:3]}"
        assert len(results) == _CONCURRENCY
        assert len(set(results)) == _CONCURRENCY, (
            f"DUPLICATE ids under concurrency (mongo): {sorted(results)}"
        )
    finally:
        try:
            db.execute(f"DROP TABLE {table}")
        except Exception:
            pass
        _close(db)
