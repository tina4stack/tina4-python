"""Tests for robust RETURNING clause detection and emulation.

Covers:
  - _has_returning_clause() — parsing accuracy, false-positive rejection
  - execute() with RETURNING — live tests against SQLite (native support)
  - execute() with RETURNING — live tests against MySQL and MSSQL (emulated)
  - execute() with RETURNING — live tests against PostgreSQL and Firebird (native)
"""

import os
import pytest

from tina4_python.Database import Database


# ---------------------------------------------------------------------------
# Unit tests for _has_returning_clause (no database needed)
# ---------------------------------------------------------------------------

class TestHasReturningClause:
    """Test the static _has_returning_clause detection method."""

    # --- True positives: should detect RETURNING ---

    def test_insert_returning_star(self):
        sql = "INSERT INTO users (name) VALUES ('Alice') RETURNING *"
        assert Database._has_returning_clause(sql) is True

    def test_insert_returning_columns(self):
        sql = "INSERT INTO users (name, email) VALUES ('Bob', 'b@b.com') RETURNING id, name"
        assert Database._has_returning_clause(sql) is True

    def test_update_returning(self):
        sql = "UPDATE users SET name = 'Charlie' WHERE id = 1 RETURNING id, name"
        assert Database._has_returning_clause(sql) is True

    def test_delete_returning(self):
        sql = "DELETE FROM users WHERE id = 1 RETURNING *"
        assert Database._has_returning_clause(sql) is True

    def test_returning_case_insensitive(self):
        sql = "insert into users (name) values ('test') Returning id"
        assert Database._has_returning_clause(sql) is True

    def test_returning_mixed_case(self):
        sql = "INSERT INTO users (name) VALUES ('test') rEtUrNiNg id"
        assert Database._has_returning_clause(sql) is True

    def test_returning_with_newlines(self):
        sql = "INSERT INTO users (name)\nVALUES ('test')\nRETURNING id, name"
        assert Database._has_returning_clause(sql) is True

    # --- True negatives: should NOT detect RETURNING ---

    def test_select_no_returning(self):
        """SELECT statements never have RETURNING."""
        sql = "SELECT * FROM users"
        assert Database._has_returning_clause(sql) is False

    def test_returning_in_string_literal(self):
        """'returning' inside a string literal is not a clause."""
        sql = "INSERT INTO logs (msg) VALUES ('returning customer logged in')"
        assert Database._has_returning_clause(sql) is False

    def test_returning_in_column_name(self):
        """A column named 'returning_date' should not trigger."""
        sql = "INSERT INTO loans (returning_date) VALUES ('2025-01-01')"
        assert Database._has_returning_clause(sql) is False

    def test_returning_in_double_quoted_identifier(self):
        """Double-quoted identifier containing 'returning'."""
        sql = 'INSERT INTO "returning" (id) VALUES (1)'
        assert Database._has_returning_clause(sql) is False

    def test_returning_in_comment_block(self):
        """Block comment containing RETURNING."""
        sql = "INSERT INTO users (name) VALUES ('x') /* RETURNING id */"
        assert Database._has_returning_clause(sql) is False

    def test_returning_in_line_comment(self):
        """Line comment containing RETURNING."""
        sql = "INSERT INTO users (name) VALUES ('x') -- RETURNING id"
        assert Database._has_returning_clause(sql) is False

    def test_select_with_returning_word(self):
        """SELECT that mentions 'returning' in WHERE clause."""
        sql = "SELECT * FROM shipments WHERE status = 'returning'"
        assert Database._has_returning_clause(sql) is False

    def test_plain_insert_no_returning(self):
        sql = "INSERT INTO users (name) VALUES ('Alice')"
        assert Database._has_returning_clause(sql) is False

    def test_plain_update_no_returning(self):
        sql = "UPDATE users SET name = 'Bob' WHERE id = 1"
        assert Database._has_returning_clause(sql) is False

    def test_plain_delete_no_returning(self):
        sql = "DELETE FROM users WHERE id = 1"
        assert Database._has_returning_clause(sql) is False

    def test_returning_as_table_alias(self):
        """Edge case: table alias called 'returning' — not a RETURNING clause."""
        sql = "SELECT returning.id FROM orders returning WHERE returning.id = 1"
        assert Database._has_returning_clause(sql) is False

    def test_returning_inside_escaped_quotes(self):
        """String with escaped quotes containing 'returning'."""
        sql = "INSERT INTO logs (msg) VALUES ('it''s returning again')"
        assert Database._has_returning_clause(sql) is False


# ---------------------------------------------------------------------------
# Live SQLite tests — native RETURNING support (SQLite >= 3.35)
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(tmp_path):
    db_path = str(tmp_path / "test_returning.db")
    db = Database(f"sqlite3:{db_path}")
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)")
    db.commit()
    return db


class TestReturningSQLite:
    """SQLite supports RETURNING natively since 3.35."""

    def test_insert_returning_star(self, sqlite_db):
        result = sqlite_db.execute(
            "INSERT INTO users (name, email) VALUES (?, ?) RETURNING *",
            ["Alice", "alice@test.com"]
        )
        sqlite_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0]["name"] == "Alice"
        assert result.records[0]["email"] == "alice@test.com"
        assert result.records[0]["id"] is not None

    def test_insert_returning_specific_columns(self, sqlite_db):
        result = sqlite_db.execute(
            "INSERT INTO users (name, email) VALUES (?, ?) RETURNING id, name",
            ["Bob", "bob@test.com"]
        )
        sqlite_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert "id" in result.records[0]
        assert "name" in result.records[0]
        assert result.records[0]["name"] == "Bob"

    def test_update_returning(self, sqlite_db):
        sqlite_db.execute("INSERT INTO users (name, email) VALUES (?, ?)", ["Charlie", "c@test.com"])
        sqlite_db.commit()
        result = sqlite_db.execute(
            "UPDATE users SET name = ? WHERE email = ? RETURNING id, name",
            ["Charles", "c@test.com"]
        )
        sqlite_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0]["name"] == "Charles"

    def test_delete_returning(self, sqlite_db):
        sqlite_db.execute("INSERT INTO users (name, email) VALUES (?, ?)", ["Dave", "d@test.com"])
        sqlite_db.commit()
        result = sqlite_db.execute(
            "DELETE FROM users WHERE email = ? RETURNING *",
            ["d@test.com"]
        )
        sqlite_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0]["name"] == "Dave"

    def test_no_false_positive_string_literal(self, sqlite_db):
        """INSERT with 'returning' in a value should NOT trigger RETURNING logic."""
        sqlite_db.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, msg TEXT)")
        sqlite_db.commit()
        result = sqlite_db.execute(
            "INSERT INTO logs (msg) VALUES (?)",
            ["returning customer"]
        )
        sqlite_db.commit()
        # Should be a plain insert result, not a RETURNING result
        assert result.error is None

    def test_no_false_positive_column_name(self, sqlite_db):
        """Column named 'returning_date' should not trigger RETURNING."""
        sqlite_db.execute("CREATE TABLE loans (id INTEGER PRIMARY KEY AUTOINCREMENT, returning_date TEXT)")
        sqlite_db.commit()
        result = sqlite_db.execute(
            "INSERT INTO loans (returning_date) VALUES (?)",
            ["2025-06-01"]
        )
        sqlite_db.commit()
        assert result.error is None


# ---------------------------------------------------------------------------
# Live PostgreSQL tests — native RETURNING
# ---------------------------------------------------------------------------

@pytest.fixture
def postgres_db():
    try:
        db = Database("psycopg2:localhost/5437:tina4_test", username="tina4", password="tina4pass")
    except Exception:
        pytest.skip("PostgreSQL not available on port 5437")
    db.execute("DROP TABLE IF EXISTS ret_test")
    db.execute("CREATE TABLE ret_test (id SERIAL PRIMARY KEY, name TEXT, email TEXT)")
    db.commit()
    yield db
    db.execute("DROP TABLE IF EXISTS ret_test")
    db.commit()


class TestReturningPostgreSQL:
    def test_insert_returning(self, postgres_db):
        result = postgres_db.execute(
            "INSERT INTO ret_test (name, email) VALUES (%s, %s) RETURNING id, name",
            ["Alice", "alice@pg.com"]
        )
        postgres_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0]["name"] == "Alice"
        assert result.records[0]["id"] is not None

    def test_update_returning(self, postgres_db):
        postgres_db.execute("INSERT INTO ret_test (name, email) VALUES (%s, %s)", ["Bob", "bob@pg.com"])
        postgres_db.commit()
        result = postgres_db.execute(
            "UPDATE ret_test SET name = %s WHERE email = %s RETURNING *",
            ["Robert", "bob@pg.com"]
        )
        postgres_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Robert"

    def test_delete_returning(self, postgres_db):
        postgres_db.execute("INSERT INTO ret_test (name, email) VALUES (%s, %s)", ["Charlie", "c@pg.com"])
        postgres_db.commit()
        result = postgres_db.execute(
            "DELETE FROM ret_test WHERE email = %s RETURNING name",
            ["c@pg.com"]
        )
        postgres_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Charlie"


# ---------------------------------------------------------------------------
# Live MySQL tests — RETURNING emulated
# ---------------------------------------------------------------------------

@pytest.fixture
def mysql_db():
    try:
        db = Database("mysql.connector:localhost/3306:tina4_test", username="tina4", password="tina4pass")
    except Exception:
        pytest.skip("MySQL not available on port 3306")
    db.execute("DROP TABLE IF EXISTS ret_test")
    db.execute("CREATE TABLE ret_test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), email VARCHAR(100))")
    db.commit()
    yield db
    db.execute("DROP TABLE IF EXISTS ret_test")
    db.commit()


class TestReturningMySQL:
    def test_insert_returning_emulated(self, mysql_db):
        result = mysql_db.execute(
            "INSERT INTO ret_test (name, email) VALUES (?, ?) RETURNING id, name",
            ["Alice", "alice@mysql.com"]
        )
        mysql_db.commit()
        assert result.records is not None
        assert len(result.records) >= 1
        assert result.records[0]["name"] == "Alice"
        assert result.records[0]["id"] is not None

    def test_insert_returning_star_emulated(self, mysql_db):
        result = mysql_db.execute(
            "INSERT INTO ret_test (name, email) VALUES (?, ?) RETURNING *",
            ["Bob", "bob@mysql.com"]
        )
        mysql_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Bob"

    def test_update_returning_emulated(self, mysql_db):
        mysql_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Charlie", "c@mysql.com"])
        mysql_db.commit()
        result = mysql_db.execute(
            "UPDATE ret_test SET name = ? WHERE email = ? RETURNING id, name",
            ["Charles", "c@mysql.com"]
        )
        mysql_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Charlie"  # SELECT runs before UPDATE

    def test_delete_returning_emulated(self, mysql_db):
        mysql_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Dave", "d@mysql.com"])
        mysql_db.commit()
        result = mysql_db.execute(
            "DELETE FROM ret_test WHERE email = ? RETURNING *",
            ["d@mysql.com"]
        )
        mysql_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Dave"


# ---------------------------------------------------------------------------
# Live MSSQL tests — RETURNING emulated
# ---------------------------------------------------------------------------

@pytest.fixture
def mssql_db():
    try:
        db = Database("pymssql:localhost/1433:tina4_test", username="sa", password="Tina4Pass!")
    except Exception:
        pytest.skip("MSSQL not available on port 1433")
    db.execute("IF OBJECT_ID('ret_test', 'U') IS NOT NULL DROP TABLE ret_test")
    db.execute("CREATE TABLE ret_test (id INT IDENTITY(1,1) PRIMARY KEY, name NVARCHAR(100), email NVARCHAR(100))")
    db.commit()
    yield db
    db.execute("IF OBJECT_ID('ret_test', 'U') IS NOT NULL DROP TABLE ret_test")
    db.commit()


class TestReturningMSSQL:
    def test_insert_returning_emulated(self, mssql_db):
        result = mssql_db.execute(
            "INSERT INTO ret_test (name, email) VALUES (?, ?) RETURNING id, name",
            ["Alice", "alice@mssql.com"]
        )
        mssql_db.commit()
        assert result.records is not None
        assert len(result.records) >= 1
        assert result.records[0]["name"] == "Alice"

    def test_update_returning_emulated(self, mssql_db):
        mssql_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Bob", "b@mssql.com"])
        mssql_db.commit()
        result = mssql_db.execute(
            "UPDATE ret_test SET name = ? WHERE email = ? RETURNING id, name",
            ["Robert", "b@mssql.com"]
        )
        mssql_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Bob"  # SELECT runs before UPDATE

    def test_delete_returning_emulated(self, mssql_db):
        mssql_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Charlie", "c@mssql.com"])
        mssql_db.commit()
        result = mssql_db.execute(
            "DELETE FROM ret_test WHERE email = ? RETURNING *",
            ["c@mssql.com"]
        )
        mssql_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Charlie"


# ---------------------------------------------------------------------------
# Live Firebird tests — native RETURNING
# ---------------------------------------------------------------------------

@pytest.fixture
def firebird_db():
    try:
        db = Database(
            "firebird.driver:localhost/33053:/firebird/data/tina4_test.fdb",
            username="SYSDBA",
            password="masterkey"
        )
    except Exception:
        pytest.skip("Firebird not available on port 33053")
    try:
        db.execute("DROP TABLE ret_test")
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    db.execute("CREATE TABLE ret_test (id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, name VARCHAR(100), email VARCHAR(100))")
    db.commit()
    yield db
    try:
        db.execute("DROP TABLE ret_test")
        db.commit()
    except Exception:
        pass


class TestReturningFirebird:
    def test_insert_returning(self, firebird_db):
        result = firebird_db.execute(
            "INSERT INTO ret_test (name, email) VALUES (?, ?) RETURNING id, name",
            ["Alice", "alice@fb.com"]
        )
        firebird_db.commit()
        assert result.records is not None
        assert len(result.records) == 1
        assert result.records[0]["name"] == "Alice"

    def test_update_returning(self, firebird_db):
        firebird_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Bob", "bob@fb.com"])
        firebird_db.commit()
        result = firebird_db.execute(
            "UPDATE ret_test SET name = ? WHERE email = ? RETURNING id, name",
            ["Robert", "bob@fb.com"]
        )
        firebird_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Robert"

    def test_delete_returning(self, firebird_db):
        firebird_db.execute("INSERT INTO ret_test (name, email) VALUES (?, ?)", ["Charlie", "c@fb.com"])
        firebird_db.commit()
        result = firebird_db.execute(
            "DELETE FROM ret_test WHERE email = ? RETURNING name",
            ["c@fb.com"]
        )
        firebird_db.commit()
        assert result.records is not None
        assert result.records[0]["name"] == "Charlie"
