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
    finally:
        db.execute(f"DROP TABLE IF EXISTS {table}")
        db.commit()


def test_sqlite_batch_insert_list_of_dicts():
    with tempfile.TemporaryDirectory() as d:
        db = Database("sqlite:///" + os.path.join(d, "batch.db"))
        _assert_batch(
            db,
            "CREATE TABLE batch_people (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER)",
        )
        db.close()


# ── live PostgreSQL ─────────────────────────────────────────────
_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USER", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASS", "tina4"),
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
        _assert_batch(db, "CREATE TABLE batch_people (id SERIAL PRIMARY KEY, name VARCHAR(100), age INTEGER)")
    finally:
        db.close()


# ── MySQL / MSSQL: not provisioned locally -> skip cleanly ──────
def _mysql_url():
    return os.environ.get("TINA4_TEST_MYSQL_URL")


def _has_mysql_connector():
    try:
        import mysql.connector  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not (_has_mysql_connector() and _mysql_url()),
                    reason="MySQL not configured (TINA4_TEST_MYSQL_URL) / driver not installed")
def test_mysql_batch_insert_list_of_dicts():
    db = Database(_mysql_url(),
                  os.environ.get("TINA4_TEST_MYSQL_USER", "root"),
                  os.environ.get("TINA4_TEST_MYSQL_PASS", ""))
    try:
        _assert_batch(db, "CREATE TABLE batch_people (id INTEGER NOT NULL AUTO_INCREMENT, name VARCHAR(100), age INTEGER, PRIMARY KEY(id))")
    finally:
        db.close()


def _mssql_url():
    return os.environ.get("TINA4_TEST_MSSQL_URL")


def _has_pymssql():
    try:
        import pymssql  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not (_has_pymssql() and _mssql_url()),
                    reason="MSSQL not configured (TINA4_TEST_MSSQL_URL) / driver not installed")
def test_mssql_batch_insert_list_of_dicts():
    db = Database(_mssql_url(),
                  os.environ.get("TINA4_TEST_MSSQL_USER", "sa"),
                  os.environ.get("TINA4_TEST_MSSQL_PASS", ""))
    try:
        _assert_batch(db, "CREATE TABLE batch_people (id INTEGER IDENTITY(1,1) NOT NULL, name VARCHAR(100), age INTEGER, PRIMARY KEY(id))")
    finally:
        db.close()
