"""Database statement semantics - the runner for statement_semantics_contract.json (ADR-0065).

tests/fixtures/statement_semantics_contract.json is a byte-for-byte copy of
tina4-documentation/plan/v3/fixtures/statement_semantics_contract.json. The same
file drives the PHP, Ruby and Node runners, so a vector added there is a vector
all four frameworks must answer identically.

  * write detection and placeholder translation walk the fixture's vectors
    through the framework's own functions;
  * fetch of a write, execute rows and the query cache run against a REAL
    SQLite file, with durability read back on a SECOND, fresh connection;
  * OUTPUT and EXEC run against a REAL SQL Server, and the no-parameters rule
    against a REAL PostgreSQL. Under TINA4_REQUIRE_SERVICES an unreachable
    service fails the run (conftest turns the skip into a failure).

NO MOCKS.
"""
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import DatabaseAdapter, DatabaseResult
from tina4_python.database.sql_translator import SQLTranslator

CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "statement_semantics_contract.json").read_text())
PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
MSSQL_URL = os.environ.get("TINA4_TEST_MSSQL_URL")
JSONB = """'{"a":1}'::jsonb"""


def _reachable(url: str, default_port: int) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or default_port), timeout=1.0):
            return True
    except OSError:
        return False


# ── Vectors: the same data through every framework's own function ──────────


def test_write_detection_answers_every_fixture_vector():
    wrong = [
        f"{vector['sql']!r}: expected write={vector['write']}"
        for vector in CONTRACT["write_detection_vectors"]
        if DatabaseAdapter._is_write_statement(vector["sql"]) is not vector["write"]
    ]
    assert not wrong, "write detection disagrees with the shared fixture:\n  " + "\n  ".join(wrong)


def test_placeholder_translation_answers_every_fixture_vector():
    wrong = []
    for vector in CONTRACT["placeholder_vectors"]:
        translated = SQLTranslator.placeholder_style(vector["sql"], ":")
        if translated != vector["numbered"]:
            wrong.append(f"{vector['sql']!r} -> {translated!r}, expected {vector['numbered']!r}")
    assert not wrong, "placeholder translation disagrees with the shared fixture:\n  " + "\n  ".join(wrong)


# ── SQLite: fetch of a write, execute rows, the query cache ─────────────────


@pytest.fixture
def sqlite_url(tmp_path, monkeypatch):
    monkeypatch.delenv("TINA4_DB_CACHE", raising=False)
    monkeypatch.delenv("TINA4_AUTO_CACHING", raising=False)
    url = f"sqlite:///{tmp_path}/statement_semantics.db"
    setup = Database(url)
    setup.execute("CREATE TABLE note (id INTEGER PRIMARY KEY AUTOINCREMENT, text VARCHAR(40))")
    setup.commit()
    setup.close()
    return url


def _rows_seen_by_a_fresh_connection(url: str) -> int:
    fresh = Database(url)
    try:
        return int(fresh.fetch_one("SELECT count(*) AS n FROM note", no_cache=True)["n"])
    finally:
        fresh.close()


def test_fetch_of_an_insert_returning_runs_once_and_commits(sqlite_url):
    writer = Database(sqlite_url)
    try:
        result = writer.fetch("INSERT INTO note (text) VALUES (?) RETURNING id", ["via fetch"])
        assert [int(row["id"]) for row in result.records] == [1]
    finally:
        writer.close()
    assert _rows_seen_by_a_fresh_connection(sqlite_url) == 1, "fetch() of a write did not land exactly once"


def test_fetch_one_of_an_insert_returning_runs_once_and_commits(sqlite_url):
    writer = Database(sqlite_url)
    try:
        row = writer.fetch_one("INSERT INTO note (text) VALUES (?) RETURNING id", ["via fetch_one"])
        assert row and int(row["id"]) == 1
    finally:
        writer.close()
    assert _rows_seen_by_a_fresh_connection(sqlite_url) == 1, "fetch_one() of a write did not land exactly once"


def test_a_fetched_write_is_never_cached_and_flushes_the_cache(sqlite_url, monkeypatch):
    monkeypatch.setenv("TINA4_DB_CACHE", "true")
    database = Database(sqlite_url)
    try:
        assert database._cache_enabled, "the query cache did not switch on from TINA4_DB_CACHE"
        assert int(database.fetch_one("SELECT count(*) AS n FROM note")["n"]) == 0  # cached read
        first = database.fetch_one("INSERT INTO note (text) VALUES (?) RETURNING id", ["same"])
        second = database.fetch_one("INSERT INTO note (text) VALUES (?) RETURNING id", ["same"])
        assert int(first["id"]) != int(second["id"]), "the second fetched write was served from the cache"
        assert int(database.fetch_one("SELECT count(*) AS n FROM note")["n"]) == 2, (
            "the cached count survived a fetched write - the write did not flush the cache"
        )
    finally:
        database.close()
    assert _rows_seen_by_a_fresh_connection(sqlite_url) == 2


def test_execute_returns_rows_for_select_with_select_and_returning(sqlite_url):
    database = Database(sqlite_url)
    try:
        database.execute("INSERT INTO note (text) VALUES (?)", ["one"])
        for sql, expected in (
            ("SELECT id, text FROM note WHERE id = ?", [{"id": 1, "text": "one"}]),
            ("WITH later AS (SELECT id FROM note WHERE id >= ?) SELECT id FROM later", [{"id": 1}]),
            ("INSERT INTO note (text) VALUES (?) RETURNING id", [{"id": 2}]),
        ):
            params = ["two"] if sql.startswith("INSERT") else [1]
            result = database.execute(sql, params)
            assert isinstance(result, DatabaseResult), f"execute({sql!r}) returned {result!r}, not the fetch() type"
            assert result.records == expected, f"execute({sql!r}) rows were {result.records!r}"
    finally:
        database.close()
    assert _rows_seen_by_a_fresh_connection(sqlite_url) == 2


def test_execute_of_a_plain_write_keeps_its_return_value(sqlite_url):
    database = Database(sqlite_url)
    try:
        assert database.execute("INSERT INTO note (text) VALUES (?)", ["plain"]) is True
    finally:
        database.close()
    assert _rows_seen_by_a_fresh_connection(sqlite_url) == 1


# ── SQL Server: OUTPUT and EXEC ─────────────────────────────────────────────


def test_execute_returns_rows_for_output_and_exec_on_sql_server():
    if not MSSQL_URL:
        pytest.skip("MSSQL not configured for the statement-semantics contract (TINA4_TEST_MSSQL_URL not set)")
    if not _reachable(MSSQL_URL, 1433):
        pytest.skip("MSSQL not reachable - skip integration test")
    database = Database(MSSQL_URL)
    try:
        database.execute("IF OBJECT_ID('contract_py_note', 'U') IS NOT NULL DROP TABLE contract_py_note")
        database.execute("CREATE TABLE contract_py_note (id INT IDENTITY(1,1) PRIMARY KEY, text VARCHAR(40))")
        database.execute("CREATE OR ALTER PROCEDURE contract_py_notes AS SELECT id, text FROM contract_py_note ORDER BY id")
        database.commit()

        inserted = database.execute("INSERT INTO contract_py_note (text) OUTPUT inserted.id VALUES (?)", ["out"])
        assert isinstance(inserted, DatabaseResult), f"execute(INSERT ... OUTPUT) returned {inserted!r}"
        assert [int(row["id"]) for row in inserted.records] == [1]

        listed = database.execute("EXEC contract_py_notes")
        assert isinstance(listed, DatabaseResult), f"execute(EXEC) returned {listed!r}"
        assert [(int(row["id"]), row["text"]) for row in listed.records] == [(1, "out")]
    finally:
        database.execute("DROP PROCEDURE IF EXISTS contract_py_notes")
        database.execute("IF OBJECT_ID('contract_py_note', 'U') IS NOT NULL DROP TABLE contract_py_note")
        database.commit()
        database.close()


# ── PostgreSQL: no parameters, no rewrite ───────────────────────────────────


@pytest.fixture
def postgres():
    if not _reachable(PG_URL, 5432):
        pytest.skip("PostgreSQL not reachable - skip integration test")
    database = Database(PG_URL)
    yield database
    database.close()


def test_sql_with_no_parameters_is_sent_exactly_as_written_on_postgresql(postgres):
    row = postgres.fetch_one(
        f"SELECT {JSONB} ? 'a' AS has_key, {JSONB} ?| array['a','z'] AS any_key, "
        f"{JSONB} ?& array['a'] AS all_keys, 'a%' AS percent",
        no_cache=True,
    )
    assert row == {"has_key": True, "any_key": True, "all_keys": True, "percent": "a%"}


def test_jsonb_exists_functions_and_literal_percent_work_with_parameters_on_postgresql(postgres):
    row = postgres.fetch_one(f"SELECT jsonb_exists({JSONB}, ?) AS has_key, 'a%' || ? AS joined", ["a", "b"], no_cache=True)
    assert row == {"has_key": True, "joined": "a%b"}
