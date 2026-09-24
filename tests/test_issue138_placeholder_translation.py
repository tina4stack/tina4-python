# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue #138 - ``?`` translation skips literals, identifiers and comments, and ``%`` survives.

The ``?`` -> ``%s`` rewrite for PostgreSQL, MySQL and SQL Server was a plain text
replace, so a ``?`` inside a string literal, a quoted identifier or a comment
became a placeholder; and psycopg reads EVERY ``%`` as a placeholder whenever
parameters are passed - fetch() always passes LIMIT/OFFSET - so ``LIKE 'a%'``
crashed with "list index out of range". #40 fixed only the no-parameters path.

The contract, the same in all four frameworks: only a ``?`` in SQL code is a
placeholder (never in '...', E'...', $$...$$, "...", `...`, -- or /* */), and a
literal ``%`` works with or without parameters.

NO MOCKS: every case runs on a real engine. The scanner cases at the bottom are
pure functions over their input.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

from tina4_python.database.sql_translator import SQLTranslator

ENGINES = {
    "postgres": ("TINA4_TEST_PG_URL", 5432, "PostgreSQL"),
    "mysql": ("TINA4_TEST_MYSQL_URL", 3306, "MySQL"),
    "mssql": ("TINA4_TEST_MSSQL_URL", 1433, "MSSQL"),
}
ONE_ROW = "FROM (SELECT 1 AS one) AS t"


def _reachable(url, port) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or port), timeout=1.0):
            return True
    except OSError:
        return False


def _open(engine):
    from tina4_python.database import Database
    variable, port, service = ENGINES[engine]
    url = os.environ.get(variable)
    if not url:
        pytest.skip(f"{service} not configured for the #138 test ({variable} not set)")
    if not _reachable(url, port):
        pytest.skip(f"{service} not reachable - skip integration test")
    database = Database(url)
    database.engine_name = engine
    return database


@pytest.fixture(params=list(ENGINES))
def db(request):
    database = _open(request.param)
    yield database
    database.close()


@pytest.fixture
def pg():
    database = _open("postgres")
    yield database
    database.close()


# ── the issue's five cases ─────────────────────────────────────────

def test_fetch_literal_percent_without_params(db):
    assert db.fetch(f"SELECT 'a%' AS v {ONE_ROW}", [], limit=5, no_cache=True).records == [{"v": "a%"}]


def test_fetch_like_literal_percent_with_a_param(db):
    rows = db.fetch(f"SELECT 'abc' AS v {ONE_ROW} WHERE 'abc' LIKE 'a%' AND one = ?", [1],
                    limit=5, no_cache=True).records
    assert rows == [{"v": "abc"}], f"{db.engine_name}: {rows!r}"


def test_fetch_one_literal_question_mark_in_a_string(db):
    assert db.fetch_one("SELECT 'why?' AS v, ? AS n", [1], no_cache=True) == {"v": "why?", "n": 1}


def test_execute_literal_percent_with_a_param(db):
    db.execute(f"SELECT 'a%' AS v {ONE_ROW} WHERE one = ?", [1])  # must not raise


def test_pattern_passed_as_a_parameter(db):
    rows = db.fetch(f"SELECT 'abc' AS v {ONE_ROW} WHERE 'abc' LIKE ?", ["a%"], limit=5, no_cache=True).records
    assert rows == [{"v": "abc"}]


# ── comments and quoted identifiers ────────────────────────────────

def test_question_mark_in_a_line_comment_is_not_a_placeholder(db):
    assert db.fetch_one("SELECT ? AS n -- is this one a placeholder?\n", [7], no_cache=True) == {"n": 7}


def test_question_mark_in_a_block_comment_is_not_a_placeholder(db):
    rows = db.fetch("SELECT /* really? 100% */ ? AS n " + ONE_ROW, [8], limit=5, no_cache=True).records
    assert rows == [{"n": 8}]


def test_question_mark_in_a_quoted_identifier_is_not_a_placeholder(db):
    quote = ("`", "`") if db.engine_name == "mysql" else ('"', '"')
    alias = f"{quote[0]}why?{quote[1]}"
    row = db.fetch_one(f"SELECT ? AS {alias}", [9], no_cache=True)
    assert row == {"why?": 9}


# ── PostgreSQL-only string forms ───────────────────────────────────

def test_postgres_dollar_quoted_string(pg):
    row = pg.fetch_one("SELECT $$why? 100%$$ AS v, $tag$ok?$tag$ AS w, ? AS n", [1], no_cache=True)
    assert row == {"v": "why? 100%", "w": "ok?", "n": 1}


def test_postgres_escape_string(pg):
    rows = pg.fetch("SELECT E'it\\'s 50%?' AS v, ? AS n", [1], limit=5, no_cache=True).records
    assert rows == [{"v": "it's 50%?", "n": 1}]


# ── the scanner, pure ──────────────────────────────────────────────

@pytest.mark.parametrize("sql, expected", [
    ("SELECT 'why?' AS v, ? AS n", "SELECT 'why?' AS v, %s AS n"),
    ("SELECT ? -- why?", "SELECT %s -- why?"),
    ("SELECT /* a? /* nested? */ b? */ ?", "SELECT /* a? /* nested? */ b? */ %s"),
    ("SELECT $$a?$$, $fn$b?$fn$, ?", "SELECT $$a?$$, $fn$b?$fn$, %s"),
    ("SELECT \"a?\", `b?`, ?", "SELECT \"a?\", `b?`, %s"),
    ("SELECT 'it''s?', ?", "SELECT 'it''s?', %s"),
    ("SELECT id FROM t WHERE a = ? AND b = %s", "SELECT id FROM t WHERE a = %s AND b = %s"),
])
def test_placeholder_style_rewrites_only_code(sql, expected):
    assert SQLTranslator.placeholder_style(sql, "%s") == expected


def test_placeholder_style_honours_mysql_backslash_escapes():
    sql = "SELECT 'it\\'s?', ?"
    assert SQLTranslator.placeholder_style(sql, "%s", backslash_escapes=True) == "SELECT 'it\\'s?', %s"


def test_escape_literal_percent_keeps_placeholders():
    assert SQLTranslator.escape_literal_percent("SELECT 'a%s%', 5 % 2, %s -- 9%") == (
        "SELECT 'a%%s%%', 5 %% 2, %s -- 9%%"
    )
