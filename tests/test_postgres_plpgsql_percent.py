"""End-to-end regression for issue #40 — psycopg2 %-substitution.

The unit-level test in ``test_postgres_percent_substitution.py`` covers
the helper. This one exercises a real round-trip through the live PG
adapter: a migration body containing ``RAISE EXCEPTION 'thing %', x``
must execute without psycopg2 trying to substitute the literal ``%``.

Yesterday's database tests didn't exercise SQL with literal ``%``
characters, which is how this slipped through to a user. This test
plus the unit tests close the gap so a future pre-release sweep would
catch a regression in the ``_safe_execute`` branching.

Skipped when no Docker postgres is reachable — keeps CI green
on machines without a DB.
"""
from __future__ import annotations

import os
import socket

import pytest

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USERNAME", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASSWORD", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} — skip integration test",
)


def _cleanup(d):
    """Drop everything these tests create, idempotently. CASCADE removes the
    dependent trigger so DROP FUNCTION cannot fail and leave the function behind
    (a leftover trigger-typed t4_issue40_raises() collided with the void-typed
    CREATE OR REPLACE on the next run). Run on setup AND teardown so a leftover
    from any prior run can never make this real-DB test flake."""
    for stmt in (
        "DROP TRIGGER IF EXISTS t4_issue40_trg ON t4_issue40_t",
        "DROP TABLE IF EXISTS t4_issue40_t CASCADE",
        "DROP FUNCTION IF EXISTS t4_issue40_raises() CASCADE",
    ):
        try:
            d.execute(stmt)
        except Exception:
            pass


@pytest.fixture
def db():
    from tina4_python.database import Database
    d = Database(
        f"postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}",
        username=PG_USER, password=PG_PASS,
    )
    _cleanup(d)   # pristine slate, even if a prior run left state behind
    yield d
    _cleanup(d)
    d.close()


def test_create_function_with_literal_percent_in_body(db):
    """The minimum repro from issue #40: a CREATE FUNCTION body with
    ``RAISE EXCEPTION 'msg %, %, %'``. Pre-fix this raised
    ``list index out of range`` from psycopg2's substitution engine.
    Post-fix: function compiles cleanly."""
    db.execute(
        """
        CREATE OR REPLACE FUNCTION t4_issue40_raises() RETURNS void
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'thing % conflicts with %', 1, 2
                USING HINT = 'literal % chars in body must survive (use 100%% rate)';
        END $$;
        """
    )
    # If we got here, the migration-style execution succeeded. Drop
    # for a clean slate before the next test.
    db.execute("DROP FUNCTION t4_issue40_raises()")


def test_select_with_literal_percent_in_string_literal(db):
    """Edge case companion: even simple SELECTs with literal ``%`` in
    a string literal blew up the same way under the old
    ``cursor.execute(sql, [])`` codepath."""
    row = db.fetch_one("SELECT 'thing % conflicts with %' AS msg")
    assert row is not None
    assert row["msg"] == "thing % conflicts with %"


def test_real_migration_body_runs_unchanged(db):
    """A complete migration that creates a table, a trigger function
    with literal ``%`` in its body, and exercises it end-to-end. The
    post-fix code path must run all three statements in sequence
    without psycopg2 trying to substitute anything."""
    db.execute("DROP TABLE IF EXISTS t4_issue40_t CASCADE")
    db.execute(
        "CREATE TABLE t4_issue40_t (id SERIAL PRIMARY KEY, name TEXT NOT NULL)"
    )
    db.execute(
        """
        CREATE OR REPLACE FUNCTION t4_issue40_raises() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.name = 'forbidden' THEN
                RAISE EXCEPTION 'name % is forbidden — saw %', NEW.name, NEW.id;
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    db.execute(
        """
        DROP TRIGGER IF EXISTS t4_issue40_trg ON t4_issue40_t;
        CREATE TRIGGER t4_issue40_trg BEFORE INSERT ON t4_issue40_t
        FOR EACH ROW EXECUTE FUNCTION t4_issue40_raises();
        """
    )
    # Insert a valid row — should work.
    db.execute("INSERT INTO t4_issue40_t (name) VALUES ('ok')")
    rows = db.fetch("SELECT * FROM t4_issue40_t").records
    assert len(rows) == 1
    assert rows[0]["name"] == "ok"
