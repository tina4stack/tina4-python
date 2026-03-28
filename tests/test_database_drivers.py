# Tests for database driver registration, URL parsing, SQL translation, and CRUD.
"""
Tests cover:
- Driver registration (URL scheme -> adapter mapping)
- Graceful import errors when driver packages are missing
- SQL translation per dialect
- Connection URL parsing
- SQLite: full CRUD tests (always available)
- PostgreSQL, MySQL, MSSQL, Firebird: skip if driver not available
"""
import pytest
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse
from tina4_python.database import Database, DatabaseResult, SQLTranslator
from tina4_python.database.connection import _DRIVERS


# ── Driver Registration ──────────────────────────────────────────


class TestDriverRegistration:
    """All drivers are registered and discoverable by URL scheme."""

    def test_sqlite_registered(self):
        assert "sqlite" in _DRIVERS

    def test_postgresql_registered(self):
        assert "postgresql" in _DRIVERS

    def test_postgres_alias_registered(self):
        assert "postgres" in _DRIVERS

    def test_mysql_registered(self):
        assert "mysql" in _DRIVERS

    def test_mssql_registered(self):
        assert "mssql" in _DRIVERS

    def test_firebird_registered(self):
        assert "firebird" in _DRIVERS

    def test_postgresql_and_postgres_same_class(self):
        assert _DRIVERS["postgresql"] is _DRIVERS["postgres"]

    def test_unknown_driver_raises(self):
        with pytest.raises(ValueError, match="Unknown database driver"):
            Database("fakedb://localhost/test")


# ── Graceful Import Errors ───────────────────────────────────────


class TestGracefulImportErrors:
    """Drivers raise clear ImportError when package is not installed."""

    def test_postgres_missing_psycopg2(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        adapter = PostgreSQLAdapter()
        with patch.dict("sys.modules", {"psycopg2": None, "psycopg2.extras": None}):
            with pytest.raises(ImportError, match="psycopg2"):
                adapter.connect("postgresql://user:pass@localhost:5432/testdb")

    def test_mysql_missing_connector(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        with patch.dict("sys.modules", {"mysql": None, "mysql.connector": None}):
            with pytest.raises(ImportError, match="mysql-connector-python"):
                adapter.connect("mysql://user:pass@localhost:3306/testdb")

    def test_mssql_missing_pymssql(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        with patch.dict("sys.modules", {"pymssql": None}):
            with pytest.raises(ImportError, match="pymssql"):
                adapter.connect("mssql://user:pass@localhost:1433/testdb")

    def test_firebird_missing_driver(self):
        from tina4_python.database import firebird as fb_module
        adapter = fb_module.FirebirdAdapter()
        original_driver = fb_module._driver
        fb_module._driver = None
        try:
            with pytest.raises(ImportError, match="Firebird driver"):
                adapter.connect("firebird://user:pass@localhost:3050/test.fdb")
        finally:
            fb_module._driver = original_driver


# ── Connection URL Parsing ───────────────────────────────────────


class TestConnectionURLParsing:
    """URL parsing extracts host, port, user, password, database correctly."""

    def test_postgresql_url(self):
        url = "postgresql://alice:secret@db.example.com:5433/myapp"
        parsed = urlparse(url)
        assert parsed.scheme == "postgresql"
        assert parsed.hostname == "db.example.com"
        assert parsed.port == 5433
        assert parsed.username == "alice"
        assert parsed.password == "secret"
        assert parsed.path == "/myapp"

    def test_mysql_url(self):
        url = "mysql://root:pass123@mysql-server:3307/shop"
        parsed = urlparse(url)
        assert parsed.scheme == "mysql"
        assert parsed.hostname == "mysql-server"
        assert parsed.port == 3307
        assert parsed.username == "root"
        assert parsed.password == "pass123"
        assert parsed.path == "/shop"

    def test_mssql_url(self):
        url = "mssql://sa:MyPass@mssql-host:1434/warehouse"
        parsed = urlparse(url)
        assert parsed.scheme == "mssql"
        assert parsed.hostname == "mssql-host"
        assert parsed.port == 1434
        assert parsed.username == "sa"
        assert parsed.password == "MyPass"

    def test_firebird_url(self):
        url = "firebird://SYSDBA:masterkey@fbhost:3050/var/lib/firebird/data/app.fdb"
        parsed = urlparse(url)
        assert parsed.scheme == "firebird"
        assert parsed.hostname == "fbhost"
        assert parsed.port == 3050
        assert parsed.username == "SYSDBA"
        assert parsed.password == "masterkey"

    def test_postgresql_defaults(self):
        url = "postgresql://localhost/testdb"
        parsed = urlparse(url)
        assert parsed.hostname == "localhost"
        assert parsed.port is None  # defaults to 5432 in adapter
        assert parsed.path == "/testdb"

    def test_sqlite_url(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(f"sqlite:///{db_path}")
        assert db.get_database_type() == "sqlite"
        db.close()


# ── SQL Translation Per Dialect ──────────────────────────────────


class TestPostgreSQLTranslation:
    """PostgreSQL-specific SQL translations."""

    def test_placeholder_to_percent_s(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        adapter = PostgreSQLAdapter()
        result = adapter._translate_sql("SELECT * FROM users WHERE id = ? AND name = ?")
        assert "%s" in result
        assert "?" not in result

    def test_autoincrement_to_serial(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        adapter = PostgreSQLAdapter()
        result = adapter._translate_sql(
            "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
        assert "SERIAL PRIMARY KEY" in result

    def test_supports_returning(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        adapter = PostgreSQLAdapter()
        assert adapter._supports_returning() is True

    def test_database_type(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        adapter = PostgreSQLAdapter()
        assert adapter.get_database_type() == "postgresql"


class TestMySQLTranslation:
    """MySQL-specific SQL translations."""

    def test_placeholder_to_percent_s(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        result = adapter._translate_sql("SELECT * FROM users WHERE id = ?")
        assert "%s" in result

    def test_concat_pipes_to_func(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        result = adapter._translate_sql("'a' || 'b' || 'c'")
        assert "CONCAT(" in result

    def test_ilike_to_lower_like(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        result = adapter._translate_sql("SELECT * FROM t WHERE name ILIKE '%test%'")
        assert "LOWER(" in result
        assert "ILIKE" not in result

    def test_autoincrement_to_auto_increment(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        result = adapter._translate_sql("CREATE TABLE t (id INTEGER AUTOINCREMENT)")
        assert "AUTO_INCREMENT" in result

    def test_no_returning(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        assert adapter._supports_returning() is False

    def test_database_type(self):
        from tina4_python.database.mysql import MySQLAdapter
        adapter = MySQLAdapter()
        assert adapter.get_database_type() == "mysql"


class TestMSSQLTranslation:
    """MSSQL-specific SQL translations."""

    def test_placeholder_to_percent_s(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        result = adapter._translate_sql("SELECT * FROM users WHERE id = ?")
        assert "%s" in result

    def test_concat_pipes_to_func(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        result = adapter._translate_sql("'x' || 'y'")
        assert "CONCAT(" in result

    def test_boolean_to_int(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        result = adapter._translate_sql("WHERE active = TRUE AND deleted = FALSE")
        assert "TRUE" not in result
        assert "FALSE" not in result
        assert "1" in result
        assert "0" in result

    def test_identity_syntax(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        result = adapter._translate_sql("CREATE TABLE t (id INTEGER AUTOINCREMENT)")
        assert "IDENTITY(1,1)" in result

    def test_no_returning(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        assert adapter._supports_returning() is False

    def test_database_type(self):
        from tina4_python.database.mssql import MSSQLAdapter
        adapter = MSSQLAdapter()
        assert adapter.get_database_type() == "mssql"


class TestFirebirdTranslation:
    """Firebird-specific SQL translations."""

    def test_limit_to_rows(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql("SELECT * FROM users LIMIT 10 OFFSET 5")
        assert "ROWS 6 TO 15" in result
        assert "LIMIT" not in result

    def test_limit_only_to_rows(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql("SELECT * FROM users LIMIT 10")
        assert "ROWS 1 TO 10" in result

    def test_ilike_to_lower_like(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql("WHERE name ILIKE '%test%'")
        assert "LOWER(" in result
        assert "ILIKE" not in result

    def test_boolean_to_int(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql("WHERE active = TRUE")
        assert "TRUE" not in result
        assert "1" in result

    def test_strips_autoincrement(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql(
            "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
        assert "AUTOINCREMENT" not in result

    def test_question_mark_placeholders_kept(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        result = adapter._translate_sql("SELECT * FROM t WHERE id = ?")
        assert "?" in result

    def test_no_returning(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        assert adapter._supports_returning() is False

    def test_database_type(self):
        from tina4_python.database.firebird import FirebirdAdapter
        adapter = FirebirdAdapter()
        assert adapter.get_database_type() == "firebird"


# ── SQLite CRUD Tests (always available) ─────────────────────────


class TestSQLiteCRUD:
    """Full CRUD tests using SQLite (stdlib, always available)."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "crud_test.db"
        d = Database(f"sqlite:///{db_path}")
        d.execute(
            "CREATE TABLE products ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, "
            "price REAL DEFAULT 0.0, "
            "active INTEGER DEFAULT 1"
            ")"
        )
        d.commit()
        yield d
        d.close()

    def test_insert(self, db):
        result = db.insert("products", {"name": "Widget", "price": 9.99})
        db.commit()
        assert result.last_id == 1
        assert result.affected_rows == 1

    def test_fetch(self, db):
        db.insert("products", {"name": "A", "price": 1.0})
        db.insert("products", {"name": "B", "price": 2.0})
        db.insert("products", {"name": "C", "price": 3.0})
        db.commit()
        result = db.fetch("SELECT * FROM products", limit=2)
        assert len(result.records) == 2
        assert result.count == 3

    def test_fetch_one(self, db):
        db.insert("products", {"name": "Solo", "price": 5.0})
        db.commit()
        row = db.fetch_one("SELECT * FROM products WHERE name = ?", ["Solo"])
        assert row is not None
        assert row["name"] == "Solo"

    def test_update(self, db):
        db.insert("products", {"name": "Old", "price": 1.0})
        db.commit()
        db.update("products", {"name": "New"}, "name = ?", ["Old"])
        db.commit()
        row = db.fetch_one("SELECT * FROM products WHERE id = ?", [1])
        assert row["name"] == "New"

    def test_delete(self, db):
        db.insert("products", {"name": "Gone", "price": 0.0})
        db.commit()
        db.delete("products", "name = ?", ["Gone"])
        db.commit()
        row = db.fetch_one("SELECT * FROM products WHERE name = ?", ["Gone"])
        assert row is None

    def test_table_exists(self, db):
        assert db.table_exists("products") is True
        assert db.table_exists("nonexistent") is False

    def test_get_tables(self, db):
        tables = db.get_tables()
        assert "products" in tables

    def test_get_columns(self, db):
        cols = db.get_columns("products")
        col_names = [c["name"] for c in cols]
        assert "id" in col_names
        assert "name" in col_names
        assert "price" in col_names
        assert "active" in col_names

    def test_transaction_rollback(self, db):
        db.insert("products", {"name": "Kept"})
        db.commit()
        db.start_transaction()
        db.insert("products", {"name": "Discarded"})
        db.rollback()
        row = db.fetch_one("SELECT * FROM products WHERE name = ?", ["Discarded"])
        assert row is None
        row = db.fetch_one("SELECT * FROM products WHERE name = ?", ["Kept"])
        assert row is not None


# ── Adapter Base Class Contract ──────────────────────────────────


class TestAdapterContract:
    """Ensure all adapters implement the required interface methods."""

    @pytest.fixture(params=["postgresql", "mysql", "mssql", "firebird"])
    def adapter_class(self, request):
        return _DRIVERS[request.param]

    def test_has_connect(self, adapter_class):
        assert hasattr(adapter_class, "connect")

    def test_has_close(self, adapter_class):
        assert hasattr(adapter_class, "close")

    def test_has_execute(self, adapter_class):
        assert hasattr(adapter_class, "execute")

    def test_has_fetch(self, adapter_class):
        assert hasattr(adapter_class, "fetch")

    def test_has_fetch_one(self, adapter_class):
        assert hasattr(adapter_class, "fetch_one")

    def test_has_insert(self, adapter_class):
        assert hasattr(adapter_class, "insert")

    def test_has_update(self, adapter_class):
        assert hasattr(adapter_class, "update")

    def test_has_delete(self, adapter_class):
        assert hasattr(adapter_class, "delete")

    def test_has_start_transaction(self, adapter_class):
        assert hasattr(adapter_class, "start_transaction")

    def test_has_commit(self, adapter_class):
        assert hasattr(adapter_class, "commit")

    def test_has_rollback(self, adapter_class):
        assert hasattr(adapter_class, "rollback")

    def test_has_table_exists(self, adapter_class):
        assert hasattr(adapter_class, "table_exists")

    def test_has_get_tables(self, adapter_class):
        assert hasattr(adapter_class, "get_tables")

    def test_has_get_columns(self, adapter_class):
        assert hasattr(adapter_class, "get_columns")

    def test_has_get_database_type(self, adapter_class):
        assert hasattr(adapter_class, "get_database_type")

    def test_has_translate_sql(self, adapter_class):
        assert hasattr(adapter_class, "_translate_sql")

    def test_has_supports_returning(self, adapter_class):
        assert hasattr(adapter_class, "_supports_returning")


# ── Live Database Tests (skip if driver not available) ───────────


def _has_psycopg2():
    try:
        import psycopg2
        return True
    except ImportError:
        return False


def _has_mysql_connector():
    try:
        import mysql.connector
        return True
    except ImportError:
        return False


def _has_pymssql():
    try:
        import pymssql
        return True
    except ImportError:
        return False


def _has_fdb():
    try:
        import fdb
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _has_psycopg2(), reason="psycopg2 not installed")
class TestPostgreSQLLive:
    """Live PostgreSQL tests — require a running PostgreSQL instance.

    Set TINA4_TEST_POSTGRES_URL=postgresql://user:pass@host:port/db to run.
    """

    @pytest.fixture
    def db(self):
        import os
        url = os.environ.get("TINA4_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("TINA4_TEST_POSTGRES_URL not set")
        d = Database(url)
        d.execute("CREATE TABLE IF NOT EXISTS _tina4_test (id SERIAL PRIMARY KEY, name VARCHAR(100))")
        d.commit()
        yield d
        d.execute("DROP TABLE IF EXISTS _tina4_test")
        d.commit()
        d.close()

    def test_insert_and_fetch(self, db):
        result = db.insert("_tina4_test", {"name": "PostgresTest"})
        db.commit()
        assert result.last_id is not None
        row = db.fetch_one("SELECT * FROM _tina4_test WHERE name = %s", ["PostgresTest"])
        assert row is not None
        assert row["name"] == "PostgresTest"

    def test_database_type(self, db):
        assert db.get_database_type() == "postgresql"


@pytest.mark.skipif(not _has_mysql_connector(), reason="mysql-connector-python not installed")
class TestMySQLLive:
    """Live MySQL tests — require a running MySQL instance.

    Set TINA4_TEST_MYSQL_URL=mysql://user:pass@host:port/db to run.
    """

    @pytest.fixture
    def db(self):
        import os
        url = os.environ.get("TINA4_TEST_MYSQL_URL")
        if not url:
            pytest.skip("TINA4_TEST_MYSQL_URL not set")
        d = Database(url)
        d.execute("CREATE TABLE IF NOT EXISTS _tina4_test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100))")
        d.commit()
        yield d
        d.execute("DROP TABLE IF EXISTS _tina4_test")
        d.commit()
        d.close()

    def test_insert_and_fetch(self, db):
        result = db.insert("_tina4_test", {"name": "MySQLTest"})
        db.commit()
        assert result.last_id is not None
        row = db.fetch_one("SELECT * FROM _tina4_test WHERE name = %s", ["MySQLTest"])
        assert row is not None

    def test_database_type(self, db):
        assert db.get_database_type() == "mysql"


@pytest.mark.skipif(not _has_pymssql(), reason="pymssql not installed")
class TestMSSQLLive:
    """Live MSSQL tests — require a running SQL Server instance.

    Set TINA4_TEST_MSSQL_URL=mssql://user:pass@host:port/db to run.
    """

    @pytest.fixture
    def db(self):
        import os
        url = os.environ.get("TINA4_TEST_MSSQL_URL")
        if not url:
            pytest.skip("TINA4_TEST_MSSQL_URL not set")
        d = Database(url)
        d.execute(
            "IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '_tina4_test') "
            "CREATE TABLE _tina4_test (id INT IDENTITY(1,1) PRIMARY KEY, name VARCHAR(100))"
        )
        d.commit()
        yield d
        d.execute("DROP TABLE IF EXISTS _tina4_test")
        d.commit()
        d.close()

    def test_insert_and_fetch(self, db):
        result = db.insert("_tina4_test", {"name": "MSSQLTest"})
        db.commit()
        assert result.last_id is not None

    def test_database_type(self, db):
        assert db.get_database_type() == "mssql"


@pytest.mark.skipif(not _has_fdb(), reason="fdb not installed")
class TestFirebirdLive:
    """Live Firebird tests — require a running Firebird instance.

    Set TINA4_TEST_FIREBIRD_URL=firebird://user:pass@host:port/path/to/db.fdb to run.
    """

    @pytest.fixture
    def db(self):
        import os
        url = os.environ.get("TINA4_TEST_FIREBIRD_URL")
        if not url:
            pytest.skip("TINA4_TEST_FIREBIRD_URL not set")
        d = Database(url)
        yield d
        d.close()

    def test_database_type(self, db):
        assert db.get_database_type() == "firebird"
