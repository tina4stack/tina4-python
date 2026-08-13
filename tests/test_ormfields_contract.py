"""Feature 18 - ORM fields and column mapping: the shared conformance contract.

Proves the reconciled field-model BEHAVIOUR (FIELD-DEC-01 gap + FIELD-DEC-02),
NO MOCKS. The cross-engine DDL cases actually CREATE the table on real
PostgreSQL / MySQL / MSSQL / Firebird and read the column type back from each
engine's OWN catalog -- this REPLACES the deleted monkeypatch mock
(``test_orm_v3_13_11::test_engine_dispatch``) that asserted a SQL string.

Case names are shared verbatim (each language's own idiom) across the four
frameworks and gated by scripts/audit-contract-fixtures.py.

Coordinates use the canonical TINA4_TEST_* convention (same as the provider
contract suites). Under TINA4_REQUIRE_SERVICES a PG/MySQL/MSSQL skip is a hard
failure (see tests/conftest.py); Firebird is gated -- it runs when
TINA4_TEST_FIREBIRD_URL is set (the lab sets it), else it stays green.
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import os
import socket
import tempfile
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.orm import (
    ORM,
    BooleanField,
    DateTimeField,
    DecimalField,
    IntegerField,
    JSONField,
    StringField,
    TextField,
    bind_database,
)


# ── real SQLite (no service) for the type/JSON/default/decimal-DDL cases ──


@pytest.fixture
def sqlite_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(f"sqlite:///{path}")
    bind_database(db)
    yield db
    try:
        db.close()
    except Exception:
        pass
    os.unlink(path)


def _ddl(db, table):
    row = db.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [table]
    )
    return row["sql"] if row else ""


def test_each_declared_field_type_round_trips_through_a_real_database(sqlite_db):
    """Every field kind: write coercion -> DDL column -> read hydration, on a
    real database (SQLite here; the engine variants below prove PG/MySQL/MSSQL/
    Firebird). The value the field went in as is the value it comes back as."""
    class Widget(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()
        note = TextField()
        qty = IntegerField()
        active = BooleanField()
        ratio = DecimalField(precision=8, scale=3)
        made_at = DateTimeField()
        payload = JSONField()

    assert Widget.create_table() is True
    w = Widget({
        "name": "gizmo", "note": "a longer note", "qty": 7, "active": True,
        "ratio": 12.345, "made_at": _dt.datetime(2026, 1, 2, 3, 4, 5),
        "payload": {"k": "v", "n": [1, 2, 3]},
    })
    assert w.save() is not False
    got = Widget.find(w.id)
    assert got.name == "gizmo"
    assert got.note == "a longer note"
    assert got.qty == 7
    assert got.active is True
    assert abs(got.ratio - 12.345) < 1e-6
    assert got.made_at == _dt.datetime(2026, 1, 2, 3, 4, 5)
    assert got.payload == {"k": "v", "n": [1, 2, 3]}


def test_a_json_field_round_trips_to_a_native_object(sqlite_db):
    """A JSONField is serialized to a JSON string on write and parsed back to a
    native dict/list on read -- model.field is a real object, never a string."""
    class Doc(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        body = JSONField()

    Doc.create_table()
    d = Doc({"body": {"tags": ["a", "b"], "meta": {"n": 1}}})
    assert d.save() is not False
    got = Doc.find(d.id)
    assert isinstance(got.body, dict)
    assert got.body["tags"] == ["a", "b"]
    assert got.body["meta"]["n"] == 1


def test_a_callable_default_is_resolved_per_instance(sqlite_db):
    """A callable default is invoked PER INSTANCE (per-row values differ), not
    stored as the function object."""
    counter = {"n": 0}

    def next_seq():
        counter["n"] += 1
        return counter["n"]

    class Ticket(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        seq = IntegerField(default=next_seq)

    a, b, c = Ticket(), Ticket(), Ticket()
    assert (a.seq, b.seq, c.seq) == (1, 2, 3)


def test_a_callable_default_is_not_present_in_the_create_table_ddl(sqlite_db):
    """A callable default is resolved per row at insert time; it must NOT reach
    the CREATE TABLE DDL (where a function object stringifies to invalid SQL)."""
    class Session(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        token = StringField(default=lambda: uuid.uuid4().hex)

    assert Session.create_table() is True
    assert "DEFAULT" not in _ddl(sqlite_db, "session")


def test_a_non_serializable_json_value_makes_save_return_false_and_is_logged(sqlite_db, capsys):
    """Negative: a value a JSONField cannot serialize (a set) makes save()
    return False and log the cause -- never raise, never silently persist."""
    class Blob(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        data = JSONField()

    Blob.create_table()
    bad = Blob({"data": {"s": {1, 2, 3}}})   # a set is not JSON-serializable
    result = bad.save()
    assert result is False
    assert Blob.count() == 0
    # The cause is captured on last_error AND written via Log.error (Tina4's Log
    # sink, not stdlib logging -- so read the real output stream, not caplog).
    assert "serial" in (bad.last_error or "").lower()
    out = capsys.readouterr()
    logged = (out.out + out.err).lower()
    assert "refused" in logged and ("json" in logged or "serial" in logged)


def test_a_decimal_field_produces_a_decimal_precision_scale_column(sqlite_db):
    """A DecimalField emits a real DECIMAL(p, s) column in the generated DDL
    (parity with Ruby decimal_field / PHP $decimals / Node type:'decimal').
    NumericField/FloatField stay REAL (the documented float default)."""
    class Money(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        amount = DecimalField(precision=12, scale=4)

    assert Money.create_table() is True
    ddl = _ddl(sqlite_db, "money").upper()
    assert "DECIMAL(12,4)" in ddl.replace(" ", "")


# ── real-engine DDL (replaces the deleted mock) ───────────────────────────

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
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _engine_db(engine) -> Database:
    """Build a real Database for the named engine, or skip. A PG/MySQL/MSSQL
    skip trips the require-services gate (its reason names the engine +
    'unreachable'); Firebird is gated (skips green when its URL is unset)."""
    if engine == "postgres":
        if not _reachable(_PG["host"], _PG["port"]):
            pytest.skip(f"postgres unreachable at {_PG['host']}:{_PG['port']} (set TINA4_TEST_PG_*)")
        return Database(f"postgres://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])
    if engine == "mysql":
        if not _reachable(_MYSQL["host"], _MYSQL["port"]):
            pytest.skip(f"mysql unreachable at {_MYSQL['host']}:{_MYSQL['port']} (set TINA4_TEST_MYSQL_*)")
        return Database(f"mysql://{_MYSQL['host']}:{_MYSQL['port']}/{_MYSQL['db']}", _MYSQL["user"], _MYSQL["pwd"])
    if engine == "mssql":
        if not _reachable(_MSSQL["host"], _MSSQL["port"]):
            pytest.skip(f"mssql unreachable at {_MSSQL['host']}:{_MSSQL['port']} (set TINA4_TEST_MSSQL_*)")
        return Database(f"mssql://{_MSSQL['host']}:{_MSSQL['port']}/{_MSSQL['db']}", _MSSQL["user"], _MSSQL["pwd"])
    if engine == "firebird":
        if not _FIREBIRD_URL:
            pytest.skip("TINA4_TEST_FIREBIRD_URL not set (needs a live Firebird)")
        return Database(_FIREBIRD_URL)
    raise AssertionError(engine)


_ENGINES = ["postgres", "mysql", "mssql", "firebird"]


def _drop(db, engine, table):
    try:
        if engine == "mssql":
            db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")
        elif engine == "firebird":
            if db.table_exists(table):
                db.execute(f"DROP TABLE {table}")
                db.commit()
        else:
            db.execute(f"DROP TABLE IF EXISTS {table}")
    except Exception:
        pass


def _low(row):
    # A driver returns catalog column labels in its OWN case (MySQL upper-cases
    # them, PG/MSSQL keep them lower). Normalise to lower so the reads below are
    # driver-independent.
    return {str(k).lower(): v for k, v in row.items()}


def _describe(db, engine, table):
    """Read each column's REAL type from the engine's own catalog. Keys are
    lower-cased column names; values carry the native type + precision/scale."""
    out = {}
    if engine == "postgres":
        rows = db.fetch(
            "SELECT column_name, data_type, udt_name, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_name = ?", [table.lower()]
        ).records
        for raw in rows:
            r = _low(raw)
            out[str(r["column_name"]).lower()] = {
                "type": (r["udt_name"] or r["data_type"]).lower(),
                "precision": r["numeric_precision"], "scale": r["numeric_scale"],
            }
    elif engine == "mysql":
        rows = db.fetch(
            "SELECT column_name, data_type, column_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns WHERE table_name = ? AND table_schema = DATABASE()", [table]
        ).records
        for raw in rows:
            r = _low(raw)
            out[str(r["column_name"]).lower()] = {
                "type": r["column_type"].lower(), "data_type": r["data_type"].lower(),
                "precision": r["numeric_precision"], "scale": r["numeric_scale"],
            }
    elif engine == "mssql":
        rows = db.fetch(
            "SELECT column_name, data_type, numeric_precision, numeric_scale, character_maximum_length "
            "FROM information_schema.columns WHERE table_name = ?", [table]
        ).records
        for raw in rows:
            r = _low(raw)
            out[str(r["column_name"]).lower()] = {
                "type": r["data_type"].lower(), "precision": r["numeric_precision"],
                "scale": r["numeric_scale"], "maxlen": r["character_maximum_length"],
            }
    elif engine == "firebird":
        rows = db.fetch(
            "SELECT TRIM(rf.rdb$field_name) AS fname, f.rdb$field_type AS ftype, "
            "f.rdb$field_sub_type AS fsub, f.rdb$field_precision AS fprec, f.rdb$field_scale AS fscale "
            "FROM rdb$relation_fields rf JOIN rdb$fields f "
            "ON rf.rdb$field_source = f.rdb$field_name WHERE rf.rdb$relation_name = ?",
            [table.upper()]
        ).records
        for raw in rows:
            r = _low(raw)
            out[str(r["fname"]).strip().lower()] = {
                "ftype": r["ftype"], "fsub": r["fsub"],
                "precision": r["fprec"], "scale": r["fscale"],
            }
    return out


def _make_engine_table(db, engine):
    table = f"ormf_{engine}_{uuid.uuid4().hex[:8]}"

    class _M(ORM):
        table_name = table
        # A natural string PK: the round-trip supplies it, so this exercises the
        # bool / json / decimal / datetime COLUMNS on the real engine without
        # depending on per-engine auto-increment. (Firebird auto-increment needs
        # a generator/trigger that ORM.create_table sets up only in Node today --
        # a separate feature 16/17 gap, out of scope for the field model.)
        id = StringField(primary_key=True, max_length=32)
        flag = BooleanField()
        payload = JSONField()
        amount = DecimalField(precision=12, scale=4)
        made_at = DateTimeField()

    bind_database(db)
    _drop(db, engine, table)
    assert _M.create_table() is True, f"create_table failed on {engine}: {db.get_error()}"
    return _M, table


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_boolean_column_is_created_with_the_engine_native_boolean_type(engine):
    db = _engine_db(engine)
    try:
        _M, table = _make_engine_table(db, engine)
        cols = _describe(db, engine, table)
        flag = cols["flag"]
        if engine == "postgres":
            assert "bool" in flag["type"]
        elif engine == "mysql":
            assert flag["type"] == "tinyint(1)"        # BOOLEAN is TINYINT(1)
        elif engine == "mssql":
            assert flag["type"] == "bit"
        elif engine == "firebird":
            assert flag["ftype"] == 8                   # LONG / INTEGER
        _drop(db, engine, table)
    finally:
        db.close()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_json_column_is_created_with_the_engine_native_json_type(engine):
    db = _engine_db(engine)
    try:
        _M, table = _make_engine_table(db, engine)
        cols = _describe(db, engine, table)
        payload = cols["payload"]
        if engine == "postgres":
            assert payload["type"] == "jsonb"
        elif engine == "mysql":
            assert payload["type"] == "json"
        elif engine == "mssql":
            assert payload["type"] == "nvarchar" and payload["maxlen"] == -1   # NVARCHAR(MAX)
        elif engine == "firebird":
            assert payload["ftype"] == 261 and payload["fsub"] == 1            # BLOB SUB_TYPE TEXT
        _drop(db, engine, table)
    finally:
        db.close()


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_decimal_column_is_created_with_decimal_precision_and_scale_on_the_engine(engine):
    db = _engine_db(engine)
    try:
        _M, table = _make_engine_table(db, engine)
        cols = _describe(db, engine, table)
        amount = cols["amount"]
        if engine == "firebird":
            # Firebird stores DECIMAL(12,4) as a scaled INT64 (scale is negative).
            assert amount["precision"] == 12
            assert amount["scale"] == -4
        else:
            assert amount["precision"] == 12
            assert amount["scale"] == 4
            if engine in ("mysql", "mssql"):
                assert amount["type"].startswith("decimal") or amount.get("data_type", "").startswith("decimal")
            else:  # postgres
                assert amount["type"] in ("numeric", "decimal")
        _drop(db, engine, table)
    finally:
        db.close()


def _parse_json_col(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        return _json.loads(value)
    return value  # a native-JSON driver (PG jsonb) may hand back a parsed object


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_engine_ddl_types_round_trip_a_real_row(engine):
    db = _engine_db(engine)
    try:
        _M, table = _make_engine_table(db, engine)
        # Drive the write/read through the DB facade with an explicit key: this
        # proves the ENGINE COLUMNS accept and return a real row of each declared
        # type, independent of ORM auto-increment (Firebird has no generator wired
        # by create_table) and the ORM natural-key save path (which opens a second
        # transaction on MySQL) -- both separate feature 16/17 concerns. The ORM's
        # own JSON serialize/hydrate is proven by the SQLite cases above.
        db.insert(table, {
            "id": "row-1", "flag": True,
            "payload": _json.dumps({"k": "v", "n": [1, 2]}),
            "amount": 1234.5678, "made_at": "2026-03-04 05:06:07",
        })
        row = db.fetch_one(f"SELECT * FROM {table} WHERE id = ?", ["row-1"])
        assert row is not None, f"row not found on {engine}"
        r = {str(k).lower(): v for k, v in row.items()}
        assert bool(r["flag"]) is True
        assert _parse_json_col(r["payload"]) == {"k": "v", "n": [1, 2]}
        assert abs(float(r["amount"]) - 1234.5678) < 1e-3
        assert "2026-03-04" in str(r["made_at"])
        _drop(db, engine, table)
    finally:
        db.close()
