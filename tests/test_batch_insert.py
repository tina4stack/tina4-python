"""Regression: adapter.insert() must accept a LIST of dicts (batch insert).

Each per-engine adapter overrides insert() and used to call ``data.keys()``
unconditionally, crashing on a list with ``'list' object has no attribute
'keys'`` -- even though ``Database.insert()`` and the docs advertise
``data: dict | list`` and the base ``DatabaseAdapter.insert()`` implements the
list case via ``execute_many``. Every override now delegates the list case to
``super().insert()``. These tests exercise a REAL batch insert end-to-end:
insert 3 rows from a list, read them back, and assert affected_rows / last_id.

SQLite always runs (temp file). PostgreSQL runs when reachable. MySQL / MSSQL
are not provisioned, so they skip cleanly (engines without local infra).
"""
from __future__ import annotations

import os
import socket
import tempfile

import pytest

from tina4_python.database import Database

ROWS = [
    {"name": "Alice", "age": 30},
    {"name": "Bob", "age": 25},
    {"name": "Eve", "age": 22},
]


def _assert_batch(db, create_sql, table="batch_people"):
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.commit()
    db.execute(create_sql)
    db.commit()
    try:
        result = db.insert(table, ROWS)   # the list path that used to crash
        db.commit()
        # affected_rows must report the whole batch (reliable across engines).
        assert result.affected_rows == 3, "all 3 rows must be inserted"
        # The rows must really be in the table — the definitive proof of insert.
        rows = db.fetch(f"SELECT name, age FROM {table} ORDER BY name").records
        assert [r["name"] for r in rows] == ["Alice", "Bob", "Eve"]
        assert [r["age"] for r in rows] == [30, 25, 22]
        # last_id for a BATCH is engine-dependent (SQLite reports the final
        # last_insert_rowid; PG/MySQL/MSSQL have no RETURNING in the batch INSERT,
        # so it may be None). When the driver DOES report it, it must be the real
        # id of the last inserted row.
        if result.last_id is not None:
            max_id = db.fetch(f"SELECT MAX(id) AS m FROM {table}").records[0]["m"]
            assert result.last_id == max_id, "last_id must be the final inserted row's id"

        # 3: a single-object insert is unaffected (one row, affected_rows == 1).
        single = db.insert(table, {"name": "Frank", "age": 40})
        db.commit()
        assert single.affected_rows == 1, "single-row insert affects exactly one row"
        assert db.fetch(f"SELECT COUNT(*) AS c FROM {table}").records[0]["c"] == 4

        # 4: an empty array is a 0-row no-op, not a crash (count unchanged).
        empty = db.insert(table, [])
        db.commit()
        assert empty.affected_rows == 0, "empty-array insert affects no rows"
        assert db.fetch(f"SELECT COUNT(*) AS c FROM {table}").records[0]["c"] == 4
    finally:
        db.execute(f"DROP TABLE IF EXISTS {table}")
        db.commit()


def _assert_atomic_rollback(db, create_sql, table="batch_rollback"):
    """Point 5 of the contract: a bad row (NULL into a NOT NULL column) rolls the
    WHOLE batch back as one transaction — no partial write. Kept as a dedicated
    helper on a FRESH table (matching the Ruby/PHP one-transaction-rollback test)
    so it never inherits transaction state from the contract run above."""
    try:
        db.rollback()  # clear any leftover txn state so the measurement is clean
    except Exception:
        pass
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.commit()
    db.execute(create_sql)
    db.commit()
    try:
        # db.insert fails loud (execute raises) and execute_many rolls the batch
        # back before the raise propagates, so nothing is left half-applied.
        with pytest.raises(Exception):
            db.insert(table, [
                {"name": "rb1", "age": 1},
                {"name": "rb2", "age": 2},
                {"name": None, "age": 3},  # violates NOT NULL
            ])
        try:
            db.rollback()  # clear the aborted-txn state for the read below
        except Exception:
            pass
        after = db.fetch(f"SELECT COUNT(*) AS c FROM {table}").records[0]["c"]
        assert after == 0, "a bad row must roll the whole batch back (no partial insert)"
    finally:
        db.execute(f"DROP TABLE IF EXISTS {table}")
        db.commit()


def test_sqlite_batch_insert_list_of_dicts():
    with tempfile.TemporaryDirectory() as d:
        db = Database("sqlite:///" + os.path.join(d, "batch.db"))
        _assert_batch(
            db,
            "CREATE TABLE batch_people (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER)",
        )
        _assert_atomic_rollback(
            db,
            "CREATE TABLE batch_rollback (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER)",
        )
        db.close()


# ── live PostgreSQL ─────────────────────────────────────────────
_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _reachable(_PG["host"], _PG["port"]),
                    reason="PostgreSQL not reachable (skip live batch-insert test)")
def test_postgres_batch_insert_list_of_dicts():
    db = Database(f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])
    try:
        _assert_batch(db, "CREATE TABLE batch_people (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, age INTEGER)")
        _assert_atomic_rollback(db, "CREATE TABLE batch_rollback (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, age INTEGER)")
    finally:
        db.close()


# ── MySQL / MSSQL: run against the live engine when reachable ──
# Mirror tests/test_database_drivers.py: build the connection from the discrete
# TINA4_TEST_MYSQL_* / _MSSQL_* vars the CI provisions (the *_URL var still works
# as an override), and gate on the driver being importable AND the service
# reachable. This is why the batch runs for real in CI (MySQL/MSSQL provisioned
# in #262) instead of skipping on the absent *_URL — previously it keyed only on
# TINA4_TEST_MYSQL_URL, which CI does not set, so the gate failed the run.
_MYSQL_HOST = os.environ.get("TINA4_TEST_MYSQL_HOST", "localhost")
_MYSQL_PORT = int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306"))
_MYSQL_USER = os.environ.get("TINA4_TEST_MYSQL_USERNAME", "root")
_MYSQL_PASS = os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "")
_MYSQL_DB = os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test")


def _mysql_url():
    return os.environ.get(
        "TINA4_TEST_MYSQL_URL", f"mysql://{_MYSQL_HOST}:{_MYSQL_PORT}/{_MYSQL_DB}"
    )


def _has_mysql_connector():
    try:
        import mysql.connector  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not (_has_mysql_connector() and _reachable(_MYSQL_HOST, _MYSQL_PORT)),
    reason=f"MySQL not reachable at {_MYSQL_HOST}:{_MYSQL_PORT} (or mysql-connector-python not installed)",
)
def test_mysql_batch_insert_list_of_dicts():
    db = Database(_mysql_url(), _MYSQL_USER, _MYSQL_PASS)
    try:
        _assert_batch(db, "CREATE TABLE batch_people (id INTEGER NOT NULL AUTO_INCREMENT, name VARCHAR(100) NOT NULL, age INTEGER, PRIMARY KEY(id))")
        _assert_atomic_rollback(db, "CREATE TABLE batch_rollback (id INTEGER NOT NULL AUTO_INCREMENT, name VARCHAR(100) NOT NULL, age INTEGER, PRIMARY KEY(id)) ENGINE=InnoDB")
    finally:
        db.close()


_MSSQL_HOST = os.environ.get("TINA4_TEST_MSSQL_HOST", "localhost")
_MSSQL_PORT = int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433"))
_MSSQL_USER = os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa")
_MSSQL_PASS = os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "")
_MSSQL_DB = os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test")


def _mssql_url():
    return os.environ.get(
        "TINA4_TEST_MSSQL_URL", f"mssql://{_MSSQL_HOST}:{_MSSQL_PORT}/{_MSSQL_DB}"
    )


def _has_pymssql():
    try:
        import pymssql  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not (_has_pymssql() and _reachable(_MSSQL_HOST, _MSSQL_PORT)),
    reason=f"MSSQL not reachable at {_MSSQL_HOST}:{_MSSQL_PORT} (or pymssql not installed)",
)
def test_mssql_batch_insert_list_of_dicts():
    db = Database(_mssql_url(), _MSSQL_USER, _MSSQL_PASS)
    try:
        _assert_batch(db, "CREATE TABLE batch_people (id INTEGER IDENTITY(1,1) NOT NULL, name VARCHAR(100) NOT NULL, age INTEGER, PRIMARY KEY(id))")
        _assert_atomic_rollback(db, "CREATE TABLE batch_rollback (id INTEGER IDENTITY(1,1) NOT NULL, name VARCHAR(100) NOT NULL, age INTEGER, PRIMARY KEY(id))")
    finally:
        db.close()
