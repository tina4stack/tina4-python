"""PostgreSQL provider as the write-path ORACLE - feature 9 (pgprovider_contract.json).

PG-DEC-01 (OWNER-DECISIONS.md Batch 5, feature 009-postgresql-provider.md): make the
adapter-contract test assert real write-path BEHAVIOUR - not just method presence -
with PostgreSQL as the reference model, in all four frameworks. PostgreSQL is the
oracle for the write contract: native RETURNING gives the true generated last-id, the
transaction is real, and the affected count is exact.

Every case drives the lab's REAL PostgreSQL :55432 (tina4/tina4) through the public
Database facade -> PostgreSQLAdapter. No mocks. Durability is read back on a SECOND,
FRESH connection where that is the property under test. The oracle table has a SERIAL
key, and each case TRUNCATE ... RESTART IDENTITY first, so the RETURNING-generated id
is deterministic (first insert -> 1, second -> 2).

Under TINA4_REQUIRE_SERVICES a skip here is a hard failure - these MUST run on the lab.

Mutation-proof (revert on the adapter/facade, watch the named case go RED):
  * make execute_many() commit each row instead of owning one transaction ->
    "execute many mid batch failure rolls back on a fresh connection" goes RED (the
    first row survives on the fresh connection).
  * drop the filterless-write guard in Database.update/delete ->
    "update without a filter or primary key raises and changes nothing" /
    "delete without a filter raises and removes nothing" go RED.
  * return a bare int/bool from execute instead of a DatabaseResult, or read last_id
    from a lastval() probe instead of RETURNING -> the last-id / affected-count cases
    go RED.
"""
import os
import socket
import uuid

import pytest

from tina4_python.database import Database

# ── real-service coordinates (the canonical TINA4_TEST_* convention; same as the
#    nextid + write-path runners) ────────────────────────────────────────────────
_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)

TABLE = "pgprovider_oracle"
DDL = (
    f"CREATE TABLE {TABLE} ("
    "id SERIAL PRIMARY KEY, "
    "code VARCHAR(40) NOT NULL UNIQUE, "
    "qty INTEGER)"
)


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _pg_url() -> str:
    return f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}"


needs_pg = pytest.mark.skipif(
    not _reachable(_PG["host"], _PG["port"]),
    reason=f"no reachable postgres at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)",
)


def _connect() -> Database:
    return Database(_pg_url(), _PG["user"], _PG["pwd"])


def _close(db) -> None:
    try:
        db.close()
    except Exception:
        try:
            db._get_adapter().close()
        except Exception:
            pass


@pytest.fixture()
def pg():
    """A real PostgreSQL connection with a fresh, empty oracle table per test.

    The table is dropped and recreated so SERIAL restarts at 1 in every test,
    which is what makes the RETURNING-generated id deterministic to assert.
    """
    db = _connect()
    db.execute(f"DROP TABLE IF EXISTS {TABLE}")
    db.commit()
    db.execute(DDL)
    db.commit()
    yield db
    try:
        db.execute(f"DROP TABLE IF EXISTS {TABLE}")
        db.commit()
    except Exception:
        pass
    _close(db)


def _rows_on_fresh_connection():
    """Read every row back on a SECOND connection - the durability witness.

    A write that is only visible on the connection that made it is not durable;
    a fresh connection cannot be fooled by an uncommitted or rolled-back write.
    """
    other = _connect()
    try:
        return [dict(r) for r in other.fetch(f"SELECT * FROM {TABLE}", limit=1000).records]
    finally:
        _close(other)


# ── pg-insert-returning-last-id ────────────────────────────────────────────────

@needs_pg
def test_insert_returns_the_returning_generated_last_id(pg):
    result = pg.insert(TABLE, {"code": "a", "qty": 10})
    assert result.last_id == 1, (
        f"expected the RETURNING-generated serial id 1, got {result.last_id!r}"
    )
    # The generated id is the row's real key, visible on a fresh connection.
    rows = _rows_on_fresh_connection()
    assert rows == [{"id": 1, "code": "a", "qty": 10}], rows


@needs_pg
def test_insert_reports_affected_rows_of_one(pg):
    result = pg.insert(TABLE, {"code": "a", "qty": 10})
    assert result.affected_rows == 1, (
        f"a single insert must report affected_rows 1, got {result.affected_rows}"
    )


@needs_pg
def test_a_second_insert_returns_the_next_generated_id_not_a_stale_one(pg):
    first = pg.insert(TABLE, {"code": "a", "qty": 10})
    second = pg.insert(TABLE, {"code": "b", "qty": 20})
    assert first.last_id == 1, f"first generated id should be 1, got {first.last_id!r}"
    assert second.last_id == 2, (
        f"second insert must return the NEXT generated id 2, got {second.last_id!r} "
        f"(a stale {first.last_id!r} would be the last-id-from-an-unrelated-probe bug)"
    )
    assert second.last_id != first.last_id


# ── pg-write-affected-count ────────────────────────────────────────────────────

@needs_pg
def test_update_reports_the_exact_number_of_rows_changed(pg):
    pg.insert(TABLE, {"code": "a", "qty": 10})
    pg.insert(TABLE, {"code": "b", "qty": 20})
    pg.insert(TABLE, {"code": "c", "qty": 40})
    result = pg.update(TABLE, {"qty": 99}, "qty < ?", [30])
    assert result.affected_rows == 2, (
        f"the filter matches exactly two of three rows, expected affected_rows 2, "
        f"got {result.affected_rows}"
    )


@needs_pg
def test_update_reports_a_null_last_id(pg):
    pg.insert(TABLE, {"code": "a", "qty": 10})
    result = pg.update(TABLE, {"qty": 99}, "code = ?", ["a"])
    assert result.last_id is None, (
        f"last_id is insert-only; an update must report None, got {result.last_id!r}"
    )


@needs_pg
def test_delete_reports_the_exact_number_of_rows_removed(pg):
    pg.insert(TABLE, {"code": "a", "qty": 10})
    pg.insert(TABLE, {"code": "b", "qty": 20})
    result = pg.delete(TABLE, {"code": "a"})
    assert result.affected_rows == 1, (
        f"deleting one matching row must report affected_rows 1, got {result.affected_rows}"
    )
    assert [r["code"] for r in _rows_on_fresh_connection()] == ["b"]


# ── pg-filterless-write-guard ──────────────────────────────────────────────────

@needs_pg
def test_update_without_a_filter_or_primary_key_raises_and_changes_nothing(pg):
    pg.insert(TABLE, {"code": "a", "qty": 10})
    pg.insert(TABLE, {"code": "b", "qty": 20})
    with pytest.raises(Exception):
        # No filter and no primary key in the data -> a full-table rewrite that
        # must be refused, not performed.
        pg.update(TABLE, {"qty": 1})
    rows = {r["code"]: r["qty"] for r in _rows_on_fresh_connection()}
    assert rows == {"a": 10, "b": 20}, f"a refused update must change nothing, got {rows}"


@needs_pg
def test_delete_without_a_filter_raises_and_removes_nothing(pg):
    pg.insert(TABLE, {"code": "a", "qty": 10})
    pg.insert(TABLE, {"code": "b", "qty": 20})
    with pytest.raises(Exception):
        pg.delete(TABLE)  # truncate() is the explicit whole-table empty, not this
    assert len(_rows_on_fresh_connection()) == 2, "a refused delete must remove nothing"


# ── pg-executemany-atomicity ───────────────────────────────────────────────────

@needs_pg
def test_execute_many_mid_batch_failure_rolls_back_on_a_fresh_connection(pg):
    # RETURNING forces the row-at-a-time loop (the batch collapser rejects it), so
    # the first set really executes inside the owned transaction before the second
    # set violates UNIQUE(code). If execute_many owns one transaction, the failure
    # rolls the whole batch back and a fresh connection sees ZERO rows.
    with pytest.raises(Exception):
        pg.execute_many(
            f"INSERT INTO {TABLE} (code, qty) VALUES (?, ?) RETURNING *",
            [["dup", 1], ["dup", 2]],
        )
    assert _rows_on_fresh_connection() == [], (
        "a mid-batch failure must roll the whole batch back - a fresh connection "
        "seeing the first row means execute_many committed per row instead of "
        "owning one transaction"
    )


@needs_pg
def test_execute_many_empty_input_is_a_zero_row_no_op(pg):
    result = pg.execute_many(f"INSERT INTO {TABLE} (code, qty) VALUES (?, ?)", [])
    assert result.affected_rows == 0, (
        f"empty input is a no-op with affected_rows 0, got {result.affected_rows}"
    )
    assert _rows_on_fresh_connection() == [], "empty input must write nothing"


# ── pg-fetch-shape ─────────────────────────────────────────────────────────────

@needs_pg
def test_fetch_returns_a_native_list_of_rows_with_native_types(pg):
    pg.insert(TABLE, {"code": "x", "qty": 42})
    result = pg.fetch(f"SELECT id, code, qty FROM {TABLE} ORDER BY id")
    assert isinstance(result.records, list) and len(result.records) == 1
    row = result.records[0]
    assert isinstance(row["qty"], int) and row["qty"] == 42, (
        f"an INTEGER column must read back as a native int, got {type(row['qty']).__name__} "
        f"{row['qty']!r}"
    )
    assert isinstance(row["code"], str) and row["code"] == "x"


@needs_pg
def test_fetch_one_returns_a_single_native_record(pg):
    pg.insert(TABLE, {"code": "y", "qty": 7})
    row = pg.fetch_one(f"SELECT code, qty FROM {TABLE} WHERE code = ?", ["y"])
    assert isinstance(row, dict), f"fetch_one must return one native record, got {row!r}"
    assert row["code"] == "y"
    assert isinstance(row["qty"], int) and row["qty"] == 7


@needs_pg
def test_fetch_one_with_no_match_returns_null(pg):
    row = pg.fetch_one(f"SELECT * FROM {TABLE} WHERE code = ?", ["nope"])
    assert row is None, f"fetch_one with no match must return None, got {row!r}"
