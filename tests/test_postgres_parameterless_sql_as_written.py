"""SQL with no parameters is sent to the engine exactly as written.

The ``?`` -> ``%s`` rewrite (#138) only makes sense when there are parameters to
bind. Run without them, it turned PostgreSQL's jsonb key operators ``?``,
``?|`` and ``?&`` into ``%s`` and the query failed with a syntax error, so there
was no way to use them at all. The contract, the same in all four frameworks
(PHP already did this): no parameters, no rewrite and no ``%`` doubling. With
parameters, ``?`` is a placeholder wherever it appears in code - use
``jsonb_exists()``, ``jsonb_exists_any()`` or ``jsonb_exists_all()`` there.

NO MOCKS: a real PostgreSQL.
"""
import os
import socket
from urllib.parse import urlparse

import pytest

PG_URL = os.environ.get("TINA4_TEST_PG_URL", "postgres://tina4:tina4@localhost:55432/tina4_py")
_PARSED = urlparse(PG_URL)
PG_HOST, PG_PORT = _PARSED.hostname or "localhost", _PARSED.port or 5432
DOC = """'{"a": 1, "b": 2}'::jsonb"""


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


def test_jsonb_key_operator_without_params(db):
    assert db.fetch_one(f"SELECT {DOC} ? 'a' AS has", no_cache=True) == {"has": True}


def test_jsonb_any_and_all_operators_without_params(db):
    row = db.fetch_one(
        f"SELECT {DOC} ?| array['z', 'a'] AS any_key, {DOC} ?& array['a', 'z'] AS all_keys", no_cache=True,
    )
    assert row == {"any_key": True, "all_keys": False}


def test_jsonb_operator_through_fetch_and_execute_without_params(db):
    """fetch() adds its own LIMIT/OFFSET binds; the caller passed none, so ``?`` stays an operator."""
    assert db.fetch(f"SELECT {DOC} ? 'b' AS has", limit=5, no_cache=True).records == [{"has": True}]
    db.execute(f"SELECT {DOC} ? 'b' AS has")  # must not raise: sent exactly as written


def test_a_literal_percent_without_params_is_not_doubled(db):
    assert db.fetch_one("SELECT '100%' AS v", no_cache=True) == {"v": "100%"}


def test_with_params_the_question_mark_is_a_placeholder(db):
    assert db.fetch_one("SELECT ?::text AS v", ["x"], no_cache=True) == {"v": "x"}
    with pytest.raises(Exception):
        # Both ? are placeholders once parameters are passed: 2 markers, 1 value.
        db.fetch_one(f"SELECT {DOC} ? 'a' AS has WHERE 1 = ?", [1], no_cache=True)


def test_with_params_use_the_jsonb_exists_functions(db):
    row = db.fetch_one(
        f"SELECT jsonb_exists({DOC}, ?) AS has, jsonb_exists_any({DOC}, ?) AS any_key, "
        f"jsonb_exists_all({DOC}, ?) AS all_keys",
        ["a", ["z", "a"], ["a", "z"]], no_cache=True,
    )
    assert row == {"has": True, "any_key": True, "all_keys": False}
