"""The write-path contract (feature 3/4 of the feature audit).

``tests/fixtures/write_path_contract.json`` is byte-identical in all four
frameworks and is the shared answer key: the same cases, the same seeds, the
same expectations, executed identically in python, php, ruby and node.

The bug these lock in: ``db.update(table, data)`` with no explicit filter used
to build ``UPDATE table SET ...`` with NO WHERE clause, so it overwrote EVERY
row and reported success. A write with no filter is now an error.

The fixture used to be ORPHANED - nothing read it, and the four runners were
hand-written independently. They drifted to 17/16/15/14 cases with different
names, and the case ``a_string_filter_with_params_works_the_same_as_a_hash_filter``
was executed by NONE of them while exactly that shape shipped broken in four
Node adapters. Every case now runs in every framework, from this one file.

RUN IT AGAINST EVERY LIVE ENGINE. SQLite alone proves nothing: the whole reason
per-adapter write SQL exists is that placeholder style, RETURNING support and
identifier quoting differ exactly where the engine differs. No mocks - a
database is a real dependency and CI provisions it.
"""

import json
import os
from pathlib import Path

import pytest

from tina4_python.database import Database

FIXTURE = Path(__file__).parent / "fixtures" / "write_path_contract.json"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))

TABLE = CONTRACT["table"]["name"]
COMPOSITE_TABLE = CONTRACT["composite_table"]["name"]

# Cases and errors are one flat list keyed by name: both halves are contract
# cases, they only differ in whether the expectation is a raise.
ALL_CASES = {c["name"]: c for c in CONTRACT["cases"] + CONTRACT["errors"]}

# Every op the dispatcher below implements. A fixture case naming an op that is
# not here fails loudly rather than being silently skipped - the orphan guard.
IMPLEMENTED_OPS = {
    "insert", "insert_batch", "update", "delete", "truncate", "primary_key",
    "transaction_rollback", "transaction_commit", "execute_raw",
}


def _engines():
    """Every engine this run can reach.

    ``TINA4_TEST_WRITE_PATH_URL`` is the shared spelling all four runners
    accept, so one CI invocation drives the identical suite everywhere. The
    per-engine triples below are Python's own extra: they let a single local
    invocation cover several engines at once.

    Every variable name is written out IN FULL rather than built from a
    prefix. The names used to be assembled as f"{prefix}_URL", which the
    environment contract gate (tests/test_env_contract.py) cannot resolve -
    it saw only a bare service prefix and had no way to know which real names
    that stood for. An explicit triple is the remedy the shared fixture
    prescribes, and it is what the Ruby queue specs did for the same reason.

    SQLite is always included and always insufficient on its own, so the run
    reports which engines it actually covered.
    """
    found = [("sqlite", (None, None, None))]
    for name, url_var, username_var, password_var in (
        (
            "write_path",
            "TINA4_TEST_WRITE_PATH_URL",
            "TINA4_TEST_WRITE_PATH_USERNAME",
            "TINA4_TEST_WRITE_PATH_PASSWORD",
        ),
        ("postgres", "TINA4_TEST_PG_URL", "TINA4_TEST_PG_USERNAME", "TINA4_TEST_PG_PASSWORD"),
        ("mysql", "TINA4_TEST_MYSQL_URL", "TINA4_TEST_MYSQL_USERNAME", "TINA4_TEST_MYSQL_PASSWORD"),
        ("mssql", "TINA4_TEST_MSSQL_URL", "TINA4_TEST_MSSQL_USERNAME", "TINA4_TEST_MSSQL_PASSWORD"),
        # Firebird is deliberately last and is NOT in the .99 default set: the
        # suite HANGS against it rather than failing, so it has to be opted into
        # knowingly. Left running it would look like a slow suite instead of a
        # blocked one. Tracked as its own item; do not add it to a CI matrix
        # until the hang is understood.
        (
            "firebird",
            "TINA4_TEST_FIREBIRD_URL",
            "TINA4_TEST_FIREBIRD_USERNAME",
            "TINA4_TEST_FIREBIRD_PASSWORD",
        ),
    ):
        url = (os.environ.get(url_var) or "").strip()
        if not url:
            continue
        # PER-ENGINE credentials, falling back to the global pair. Without this
        # the engines cannot run in ONE invocation: MSSQL's login is not MySQL's,
        # so a single TINA4_DATABASE_USERNAME can only ever satisfy some of them
        # and the rest fail at connect - which reads like a broken suite rather
        # than a credential problem.
        user = os.environ.get(username_var) or os.environ.get("TINA4_DATABASE_USERNAME") or ""
        password = os.environ.get(password_var) or os.environ.get("TINA4_DATABASE_PASSWORD") or ""
        found.append((name, (url, user, password)))
    return found


ENGINES = _engines()


class ContractConnection:
    """One engine under test, plus the ability to open a SECOND connection.

    ``visible_after_reconnect`` is the whole reason the second connection
    exists: a write that is only visible on the connection that made it is not
    durable, and reading it back on the same handle cannot tell the difference.
    """

    def __init__(self, url, username, password):
        self._url = url
        self._username = username
        self._password = password
        self.database = self.connect()

    def connect(self):
        return Database(self._url, username=self._username, password=self._password)


@pytest.fixture(scope="module", params=ENGINES, ids=[name for name, _ in ENGINES])
def contract(request, tmp_path_factory):
    """Both contract tables on a real engine, created once per engine."""
    _, (url, username, password) = request.param
    if url is None:
        url = f"sqlite:///{tmp_path_factory.mktemp('writepath')}/contract.db"
        username = password = ""

    connection = ContractConnection(url, username, password)
    database = connection.database

    for table in (TABLE, COMPOSITE_TABLE):
        try:
            database.execute(f"DROP TABLE {table}")
        except Exception:  # noqa: BLE001 - first run against this engine
            pass
    # The DDL lives in the shared fixture so all four frameworks create
    # literally the same table. Ids come from the case data, not a sequence -
    # an identity column would fight the explicit ids the cases name.
    database.execute(CONTRACT["table"]["ddl"])
    database.execute(CONTRACT["composite_table"]["ddl"])
    database.commit()

    yield connection

    for table in (TABLE, COMPOSITE_TABLE):
        try:
            database.execute(f"DROP TABLE {table}")
            database.commit()
        except Exception:  # noqa: BLE001 - teardown must never mask a failure
            pass


def _table_for(case):
    return COMPOSITE_TABLE if case.get("table") == "composite" else TABLE


def _rows(database, table):
    """Every row in the table. The limit is explicit - fetch() defaults to 10."""
    return [dict(r) for r in database.fetch(f"SELECT * FROM {table}", limit=1000).records]


def _same(actual, expected):
    """Engine-tolerant value comparison.

    Engines disagree on the Python type of an INTEGER column (int, Decimal,
    str on some ODBC paths). This contract is about WHICH rows a write touched,
    not about type mapping, which the adapter contract owns.
    """
    return actual == expected or str(actual) == str(expected)


def _reset(database):
    """Both tables empty. Raw DELETE, never truncate() - that is under test."""
    for table in (TABLE, COMPOSITE_TABLE):
        database.execute(f"DELETE FROM {table}")
    database.commit()


def _seed(database, case, table):
    for row in case.get("seed", []):
        database.insert(table, dict(row))
    database.commit()


def _run_op(database, case, table):
    """Execute the case's declared op. Returns whatever the op returns."""
    op = case["op"]
    data = case.get("data")

    if op in ("insert", "insert_batch"):
        return database.insert(table, data if op == "insert_batch" else dict(data))

    if op == "update":
        if "filter_sql" in case:
            return database.update(table, dict(data), case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return database.update(table, dict(data), dict(case["filter"]))
        return database.update(table, dict(data))

    if op == "delete":
        if "filter_sql" in case:
            return database.delete(table, case["filter_sql"], list(case["filter_params"]))
        if "filter" in case:
            return database.delete(table, dict(case["filter"]))
        return database.delete(table)

    if op == "truncate":
        return database.truncate(table)

    if op == "primary_key":
        return database.primary_key(table)

    if op in ("transaction_rollback", "transaction_commit"):
        database.start_transaction()
        database.insert(table, dict(data))
        if op == "transaction_commit":
            database.commit()
        else:
            database.rollback()
        return None

    if op == "execute_raw":
        return database.execute(case["sql"])

    raise AssertionError(f"unimplemented op {op!r} in case {case['name']!r}")


def _check_expectations(connection, case, table, result):
    """Every expectation the fixture declares, checked by name."""
    name = case["name"]
    expect = case.get("expect", {})
    database = connection.database

    if "affected_rows" in expect:
        assert result.affected_rows == expect["affected_rows"], (
            f"{name}: expected affected_rows {expect['affected_rows']}, "
            f"got {result.affected_rows}"
        )

    rows = _rows(database, table) if ("rows_after" in expect or "unchanged" in expect) else []

    if "rows_after" in expect:
        assert len(rows) == expect["rows_after"], (
            f"{name}: expected {expect['rows_after']} row(s) after, got {len(rows)}: {rows}"
        )

    for matcher in expect.get("unchanged", []):
        matched = [r for r in rows if all(_same(r.get(k), v) for k, v in matcher.items())]
        assert len(matched) == 1, (
            f"{name}: expected exactly one row matching {matcher}, found "
            f"{len(matched)} in {rows}"
        )

    if "primary_key" in expect:
        assert list(result) == expect["primary_key"], (
            f"{name}: expected primary key {expect['primary_key']}, got {result!r}"
        )

    if expect.get("last_id_is_null"):
        assert result.last_id is None, (
            f"{name}: last_id is insert-only, but this write reported {result.last_id!r}"
        )

    if "last_id_is_not_stale" in expect:
        stale = expect["last_id_is_not_stale"]
        reported = result.last_id
        # None / 0 / "" all mean "this engine cannot report one", which the
        # contract allows. A stale value is the failure being pinned.
        if reported not in (None, 0, ""):
            assert not _same(reported, stale), (
                f"{name}: last_id came back as the EARLIER row's id ({stale!r}) - "
                f"the adapter is reporting a stale id rather than null"
            )

    if expect.get("visible_after_reconnect"):
        other = connection.connect()
        try:
            assert len(_rows(other, table)) == expect.get("rows_after", 1), (
                f"{name}: the write is not visible on a second connection - "
                f"it was never durable"
            )
        finally:
            try:
                other.close()
            except Exception:  # noqa: BLE001 - some adapters have no close()
                pass


def test_the_run_records_which_engines_it_covered():
    """Not a gate - the record.

    A reader must be able to see whether this contract was checked against real
    engines or only against the one that shares nothing with them.
    """
    print(f"\nwrite-path contract covered: {', '.join(n for n, _ in ENGINES)}")
    assert ENGINES


def test_the_runner_implements_every_op_the_shared_fixture_uses():
    """The orphan guard.

    A case naming an op the dispatcher does not implement must FAIL, never be
    quietly skipped. Silent skipping is how the fixture went unread for its
    whole life while the runners drifted apart.
    """
    declared = {c["op"] for c in ALL_CASES.values()}
    assert declared <= IMPLEMENTED_OPS, (
        f"the shared fixture declares op(s) this runner cannot execute: "
        f"{sorted(declared - IMPLEMENTED_OPS)}"
    )


@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_case_from_the_shared_fixture(contract, name):
    """Every case in the shared fixture, checked against the same answer key."""
    case = ALL_CASES[name]
    table = _table_for(case)
    database = contract.database

    _reset(database)
    _seed(database, case, table)

    if case.get("expect_raises"):
        with pytest.raises(Exception):  # noqa: B017 - the framework's own type varies by op
            _run_op(database, case, table)
        # The write must not have landed. This is the data-loss property.
        _check_expectations(contract, case, table, None)
        if case.get("expect_error_recorded"):
            assert database.get_error(), (
                f"{name}: the statement raised but get_error() was empty - "
                f"the cause has to stay readable after the raise"
            )
        return

    result = _run_op(database, case, table)
    _check_expectations(contract, case, table, result)
