"""Lock-in tests for the migration footgun fixes (v3.13.39).

- [10] `//` delimiter no longer swallows a URL (`https://…`) as a stored-proc block.
- [8]  discovery sort is numeric-aware (`9_` before `10_`).
- [9]  CREATE TABLE is idempotent on engines lacking IF NOT EXISTS (Firebird/MSSQL).
"""
from tina4_python.migration.runner import (
    _split_statements,
    _parse_set_term,
    _migration_sort_key,
    _should_skip_create_table,
    _normalize_quotes,
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


# ── SET TERM switches the terminator so PSQL bodies survive ──────────────

def test_set_term_keeps_trigger_body_intact():
    # A trigger body has ';'-terminated inner statements; under the default ';'
    # runner it must survive as ONE statement, not be split on those inner ';'.
    sql = (
        "SET TERM ^ ;\n"
        "CREATE OR ALTER TRIGGER t_bi FOR t ACTIVE BEFORE INSERT AS\n"
        "BEGIN\n"
        "  IF (NEW.id IS NULL) THEN NEW.id = GEN_ID(GEN_T, 1);\n"
        "END^\n"
        "SET TERM ; ^"
    )
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 1, f"trigger body was split on its inner ';': {stmts}"
    assert stmts[0].startswith("CREATE OR ALTER TRIGGER")
    assert stmts[0].endswith("END")
    assert "NEW.id = GEN_ID(GEN_T, 1);" in stmts[0]


def test_set_term_directives_are_consumed_not_emitted():
    sql = "SET TERM ^ ;\nEXECUTE BLOCK AS BEGIN a; b; END^\nSET TERM ; ^"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 1
    assert all("SET TERM" not in s for s in stmts), f"SET TERM leaked as SQL: {stmts}"


def test_set_term_restores_previous_delimiter():
    # After `SET TERM ; ^`, plain ';' splitting resumes.
    sql = (
        "CREATE TABLE a (id INT);\n"
        "SET TERM ^ ;\n"
        "CREATE TRIGGER a_bi FOR a AS BEGIN NEW.id = 1; END^\n"
        "SET TERM ; ^\n"
        "INSERT INTO a VALUES (1);\nUPDATE a SET id = 2;"
    )
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 4, f"delimiter not restored to ';' after the block: {stmts}"
    assert stmts[0].startswith("CREATE TABLE")
    assert stmts[1].startswith("CREATE TRIGGER")
    assert stmts[2].startswith("INSERT INTO")
    assert stmts[3].startswith("UPDATE")


def test_set_term_supports_multi_char_terminator():
    sql = "SET TERM !! ;\nCREATE TRIGGER t FOR x AS BEGIN NEW.a = 1; END!!\nSET TERM ; !!"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 1
    assert "!!" not in stmts[0]
    assert "SET TERM" not in stmts[0]


def test_plain_semicolon_unaffected_by_set_term_support():
    # No SET TERM → ordinary ';' splitting, behaviour unchanged.
    sql = "CREATE TABLE a (id INT);\nINSERT INTO a VALUES (1);\nUPDATE a SET id = 2;"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 3
    assert not any(s.endswith(";") for s in stmts)


def test_parse_set_term_recognises_directive_only():
    assert _parse_set_term("SET TERM ^") == "^"
    assert _parse_set_term("set term !!") == "!!"
    assert _parse_set_term("CREATE TABLE a (id INT)") is None
    assert _parse_set_term("SELECT 'SET TERM ^ ;'") is None


# ── smart/curly quotes normalized so the SQL runs ───────────────────────

def test_smart_quotes_normalized_before_split():
    # Smart double quotes around an identifier + smart single quotes around a
    # value — as an editor/doc would produce. They must become straight ASCII so
    # the statement actually runs.
    sql = "CREATE TABLE “users” (name TEXT DEFAULT ‘guest’);"
    joined = " ".join(_split_statements(sql, ";"))
    for smart in ("“", "”", "‘", "’", "′", "″"):
        assert smart not in joined, f"smart quote {smart!r} survived"
    assert '"users"' in joined
    assert "'guest'" in joined


def test_normalize_quotes_preserves_straight_and_content():
    # Straight quotes and ordinary apostrophe-free content are untouched.
    sql = "INSERT INTO t (v) VALUES ('plain');"
    assert _normalize_quotes(sql) == sql


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


# ── [#54] a ';' inside a comment or string literal must NOT split a statement ──

def test_semicolon_in_line_comment_does_not_fragment():
    # The exact issue #54 repro: a ';' inside a '-- …' line comment used to
    # fragment this ONE CREATE TABLE into broken pieces (sqlite "incomplete input").
    sql = (
        "CREATE TABLE users (\n"
        "    id INTEGER PRIMARY KEY,   -- drop then re-add; old way\n"
        "    name TEXT NOT NULL\n"
        ");"
    )
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 1, f"';' inside a -- comment fragmented the statement: {stmts}"
    assert "id INTEGER PRIMARY KEY" in stmts[0]
    assert "name TEXT NOT NULL" in stmts[0]
    assert "old way" not in stmts[0], "line comment text was not stripped"


def test_semicolon_in_block_comment_does_not_fragment():
    sql = "CREATE TABLE t (id INTEGER /* a; b; c */, name TEXT);"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 1, f"';' inside a /* */ comment fragmented the statement: {stmts}"
    assert "a; b; c" not in stmts[0], "block comment text was not stripped"
    assert "id INTEGER" in stmts[0] and "name TEXT" in stmts[0]


def test_semicolon_in_string_literal_does_not_split():
    # A ';' inside a quoted value is data, not a delimiter.
    sql = "INSERT INTO t (v) VALUES ('a;b;c'); INSERT INTO t (v) VALUES ('d');"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 2, f"';' inside a string literal split the statement: {stmts}"
    assert "'a;b;c'" in stmts[0], "string-literal content was corrupted"
    assert "'d'" in stmts[1]


def test_double_dash_inside_string_literal_is_not_a_comment():
    # A '--' inside a quoted string is data, not the start of a line comment.
    sql = "INSERT INTO t (v) VALUES ('a--b'); INSERT INTO t (v) VALUES ('c');"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 2, stmts
    assert "'a--b'" in stmts[0], "'--' inside a string literal was wrongly stripped as a comment"


def test_quoted_quote_escape_does_not_end_string_early():
    # SQL escapes a quote by doubling it ('') — a ';' after the escaped quote but
    # still inside the literal must not split.
    sql = "INSERT INTO t (v) VALUES ('O''Brien; Jr'); SELECT 1;"
    stmts = _split_statements(sql, ";")
    assert len(stmts) == 2, f"doubled-quote escape mishandled, split wrongly: {stmts}"
    assert "'O''Brien; Jr'" in stmts[0]


def test_migrate_applies_statement_with_semicolon_in_comment(tmp_path):
    # End-to-end against a REAL temp SQLite DB (no mocks): the issue's repro
    # migration must apply cleanly and create the table.
    from tina4_python.database import Database
    from tina4_python.migration import Migration

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "000001_create_users.sql").write_text(
        "CREATE TABLE users (\n"
        "    id INTEGER PRIMARY KEY,   -- drop then re-add; old way\n"
        "    name TEXT NOT NULL\n"
        ");"
    )
    db = Database(f"sqlite:///{tmp_path / 'mig54.db'}")
    try:
        ran = Migration(db, str(mig_dir)).migrate()
        assert ran == ["000001_create_users.sql"]
        assert db.table_exists("users"), "table was not created — migration failed to apply"
        # The table is real and usable.
        db.execute("INSERT INTO users (name) VALUES (?)", ["Alice"])
        db.commit()
        assert db.fetch("SELECT name FROM users").records[0]["name"] == "Alice"
    finally:
        db.close()
