"""ADR-0074 (amends the ADR-0043 mechanism, not its contract): fetch() runs the
statement ONCE when the page it returned already proves the total.

MEASURED on origin/v3: every paginated fetch() ran ``SELECT COUNT(*) FROM (<sql>)``
and then ``<sql> LIMIT n OFFSET m``, so the statement executed twice. A 1s statement
took 1.96s on PostgreSQL and 1.98s over ODBC; the user's 2s pg_sleep cost ~3.6s.

The total is still the true total (ADR-0043). It is only DERIVED when the page
proves it: a non-empty short page is the last page (total = offset + rows), and an
unpaginated read's total is its row count. A full page, or an empty page past
offset 0, still runs the COUNT probe.

How each engine is observed executing the statement - the engine's own record,
never a stand-in:
  sqlite    the connection's trace callback (every statement SQLite runs)
  postgres  a sequence: nextval() in the statement advances it once per execution
  odbc      the same PostgreSQL sequence, through the ODBC driver
  firebird  a selectable procedure advancing a generator once per execution
  mssql     sys.dm_exec_query_stats execution counts for statements carrying a marker
  mysql     wall time of SLEEP(0.6) (no per-statement counter is readable)
  mongodb   the database profiler (system.profile): count/aggregate vs find

Mutation-proof: make DatabaseAdapter._total_from_page() return None (always
probe) and every "runs once" case goes RED; make it return the page length for a
FULL page and the "full page still counts" cases go RED.
"""
import time
import uuid

import pytest

from db_engine_matrix import engines
from tina4_python.database import Database

ENGINES = engines()


@pytest.fixture(scope="module", params=ENGINES, ids=[e[0] for e in ENGINES])
def engine(request, tmp_path_factory):
    name, url, user, password = request.param
    if name == "sqlite":
        url = f"sqlite:///{tmp_path_factory.mktemp('single')}/single.db"
    if name == "mongodb":
        url = url.rsplit("/", 1)[0] + "/tina4_single_exec"
    db = Database(url, user, password, pool=1)
    table = "t4single"
    try:
        db.execute(f"DROP TABLE {table}")
        db.commit()
    except Exception:  # noqa: BLE001 - first run
        db.rollback()
    if name == "mongodb":
        # Seeded natively: execute_many is one atomic batch, and the lab's
        # standalone MongoDB has no transactions (ADR-0044 DBA-P02).
        db.adapter._collection(table).delete_many({})
        db.adapter._collection(table).insert_many([{"id": n, "label": f"row-{n}"} for n in range(1, 8)])
    else:
        db.execute(f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY, label VARCHAR(20))")
        db.commit()
        db.execute_many(f"INSERT INTO {table} (id, label) VALUES (?, ?)",
                        [[n, f"row-{n}"] for n in range(1, 8)])
        db.commit()
    yield name, db
    try:
        db.execute(f"DROP TABLE {table}")
        db.commit()
    except Exception:  # noqa: BLE001
        pass
    db.close()


def _executions(name, db, run_fetch):
    """How many times the engine executed the statement ``run_fetch`` issues."""
    if name == "sqlite":
        statements = []
        adapter = db.checkout()
        adapter._conn.set_trace_callback(statements.append)
        db.checkin(adapter)
        try:
            run_fetch("SELECT id, label FROM t4single WHERE id <= 3 ORDER BY id")
        finally:
            adapter._conn.set_trace_callback(None)
        return sum(1 for s in statements if "t4single" in s)

    if name in ("postgres", "odbc"):
        seq = f"t4single_{uuid.uuid4().hex[:8]}"
        db.execute(f"CREATE SEQUENCE {seq}")
        db.commit()
        try:
            run_fetch(f"SELECT nextval('{seq}') AS v")
            after = int(db.fetch_one(f"SELECT nextval('{seq}') AS v")["v"])
            return after - 1
        finally:
            db.execute(f"DROP SEQUENCE {seq}")
            db.commit()

    if name == "firebird":
        # A generator read in a plain SELECT is not evaluated by the COUNT
        # wrapper, so it cannot see a second execution. A selectable procedure
        # must RUN for COUNT(*) to know how many rows it yields.
        suffix = uuid.uuid4().hex[:8].upper()
        gen, proc = f"T4S_G{suffix}", f"T4S_P{suffix}"
        db.execute(f"CREATE GENERATOR {gen}")
        db.execute(f"CREATE PROCEDURE {proc} RETURNS (V BIGINT) AS "
                   f"BEGIN V = GEN_ID({gen}, 1); SUSPEND; END")
        db.commit()
        try:
            run_fetch(f"SELECT V FROM {proc}")
            return int(db.fetch_one(f"SELECT GEN_ID({gen}, 0) AS v FROM RDB$DATABASE")["v"])
        finally:
            db.execute(f"DROP PROCEDURE {proc}")
            db.execute(f"DROP GENERATOR {gen}")
            db.commit()

    if name == "mssql":
        marker = f"t4m{uuid.uuid4().hex[:12]}"
        run_fetch(f"SELECT id, label, '{marker}' AS m FROM t4single WHERE id <= 3")
        half = len(marker) // 2
        row = db.fetch_one(
            "SELECT COALESCE(SUM(qs.execution_count), 0) AS n FROM sys.dm_exec_query_stats qs "
            "CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st "
            f"WHERE st.text LIKE '%' + '{marker[:half]}' + '{marker[half:]}' + '%'"
        )
        return int(row["n"])

    if name == "mysql":
        started = time.monotonic()
        run_fetch("SELECT SLEEP(0.6) AS s")
        elapsed = time.monotonic() - started
        return 1 if elapsed < 1.0 else 2

    if name == "mongodb":
        mongo = db.adapter._collection("t4single").database
        mongo.command("profile", 0)
        mongo["system.profile"].drop()
        mongo.command("profile", 2)
        try:
            # The Mongo SQL provider binds values only through parameters, so
            # the statement carries no literal filter.
            run_fetch("SELECT id, label FROM t4single")
        finally:
            mongo.command("profile", 0)
        ops = list(mongo["system.profile"].find({"ns": f"{mongo.name}.t4single"}))
        return sum(1 for op in ops if op.get("op") in ("query", "command"))

    raise AssertionError(f"no execution counter for {name}")


def test_a_short_first_page_runs_the_statement_once(engine):
    name, db = engine
    assert _executions(name, db, lambda sql: db.fetch(sql, limit=100)) == 1


def test_fetch_all_runs_the_statement_once(engine):
    name, db = engine
    assert _executions(name, db, lambda sql: db.fetch_all(sql)) == 1


def test_the_async_api_runs_the_statement_once(engine):
    import asyncio
    name, db = engine
    assert _executions(name, db, lambda sql: asyncio.run(db.fetch_async(sql, limit=100))) == 1


def test_a_full_page_still_reports_the_true_total(engine):
    """ADR-0043: total is the COUNT for the filter, never the rows returned."""
    _, db = engine
    result = db.fetch("SELECT id, label FROM t4single ORDER BY id", limit=3, offset=0)
    assert len(result.records) == 3
    assert result.count == 7
    assert result.to_paginate()["total_pages"] == 3


def test_a_short_last_page_reports_the_true_total(engine):
    _, db = engine
    result = db.fetch("SELECT id, label FROM t4single ORDER BY id", limit=3, offset=6)
    assert len(result.records) == 1
    assert result.count == 7


def test_an_empty_page_past_the_end_still_reports_the_true_total(engine):
    _, db = engine
    result = db.fetch("SELECT id, label FROM t4single ORDER BY id", limit=3, offset=30)
    assert result.records == []
    assert result.count == 7


def test_a_filter_that_matches_nothing_reports_zero(engine):
    _, db = engine
    result = db.fetch("SELECT id, label FROM t4single WHERE id > ? ORDER BY id", [100], limit=3)
    assert result.records == [] and result.count == 0
