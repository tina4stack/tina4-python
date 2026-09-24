"""ADR-0069: identifiers that reach SQL come from the model, never the caller.

Two surfaces in Python:

B. ``ORM.find(dict)``. Each key must resolve to a DECLARED field, either by the
   field name or by that field's column (``field_mapping`` or ``Field(column=)``).
   The resolved column is emitted through the bound adapter's
   ``quote_identifier``, the same way the ORM's own INSERT/UPDATE emit columns.
   A key that does not resolve raises ``ValueError`` before any SQL runs:
       "Unknown filter field 'KEY' for model <ModelName>"
   ``where()``, ``load()``, ``select()``, QueryBuilder and the raw ``order_by``
   string stay unchanged - they are documented raw-SQL APIs.

C. DocStore SQLite fallback. Every field path that becomes a JSON path literal
   (filter keys at any depth, operator fields, sort keys) is split on '.', and
   every segment must match ``[A-Za-z0-9_-]+``. Otherwise ``ValueError``:
       "DocStore: invalid field path 'KEY' - each dot-separated segment must
        match [A-Za-z0-9_-]+"
   Every key shape the fallback ACCEPTS returns the same documents as a real
   MongoDB for the same data and query (ADR-0025).

The inputs are neutral: an undeclared column that really exists in the table,
and keys that contain a space, a quote or a bracket.

NO MOCKS. Real SQLite, PostgreSQL, MySQL, MSSQL, Firebird and MongoDB. Under
TINA4_REQUIRE_SERVICES=1 an engine whose URL is set but unreachable FAILS
(tests/conftest.py gate), and an unreachable MongoDB always fails.
"""
from __future__ import annotations

import os
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.docstore import SqliteDatabase
from tina4_python.orm import ORM, IntegerField, StringField


def _unavailable(need: str, message: str):
    """Skip tagged [needs:<need>]. Under TINA4_REQUIRE_SERVICES the conftest gate
    fails it unless the need is excusable: an optional engine whose coordinate
    env var is unset. Mongo is always provisioned, so it is never excused."""
    pytest.skip(f"[needs:{need}] {message}")


# ── B. ORM find(dict) on every engine ────────────────────────────────────────

# Every variable name is written out in full so tests/test_env_contract.py can
# check it against tests/fixtures/test_env_contract.json.
ENGINE_ENV = {
    "postgres": ("TINA4_TEST_PG_URL", "TINA4_TEST_PG_USERNAME", "TINA4_TEST_PG_PASSWORD"),
    "mysql": ("TINA4_TEST_MYSQL_URL", "TINA4_TEST_MYSQL_USERNAME", "TINA4_TEST_MYSQL_PASSWORD"),
    "mssql": ("TINA4_TEST_MSSQL_URL", "TINA4_TEST_MSSQL_USERNAME", "TINA4_TEST_MSSQL_PASSWORD"),
    "firebird": (
        "TINA4_TEST_FIREBIRD_URL",
        "TINA4_TEST_FIREBIRD_USERNAME",
        "TINA4_TEST_FIREBIRD_PASSWORD",
    ),
}
ENGINES = ["sqlite", *ENGINE_ENV]


class IdentifierProbe(ORM):
    """Four declared fields. Two reach the table under a different column name:
    ``display_name`` through ``field_mapping`` and ``remark`` through
    ``Field(column=)``. The table ALSO has ``hidden_col``, which the model does
    not declare - the undeclared-but-real column."""

    table_name = "identifier_probe"
    id = IntegerField(primary_key=True)
    name = StringField()
    display_name = StringField()
    remark = StringField(column="note_col")
    field_mapping = {"display_name": "label_text"}


ROWS = [
    {"id": 1, "name": "alpha", "label_text": "Alpha", "note_col": "first", "hidden_col": "h1"},
    {"id": 2, "name": "beta", "label_text": "Beta", "note_col": "second", "hidden_col": "h2"},
    {"id": 3, "name": "alpha", "label_text": "Gamma", "note_col": "third", "hidden_col": "h3"},
]


@pytest.fixture(scope="module", params=ENGINES)
def probe_db(request, tmp_path_factory):
    """The probe table on one real engine, dropped afterwards."""
    engine = request.param
    if engine == "sqlite":
        database = Database(f"sqlite:///{tmp_path_factory.mktemp('allowlist')}/probe.db")
    else:
        url_var, username_var, password_var = ENGINE_ENV[engine]
        url = (os.environ.get(url_var) or "").strip()
        if not url:
            _unavailable(engine, f"{engine} not reachable: {url_var} is not set")
        try:
            database = Database(
                url,
                username=os.environ.get(username_var) or "",
                password=os.environ.get(password_var) or "",
            )
        except Exception as error:  # noqa: BLE001 - the message is the finding
            _unavailable(engine, f"{engine} not reachable at {url_var}: {type(error).__name__}: {error}")

    table = f"idprobe_{uuid.uuid4().hex[:8]}"
    database.execute(
        f"CREATE TABLE {table} ("
        " id INTEGER NOT NULL PRIMARY KEY,"
        " name VARCHAR(50),"
        " label_text VARCHAR(50),"
        " note_col VARCHAR(50),"
        " hidden_col VARCHAR(50))"
    )
    database.commit()
    for row in ROWS:
        database.insert(table, row)
    database.commit()

    IdentifierProbe.table_name = table
    IdentifierProbe._db = database
    yield engine, database
    IdentifierProbe._db = None
    try:
        database.execute(f"DROP TABLE {table}")
        database.commit()
    except Exception:  # noqa: BLE001 - teardown must never mask a failure
        pass
    database.close()


def _ids(result) -> list[int]:
    return sorted(int(record.id) for record in result)


UNKNOWN_KEYS = [
    "hidden_col",   # a real column the model does not declare
    "name x",       # contains a space
    "name'",        # contains a quote
    "name]",        # contains a bracket
    "Name",         # a declared field's name in the wrong case is not the field
]


def test_orm_find_rejects_undeclared_filter_key(probe_db):
    engine, _ = probe_db

    # NEGATIVE: every unknown key raises before any SQL, naming key and model.
    for key in UNKNOWN_KEYS:
        with pytest.raises(ValueError) as raised:
            IdentifierProbe.find({key: "h1"})
        assert str(raised.value) == f"Unknown filter field '{key}' for model IdentifierProbe", (
            f"[{engine}] {key!r}: {raised.value}"
        )
    # An unknown key next to a valid one still rejects the whole filter.
    with pytest.raises(ValueError, match="Unknown filter field 'hidden_col'"):
        IdentifierProbe.find({"name": "alpha", "hidden_col": "h1"})

    # POSITIVE: declared field by name.
    assert _ids(IdentifierProbe.find({"name": "alpha"})) == [1, 3], engine
    assert _ids(IdentifierProbe.find({"id": 2})) == [2], engine
    # field_mapping: by the field name AND by its column.
    assert _ids(IdentifierProbe.find({"display_name": "Beta"})) == [2], engine
    assert _ids(IdentifierProbe.find({"label_text": "Beta"})) == [2], engine
    # Field(column=): by the field name AND by its column.
    assert _ids(IdentifierProbe.find({"remark": "third"})) == [3], engine
    assert _ids(IdentifierProbe.find({"note_col": "third"})) == [3], engine
    # Several keys are AND-ed, and the hydrated field carries the mapped value.
    matched = IdentifierProbe.find({"name": "alpha", "display_name": "Gamma"})
    assert _ids(matched) == [3], engine
    assert matched[0].display_name == "Gamma", engine
    # The documented raw order_by string is unchanged.
    ordered = IdentifierProbe.find({"name": "alpha"}, order_by="id DESC")
    assert [int(record.id) for record in ordered] == [3, 1], engine


# ── G2. ORM save() writes only declared fields ───────────────────────────────

def _row(database, table, row_id) -> dict:
    row = database.fetch_one(f"SELECT * FROM {table} WHERE id = ?", [row_id])
    return {str(key).lower(): value for key, value in (row or {}).items()}


def test_orm_save_writes_only_declared_fields(probe_db):
    engine, database = probe_db
    table = IdentifierProbe.table_name
    try:
        # INSERT: an undeclared key in the constructor data and an undeclared
        # attribute set afterwards are both left out of the column list.
        created = IdentifierProbe({"id": 10, "name": "g2", "hidden_col": "from-data"})
        created.hidden_col = "from-attribute"
        assert created.save() is not False, (engine, created.get_error())
        inserted = _row(database, table, 10)
        assert inserted["name"] == "g2", engine
        assert inserted["hidden_col"] is None, (engine, inserted)

        # UPDATE: a loaded row with an undeclared attribute changed keeps the
        # stored value of that column; the declared field is written.
        database.insert(table, {"id": 11, "name": "before", "hidden_col": "kept"})
        database.commit()
        loaded = IdentifierProbe.find_by_id(11)
        loaded.name = "after"
        loaded.hidden_col = "overwritten"
        assert loaded.save() is not False, (engine, loaded.get_error())
        updated = _row(database, table, 11)
        assert updated["name"] == "after", engine
        assert updated["hidden_col"] == "kept", (engine, updated)
    finally:
        database.delete(table, [{"id": 10}, {"id": 11}])
        database.commit()


# ── G3. Database write helpers accept only identifier keys ───────────────────

NON_IDENTIFIER_KEYS = ["na me", "na'me", 'na"me', "na]me", "na(me)", "na-me", "1name", ""]


def test_db_write_helpers_reject_non_identifier_keys(probe_db):
    engine, database = probe_db
    table = f"wkeys_{uuid.uuid4().hex[:8]}"
    database.execute(
        f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(50), cost$ INTEGER)"
    )
    database.commit()

    def snapshot():
        rows = database.fetch(f"SELECT id, name, cost$ FROM {table} ORDER BY id").records
        return [tuple(value for _, value in sorted(
            ((str(key).lower(), value) for key, value in row.items()))) for row in rows]

    try:
        # POSITIVE: plain identifiers (a '$' included) still write, in every form.
        database.insert(table, {"id": 1, "name": "one", "cost$": 5})
        database.insert(table, [
            {"id": 2, "name": "two", "cost$": 6},
            {"id": 3, "name": "three", "cost$": 7},
        ])
        database.update(table, {"name": "uno"}, {"id": 1})
        database.update(table, {"id": 2, "name": "dos"})
        database.delete(table, {"id": 3})
        database.delete(table, [{"id": 99}])
        database.commit()
        before = snapshot()
        # sorted by column name: cost$, id, name
        assert before == [(5, 1, "uno"), (6, 2, "dos")], (engine, before)

        # NEGATIVE: every helper, as a data key and as a filter-map key.
        for key in NON_IDENTIFIER_KEYS:
            attempts = {
                "insert": lambda: database.insert(table, {"id": 50, key: 1}),
                "insert-batch": lambda: database.insert(table, [{"id": 51, key: 1}]),
                "update-data": lambda: database.update(table, {key: 1}, {"id": 1}),
                "update-filter": lambda: database.update(table, {"name": "x"}, {key: 1}),
                "delete": lambda: database.delete(table, {key: 1}),
                "delete-batch": lambda: database.delete(table, [{key: 1}]),
            }
            for helper, attempt in attempts.items():
                with pytest.raises(ValueError) as raised:
                    attempt()
                assert str(raised.value) == f"Invalid column name '{key}'", (
                    engine, helper, key, str(raised.value),
                )
        assert snapshot() == before, engine
    finally:
        try:
            database.execute(f"DROP TABLE {table}")
            database.commit()
        except Exception:  # noqa: BLE001 - teardown must never mask a failure
            pass


# ── C. DocStore field paths ──────────────────────────────────────────────────

INVALID_PATH_MESSAGE = (
    "DocStore: invalid field path '{key}' - each dot-separated segment must match [A-Za-z0-9_-]+"
)

UNSAFE_PATHS = ["a b", "a'b", "a]b", "a..b", ".a", "a.", ""]

SAFE_DOCUMENTS = [
    {"_id": "d1", "a_b": 1, "a-b": "x", "A1": True, "nested": {"key": "n1"}},
    {"_id": "d2", "a_b": 2, "a-b": "y", "A1": False, "nested": {"key": "n2"}},
    {"_id": "d3", "a_b": 3, "a-b": "x", "A1": True, "nested": {"key": "n3"}},
]

SAFE_QUERIES = [
    ({"a_b": 2}, None),
    ({"a-b": "x"}, None),
    ({"A1": True}, None),
    ({"nested.key": "n3"}, None),
    ({"_id": "d1"}, None),
    ({"a_b": {"$gte": 2}}, None),
    ({"$or": [{"a-b": "y"}, {"nested.key": "n1"}]}, None),
    ({}, [("a_b", -1)]),
    ({}, [("a-b", 1), ("A1", -1), ("_id", 1)]),
    ({}, [("nested.key", -1)]),
]


@pytest.fixture
def fallback(tmp_path):
    """A real SQLite-backed DocStore with a statement log on its connection."""
    database = SqliteDatabase(str(tmp_path / "docstore.db"))
    collection = database.get_collection("paths")
    collection.insert_many([dict(document) for document in SAFE_DOCUMENTS])
    statements: list[str] = []
    database._conn.set_trace_callback(statements.append)
    yield collection, statements
    database._conn.set_trace_callback(None)
    database.close()


def _run(collection, query, sort):
    cursor = collection.find(query)
    if sort:
        cursor = cursor.sort(sort)
    return [document["_id"] for document in cursor]


def test_docstore_rejects_unsafe_field_path(fallback):
    collection, statements = fallback
    attempts = []
    for key in UNSAFE_PATHS:
        attempts += [
            (key, lambda key=key: collection.find({key: 1}).to_list()),
            (key, lambda key=key: collection.find({"$or": [{"a_b": 1}, {key: 1}]}).to_list()),
            (key, lambda key=key: collection.find({"$and": [{"$or": [{key: 1}]}]}).to_list()),
            (key, lambda key=key: collection.find({key: {"$gt": 1}}).to_list()),
            (key, lambda key=key: collection.find({key: {"$exists": True}}).to_list()),
            (key, lambda key=key: collection.find({key: {"$in": [1, 2]}}).to_list()),
            (key, lambda key=key: collection.find({}).sort(key, -1).to_list()),
            (key, lambda key=key: collection.find({}).sort([("a_b", 1), (key, 1)]).to_list()),
            (key, lambda key=key: collection.count_documents({key: 1})),
            (key, lambda key=key: collection.delete_many({key: 1})),
            (key, lambda key=key: collection.update_many({key: 1}, {"$set": {"a_b": 9}})),
        ]
    for key, attempt in attempts:
        statements.clear()
        with pytest.raises(ValueError) as raised:
            attempt()
        assert str(raised.value) == INVALID_PATH_MESSAGE.format(key=key), raised.value
        assert statements == [], f"SQL ran before the path {key!r} was rejected: {statements}"

    # Nothing was changed by any of the rejected calls.
    assert collection.count_documents({}) == 3
    assert collection.count_documents({"a_b": 9}) == 0


def test_docstore_accepts_safe_field_paths(fallback):
    collection, _ = fallback
    expected = [
        ["d2"],
        ["d1", "d3"],
        ["d1", "d3"],
        ["d3"],
        ["d1"],
        ["d2", "d3"],
        ["d1", "d2"],
        ["d3", "d2", "d1"],
        ["d1", "d3", "d2"],
        ["d3", "d2", "d1"],
    ]
    for (query, sort), want in zip(SAFE_QUERIES, expected):
        got = _run(collection, query, sort)
        if sort is None:
            got = sorted(got)
        assert got == want, f"{query} sort={sort}: {got}"
    # A path with a dash is still quoted correctly inside the JSON path.
    assert collection.count_documents({"a-b": {"$in": ["x", "y"]}}) == 3


MONGO_HOST = os.environ.get("TINA4_TEST_MONGO_HOST", "localhost")
MONGO_PORT = os.environ.get("TINA4_TEST_MONGO_PORT", "27017")
MONGO_URI = os.environ.get("TINA4_TEST_MONGO_URI") or f"mongodb://{MONGO_HOST}:{MONGO_PORT}"


@pytest.fixture
def real_mongo():
    """A real MongoDB collection in a unique database, dropped afterwards."""
    try:
        import pymongo
    except ImportError:
        _unavailable("mongo", "pymongo not installed (mongo client for the real-MongoDB case)")
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except Exception as error:  # noqa: BLE001 - the message is the finding
        client.close()
        _unavailable("mongo", f"no reachable MongoDB at {MONGO_URI}: {type(error).__name__}")
    database_name = f"tina4_sqli_py_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    collection = client[database_name]["paths"]
    collection.insert_many([dict(document) for document in SAFE_DOCUMENTS])
    yield collection
    client.drop_database(database_name)
    client.close()


def test_docstore_safe_paths_match_on_real_mongo(fallback, real_mongo):
    collection, _ = fallback
    for query, sort in SAFE_QUERIES:
        on_fallback = _run(collection, query, sort)
        on_mongo = _run(real_mongo, query, sort)
        if sort is None:
            on_fallback, on_mongo = sorted(on_fallback), sorted(on_mongo)
        assert on_fallback == on_mongo, f"{query} sort={sort}: fallback {on_fallback} != mongo {on_mongo}"
        assert on_fallback, f"{query} matched nothing on either provider - not a real comparison"

    # A key the fallback rejects raises there rather than silently matching
    # nothing (ADR-0025 corollary 4).
    with pytest.raises(ValueError):
        collection.find({"a b": 1}).to_list()
