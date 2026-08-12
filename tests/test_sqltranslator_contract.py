"""SQL translator literal-safe + BIGINT-autoincrement contract - feature 7
(sqltranslator_contract.json).

Locks out a DATA-CORRUPTION defect against REAL databases (no mocks): the dialect
rewrites (|| -> CONCAT, ILIKE -> LOWER LIKE, TRUE/FALSE -> 1/0) used to MANGLE
STRING LITERALS - a value of 'a||b', a label 'TRUE', or a LIKE pattern that
mentions ILIKE was rewritten as if it were SQL. The concat rewrite additionally
split the WHOLE statement on ||, so ``SELECT a || b FROM t`` became
``CONCAT(SELECT a, b FROM t)`` (invalid SQL). The rewrites are now literal-safe
(mask literals/comments -> rewrite -> restore) and concat only rewrites the
operand chain.

SQLTRANS-DEC-03: a ``BIGINT ... AUTOINCREMENT`` DDL now yields a real 64-bit
auto-increment column per dialect (PostgreSQL BIGSERIAL, MySQL BIGINT
AUTO_INCREMENT), instead of a plain BIGINT with the keyword stripped and no
sequence.

Real services on the .99 lab: PostgreSQL :55432 (tina4/tina4), MySQL :3306
(tina4/tina4 -> tina4_test). Under TINA4_REQUIRE_SERVICES a skip here is a hard
failure - these MUST run. Every case RUNS the translated statement on the real
engine and checks the rows/DDL, never a string comparison alone.

Mutation-proof (revert the literal-safe rewrite to the old naive one):
  * "pipes inside a string literal are preserved" goes RED - the || inside
    'a||b' is wrongly turned into CONCAT and the query errors / returns nothing.
  * "boolean token inside a string literal is preserved" goes RED - 'TRUE'
    becomes '1' and the row is not found.
  * "ilike pattern with multiple words survives and runs" goes RED - the greedy
    \\S+ truncates '%two words%' to '%two and the query errors.
Revert the PostgreSQL BIGINT branch and "bigint autoincrement creates a real
bigint column" goes RED - the insert with no id violates the NOT NULL key.
"""
import os
import socket
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.database.sql_translator import SQLTranslator

# ── real-service connection coordinates (canonical TINA4_TEST_* convention) ──
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


def _reachable(host, port) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


_MYSQL_UP = _reachable(_MYSQL["host"], _MYSQL["port"])
_PG_UP = _reachable(_PG["host"], _PG["port"])
needs_mysql = pytest.mark.skipif(not _MYSQL_UP, reason="MySQL not reachable for the SQL-translator contract")
needs_pg = pytest.mark.skipif(not _PG_UP, reason="PostgreSQL not reachable for the SQL-translator contract")


def _mysql() -> Database:
    return Database(f"mysql://{_MYSQL['host']}:{_MYSQL['port']}/{_MYSQL['db']}", _MYSQL["user"], _MYSQL["pwd"])


def _pg() -> Database:
    return Database(f"postgresql://{_PG['host']}:{_PG['port']}/{_PG['db']}", _PG["user"], _PG["pwd"])


def _table(prefix: str) -> str:
    return f"tina4_sqltrans_{prefix}_{uuid.uuid4().hex[:10]}"


# ── Invariant 1: literal-safe concat / bool / ilike, RUN on a real engine ──

@needs_mysql
def test_concat_pipes_translate_outside_literals_and_run():
    """`first_name || ' ' || last_name` translates to CONCAT and returns the
    joined value through the real MySQL adapter path (not a whole-statement
    split)."""
    db = _mysql()
    t = _table("concat")
    db.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTO_INCREMENT, first_name VARCHAR(50), last_name VARCHAR(50))")
    try:
        db.execute(f"INSERT INTO {t} (first_name, last_name) VALUES (?, ?)", ["Jane", "Doe"])
        row = db.fetch_one(f"SELECT (first_name || ' ' || last_name) AS fullname FROM {t}")
        assert row is not None and row["fullname"] == "Jane Doe"
    finally:
        db.execute(f"DROP TABLE {t}")


@needs_mysql
def test_pipes_inside_a_string_literal_are_preserved():
    """A `||` INSIDE a quoted value is data: the row keyed on 'a||b' is found,
    proving the literal was not mangled into CONCAT."""
    db = _mysql()
    t = _table("litpipe")
    db.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTO_INCREMENT, data VARCHAR(50))")
    try:
        db.execute(f"INSERT INTO {t} (data) VALUES (?)", ["a||b"])
        db.execute(f"INSERT INTO {t} (data) VALUES (?)", ["plain"])
        rows = db.fetch(f"SELECT id, data FROM {t} WHERE data = 'a||b'")
        assert len(rows.records) == 1
        assert rows.records[0]["data"] == "a||b"
    finally:
        db.execute(f"DROP TABLE {t}")


@needs_mysql
def test_ilike_pattern_with_multiple_words_survives_and_runs():
    """A multi-word ILIKE pattern is captured whole and the case-insensitive
    match returns the row on a real engine (the old greedy \\S+ truncated it)."""
    db = _mysql()
    t = _table("ilike")
    db.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTO_INCREMENT, bio VARCHAR(100))")
    try:
        db.execute(f"INSERT INTO {t} (bio) VALUES (?)", ["Loves TWO WORDS and coffee"])
        db.execute(f"INSERT INTO {t} (bio) VALUES (?)", ["nothing here"])
        rows = db.fetch(f"SELECT id, bio FROM {t} WHERE bio ILIKE '%two words%'")
        assert len(rows.records) == 1
        assert "TWO WORDS" in rows.records[0]["bio"]
    finally:
        db.execute(f"DROP TABLE {t}")


@needs_mysql
def test_boolean_token_inside_a_string_literal_is_preserved():
    """boolean_to_int rewrites the bare TRUE to 1 but leaves the literal 'TRUE'
    untouched; the translated statement RUNS on the real engine and finds the
    row (flag=1, label='TRUE')."""
    db = _mysql()
    t = _table("boollit")
    db.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTO_INCREMENT, flag INTEGER, label VARCHAR(20))")
    try:
        db.execute(f"INSERT INTO {t} (flag, label) VALUES (?, ?)", [1, "TRUE"])
        db.execute(f"INSERT INTO {t} (flag, label) VALUES (?, ?)", [0, "other"])
        canonical = f"SELECT id, label FROM {t} WHERE flag = TRUE AND label = 'TRUE'"
        translated = SQLTranslator.boolean_to_int(canonical)
        assert "flag = 1" in translated and "label = 'TRUE'" in translated
        rows = db.fetch(translated)
        assert len(rows.records) == 1
        assert rows.records[0]["label"] == "TRUE"
    finally:
        db.execute(f"DROP TABLE {t}")


# ── Invariant 2: BIGINT autoincrement creates a real 64-bit column ──

def _bigint_case(db: Database, engine: str):
    t = _table("bigint")
    ddl = f"CREATE TABLE {t} (id BIGINT PRIMARY KEY AUTOINCREMENT, name VARCHAR(50))"
    translated = SQLTranslator.auto_increment_syntax(ddl, engine)
    db.execute(translated)
    try:
        # An insert with NO id must auto-generate one: proves a real sequence /
        # identity exists (a plain BIGINT PK with the keyword stripped would fail
        # the NOT NULL key here).
        db.execute(f"INSERT INTO {t} (name) VALUES (?)", ["alpha"])
        row = db.fetch_one(f"SELECT id FROM {t} WHERE name = ?", ["alpha"])
        assert row is not None and int(row["id"]) >= 1
        # The column is really 64-bit, not a 32-bit SERIAL/INT. (The result key
        # casing differs by driver - PostgreSQL lowercases, MySQL keeps DATA_TYPE
        # - so read the single value rather than a fixed key name.)
        dt = db.fetch_one(
            "SELECT data_type AS dtype FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = 'id'",
            [t],
        )
        assert dt is not None
        assert str(next(iter(dt.values()))).lower() == "bigint"
    finally:
        db.execute(f"DROP TABLE {t}")


@needs_pg
def test_bigint_autoincrement_creates_a_real_bigint_column_postgres():
    """PostgreSQL: BIGINT PRIMARY KEY AUTOINCREMENT -> BIGSERIAL, a real 64-bit
    auto-increment column."""
    _bigint_case(_pg(), "postgresql")


@needs_mysql
def test_bigint_autoincrement_creates_a_real_bigint_column_mysql():
    """MySQL: BIGINT PRIMARY KEY AUTOINCREMENT -> BIGINT ... AUTO_INCREMENT,
    a real 64-bit auto-increment column (parity lock)."""
    _bigint_case(_mysql(), "mysql")
