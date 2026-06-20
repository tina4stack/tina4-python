"""Lock-in tests for the migration footgun fixes (v3.13.39).

- [10] `//` delimiter no longer swallows a URL (`https://…`) as a stored-proc block.
- [8]  discovery sort is numeric-aware (`9_` before `10_`).
- [9]  CREATE TABLE is idempotent on engines lacking IF NOT EXISTS (Firebird/MSSQL).
"""
from tina4_python.migration.runner import (
    _split_statements,
    _migration_sort_key,
    _should_skip_create_table,
)


class _FakeDB:
    def __init__(self, engine, table_exists):
        self._engine = engine
        self._exists = table_exists

    def get_database_type(self):
        return self._engine

    def table_exists(self, _name):
        return self._exists


# ── [10] `//` delimiter must not swallow a URL ──────────────────────────

def test_split_does_not_swallow_url_scheme():
    sql = (
        "INSERT INTO cfg (k, v) VALUES ('home', 'https://a.example.com');\n"
        "INSERT INTO cfg (k, v) VALUES ('cb', 'https://b.example.com');"
    )
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 2, f"URL `//` was captured as a block, breaking split: {stmts}"
    assert "https://a.example.com" in stmts[0]
    assert "https://b.example.com" in stmts[1]


def test_split_still_handles_real_stored_proc_block():
    # A genuine `// ... //` stored-proc block (delimiters not preceded by `:`)
    # is still kept intact as one statement.
    sql = "CREATE PROCEDURE foo() // BEGIN SELECT 1; SELECT 2; END //;"
    stmts = _split_statements(sql, ";")
    assert any("BEGIN SELECT 1; SELECT 2; END" in s for s in stmts), stmts


# ── [8] numeric-aware discovery order ───────────────────────────────────

def test_sort_key_is_numeric_aware():
    names = ["10_b.sql", "9_a.sql", "2_x.sql", "alpha.sql"]
    assert sorted(names, key=_migration_sort_key) == [
        "2_x.sql", "9_a.sql", "10_b.sql", "alpha.sql",
    ]


# ── [9] CREATE TABLE idempotency on Firebird/MSSQL ──────────────────────

def test_create_table_skipped_on_mssql_when_table_exists():
    reason = _should_skip_create_table(_FakeDB("mssql", True), "CREATE TABLE users (id INT)")
    assert reason and "users" in reason


def test_create_table_skipped_on_firebird_bracketless_when_exists():
    reason = _should_skip_create_table(_FakeDB("firebird", True), 'CREATE TABLE "Orders" (id INT)')
    assert reason and "Orders" in reason


def test_create_table_not_skipped_when_absent():
    assert _should_skip_create_table(_FakeDB("firebird", False), "CREATE TABLE users (id INT)") is None


def test_create_table_not_skipped_on_sqlite_left_to_if_not_exists():
    # SQLite/MySQL/PostgreSQL support IF NOT EXISTS → never skipped by this guard.
    assert _should_skip_create_table(_FakeDB("sqlite", True), "CREATE TABLE users (id INT)") is None
    assert _should_skip_create_table(_FakeDB("postgres", True), "CREATE TABLE users (id INT)") is None


def test_non_create_statement_ignored():
    assert _should_skip_create_table(_FakeDB("mssql", True), "INSERT INTO users VALUES (1)") is None
