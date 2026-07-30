"""The batch-write contract (feature 3 of the feature audit).

``tests/fixtures/batch_write_contract.json`` is byte-identical in all four
frameworks and is the shared answer key: the same cases, the same engine
parameter caps, the same rejections, checked identically in python, php, ruby
and node.

A batch that loops one INSERT per row pays a full network round-trip per row.
Measured over 500 rows on the .99 host: PostgreSQL 9848ms row-at-a-time against
15.8ms as one multi-row VALUES (625x), MySQL 216x, MSSQL 121x.

The chunking rules are PURE, so they are checked here without a database. The
live-engine half of the contract lives in the write-path runner, which proves
the rows actually land - a faster batch that writes the wrong rows is a bug, not
an optimisation.
"""
import json
from pathlib import Path

import pytest

from tina4_python.database.sql_translator import SQLTranslator

FIXTURE = Path(__file__).parent / "fixtures" / "batch_write_contract.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {c["name"]: c for c in CONTRACT["cases"]}


def _rows(count, columns):
    return [[f"v{r}c{c}" for c in range(columns)] for r in range(count)]


def _build(case):
    return SQLTranslator.build_batch_inserts(
        case["sql"], _rows(case["rows"], case["columns"]), case["engine"]
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_case_from_the_shared_fixture(name):
    """Every case in the shared fixture, checked against the same answer key."""
    case = CASES[name]
    expect = case["expect"]
    statements = _build(case)

    assert len(statements) == expect["statements"], (
        f"{name}: expected {expect['statements']} statement(s), got {len(statements)}"
    )

    if expect["statements"] == 0:
        return

    first_sql, first_params = statements[0]
    assert first_sql.count("(") - 1 == expect["rows_in_first"], (
        f"{name}: first statement should carry {expect['rows_in_first']} row tuples"
    )
    assert len(first_params) == expect["params_in_first"]
    assert first_sql.count("?") == expect["params_in_first"]


def test_the_engine_caps_match_the_shared_fixture():
    """The caps are a real engine limit, not a tunable.

    MSSQL's 2100 is the tightest and is what makes chunking mandatory. A drift
    here would emit a statement a live engine rejects outright.
    """
    for engine, cap in CONTRACT["max_bind_params"].items():
        if engine.startswith("_"):
            continue
        assert SQLTranslator.MAX_BIND_PARAMS.get(engine) == cap, (
            f"{engine} cap drifted from the shared fixture"
        )


def test_no_chunk_ever_exceeds_the_engine_cap():
    """The property the caps exist for, checked across every engine and width.

    Exceeding the cap is a hard error on a real engine, so this is checked
    exhaustively rather than at the two boundaries the fixture names.
    """
    for engine, cap in SQLTranslator.MAX_BIND_PARAMS.items():
        if cap <= 0:
            continue
        for columns in range(1, 12):
            sql = f"INSERT INTO t ({', '.join('c' + str(i) for i in range(columns))}) VALUES ({', '.join(['?'] * columns)})"
            for _sql, params in SQLTranslator.build_batch_inserts(sql, _rows(1500, columns), engine):
                assert len(params) <= cap, f"{engine}/{columns}col chunk had {len(params)} params, cap {cap}"


def test_every_row_and_value_survives_the_collapse_in_order():
    """Rows must be written in the order supplied, with nothing dropped.

    Chunk boundaries are the risk: a batch spanning several statements must
    still flatten to exactly the original sequence of values.
    """
    rows = _rows(701, 3)
    statements = SQLTranslator.build_batch_inserts(
        "INSERT INTO t (a, b, c) VALUES (?, ?, ?)", rows, "mssql"
    )
    assert len(statements) > 1, "this case is only meaningful when it chunks"

    flat = []
    for _sql, params in statements:
        flat.extend(params)
    expected = [value for row in rows for value in row]
    assert flat == expected


@pytest.mark.parametrize(
    "reason",
    sorted(k for k in CONTRACT["collapsible"]["rejected"] if not k.startswith("_")),
)
def test_negative_the_fixtures_rejected_shapes_never_collapse(reason):
    """Each rejection in the shared fixture has a case proving it holds.

    Returning empty means "keep looping", which is always correct. Collapsing
    one of these would silently change what the batch writes.
    """
    samples = {
        "RETURNING": ("INSERT INTO t (a) VALUES (?) RETURNING *", 1),
        "ON CONFLICT": ("INSERT INTO t (a) VALUES (?) ON CONFLICT (a) DO NOTHING", 1),
        "ON DUPLICATE KEY": ("INSERT INTO t (a) VALUES (?) ON DUPLICATE KEY UPDATE a = a", 1),
        "not_an_insert": ("UPDATE t SET a = ? WHERE b = ?", 2),
        "literal_in_values": ("INSERT INTO t (a, b) VALUES (?, now())", 1),
        "ragged_params": ("INSERT INTO t (a, b) VALUES (?, ?)", 2),
        "single_row": ("INSERT INTO t (a) VALUES (?)", 1),
    }
    sql, columns = samples[reason]

    if reason == "ragged_params":
        rows = [["a", "b"], ["c"]]
    elif reason == "single_row":
        rows = _rows(1, columns)
    else:
        rows = _rows(10, columns)

    assert SQLTranslator.build_batch_inserts(sql, rows, "postgres") == [], (
        f"{reason} was collapsed - it must fall back to the row-at-a-time loop"
    )


def test_negative_a_batch_is_never_collapsed_on_firebird():
    """Firebird has no multi-row VALUES syntax.

    Collapsing there emits SQL the engine cannot parse, trading a working slow
    path for a broken fast one.
    """
    for engine in ("firebird", "odbc", "mongodb"):
        assert SQLTranslator.build_batch_inserts(
            "INSERT INTO t (a, b, c) VALUES (?, ?, ?)", _rows(100, 3), engine
        ) == [], f"{engine} must keep the row-at-a-time loop"


def test_negative_an_unknown_engine_falls_back_rather_than_guessing():
    """An engine with no recorded cap must not be assumed to have one."""
    assert SQLTranslator.build_batch_inserts(
        "INSERT INTO t (a) VALUES (?)", _rows(10, 1), "some_new_engine"
    ) == []


@pytest.mark.parametrize(
    "alias,canonical",
    sorted(
        (a, c) for a, c in CONTRACT["engine_aliases"].items() if not a.startswith("_")
    ),
)
def test_an_engine_alias_resolves_to_the_same_cap_as_its_canonical_name(alias, canonical):
    """The drift that made this optimisation a no-op on PostgreSQL.

    Python and PHP report "postgresql" while Ruby and Node report "postgres".
    Reading the cap table without normalising misses, the cap comes back 0, and
    the batch silently keeps looping - on the engine with the largest measured
    win (625x). A live run caught it; this pins it.
    """
    assert SQLTranslator.ENGINE_ALIASES.get(alias) == canonical

    sql = "INSERT INTO t (a, b, c) VALUES (?, ?, ?)"
    rows = _rows(10, 3)
    assert SQLTranslator.build_batch_inserts(sql, rows, alias) == \
        SQLTranslator.build_batch_inserts(sql, rows, canonical)


def test_a_collapsed_batch_still_reports_the_LAST_rows_id_on_mysql():
    """Regression: collapsing a batch silently changed last_id on MySQL.

    MySQL's LAST_INSERT_ID() reports the FIRST generated id of a multi-row
    INSERT, not the last (verified live: a 3-row insert into a fresh table
    reports 1 while MAX(id) is 3). A row-at-a-time batch reported the LAST row's
    id simply because the last statement inserted the last row, so the collapse
    quietly redefined the contract - caught by tests/test_batch_insert.py, which
    asserts last_id is the real id of the final inserted row.
    """
    # 3 rows in the chunk, MySQL reported the first id (1) -> the last is 3.
    assert SQLTranslator.batch_last_id(1, 3, "mysql") == 3
    assert SQLTranslator.batch_last_id(10, 5, "mariadb") == 14   # alias resolves too


@pytest.mark.parametrize("engine", ["sqlite", "postgres", "postgresql", "mssql"])
def test_negative_engines_that_already_report_the_last_id_are_left_alone(engine):
    """Only the engines that need it are adjusted.

    SQLite (last_insert_rowid), PostgreSQL (lastval) and MSSQL already report
    the LAST id. Adding the offset there would push last_id PAST the real row.
    """
    assert SQLTranslator.batch_last_id(7, 3, engine) == 7


def test_negative_a_single_row_chunk_never_shifts_the_id():
    """first + 1 - 1 == first: a one-row chunk must be untouched everywhere."""
    for engine in ("mysql", "sqlite", "postgres", "mssql"):
        assert SQLTranslator.batch_last_id(42, 1, engine) == 42


def test_negative_a_non_numeric_last_id_is_passed_through_unchanged():
    """A UUID/ULID primary key has no arithmetic successor."""
    assert SQLTranslator.batch_last_id("018f-2b7c-uuid", 3, "mysql") == "018f-2b7c-uuid"
    assert SQLTranslator.batch_last_id(None, 3, "mysql") is None


def test_negative_postgresql_spelled_in_full_still_collapses():
    """The exact value Python's own adapter returns.

    get_database_type() returns "postgresql", so this is the spelling that
    actually reaches build_batch_inserts in production. If it stops collapsing,
    every PostgreSQL batch quietly reverts to one round-trip per row.
    """
    statements = SQLTranslator.build_batch_inserts(
        "INSERT INTO t (a, b, c) VALUES (?, ?, ?)", _rows(50, 3), "postgresql"
    )
    assert len(statements) == 1, "postgresql must collapse, not fall back to the loop"
    assert len(statements[0][1]) == 150
