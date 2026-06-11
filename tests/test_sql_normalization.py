"""v3.13.12 — strip trailing ``;`` from user SQL in fetch / fetch_one.

The framework wraps user SQL with ``SELECT COUNT(*) FROM ({sql}) AS
_count_subquery`` (the fetch pagination probe) and appends LIMIT /
OFFSET / ROWS / FETCH NEXT clauses. A trailing ``;`` in the user's
SQL breaks both wrappers — the result is either invalid SQL or two
statements where the second is broken.

This test file pins the strip-trailing-semicolons behaviour at two
levels:

  1. The shared ``DatabaseAdapter._strip_trailing_semicolons`` helper
     (unit-level).
  2. ``Database.fetch`` and ``Database.fetch_one`` against a real
     SQLite database — i.e. that the wrapping pipeline actually
     survives a user-supplied trailing ``;``.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import DatabaseAdapter


# ── Unit: the helper itself ────────────────────────────────────────


class TestStripTrailingSemicolons:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("SELECT 1", "SELECT 1"),
            ("SELECT 1;", "SELECT 1"),
            ("SELECT 1 ;", "SELECT 1"),
            ("SELECT 1;;;", "SELECT 1"),
            ("SELECT 1  ;  ;  ", "SELECT 1"),
            ("SELECT 1\n;\n", "SELECT 1"),
            # Internal semicolons (in literals, comments) are not our problem —
            # left alone.
            ("SELECT ';' AS x", "SELECT ';' AS x"),
            ("SELECT ';' AS x;", "SELECT ';' AS x"),
            # Empty / None handled gracefully.
            ("", ""),
            ("   ", ""),
            (";;;", ""),
        ],
    )
    def test_basic_cases(self, given, expected):
        assert DatabaseAdapter._strip_trailing_semicolons(given) == expected

    def test_none_passthrough(self):
        # Method accepts ``str`` typing but defensive against None.
        assert DatabaseAdapter._strip_trailing_semicolons(None) is None  # type: ignore[arg-type]


# ── Integration: SQLite via the Database wrapper ───────────────────


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite:///{path}")
    database.execute(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
    )
    for i in range(5):
        database.execute("INSERT INTO widgets (name) VALUES (?)", [f"widget-{i}"])
    database.commit()
    yield database
    try:
        database.close()
    except Exception:
        pass
    os.unlink(path)


class TestFetchSurvivesTrailingSemicolon:
    """Pre-v3.13.12 these would have failed because the framework's
    pagination wrapping produces invalid SQL when the user's input
    ends with ``;``."""

    def test_fetch_with_trailing_semicolon(self, db):
        # Pre-v3.13.12: ``SELECT * FROM widgets; LIMIT 100 OFFSET 0`` — invalid
        result = db.fetch("SELECT * FROM widgets;")
        assert result.records, "fetch should still return rows when user SQL ends with ';'"
        assert len(result.records) == 5

    def test_fetch_with_double_trailing_semicolon(self, db):
        result = db.fetch("SELECT * FROM widgets;;")
        assert len(result.records) == 5

    def test_fetch_with_trailing_whitespace_and_semicolon(self, db):
        result = db.fetch("SELECT * FROM widgets   ;   \n   ")
        assert len(result.records) == 5

    def test_fetch_one_with_trailing_semicolon(self, db):
        # Pre-v3.13.12: SQLite would reject ``SELECT * FROM widgets WHERE id = 1;``
        # passed through to .execute() with extra wrapping
        row = db.fetch_one("SELECT * FROM widgets WHERE id = ?;", [1])
        assert row is not None
        assert row["name"] == "widget-0"

    def test_fetch_clean_sql_unchanged(self, db):
        """Regression guard: SQL without a trailing ``;`` works
        exactly the same as before (no double-stripping or whitespace
        weirdness)."""
        result = db.fetch("SELECT * FROM widgets WHERE name = ?", ["widget-2"])
        assert len(result.records) == 1
        assert result.records[0]["name"] == "widget-2"

    def test_count_probe_survives_trailing_semicolon(self, db):
        """The COUNT(*) probe wraps the user SQL in a subquery. With a
        trailing ``;``, that subquery used to be syntactically broken.
        After v3.13.12 the count should match the row count."""
        result = db.fetch("SELECT * FROM widgets;")
        assert result.count == 5, (
            f"COUNT probe wrap must survive trailing ';' (got count={result.count})"
        )


# ── fetch_all semantics: return ALL rows by default ─────────────────


@pytest.fixture
def big_db():
    """A SQLite with 150 rows — bigger than the legacy ``limit=100``
    silent truncation default so we can prove fetch_all returns all
    150 rows now."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite:///{path}")
    database.execute(
        "CREATE TABLE rows (id INTEGER PRIMARY KEY AUTOINCREMENT, n INTEGER)"
    )
    for i in range(150):
        database.execute("INSERT INTO rows (n) VALUES (?)", [i])
    database.commit()
    yield database
    try:
        database.close()
    except Exception:
        pass
    os.unlink(path)


class TestFetchAllReturnsAllRows:
    """Pre-v3.13.12 ``fetch_all`` defaulted to ``limit=100`` and silently
    truncated. v3.13.12 makes ``fetch_all`` actually fetch all rows — its
    name promises that, so the behaviour now matches."""

    def test_fetch_all_returns_all_rows_by_default(self, big_db):
        rows = big_db.fetch_all("SELECT * FROM rows ORDER BY n")
        assert len(rows) == 150, (
            f"fetch_all must return ALL rows by default (got {len(rows)}). "
            "Pre-v3.13.12 silently truncated to 100."
        )

    def test_fetch_all_with_explicit_limit_still_caps(self, big_db):
        """Opt-in cap still works."""
        rows = big_db.fetch_all("SELECT * FROM rows ORDER BY n", limit=10)
        assert len(rows) == 10

    def test_fetch_all_with_explicit_limit_and_offset(self, big_db):
        rows = big_db.fetch_all("SELECT * FROM rows ORDER BY n", limit=5, offset=20)
        assert len(rows) == 5
        assert rows[0]["n"] == 20
        assert rows[4]["n"] == 24

    def test_fetch_default_still_paginates_to_100(self, big_db):
        """fetch() (the metadata-returning sibling) keeps its 100-row
        default — pagination is its job, count is its metadata. Only
        fetch_all changed."""
        result = big_db.fetch("SELECT * FROM rows ORDER BY n")
        assert len(result.records) == 100
        assert result.count == 150  # total still reflects the whole set

    def test_fetch_with_limit_zero_also_returns_all(self, big_db):
        """The underlying mechanism — ``limit=0`` on fetch() — also
        returns all rows. fetch_all delegates here."""
        result = big_db.fetch("SELECT * FROM rows ORDER BY n", limit=0)
        assert len(result.records) == 150

    def test_fetch_all_preserves_trailing_semicolon_strip(self, big_db):
        """The two v3.13.12 changes compose — fetch_all with a trailing
        semicolon still returns all 150 rows."""
        rows = big_db.fetch_all("SELECT * FROM rows ORDER BY n;")
        assert len(rows) == 150
