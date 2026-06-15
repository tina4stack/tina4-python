"""Regression test for issue #51 — PostgreSQL idle-in-transaction leak.

psycopg2 runs with ``autocommit = False`` (the framework's safe default —
writes must be committed explicitly). A bare ``SELECT`` therefore opens a
transaction too; before v3.13.15 ``fetch()`` / ``fetch_one()`` never closed
it, so the connection sat ``idle in transaction`` for its whole life,
holding a pool slot and any locks it touched. Short-lived boot connections
(the migration runner's ``MAX(batch)`` lookup) leaked one each until
``max_connections`` was exhausted — then autodiscovery failed mid-boot and
every route 404'd while ``/health-check`` still passed ("ready but broken").

The fix: after a successful non-transactional read, roll back the implicit
transaction (a SELECT has nothing to persist). Inside an explicit
``start_transaction()`` the caller owns it, so we defer. Writes go through
``execute()`` and are deliberately left untouched — with autocommit off they
must be committed explicitly.

These tests need no live PostgreSQL. The ``_end_read_txn`` checks run with no
psycopg2 at all; the ``fetch`` wiring checks use a fake connection and stub
``psycopg2`` only when the optional driver isn't installed (so they still run
in CI, where the ``postgres`` extra is absent).
"""
import sys
import types

import pytest

from tina4_python.database.postgres import PostgreSQLAdapter


@pytest.fixture(autouse=True)
def _ensure_psycopg2(monkeypatch):
    """fetch()/fetch_one() do ``import psycopg2.extras``. The driver is an
    optional extra, so stub it when absent — the fake cursor ignores the
    cursor_factory anyway. Real psycopg2 is used untouched when present."""
    try:
        import psycopg2.extras  # noqa: F401
    except Exception:
        psycopg2 = types.ModuleType("psycopg2")
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        psycopg2.extras = extras
        monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


class FakeCursor:
    """Minimal psycopg2-cursor stand-in. Returns a count dict for the
    COUNT(*) probe in fetch(), and the supplied rows otherwise."""

    def __init__(self, rows):
        self._rows = rows
        self._last_sql = ""

    def execute(self, sql, params=None):
        self._last_sql = sql

    def fetchone(self):
        if "_count_subquery" in self._last_sql:
            return {"cnt": len(self._rows)}
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    @property
    def description(self):
        return [("col",)]


class FakeInfo:
    # 0 == TRANSACTION_STATUS_IDLE — never equals INERROR, so the
    # pre-flight heal step is a no-op and any rollback we observe is
    # purely from _end_read_txn().
    transaction_status = 0


class FakeConn:
    """Records rollback()/commit() so we can assert the implicit read
    transaction is closed exactly once."""

    def __init__(self, rows):
        self._rows = rows
        self.rollbacks = 0
        self.commits = 0
        self.info = FakeInfo()

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._rows)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


def _adapter(rows, in_transaction=False):
    adapter = PostgreSQLAdapter()
    adapter._conn = FakeConn(rows)
    adapter._in_transaction = in_transaction
    return adapter


# ── _end_read_txn() unit (no psycopg2 needed) ───────────────────────

def test_end_read_txn_rolls_back_when_implicit():
    adapter = _adapter([])
    adapter._end_read_txn()
    assert adapter._conn.rollbacks == 1


def test_end_read_txn_defers_inside_explicit_transaction():
    adapter = _adapter([], in_transaction=True)
    adapter._end_read_txn()
    assert adapter._conn.rollbacks == 0, (
        "Inside an explicit transaction the caller owns it — must not rollback."
    )


def test_end_read_txn_no_connection_is_safe():
    adapter = PostgreSQLAdapter()
    adapter._conn = None
    adapter._end_read_txn()  # must not raise


# ── fetch_one() / fetch() wiring ────────────────────────────────────

def test_fetch_one_closes_idle_transaction():
    adapter = _adapter([{"one": 1}])
    row = adapter.fetch_one("SELECT 1 AS one")
    assert row == {"one": 1}
    assert adapter._conn.rollbacks == 1, (
        "fetch_one must close the implicit read transaction (#51) so the "
        "connection doesn't sit idle-in-transaction."
    )


def test_fetch_one_defers_inside_explicit_transaction():
    adapter = _adapter([{"one": 1}], in_transaction=True)
    adapter.fetch_one("SELECT 1 AS one")
    assert adapter._conn.rollbacks == 0


def test_fetch_closes_idle_transaction():
    adapter = _adapter([{"one": 1}])
    result = adapter.fetch("SELECT 1 AS one")
    assert result.records == [{"one": 1}]
    assert adapter._conn.rollbacks == 1


def test_fetch_defers_inside_explicit_transaction():
    adapter = _adapter([{"one": 1}], in_transaction=True)
    adapter.fetch("SELECT 1 AS one")
    assert adapter._conn.rollbacks == 0
