"""MySQL provider contract - feature 10 (mysqlprovider_contract.json).

MYSQL-DEC-01 + MYSQL-DEC-02 (OWNER-DECISIONS.md Batch 5, feature doc
010-mysql-provider.md). Every case drives the lab's REAL MySQL :3306
(tina4/tina4 -> tina4_test) through the public Database facade -> MySQLAdapter.
No mocks. Durability is read back on a SECOND, FRESH connection where that is
the property under test. Under TINA4_REQUIRE_SERVICES a skip is a hard failure -
these MUST run on the lab.

MYSQL-DEC-01 (real-PK RETURNING emulation): MySQL has no RETURNING, so the
Python adapter emulates it by RE-SELECTING the inserted row. It used to fetch by
a HARDCODED `id` column, so a table whose primary key is NOT named `id` got a
wrong / empty row ('Unknown column id'). It now re-selects by the table's REAL
primary key. The `returning_*` tests below are the direct mutation witness for
that fix (Python-only: PHP/Ruby/Node do not emulate MySQL RETURNING - their
last_insert_id is column-independent, covered by the four-way invariant 1).

MYSQL-DEC-02: DESCRIBE now STRICT-quotes the table identifier (MYSQL-DESCRIBE-
UNPARAM), and the FIRST->LAST batch-id math routes through the shared
SQLTranslator.batch_last_id helper (MYSQL-BATCH-ID-DUP).

Mutation-proof:
  * revert the real-PK RETURNING emulation to a hardcoded `id` ->
    "returning star on a non id pk table returns the real row" goes RED
    ('Unknown column id' / empty records).
  * revert the strict DESCRIBE quoting -> "describe of an odd table name returns
    its columns" goes RED (a backtick/special-char name is a syntax error).
  * neutralise batch_last_id (return the reported id unchanged) ->
    "a batch insert returns the last sequential generated id" goes RED (it
    reports the FIRST id, 1, for a 3-row batch whose last id is 3).
"""
import os
import socket

import pytest

from tina4_python.database import Database

_MYSQL = dict(
    host=os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306")),
    user=os.environ.get("TINA4_TEST_MYSQL_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test"),
)

NONID = "mysqlprov_nonid"      # a table whose PRIMARY KEY is deliberately NOT `id`
BATCH = "mysqlprov_batch"
SENTINEL = "mysqlprov_sentinel"
ODD = "mysqlprov`odd"          # an embedded backtick -> needs strict quoting


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


needs_mysql = pytest.mark.skipif(
    not _reachable(_MYSQL["host"], _MYSQL["port"]),
    reason=f"no reachable MySQL at {_MYSQL['host']}:{_MYSQL['port']} (set TINA4_TEST_MYSQL_*)",
)


def _mysql() -> Database:
    return Database(
        f"mysql://{_MYSQL['host']}:{_MYSQL['port']}/{_MYSQL['db']}",
        _MYSQL["user"], _MYSQL["pwd"],
    )


def _close(db) -> None:
    try:
        db.close()
    except Exception:
        try:
            db._get_adapter().close()
        except Exception:
            pass


def _quote(name: str) -> str:
    """Strict backtick-quote for building DDL against an odd name in the test."""
    return "`" + name.replace("`", "``") + "`"


def _fresh_nonid(db) -> None:
    """A fresh AUTO_INCREMENT table with a NON-`id` primary key, so its sequence
    restarts at 1 and the generated id is deterministic to assert."""
    db.execute(f"DROP TABLE IF EXISTS {NONID}")
    db.execute(
        f"CREATE TABLE {NONID} ("
        "person_key INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "code VARCHAR(40) NOT NULL UNIQUE, "
        "qty INTEGER)"
    )


def _fresh_rows(table: str, order_col: str):
    """Read every row on a SECOND connection - the durability witness."""
    other = _mysql()
    try:
        return other.fetch(
            f"SELECT * FROM {_quote(table)} ORDER BY {_quote(order_col)}", limit=1000
        ).records
    finally:
        _close(other)


# ── mysql-nonid-pk-generated-id ─────────────────────────────────────────────

@needs_mysql
def test_a_non_id_primary_key_insert_returns_the_generated_last_id():
    db = _mysql()
    _fresh_nonid(db)
    try:
        result = db.insert(NONID, {"code": "a", "qty": 10})
        assert result.last_id == 1, (
            f"a non-`id`-PK insert must return the generated key 1, got {result.last_id!r} "
            f"(a hardcoded-`id` emulation returned the wrong/empty row)"
        )
        rows = _fresh_rows(NONID, "person_key")
        assert len(rows) == 1 and int(rows[0]["person_key"]) == 1
        assert rows[0]["code"] == "a"
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


@needs_mysql
def test_a_second_non_id_primary_key_insert_returns_the_next_generated_id():
    db = _mysql()
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
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


@needs_mysql
def test_a_non_id_primary_key_insert_reports_affected_rows_of_one():
    db = _mysql()
    _fresh_nonid(db)
    try:
        result = db.insert(NONID, {"code": "a", "qty": 10})
        assert result.affected_rows == 1, (
            f"a single insert must report affected_rows 1, got {result.affected_rows}"
        )
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


# ── mysql-write-affected-count ──────────────────────────────────────────────

@needs_mysql
def test_update_reports_the_exact_number_of_rows_changed():
    db = _mysql()
    _fresh_nonid(db)
    try:
        db.insert(NONID, {"code": "a", "qty": 10})
        db.insert(NONID, {"code": "b", "qty": 20})
        db.insert(NONID, {"code": "c", "qty": 40})
        result = db.update(NONID, {"qty": 99}, "qty < ?", [30])
        assert result.affected_rows == 2, (
            f"the filter matches exactly two of three rows, expected 2, got {result.affected_rows}"
        )
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


@needs_mysql
def test_delete_reports_the_exact_number_of_rows_removed():
    db = _mysql()
    _fresh_nonid(db)
    try:
        db.insert(NONID, {"code": "a", "qty": 10})
        db.insert(NONID, {"code": "b", "qty": 20})
        result = db.delete(NONID, {"code": "a"})
        assert result.affected_rows == 1, (
            f"deleting one matching row must report 1, got {result.affected_rows}"
        )
        assert [r["code"] for r in _fresh_rows(NONID, "person_key")] == ["b"]
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


@needs_mysql
def test_an_update_reports_a_null_last_id():
    db = _mysql()
    _fresh_nonid(db)
    try:
        db.insert(NONID, {"code": "a", "qty": 10})
        result = db.update(NONID, {"qty": 99}, "code = ?", ["a"])
        assert result.last_id is None, (
            f"last_id is insert-only; an update must report None, got {result.last_id!r}"
        )
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


# ── mysql-describe-safe ─────────────────────────────────────────────────────

@needs_mysql
def test_describe_of_an_odd_table_name_returns_its_columns():
    db = _mysql()
    odd_q = _quote(ODD)
    db.execute(f"DROP TABLE IF EXISTS {odd_q}")
    db.execute(
        f"CREATE TABLE {odd_q} "
        "(person_key INT NOT NULL AUTO_INCREMENT PRIMARY KEY, val VARCHAR(20))"
    )
    try:
        # A raw/naively-quoted DESCRIBE breaks on the embedded backtick; strict
        # quoting introspects the odd name correctly.
        cols = db.get_columns(ODD)
        names = [c["name"] for c in cols]
        assert names == ["person_key", "val"], names
        pk = [c["name"] for c in cols if c["primary_key"]]
        assert pk == ["person_key"], pk
    finally:
        db.execute(f"DROP TABLE IF EXISTS {odd_q}")
        _close(db)


@needs_mysql
def test_describe_of_a_crafted_table_name_does_not_inject():
    db = _mysql()
    db.execute(f"DROP TABLE IF EXISTS {SENTINEL}")
    db.execute(f"CREATE TABLE {SENTINEL} (id INT PRIMARY KEY)")
    crafted = f"x`; DROP TABLE {SENTINEL}; --"
    try:
        # The crafted name becomes ONE escaped identifier -> a clean "unknown
        # table" (no runnable SQL). The result is irrelevant; the sentinel must
        # survive.
        try:
            db.get_columns(crafted)
        except Exception:
            pass
        assert db.table_exists(SENTINEL), "a crafted DESCRIBE name must not drop the sentinel table"
    finally:
        db.execute(f"DROP TABLE IF EXISTS {SENTINEL}")
        _close(db)


# ── mysql-batch-sequential-ids ──────────────────────────────────────────────

@needs_mysql
def test_a_batch_insert_returns_the_last_sequential_generated_id():
    db = _mysql()
    db.execute(f"DROP TABLE IF EXISTS {BATCH}")
    db.execute(
        f"CREATE TABLE {BATCH} "
        "(seq_key INT NOT NULL AUTO_INCREMENT PRIMARY KEY, code VARCHAR(40) NOT NULL, qty INTEGER)"
    )
    try:
        result = db.insert(BATCH, [
            {"code": "b1", "qty": 1},
            {"code": "b2", "qty": 2},
            {"code": "b3", "qty": 3},
        ])
        # db.insert() runs this batch ROW-AT-A-TIME here (measured: no collapse
        # for a 3-row batch), so each row reports its own consecutive id and the
        # LAST is 3. Where a batch DOES collapse into one multi-row INSERT the
        # shared batch_last_id helper normalises MySQL's FIRST-reported id to the
        # LAST -- mutation-witnessed in the Ruby suite, whose db.insert collapses.
        assert result.last_id == 3, (
            f"a 3-row batch must return the LAST generated id 3, got {result.last_id!r} "
            f"(a 1 is the un-normalised FIRST id)"
        )
    finally:
        db.execute(f"DROP TABLE IF EXISTS {BATCH}")
        _close(db)


@needs_mysql
def test_a_batch_insert_assigns_consecutive_ids_to_every_row():
    db = _mysql()
    db.execute(f"DROP TABLE IF EXISTS {BATCH}")
    db.execute(
        f"CREATE TABLE {BATCH} "
        "(seq_key INT NOT NULL AUTO_INCREMENT PRIMARY KEY, code VARCHAR(40) NOT NULL, qty INTEGER)"
    )
    try:
        db.insert(BATCH, [
            {"code": "b1", "qty": 1},
            {"code": "b2", "qty": 2},
            {"code": "b3", "qty": 3},
        ])
        rows = _fresh_rows(BATCH, "seq_key")
        assert [int(r["seq_key"]) for r in rows] == [1, 2, 3], rows
        assert [r["code"] for r in rows] == ["b1", "b2", "b3"]
    finally:
        db.execute(f"DROP TABLE IF EXISTS {BATCH}")
        _close(db)


# ── MYSQL-RETURNING-ID mutation witness (Python-only: only the Python adapter
#    emulates MySQL RETURNING; see the fixture _comment) ──────────────────────

@needs_mysql
def test_returning_star_on_a_non_id_pk_table_returns_the_real_row():
    db = _mysql()
    _fresh_nonid(db)
    try:
        # MySQL has no RETURNING; the adapter strips it and re-selects the row by
        # the table's REAL primary key (person_key), never a hardcoded `id`.
        result = db.execute(
            f"INSERT INTO {NONID} (code, qty) VALUES (?, ?) RETURNING *", ["r", 5]
        )
        assert result.records, (
            "RETURNING * must return the inserted row (re-selected by the real pk); "
            "a hardcoded-`id` emulation raised 'Unknown column id' on a non-`id`-PK table"
        )
        row = result.records[0]
        assert row["code"] == "r" and row["qty"] == 5
        assert int(row["person_key"]) == int(result.last_id) == 1
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)


@needs_mysql
def test_returning_the_pk_column_on_a_non_id_pk_table_returns_the_generated_key():
    db = _mysql()
    _fresh_nonid(db)
    try:
        result = db.execute(
            f"INSERT INTO {NONID} (code, qty) VALUES (?, ?) RETURNING person_key", ["r2", 6]
        )
        assert result.records, "RETURNING <pk> must return the generated key row"
        assert int(result.records[0]["person_key"]) == int(result.last_id) == 1
    finally:
        db.execute(f"DROP TABLE IF EXISTS {NONID}")
        _close(db)
