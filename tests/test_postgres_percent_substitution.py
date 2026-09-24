# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression test for issue #40 — psycopg2 % substitution.

A migration containing PL/pgSQL with `RAISE EXCEPTION 'thing %', x`
used to fail with `list index out of range` because psycopg2
interpreted % as a placeholder even when params=None/[]. The fix
routes empty/None params through cursor.execute(sql) (no params arg)
so substitution is skipped. With real parameters, a literal % is doubled
first so it survives substitution (#138).

NO MOCKS. This file used to hand ``_safe_execute`` a fake cursor that recorded
which branch it took; it proved the branch, never that PostgreSQL got the right
SQL. Every case below runs ``_safe_execute`` on a REAL psycopg2 cursor and reads
the value PostgreSQL sends back.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

from tina4_python.database.postgres import PostgreSQLAdapter

PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
_PARSED = urlparse(PG_URL)
PG_HOST, PG_PORT = _PARSED.hostname or "localhost", _PARSED.port or 5432
FUNCTION = "issue40_py_enforce"


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} - skip integration test",
)


@pytest.fixture
def db():
    from tina4_python.database import Database
    database = Database(PG_URL)
    yield database
    database.close()


@pytest.fixture
def cursor(db):
    """A real psycopg2 cursor; rolled back afterwards so nothing lingers."""
    connection = db._get_adapter()._conn
    real_cursor = connection.cursor()
    yield real_cursor
    connection.rollback()


def _value(cursor, sql, params):
    PostgreSQLAdapter._safe_execute(cursor, sql, params)
    return cursor.fetchone()


def test_safe_execute_no_params_skips_substitution_pass(cursor):
    """params=None: the SQL goes to PostgreSQL untouched, literal % included."""
    assert _value(cursor, "SELECT 'thing % conflicts with %' AS v", None) == ("thing % conflicts with %",)


def test_safe_execute_empty_list_also_skips_substitution(cursor):
    """params=[] is the same case - psycopg2 substitutes whenever the argument is supplied at all."""
    assert _value(cursor, "SELECT 'literal %s and %' AS v", []) == ("literal %s and %",)


def test_safe_execute_with_real_params_passes_them_through(cursor):
    assert _value(cursor, "SELECT %s::int + %s::int AS v", [1, 2]) == (3,)


def test_safe_execute_falsy_zero_param_routed_correctly(cursor):
    """[0] is a real parameter list (length 1), not 'no params'."""
    assert _value(cursor, "SELECT %s::int AS v", [0]) == (0,)


def test_safe_execute_literal_percent_with_real_params(cursor):
    """#138: with parameters a literal % is doubled first, so it survives substitution."""
    assert _value(cursor, "SELECT '100%' AS v, %s::int AS n", [7]) == ("100%", 7)


def test_plpgsql_body_with_percent_does_not_raise(db):
    """The exact case from issue #40: CREATE FUNCTION with literal % in its body,
    created through execute() and then called for real."""
    db.execute(f"""
    CREATE OR REPLACE FUNCTION {FUNCTION}(a int, b int) RETURNS void
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'thing % conflicts with %', a, b
            USING HINT = 'use 100%% real values';
    END $$;
    """)
    try:
        with pytest.raises(Exception) as raised:
            db.fetch_one(f"SELECT {FUNCTION}(1, 2)", no_cache=True)
        assert "thing 1 conflicts with 2" in str(raised.value)
    finally:
        db.rollback()
        db.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(int, int)")
