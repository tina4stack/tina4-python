"""MSSQL provider contract - feature 11 (mssqlprovider_contract.json).

MSSQL-DEC-01 + MSSQL-DEC-02 (OWNER-DECISIONS.md Batch 5, feature doc
011-mssql-provider.md). Every case drives the lab's REAL SQL Server :1433
(sa -> tina4_test) through the public Database facade -> MSSQLAdapter. No mocks.
Durability is read back on a SECOND, FRESH connection where that is the property.
Under TINA4_REQUIRE_SERVICES a skip here is a hard FAILURE - these MUST run.

MSSQL-DEC-02 (real-PK RETURNING emulation): SQL Server has no RETURNING, so the
Python adapter strips it and re-selects the inserted row. It used to fetch by a
HARDCODED `id` column (`... WHERE id = %s`), so a table whose primary key is NOT
named `id` raised "Invalid column name 'id'". It now re-selects by the table's
REAL primary key (introspected, bracket-quoted, cached). The `returning_*` tests
below are the direct mutation witness for that fix - Python-only, because only
the Python adapter emulates MSSQL RETURNING; PHP/Ruby/Node surface the generated
key through SCOPE_IDENTITY, which is column-name-independent and already correct
(the four-way invariant `mssql-nonid-pk-generated-id`).

MSSQL-DEC-01 (safe parameter handling): a binary parameter round-trips (Node
VarBinary; Python pymssql binds bytes natively; PHP/Ruby inline a 0x literal).

MSSQL-DEC-02 (one pagination strategy): OFFSET/FETCH in all four (Node used TOP).

Mutation-proof:
  * revert the real-PK RETURNING emulation to a hardcoded `id` ->
    "returning star on a non id pk table returns the real row" goes RED
    ("Invalid column name 'id'").
"""
import os
import socket

import pytest

from tina4_python.database import Database

_MSSQL = dict(
    host=os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433")),
    user=os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa"),
    pwd=os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure"),
    db=os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test"),
)

NONID = "mssqlprov_nonid"    # a table whose PRIMARY KEY is deliberately NOT `id`
PARAMS = "mssqlprov_params"  # binary + text round-trip
PAGE = "mssqlprov_page"      # OFFSET/FETCH pagination window

# A payload with a NUL byte and high bytes - the case a text bind / quoted string
# corrupts and only a real varbinary bind round-trips.
BIN = bytes([0, 1, 255, 2, 16, 200, 0, 127])


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


needs_mssql = pytest.mark.skipif(
    not _reachable(_MSSQL["host"], _MSSQL["port"]),
    reason=f"no reachable MSSQL at {_MSSQL['host']}:{_MSSQL['port']} (set TINA4_TEST_MSSQL_*)",
)


def _mssql() -> Database:
    return Database(
        f"mssql://{_MSSQL['host']}:{_MSSQL['port']}/{_MSSQL['db']}",
        _MSSQL["user"], _MSSQL["pwd"],
    )


def _close(db) -> None:
    try:
        db.close()
    except Exception:
        try:
            db._get_adapter().close()
        except Exception:
            pass


def _drop(db, table: str) -> None:
    # SQL Server has no portable DROP TABLE IF EXISTS on every version; the
    # OBJECT_ID guard is the universal form used by the other live MSSQL tests.
    db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")


def _fresh_nonid(db) -> None:
    """A fresh IDENTITY table with a NON-`id` primary key, so its identity
    restarts at 1 and the generated key is deterministic to assert."""
    _drop(db, NONID)
    db.execute(
        f"CREATE TABLE {NONID} ("
        "person_key INT IDENTITY(1,1) PRIMARY KEY, "
        "code VARCHAR(40) NOT NULL, "
        "qty INT)"
    )


def _fresh_rows(table: str, order_col: str):
    """Read every row on a SECOND connection - the durability witness."""
    other = _mssql()
    try:
        return other.fetch(
            f"SELECT * FROM {table} ORDER BY {order_col}", limit=1000
        ).records
    finally:
        _close(other)


# -- mssql-nonid-pk-generated-id --------------------------------------------

@needs_mssql
def test_a_non_id_primary_key_insert_returns_the_generated_last_id():
    db = _mssql()
    _fresh_nonid(db)
    try:
        result = db.insert(NONID, {"code": "a", "qty": 10})
        assert result.last_id == 1, (
            f"a non-`id`-PK insert must return the generated key 1 (SCOPE_IDENTITY), "
            f"got {result.last_id!r}"
        )
        rows = _fresh_rows(NONID, "person_key")
        assert len(rows) == 1 and int(rows[0]["person_key"]) == 1
        assert rows[0]["code"] == "a"
    finally:
        _drop(db, NONID)
        _close(db)


@needs_mssql
def test_a_second_non_id_primary_key_insert_returns_the_next_generated_id():
    db = _mssql()
    _fresh_nonid(db)
    try:
        first = db.insert(NONID, {"code": "a", "qty": 10})
        second = db.insert(NONID, {"code": "b", "qty": 20})
        assert first.last_id == 1, f"first generated id should be 1, got {first.last_id!r}"
        assert second.last_id == 2, (
            f"second insert must return the NEXT generated id 2, got {second.last_id!r}"
        )
        assert second.last_id != first.last_id
    finally:
        _drop(db, NONID)
        _close(db)


@needs_mssql
def test_a_non_id_primary_key_insert_reports_affected_rows_of_one():
    db = _mssql()
    _fresh_nonid(db)
    try:
        result = db.insert(NONID, {"code": "a", "qty": 10})
        assert result.affected_rows == 1, (
            f"a single insert must report affected_rows 1, got {result.affected_rows}"
        )
    finally:
        _drop(db, NONID)
        _close(db)


# -- mssql-safe-params ------------------------------------------------------

@needs_mssql
def test_a_binary_parameter_round_trips_intact():
    db = _mssql()
    _drop(db, PARAMS)
    # Explicit NULL: FreeTDS / pdo_dblib connections run ANSI_NULL_DFLT_OFF, so an
    # unspecified column is NOT NULL there - mark the optional columns nullable so
    # a single-column insert does not trip the other column's NOT NULL default.
    db.execute(f"CREATE TABLE {PARAMS} (k INT PRIMARY KEY, txt VARCHAR(100) NULL, blob VARBINARY(100) NULL)")
    try:
        db.execute(f"INSERT INTO {PARAMS} (k, blob) VALUES (?, ?)", [1, BIN])
        other = _mssql()
        try:
            row = other.fetch_one(f"SELECT blob FROM {PARAMS} WHERE k = ?", [1])
        finally:
            _close(other)
        assert row is not None, "the binary row must be readable on a fresh connection"
        got = bytes(row["blob"]) if row["blob"] is not None else b""
        assert got == BIN, (
            f"binary must round-trip byte-for-byte: sent {BIN.hex()}, got {got.hex()}"
        )
    finally:
        _drop(db, PARAMS)
        _close(db)


@needs_mssql
def test_a_text_parameter_round_trips_intact():
    db = _mssql()
    _drop(db, PARAMS)
    # Explicit NULL: FreeTDS / pdo_dblib connections run ANSI_NULL_DFLT_OFF, so an
    # unspecified column is NOT NULL there - mark the optional columns nullable so
    # a single-column insert does not trip the other column's NOT NULL default.
    db.execute(f"CREATE TABLE {PARAMS} (k INT PRIMARY KEY, txt VARCHAR(100) NULL, blob VARBINARY(100) NULL)")
    text = "it's a \"quoted\" O'Brien value"
    try:
        # Ordinary UTF-8 text stays on the bound path (never mis-routed to a 0x
        # literal), with correct quote-escaping.
        db.execute(f"INSERT INTO {PARAMS} (k, txt) VALUES (?, ?)", [2, text])
        other = _mssql()
        try:
            row = other.fetch_one(f"SELECT txt FROM {PARAMS} WHERE k = ?", [2])
        finally:
            _close(other)
        assert row is not None and row["txt"] == text, (
            f"text must round-trip intact: sent {text!r}, got {row}"
        )
    finally:
        _drop(db, PARAMS)
        _close(db)


# -- mssql-offset-fetch-pagination ------------------------------------------

def _fresh_page(db) -> None:
    _drop(db, PAGE)
    db.execute(f"CREATE TABLE {PAGE} (id INT PRIMARY KEY, val VARCHAR(20))")
    for i, v in enumerate(["a", "b", "c", "d", "e"], start=1):
        db.execute(f"INSERT INTO {PAGE} (id, val) VALUES (?, ?)", [i, v])


@needs_mssql
def test_a_paginated_query_returns_the_first_page_window():
    db = _mssql()
    _fresh_page(db)
    try:
        result = db.fetch(f"SELECT id, val FROM {PAGE} ORDER BY id", limit=2, offset=0)
        ids = [int(r["id"]) for r in result.records]
        assert ids == [1, 2], f"first page (limit 2, offset 0) must be [1, 2], got {ids}"
    finally:
        _drop(db, PAGE)
        _close(db)


@needs_mssql
def test_a_paginated_query_returns_a_later_page_window_with_offset():
    db = _mssql()
    _fresh_page(db)
    try:
        result = db.fetch(f"SELECT id, val FROM {PAGE} ORDER BY id", limit=2, offset=2)
        ids = [int(r["id"]) for r in result.records]
        vals = [r["val"] for r in result.records]
        assert ids == [3, 4], (
            f"the offset window (limit 2, offset 2) must be [3, 4] via OFFSET/FETCH, got {ids} "
            f"(a TOP-only strategy that ignores the offset returns [1, 2])"
        )
        assert vals == ["c", "d"]
    finally:
        _drop(db, PAGE)
        _close(db)


# -- MSSQL-RETURNING-ID mutation witness (Python-only: only the Python adapter
#    emulates MSSQL RETURNING; see the fixture _comment) ----------------------

@needs_mssql
def test_returning_star_on_a_non_id_pk_table_returns_the_real_row():
    db = _mssql()
    _fresh_nonid(db)
    try:
        # MSSQL has no RETURNING; the adapter strips it and re-selects the row by
        # the table's REAL primary key (person_key), never a hardcoded `id`.
        result = db.execute(
            f"INSERT INTO {NONID} (code, qty) VALUES (?, ?) RETURNING *", ["r", 5]
        )
        assert result.records, (
            "RETURNING * must return the inserted row (re-selected by the real pk); "
            "a hardcoded-`id` emulation raised 'Invalid column name id' on a non-`id`-PK table"
        )
        row = result.records[0]
        assert row["code"] == "r" and int(row["qty"]) == 5
        assert int(row["person_key"]) == int(result.last_id) == 1
    finally:
        _drop(db, NONID)
        _close(db)


@needs_mssql
def test_returning_the_pk_column_on_a_non_id_pk_table_returns_the_generated_key():
    db = _mssql()
    _fresh_nonid(db)
    try:
        result = db.execute(
            f"INSERT INTO {NONID} (code, qty) VALUES (?, ?) RETURNING person_key", ["r2", 6]
        )
        assert result.records, "RETURNING <pk> must return the generated key row"
        assert int(result.records[0]["person_key"]) == int(result.last_id) == 1
    finally:
        _drop(db, NONID)
        _close(db)
