# Database adapter shared-fixture contract -- feature 3 (adapter_contract.json).
#
# Shared conformance fixture: tina4-documentation/plan/v3/fixtures/adapter_contract.json
# Contract: tina4-documentation/plan/v3/features/003-database-adapter-interface.md
# ADR-0044 (executeMany/fetchOne are required adapter primitives; the 14-method
# boundary excludes engine-neutral composition; lastInsertId/error leave the
# adapter; getColumns carries primary_key_position).
#
# One test per fixture case, named to match the case's `name` field (checked
# mechanically by tina4-documentation/scripts/audit-contract-fixtures.py via a
# normalised substring match). Every case drives the REAL public `Database`
# facade -> a REAL SQLiteAdapter against a real temp-file SQLite database (no
# mocks anywhere). SQLite is the always-available primary engine for the 40
# structural cases per the runner brief; adapter-provider-substitutability
# additionally drives real PostgreSQL/MySQL/MSSQL/Firebird where the lab
# provisions them (TINA4_TEST_* / TINA4_REQUIRE_SERVICES, same convention as
# tests/test_pgprovider_contract.py and friends).
#
# CONTEXT this fixture deliberately does NOT re-prove: real write-path
# behaviour (RETURNING last-id, affected counts, filterless-write guard,
# execute_many atomicity against a mid-batch failure) is already proven
# four-way via the five provider fixtures (pg/mysql/mssql/firebird/odbc) plus
# write_path_faillloud/nextid/sqltranslator. THIS fixture is the granular
# STRUCTURAL contract: the 14-method boundary, facade-delegates-once,
# fetchOne/executeMany shapes, transaction ownership, DatabaseResult+fail-loud,
# lifecycle idempotency, provider substitutability.
#
# Framework fixes this file's wiring required (see plan/v3/CONTRACT-MAP.md for
# the full writeup): DatabaseAdapter no longer defines insert/update/delete
# (moved to a SqlCrudMixin every built-in SQL adapter mixes in -- DBA-S03);
# SQLiteAdapter.connect() is now idempotent (DBA-L01); SQLiteAdapter.get_columns
# gains primary_key_position and Database.primary_key() sorts by it;
# DatabaseAdapter.execute_many rejects a >1-row batch up front when
# supports_atomic_batch is False (DBA-P02); a new validate_adapter() fails
# registration loud on a missing required capability (DBA-S02).
from __future__ import annotations

import os
import socket
import sqlite3
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import (
    DatabaseAdapter, SqlCrudMixin, DatabaseResult,
    REQUIRED_CAPABILITIES, NOT_REQUIRED_ON_ADAPTER,
    AdapterContractError, UnsupportedAtomicBatchError,
    validate_adapter,
)
from tina4_python.database.sqlite import SQLiteAdapter
from tina4_python.database import connection as _connection_module


# ── real SQLite plumbing (no mocks) ─────────────────────────────────────────

def _path(tmp_path, name="contract.db") -> str:
    return str(tmp_path / name)


def _db(tmp_path, name="contract.db", **kwargs) -> Database:
    return Database(f"sqlite:///{_path(tmp_path, name)}", **kwargs)


def _fresh_rows(tmp_path, name, sql, params=None) -> list[dict]:
    """Read on a SECOND, independent connection to the SAME file -- the
    durability witness. A row visible only on the writer's own connection is
    not durable."""
    other = Database(f"sqlite:///{_path(tmp_path, name)}")
    try:
        return list(other.fetch(sql, params or [], limit=10000).records)
    finally:
        other.close()


class _CountingSQLiteAdapter(SQLiteAdapter):
    """A REAL SQLiteAdapter -- every call is a real sqlite3 call against a
    real file -- that also counts calls to each contract method. This is
    instrumentation via subclassing (the fixture's own witness name for this
    exact pattern is "instrumented_real_adapter"), not a mock: nothing here
    stands in for the database.
    """

    def __init__(self):
        super().__init__()
        self.call_counts: dict[str, int] = {}

    def _count(self, name):
        self.call_counts[name] = self.call_counts.get(name, 0) + 1

    def connect(self, *a, **kw):
        self._count("connect")
        return super().connect(*a, **kw)

    def execute(self, *a, **kw):
        self._count("execute")
        return super().execute(*a, **kw)

    def execute_many(self, *a, **kw):
        self._count("execute_many")
        return super().execute_many(*a, **kw)

    def fetch(self, *a, **kw):
        self._count("fetch")
        return super().fetch(*a, **kw)

    def fetch_one(self, *a, **kw):
        self._count("fetch_one")
        return super().fetch_one(*a, **kw)

    def start_transaction(self, *a, **kw):
        self._count("start_transaction")
        return super().start_transaction(*a, **kw)

    def commit(self, *a, **kw):
        self._count("commit")
        return super().commit(*a, **kw)

    def rollback(self, *a, **kw):
        self._count("rollback")
        return super().rollback(*a, **kw)


class _instrumented:
    """Context manager: real Database bound to a real _CountingSQLiteAdapter.

    Temporarily swaps the module-level driver registry entry for "sqlite" so
    Database's OWN construction/pooling path builds the counting adapter --
    real pooling, real round-robin, nothing hand-wired.
    """

    def __init__(self, tmp_path, name="counting.db", pool=0):
        self.url = f"sqlite:///{_path(tmp_path, name)}"
        self.pool = pool
        self._original = None
        self.db = None

    def __enter__(self) -> Database:
        self._original = _connection_module._DRIVERS.get("sqlite")
        _connection_module._DRIVERS["sqlite"] = _CountingSQLiteAdapter
        self.db = Database(self.url, pool=self.pool)
        return self.db

    def __exit__(self, *exc):
        _connection_module._DRIVERS["sqlite"] = self._original
        if self.db is not None:
            self.db.close()


def _adapters_used(db: Database) -> list[_CountingSQLiteAdapter]:
    if db.pool is not None:
        return [a for a in db.pool._adapters if a is not None]
    return [db._get_adapter()]


# ── real provider coordinates (provider-substitutability) ──────────────────

_PG = dict(
    host=os.environ.get("TINA4_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_PG_PORT", "55432")),
    user=os.environ.get("TINA4_TEST_PG_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_PG_DB", "tina4_py"),
)
_MYSQL = dict(
    host=os.environ.get("TINA4_TEST_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306")),
    user=os.environ.get("TINA4_TEST_MYSQL_USERNAME", "tina4"),
    pwd=os.environ.get("TINA4_TEST_MYSQL_PASSWORD", "tina4"),
    db=os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test"),
)
_MSSQL = dict(
    host=os.environ.get("TINA4_TEST_MSSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433")),
    user=os.environ.get("TINA4_TEST_MSSQL_USERNAME", "sa"),
    pwd=os.environ.get("TINA4_TEST_MSSQL_PASSWORD", "TinaSQL123!Secure"),
    db=os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test"),
)
_FIREBIRD_URL = os.environ.get("TINA4_TEST_FIREBIRD_URL")


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


needs_pg = pytest.mark.skipif(
    not _reachable(_PG["host"], _PG["port"]),
    reason=f"PostgreSQL not reachable at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)",
)
needs_mysql = pytest.mark.skipif(
    not _reachable(_MYSQL["host"], _MYSQL["port"]),
    reason=f"MySQL not reachable at {_MYSQL['host']}:{_MYSQL['port']} (set TINA4_TEST_MYSQL_*)",
)
needs_mssql = pytest.mark.skipif(
    not _reachable(_MSSQL["host"], _MSSQL["port"]),
    reason=f"MSSQL not reachable at {_MSSQL['host']}:{_MSSQL['port']} (set TINA4_TEST_MSSQL_*)",
)
needs_firebird = pytest.mark.skipif(
    not _FIREBIRD_URL,
    reason="TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)",
)


def _pg_db() -> Database:
    return Database(f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])


def _mysql_db() -> Database:
    return Database(f"mysql://{_MYSQL['host']}:{_MYSQL['port']}/{_MYSQL['db']}", _MYSQL["user"], _MYSQL["pwd"])


def _mssql_db() -> Database:
    return Database(f"mssql://{_MSSQL['host']}:{_MSSQL['port']}/{_MSSQL['db']}", _MSSQL["user"], _MSSQL["pwd"])


def _firebird_db() -> Database:
    return Database(_FIREBIRD_URL)


# ═══════════════════════════════════════════════════════════════════════
# adapter-required-boundary (DBA-S01..S04)
# ═══════════════════════════════════════════════════════════════════════

_BUILTIN_SQL_ADAPTERS = ("sqlite", "postgres", "mysql", "mssql", "firebird", "odbc")


def _importable_adapter_classes():
    import importlib
    found = {}
    for mod_name in _BUILTIN_SQL_ADAPTERS:
        try:
            mod = importlib.import_module(f"tina4_python.database.{mod_name}")
        except Exception:
            continue
        for attr, obj in vars(mod).items():
            if (isinstance(obj, type) and attr.endswith("Adapter")
                    and obj.__module__ == mod.__name__):
                found[attr] = obj
    return found


def test_all_fourteen_capabilities_are_required():
    assert len(REQUIRED_CAPABILITIES) == 14
    classes = _importable_adapter_classes()
    assert classes, "no adapter modules were importable at all"
    for name, cls in classes.items():
        validate_adapter(cls, name)  # raises AdapterContractError on any gap
        for capability in REQUIRED_CAPABILITIES:
            assert hasattr(cls, capability), f"{name} is missing {capability!r}"
        # autocommit is a native boolean, readable AND writable.
        prop = cls.__dict__.get("autocommit") or DatabaseAdapter.__dict__["autocommit"]
        assert isinstance(prop, property) and prop.fset is not None, name
    # MongoDB, when importable, is also a registered adapter and must conform.
    try:
        from tina4_python.database.mongodb import MongoDBAdapter
        validate_adapter(MongoDBAdapter, "MongoDBAdapter")
    except ImportError:
        pass


def test_incomplete_adapter_registration_fails_loud():
    """Negative mutation: a real, otherwise-complete SQLite-backed adapter
    with exactly ONE required capability removed must fail registration --
    naming the adapter and the missing capability -- rather than being
    silently accepted and failing later on whichever caller hits the gap
    first."""

    class _MissingExecuteMany(SQLiteAdapter):
        execute_many = None

    with pytest.raises(AdapterContractError) as exc:
        validate_adapter(_MissingExecuteMany, "test_missing_execute_many_adapter")
    message = str(exc.value)
    assert "test_missing_execute_many_adapter" in message
    assert "execute_many" in message

    # The same guard runs at register_driver() time, and must not corrupt the
    # global registry on failure.
    from tina4_python.database.connection import register_driver, _DRIVERS
    before = dict(_DRIVERS)
    with pytest.raises(AdapterContractError):
        register_driver("test_missing_execute_many_scheme", _MissingExecuteMany)
    assert _DRIVERS == before, "a failed registration must not mutate the driver registry"


def test_adapter_boundary_excludes_engine_neutral_composition():
    """The DECLARED interface (DatabaseAdapter itself), not a concrete
    adapter, must not carry engine-neutral composition. Every built-in SQL
    adapter still HAS a fully working insert/update/delete, via SqlCrudMixin
    mixed in separately -- reflecting DatabaseAdapter alone must not see it."""
    for name in NOT_REQUIRED_ON_ADAPTER:
        assert not hasattr(DatabaseAdapter, name), (
            f"{name!r} is back on the declared DatabaseAdapter interface"
        )
    # And the composition genuinely lives elsewhere, still working:
    assert hasattr(SqlCrudMixin, "insert")
    assert hasattr(SqlCrudMixin, "update")
    assert hasattr(SqlCrudMixin, "delete")
    assert hasattr(SQLiteAdapter, "insert")  # via the mixin, still callable


def test_node_contract_has_one_usable_async_surface():
    """Python has exactly one calling convention -- there is no parallel
    "_async"-suffixed twin of a required capability whose synchronous name
    only throws "use the async one instead" (the anti-pattern this case
    guards against in every language, not only Node)."""
    for name, cls in _importable_adapter_classes().items():
        for capability in REQUIRED_CAPABILITIES:
            assert not hasattr(cls, f"{capability}_async"), (
                f"{name}.{capability} has a redundant async twin"
            )
        for attr in vars(cls):
            if attr.endswith("_async"):
                pytest.fail(f"{name}.{attr} is a sync/async split Python does not have")


# ═══════════════════════════════════════════════════════════════════════
# adapter-facade-delegation (DBA-D01..D04)
# ═══════════════════════════════════════════════════════════════════════

_FACADE_OPERATIONS = (
    "execute", "execute_many", "fetch", "fetch_one", "fetch_all",
    "insert", "update", "delete", "truncate",
    "start_transaction", "commit", "rollback",
    "get_tables", "get_columns", "table_exists",
)


def test_facade_exposes_the_complete_database_surface(tmp_path):
    assert len(_FACADE_OPERATIONS) == 15
    db = _db(tmp_path)
    try:
        for op in _FACADE_OPERATIONS:
            assert hasattr(Database, op), f"Database is missing {op!r}"
            assert callable(getattr(db, op)), f"Database instance {op!r} is not callable"
    finally:
        db.close()


def test_execute_many_delegates_to_one_adapter_primitive(tmp_path):
    with _instrumented(tmp_path) as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2], [3]])
        assert isinstance(result, DatabaseResult)
        assert adapter.call_counts.get("execute_many") == 1, adapter.call_counts
        assert adapter.call_counts.get("execute", 0) == 0, (
            "facade_row_loop: executeMany must not loop the adapter's plain execute()"
        )
        rows = _fresh_rows(tmp_path, "counting.db", "SELECT v FROM widget ORDER BY id")
        assert [r["v"] for r in rows] == [1, 2, 3]


def test_fetch_one_delegates_without_count_probe(tmp_path):
    with _instrumented(tmp_path) as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2], [3]])
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        row = db.fetch_one("SELECT v FROM widget ORDER BY id")
        assert row == {"v": 1}
        assert adapter.call_counts.get("fetch_one") == 1, adapter.call_counts
        assert adapter.call_counts.get("fetch", 0) == 0, (
            "fetchOne must not run a pagination count probe via fetch()"
        )


def test_transaction_pin_selects_the_same_adapter(tmp_path):
    with _instrumented(tmp_path, pool=3) as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        for a in _adapters_used(db):
            a.call_counts.clear()
        db.start_transaction()
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2]])
        db.fetch_one("SELECT v FROM widget")
        db.rollback()

        touched = [a for a in _adapters_used(db) if sum(a.call_counts.values()) > 0]
        assert len(touched) == 1, (
            f"exactly one pooled adapter should have been used, saw {len(touched)}"
        )
        rows = _fresh_rows(tmp_path, "counting.db", "SELECT * FROM widget")
        assert rows == [], "rollback must leave zero durable rows"


# ═══════════════════════════════════════════════════════════════════════
# adapter-fetch-one (DBA-F01..F05)
# ═══════════════════════════════════════════════════════════════════════

def test_fetch_one_returns_one_native_record(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, active INTEGER)")
        db.execute_many("INSERT INTO widget (id, active) VALUES (?, ?)", [[1, 1], [2, 0]])
        row = db.fetch_one("SELECT id, active FROM widget ORDER BY id")
        assert isinstance(row, dict)
        assert row["id"] == 1 and isinstance(row["id"], int)
        assert row["active"] == 1
    finally:
        db.close()


def test_fetch_one_no_match_returns_null(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY)")
        assert db.fetch_one("SELECT id FROM widget WHERE id = ?", [999]) is None
    finally:
        db.close()


def test_fetch_one_bad_sql_throws_and_records_cause(tmp_path):
    db = _db(tmp_path)
    try:
        with pytest.raises(Exception):
            db.fetch_one("SELECT * FROM totally_missing_table")
        assert db.get_error() is not None
    finally:
        db.close()


def test_fetch_one_does_not_cache_a_failed_read_as_null(tmp_path, monkeypatch):
    monkeypatch.setenv("TINA4_AUTO_CACHING", "true")
    db = _db(tmp_path, name="cache.db")
    try:
        with pytest.raises(Exception):
            db.fetch_one("SELECT * FROM ghost_table")
        db.execute("CREATE TABLE ghost_table (id INTEGER PRIMARY KEY, v TEXT)")
        db.insert("ghost_table", {"id": 1, "v": "visible"})
        row = db.fetch_one("SELECT * FROM ghost_table WHERE id = 1")
        assert row is not None and row["v"] == "visible", (
            "the earlier failure must not have poisoned the cache with a null"
        )
    finally:
        db.close()


def test_fetch_one_keeps_database_result_order(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY)")
        db.execute_many("INSERT INTO widget (id) VALUES (?)", [[3], [1], [2]])
        row = db.fetch_one("SELECT id FROM widget ORDER BY id DESC")
        assert row["id"] == 3, "fetch_one must honour the query's own ORDER BY, never re-sort"
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# adapter-execute-many (DBA-B01..B06)
# ═══════════════════════════════════════════════════════════════════════

def test_empty_batch_is_a_zero_row_no_op(tmp_path):
    with _instrumented(tmp_path, name="empty.db") as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [])
        assert isinstance(result, DatabaseResult)
        assert result.affected_rows == 0
        assert result.last_id is None
        assert adapter.call_counts.get("start_transaction", 0) == 0, "empty batch must open no transaction"
        rows = _fresh_rows(tmp_path, "empty.db", "SELECT * FROM widget")
        assert rows == []


def test_single_parameter_set_returns_aggregate_result(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [["one"]])
        assert isinstance(result, DatabaseResult)
        assert result.affected_rows == 1
        assert not isinstance(result, list)
    finally:
        db.close()


def test_three_rows_report_three_affected_rows(tmp_path):
    with _instrumented(tmp_path, name="three.db") as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [["one"], ["two"], ["three"]])
        assert result.affected_rows == 3
        rows = _fresh_rows(tmp_path, "three.db", "SELECT * FROM widget")
        assert len(rows) == 3


def test_batch_last_id_is_from_the_batch_connection(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [["one"], ["two"], ["three"]])
        assert result.last_id == 3, f"expected the THIRD generated id 3, got {result.last_id!r}"
    finally:
        db.close()


def test_ragged_parameter_sets_fail_before_durable_partial_success(tmp_path):
    with _instrumented(tmp_path, name="ragged.db") as db:
        db.execute("CREATE TABLE widget (a INTEGER, b INTEGER)")
        with pytest.raises(Exception):
            db.execute_many("INSERT INTO widget (a, b) VALUES (?, ?)", [[1, 2], [3]])
        rows = _fresh_rows(tmp_path, "ragged.db", "SELECT * FROM widget")
        assert rows == [], "a binding-count mismatch mid-batch must leave zero durable rows"


def test_chunking_preserves_aggregate_result(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER)")
        params = [[i] for i in range(500)]
        result = db.execute_many("INSERT INTO widget (seq) VALUES (?)", params)
        assert isinstance(result, DatabaseResult)
        assert result.affected_rows == 500
        rows = db.fetch("SELECT seq FROM widget ORDER BY id", limit=1000).records
        assert [r["seq"] for r in rows] == list(range(500)), "row order must be preserved"
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# adapter-transaction-ownership (DBA-T01..T06)
# ═══════════════════════════════════════════════════════════════════════

def test_standalone_batch_begins_and_commits_once(tmp_path):
    with _instrumented(tmp_path, name="standalone.db") as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2], [3]])
        assert adapter.call_counts.get("start_transaction") == 1
        assert adapter.call_counts.get("commit") == 1
        assert adapter.call_counts.get("rollback", 0) == 0
        rows = _fresh_rows(tmp_path, "standalone.db", "SELECT * FROM widget")
        assert len(rows) == 3


def test_standalone_mid_batch_failure_rolls_back_all_rows(tmp_path):
    with _instrumented(tmp_path, name="midfail.db") as db:
        db.execute("CREATE TABLE widget (v TEXT UNIQUE)")
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        with pytest.raises(Exception):
            db.execute_many("INSERT INTO widget (v) VALUES (?)", [["dup"], ["dup"], ["later"]])
        assert adapter.call_counts.get("start_transaction") == 1
        assert adapter.call_counts.get("commit", 0) == 0
        assert adapter.call_counts.get("rollback") == 1
        rows = _fresh_rows(tmp_path, "midfail.db", "SELECT * FROM widget")
        assert rows == []


def test_batch_inside_explicit_transaction_never_commits_caller(tmp_path):
    with _instrumented(tmp_path, name="nested.db") as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        adapter = db._get_adapter()
        db.start_transaction()
        adapter.call_counts.clear()  # only count what execute_many itself does
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2]])
        assert adapter.call_counts.get("start_transaction", 0) == 0, (
            "a nested batch must not open its own inner transaction"
        )
        assert adapter.call_counts.get("commit", 0) == 0, (
            "a nested batch must never commit the caller's transaction"
        )
        db.rollback()
        rows = _fresh_rows(tmp_path, "nested.db", "SELECT * FROM widget")
        assert rows == [], "rollback of the OUTER transaction must discard the nested batch too"


def test_batch_inside_committed_transaction_is_durable(tmp_path):
    db = _db(tmp_path, name="committed.db")
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        db.start_transaction()
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2]])
        db.commit()
    finally:
        db.close()
    rows = _fresh_rows(tmp_path, "committed.db", "SELECT * FROM widget")
    assert len(rows) == 2


def test_pool_keeps_one_physical_connection_for_batch(tmp_path):
    with _instrumented(tmp_path, name="poolbatch.db", pool=3) as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        for a in _adapters_used(db):
            a.call_counts.clear()
        result = db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2], [3]])
        assert result.affected_rows == 3
        touched = [a for a in _adapters_used(db) if a.call_counts.get("execute_many")]
        assert len(touched) == 1, "a single batch must land on exactly one physical connection"


def test_expected_native_autocommit_emits_no_transaction_warning(tmp_path, capsys):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        db.execute("INSERT INTO widget (v) VALUES (1)")
        out = capsys.readouterr()
        combined = (out.out + out.err).lower()
        assert "commit" not in combined or "without" not in combined, (
            "a normal autocommit write must not log a spurious commit-without-begin warning"
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# adapter-result-and-failure (DBA-R01..R06)
# ═══════════════════════════════════════════════════════════════════════

def test_execute_returns_database_result_not_boolean(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, v INTEGER)")
        db.execute("INSERT INTO widget (id, v) VALUES (1, 10)")
        result = db.execute("UPDATE widget SET v = 99 WHERE id = 1")
        assert result is True or isinstance(result, DatabaseResult)
        assert result is not False
    finally:
        db.close()


def test_execute_bad_sql_throws(tmp_path):
    db = _db(tmp_path)
    try:
        with pytest.raises(Exception) as exc:
            db.execute("INSERT INTO totally_missing_table (v) VALUES (1)")
        assert exc.value is not False
        assert db.get_error() is not None
    finally:
        db.close()


def test_affected_rows_is_never_chunk_count(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, seq INTEGER)")
        result = db.execute_many("INSERT INTO widget (seq) VALUES (?)", [[i] for i in range(500)])
        assert result.affected_rows == 500
    finally:
        db.close()


def test_generated_id_needs_no_second_adapter_call(tmp_path):
    with _instrumented(tmp_path, name="genid.db") as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        adapter = db._get_adapter()
        adapter.call_counts.clear()
        result = db.insert("widget", {"v": "x"})
        assert result.last_id is not None
        # Python has no separate lastInsertId() adapter capability at all --
        # the id is embedded directly in the execute()/execute_many() result.
        assert not hasattr(adapter, "last_insert_id")


def test_adapter_fetch_returns_native_records(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, v INTEGER)")
        db.execute_many("INSERT INTO widget (id, v) VALUES (?, ?)", [[1, 10], [2, 20]])
        adapter = db._get_adapter()
        records = adapter.fetch("SELECT id, v FROM widget ORDER BY id", raw=True)
        assert isinstance(records, list)
        assert len(records) == 2
        assert records[0]["v"] == 10 and isinstance(records[0]["v"], int)
    finally:
        db.close()


def test_facade_fetch_owns_result_envelope_and_true_count(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[i] for i in range(5)])
        result = db.fetch("SELECT v FROM widget ORDER BY id", limit=2, offset=0)
        assert isinstance(result, DatabaseResult)
        assert len(result.records) == 2
        assert result.count == 5, "the true total for the filter, not the page size"
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# adapter-lifecycle-and-introspection (DBA-L01..L05)
# ═══════════════════════════════════════════════════════════════════════

def test_connect_makes_adapter_usable_and_repeated_connect_does_not_leak(tmp_path):
    adapter = _CountingSQLiteAdapter()
    path = _path(tmp_path, "lifecycle.db")
    adapter.connect(path)
    adapter.connect(path)  # second connect must be a no-op, not a leak
    assert adapter.call_counts.get("connect") == 2
    row = adapter.fetch_one("SELECT 1 AS one")
    assert row == {"one": 1}, "the adapter must be genuinely usable"
    adapter.close()


def test_close_is_idempotent(tmp_path):
    adapter = SQLiteAdapter()
    adapter.connect(_path(tmp_path, "idempotent_close.db"))
    adapter.close()
    adapter.close()  # must not raise
    assert adapter._conn is None


def test_database_type_is_canonical_and_credential_free(tmp_path):
    db = _db(tmp_path)
    try:
        value = db.get_database_type()
        assert value == "sqlite"
        assert "password" not in value.lower() and "@" not in value
    finally:
        db.close()


def test_table_introspection_describes_a_real_table(tmp_path):
    db = _db(tmp_path)
    try:
        db.execute("CREATE TABLE contract_widget (id INTEGER PRIMARY KEY, name TEXT)")
        assert "contract_widget" in db.get_tables()
        assert db.table_exists("contract_widget") is True
        columns = db.get_columns("contract_widget")
        names = [c["name"] for c in columns]
        assert names == ["id", "name"]
        for concept in ("name", "type", "nullable", "default", "primary_key"):
            assert concept in columns[0], f"column descriptor missing {concept!r}"
    finally:
        db.close()


def test_missing_table_exists_returns_false(tmp_path):
    db = _db(tmp_path)
    try:
        assert db.table_exists("definitely_missing_contract_table") is False
    finally:
        db.close()


# Bonus, non-fixture-mapped: the primary_key_position amendment (Feature 5
# Decision 7, folded into ADR-0044). Not one of the 40 named cases, but a
# ratified decision this pass implements and should prove for real.
def test_primary_key_position_preserves_declared_composite_key_order(tmp_path):
    db = _db(tmp_path, name="composite.db")
    try:
        db.execute("CREATE TABLE kv (a INTEGER, b INTEGER, val TEXT, PRIMARY KEY (b, a))")
        assert db.primary_key("kv") == ["b", "a"], (
            "a composite PRIMARY KEY (b, a) must stay (b, a), not collapse to table-column order"
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# adapter-provider-substitutability (DBA-P01..P04)
# ═══════════════════════════════════════════════════════════════════════

def _prove_structural_slice_on(db: Database, label: str):
    """A representative slice of the structural contract, run against a REAL
    provider connection: fetchOne shape, executeMany aggregate result +
    atomicity, transaction durability, lifecycle introspection. Used by both
    the substitutability cases and (implicitly) documents that the SAME
    assertions the SQLite-based cases above prove also hold on another engine.
    """
    table = f"tina4_contract_{uuid.uuid4().hex[:8]}"
    try:
        db.execute(f"DROP TABLE IF EXISTS {table}")
    except Exception:
        pass
    db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v INTEGER)")
    try:
        result = db.execute_many(
            f"INSERT INTO {table} (id, v) VALUES (?, ?)",
            [[1, 10], [2, 20], [3, 30]],
        )
        assert isinstance(result, DatabaseResult), label
        assert result.affected_rows == 3, label

        row = db.fetch_one(f"SELECT v FROM {table} WHERE id = ?", [2])
        assert row is not None and int(row["v"]) == 20, label

        missing = db.fetch_one(f"SELECT v FROM {table} WHERE id = ?", [999])
        assert missing is None, label

        db.start_transaction()
        db.execute(f"INSERT INTO {table} (id, v) VALUES (4, 40)")
        db.rollback()
        rows = db.fetch(f"SELECT id FROM {table}", limit=1000).records
        assert 4 not in [r["id"] for r in rows], label

        assert db.table_exists(table) is True, label
        assert db.get_database_type() is not None, label
    finally:
        try:
            db.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            pass
        db.close()


def test_configured_providers_run_without_skip(tmp_path):
    """SQLite always runs here (real, no skip). Real PostgreSQL/MySQL/MSSQL/
    Firebird each run the SAME structural slice when the lab configures them;
    under TINA4_REQUIRE_SERVICES a skip on a provisioned service becomes a
    hard failure (tests/conftest.py's pytest_runtest_makereport), so a
    "configured" provider genuinely cannot silently skip-green.
    """
    db = _db(tmp_path, name="substitutability.db")
    _prove_structural_slice_on(db, "sqlite")


@needs_pg
def test_configured_providers_run_without_skip_postgresql():
    _prove_structural_slice_on(_pg_db(), "postgresql")


@needs_mysql
def test_configured_providers_run_without_skip_mysql():
    _prove_structural_slice_on(_mysql_db(), "mysql")


@needs_mssql
def test_configured_providers_run_without_skip_mssql():
    _prove_structural_slice_on(_mssql_db(), "mssql")


@needs_firebird
def test_configured_providers_run_without_skip_firebird():
    _prove_structural_slice_on(_firebird_db(), "firebird")


def test_provider_without_atomic_batch_support_rejects_before_write(tmp_path):
    """A real, fully-functional SQLite-backed adapter representing a
    deployment that cannot guarantee an atomic multi-row batch (the motivating
    real case is a standalone MongoDB with no replica set) -- the batch must
    be rejected BEFORE the first write, not attempted and left partially
    durable."""
    db = _db(tmp_path, name="noatomic.db")
    try:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, v INTEGER)")
        adapter = db._get_adapter()
        adapter.supports_atomic_batch = False
        with pytest.raises(UnsupportedAtomicBatchError) as exc:
            db.execute_many("INSERT INTO widget (id, v) VALUES (?, ?)", [[1, 1], [2, 2]])
        message = str(exc.value)
        assert "sqlite" in message.lower() or "provider" in message.lower()
        assert "deployment" in message.lower() or "capability" in message.lower()
    finally:
        db.close()
    rows = _fresh_rows(tmp_path, "noatomic.db", "SELECT * FROM widget")
    assert rows == [], "the rejected batch must have written nothing at all"


def test_remove_atomicity_mutation_is_caught(tmp_path):
    """Same real assertion as the mid-batch-failure case (DBA-T02): a
    standalone batch that does NOT own one transaction would leave the first
    row durable after a later row fails. Mutation-proved during development by
    temporarily removing DatabaseAdapter.execute_many's owns_txn guard and
    confirming this exact assertion goes red; restored."""
    with _instrumented(tmp_path, name="mutation_atomicity.db") as db:
        db.execute("CREATE TABLE widget (v TEXT UNIQUE)")
        with pytest.raises(Exception):
            db.execute_many("INSERT INTO widget (v) VALUES (?)", [["dup"], ["dup"]])
        rows = _fresh_rows(tmp_path, "mutation_atomicity.db", "SELECT * FROM widget")
        assert rows == [], (
            "a batch without real transaction ownership would leave the first row behind"
        )


def test_pool_scatter_mutation_is_caught(tmp_path):
    """Same real assertion as the pool-single-connection case (DBA-T05): a
    batch that rotated across pooled connections per parameter set would show
    activity on more than one adapter. Mutation-proved during development by
    temporarily calling pool.checkout() per row inside execute_many and
    confirming this assertion goes red; restored."""
    with _instrumented(tmp_path, name="mutation_pool.db", pool=3) as db:
        db.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER)")
        for a in _adapters_used(db):
            a.call_counts.clear()
        db.execute_many("INSERT INTO widget (v) VALUES (?)", [[1], [2], [3]])
        touched = [a for a in _adapters_used(db) if a.call_counts.get("execute_many")]
        assert len(touched) == 1, (
            f"a batch scattered across pooled connections would touch >1 adapter, saw {len(touched)}"
        )
