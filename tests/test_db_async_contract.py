"""ADR-0074: the async API is the sync API, awaited. Same results, same errors.

Every case in the shared write-path fixture (tests/fixtures/write_path_contract.json)
runs TWICE on every configured engine - once through the sync API, once through
the async API - from the same seed, and the two outcomes must be identical: the
returned value (affected_rows, last_id, records, count), the rows left in the
table, and the exception type when the case expects a raise. The fixture's own
expectations are then checked against the ASYNC result, so the async path is held
to the answer key, not merely to the sync path.

Pagination (ADR-0043) and the ORM get the same treatment. No mocks: real engines.

Mutation-proof: make ``insert_async`` drop ``last_id`` (or ``update_async`` skip
the filterless-write guard) and the matching fixture case goes RED here.
"""
import asyncio
import json
from pathlib import Path

import pytest

from db_engine_matrix import engines
from tina4_python.database import Database

FIXTURE = Path(__file__).parent / "fixtures" / "write_path_contract.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))
TABLE = CONTRACT["table"]["name"]
COMPOSITE_TABLE = CONTRACT["composite_table"]["name"]
ALL_CASES = {c["name"]: c for c in CONTRACT["cases"] + CONTRACT["errors"]}

SQL_ENGINES = [e for e in engines() if e[0] != "mongodb"]


@pytest.fixture(scope="module", params=SQL_ENGINES, ids=[e[0] for e in SQL_ENGINES])
def database(request, tmp_path_factory):
    name, url, user, password = request.param
    if name == "sqlite":
        url = f"sqlite:///{tmp_path_factory.mktemp('asyncparity')}/parity.db"
    db = Database(url, user, password)
    for table in (TABLE, COMPOSITE_TABLE, "t4async_page"):
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:  # noqa: BLE001 - first run against this engine
            db.rollback()
    db.execute(CONTRACT["table"]["ddl"])
    db.execute(CONTRACT["composite_table"]["ddl"])
    db.execute("CREATE TABLE t4async_page (id INTEGER NOT NULL PRIMARY KEY, label VARCHAR(20))")
    db.commit()
    db.execute_many("INSERT INTO t4async_page (id, label) VALUES (?, ?)",
                    [[n, f"row-{n}"] for n in range(1, 251)])
    db.commit()
    yield db
    for table in (TABLE, COMPOSITE_TABLE, "t4async_page"):
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:  # noqa: BLE001 - teardown never masks a failure
            db.rollback()
    db.close()


def _table_for(case):
    return COMPOSITE_TABLE if case.get("table") == "composite" else TABLE


def _reset(db, case):
    for table in (TABLE, COMPOSITE_TABLE):
        db.execute(f"DELETE FROM {table}")
    db.commit()
    for row in case.get("seed", []):
        db.insert(_table_for(case), dict(row))
    db.commit()


def _run_sync(db, case, table):
    op, data = case["op"], case.get("data")
    if op in ("insert", "insert_batch"):
        return db.insert(table, data if op == "insert_batch" else dict(data))
    if op == "update":
        if "filter_sql" in case:
            return db.update(table, dict(data), case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return db.update(table, dict(data), dict(case["filter"]))
        return db.update(table, dict(data))
    if op == "delete":
        if "filter_sql" in case:
            return db.delete(table, case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return db.delete(table, dict(case["filter"]))
        return db.delete(table)
    if op == "truncate":
        return db.truncate(table)
    if op == "primary_key":
        return db.primary_key(table)
    if op in ("transaction_rollback", "transaction_commit"):
        db.start_transaction()
        db.insert(table, dict(data))
        db.commit() if op == "transaction_commit" else db.rollback()
        return None
    if op == "execute_raw":
        return db.execute(case["sql"])
    raise AssertionError(f"unimplemented op {op!r}")


async def _run_async(db, case, table):
    op, data = case["op"], case.get("data")
    if op in ("insert", "insert_batch"):
        return await db.insert_async(table, data if op == "insert_batch" else dict(data))
    if op == "update":
        if "filter_sql" in case:
            return await db.update_async(table, dict(data), case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return await db.update_async(table, dict(data), dict(case["filter"]))
        return await db.update_async(table, dict(data))
    if op == "delete":
        if "filter_sql" in case:
            return await db.delete_async(table, case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return await db.delete_async(table, dict(case["filter"]))
        return await db.delete_async(table)
    if op == "truncate":
        return await db.truncate_async(table)
    if op == "primary_key":
        return await db.primary_key_async(table)
    if op in ("transaction_rollback", "transaction_commit"):
        await db.start_transaction_async()
        await db.insert_async(table, dict(data))
        if op == "transaction_commit":
            await db.commit_async()
        else:
            await db.rollback_async()
        return None
    if op == "execute_raw":
        return await db.execute_async(case["sql"])
    raise AssertionError(f"unimplemented op {op!r}")


def _normalise(value):
    """Engine values compared as text: the contract is WHICH rows, not the type map."""
    if isinstance(value, dict):
        return {str(k).lower(): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return None if value is None else str(value)


def _summary(result):
    if result is None or isinstance(result, (bool, list)):
        return {"type": type(result).__name__, "value": _normalise(result)}
    return {
        "type": type(result).__name__,
        "affected_rows": result.affected_rows,
        "last_id": _normalise(result.last_id),
        "count": result.count,
        "records": _normalise(result.records),
    }


def _rows(db, table):
    return sorted(_normalise([dict(r) for r in db.fetch(f"SELECT * FROM {table}", limit=0).records]),
                  key=lambda row: json.dumps(row, sort_keys=True))


def _outcome(db, case, runner):
    table = _table_for(case)
    _reset(db, case)
    try:
        value = runner(db, case, table)
        outcome = {"result": _summary(value)}
    except Exception as exc:  # noqa: BLE001 - the error type IS the observation
        outcome = {"raised": type(exc).__name__}
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    outcome["rows"] = _rows(db, table)
    return outcome


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_write_path_case_is_identical_through_both_apis(database, name):
    case = ALL_CASES[name]
    sync = _outcome(database, case, _run_sync)
    asynchronous = _outcome(database, case, lambda db, c, t: asyncio.run(_run_async(db, c, t)))
    assert asynchronous == sync, f"{name}: async API diverged from sync\n sync:  {sync}\n async: {asynchronous}"
    if case.get("expect_raises"):
        assert "raised" in asynchronous, f"{name}: the async API did not raise"
    expect = case.get("expect", {})
    if "rows_after" in expect:
        assert len(asynchronous["rows"]) == expect["rows_after"], name
    if "affected_rows" in expect:
        assert asynchronous["result"]["affected_rows"] == expect["affected_rows"], name


@pytest.mark.parametrize("limit,offset", [(20, 40), (20, 240), (20, 500), (0, 0), (300, 0)])
def test_fetch_and_to_paginate_are_identical_through_both_apis(database, limit, offset):
    sql = "SELECT id, label FROM t4async_page ORDER BY id"
    sync = database.fetch(sql, limit=limit, offset=offset)
    asynchronous = asyncio.run(database.fetch_async(sql, limit=limit, offset=offset))
    assert type(asynchronous) is type(sync)
    assert _normalise(asynchronous.records) == _normalise(sync.records)
    assert asynchronous.count == sync.count == 250
    assert asynchronous.to_paginate().keys() == sync.to_paginate().keys()
    assert {k: v for k, v in asynchronous.to_paginate().items() if k != "records"} == \
        {k: v for k, v in sync.to_paginate().items() if k != "records"}


def test_fetch_one_fetch_all_and_introspection_are_identical(database):
    sql = "SELECT id, label FROM t4async_page WHERE id = ?"

    async def run():
        return (
            await database.fetch_one_async(sql, [7]),
            await database.fetch_one_async(sql, [9999]),
            await database.fetch_all_async("SELECT id FROM t4async_page ORDER BY id"),
            await database.table_exists_async("t4async_page"),
            await database.table_exists_async("t4async_no_such_table"),
            await database.get_columns_async("t4async_page"),
        )

    got = asyncio.run(run())
    want = (
        database.fetch_one(sql, [7]),
        database.fetch_one(sql, [9999]),
        database.fetch_all("SELECT id FROM t4async_page ORDER BY id"),
        database.table_exists("t4async_page"),
        database.table_exists("t4async_no_such_table"),
        database.get_columns("t4async_page"),
    )
    assert _normalise(got) == _normalise(want)
    assert got[1] is None and len(got[2]) == 250


def test_a_sql_error_raises_the_same_type_and_records_the_same_error(database):
    bad = "SELECT no_such_column FROM t4async_page"
    with pytest.raises(Exception) as sync_error:
        database.fetch(bad)
    sync_recorded = database.get_error()
    with pytest.raises(Exception) as async_error:
        asyncio.run(database.fetch_async(bad))
    assert type(async_error.value) is type(sync_error.value)
    assert database.get_error() == sync_recorded and sync_recorded


def test_orm_async_methods_match_the_sync_methods(database):
    from tina4_python.orm import ORM, IntegerField, StringField

    class Page(ORM):
        table_name = "t4async_page"
        id = IntegerField(primary_key=True)
        label = StringField()

    Page._db = database

    async def run():
        found = await Page.find_by_id_async(12)
        page = await Page.where_async("id > ?", [200], limit=10, offset=5)
        every = await Page.all_async(limit=3)
        total = await Page.count_async("id <= ?", [100])
        missing = await Page.find_by_id_async(99999)
        created = Page({"id": 9001, "label": "async-made"})
        await created.save_async()
        loaded = Page()
        loaded.id = 9001
        await loaded.load_async()
        await created.delete_async()
        gone = await Page.find_by_id_async(9001)
        return found, page, every, total, missing, loaded, gone

    try:
        found, page, every, total, missing, loaded, gone = asyncio.run(run())
        assert _normalise(found.to_dict()) == _normalise(Page.find_by_id(12).to_dict())
        sync_page = Page.where("id > ?", [200], limit=10, offset=5)
        assert [p.id for p in page] == [p.id for p in sync_page]
        assert page.get_total_records() == sync_page.get_total_records() == 50
        assert [p.id for p in every] == [p.id for p in Page.all(limit=3)]
        assert total == Page.count("id <= ?", [100]) == 100
        assert missing is None
        assert loaded.label == "async-made"
        assert gone is None
    finally:
        Page._db = None
