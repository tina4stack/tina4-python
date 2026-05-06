"""Regression test for issue #40 — psycopg2 % substitution.

A migration containing PL/pgSQL with `RAISE EXCEPTION 'thing %', x`
used to fail with `list index out of range` because psycopg2
interpreted % as a placeholder even when params=None/[]. The fix
routes empty/None params through cursor.execute(sql) (no params arg)
so substitution is skipped.

These tests don't require a live Postgres — we exercise the
_safe_execute helper directly with a fake cursor that records what
psycopg2 would have received.
"""
import pytest

from tina4_python.database.postgres import PostgreSQLAdapter


class FakeCursor:
    """Records every (sql, params_supplied?) call. Lets us verify
    the helper picks the no-params-arg branch correctly."""

    def __init__(self):
        self.calls: list[tuple[str, bool, object]] = []

    def execute(self, sql, params=...):  # sentinel for "not passed"
        if params is ...:
            self.calls.append((sql, False, None))
        else:
            self.calls.append((sql, True, params))


def test_safe_execute_no_params_skips_substitution_pass():
    """Issue #40: when params is None, must call cursor.execute(sql)
    with NO second arg so psycopg2 doesn't try to treat % as a
    placeholder."""
    cur = FakeCursor()
    sql = "CREATE FUNCTION foo() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'thing % conflicts with %', a, b; END $$ LANGUAGE plpgsql"
    PostgreSQLAdapter._safe_execute(cur, sql, None)
    assert len(cur.calls) == 1
    received_sql, had_params_arg, _ = cur.calls[0]
    assert received_sql == sql
    assert had_params_arg is False, (
        "params=None must route to cursor.execute(sql) with no second arg "
        "— otherwise psycopg2 tries to substitute % and a PL/pgSQL body "
        "with literal %% chars blows up (#40)."
    )


def test_safe_execute_empty_list_also_skips_substitution():
    """params=[] is the same case as params=None — psycopg2 still
    triggers substitution if the arg is supplied at all."""
    cur = FakeCursor()
    PostgreSQLAdapter._safe_execute(cur, "RAISE EXCEPTION 'literal %s'", [])
    assert cur.calls[0][1] is False, (
        "Empty list must still route through the no-arg branch."
    )


def test_safe_execute_with_real_params_passes_them_through():
    """When params is non-empty, normal execution path applies
    — psycopg2 substitutes %s correctly."""
    cur = FakeCursor()
    PostgreSQLAdapter._safe_execute(
        cur,
        "INSERT INTO t(a, b) VALUES (%s, %s)",
        [1, 2],
    )
    sql, had_params_arg, params = cur.calls[0]
    assert had_params_arg is True
    assert params == [1, 2]


def test_safe_execute_falsy_zero_param_routed_correctly():
    """[0] is truthy as a list (length 1), so passes through with
    params. Guards against an over-eager `if not params` check."""
    cur = FakeCursor()
    PostgreSQLAdapter._safe_execute(cur, "SELECT %s", [0])
    assert cur.calls[0][1] is True
    assert cur.calls[0][2] == [0]


def test_plpgsql_body_with_percent_does_not_raise():
    """The exact case from issue #40 — a CREATE FUNCTION with literal
    % chars in the body. With the fix, psycopg2 never sees the %
    chars during substitution."""
    cur = FakeCursor()
    body = """
    CREATE OR REPLACE FUNCTION enforce_unique() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF FOUND THEN
            RAISE EXCEPTION 'thing % conflicts with %', NEW.a, NEW.b
                USING HINT = 'use 100%% real values';
        END IF;
        RETURN NEW;
    END $$;
    """
    # Should not raise — the helper's branch routes us away from
    # psycopg2's substitution engine entirely.
    PostgreSQLAdapter._safe_execute(cur, body, None)
    assert cur.calls[0][1] is False
