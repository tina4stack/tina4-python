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
import os
import socket

import pytest
from unittest.mock import patch
from tina4_python.database import Database
from tina4_python.database.connection import _DRIVERS


# ── Live PostgreSQL connection config (canonical TINA4_TEST_PG_* convention) ──
# Matches the rest of the suite (test_postgres_create_table.py,
# test_postgres_uuid_pk.py, ...): a real container at localhost:55432,
# user/pass/db all "tina4". Skips automatically when nothing is listening.

PG_HOST = os.environ.get("TINA4_TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TINA4_TEST_PG_PORT", "55432"))
PG_USER = os.environ.get("TINA4_TEST_PG_USER", "tina4")
PG_PASS = os.environ.get("TINA4_TEST_PG_PASS", "tina4")
PG_DB = os.environ.get("TINA4_TEST_PG_DB", "tina4")


def _pg_reachable() -> bool:
    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _pg_url() -> str:
    return f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"


# ── Live MySQL connection config (#262 — now provisioned in CI + local infra) ──
# Mirrors the PG block: a real container at localhost:3306, user/pass "tina4",
# db "tina4_test". Skips automatically when nothing is listening; under
# TINA4_REQUIRE_SERVICES the conftest gate turns that skip into a failure
# (MySQL is in the provisioned keyword list since 3.13.44).
MYSQL_HOST = os.environ.get("TINA4_TEST_MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("TINA4_TEST_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("TINA4_TEST_MYSQL_USER", "tina4")
MYSQL_PASS = os.environ.get("TINA4_TEST_MYSQL_PASS", "tina4")
MYSQL_DB = os.environ.get("TINA4_TEST_MYSQL_DB", "tina4_test")

MSSQL_HOST = os.environ.get("TINA4_TEST_MSSQL_HOST", "localhost")
MSSQL_PORT = int(os.environ.get("TINA4_TEST_MSSQL_PORT", "1433"))
MSSQL_USER = os.environ.get("TINA4_TEST_MSSQL_USER", "sa")
MSSQL_PASS = os.environ.get("TINA4_TEST_MSSQL_PASS", "TinaSQL123!Secure")
MSSQL_DB = os.environ.get("TINA4_TEST_MSSQL_DB", "tina4_test")


def _mysql_reachable() -> bool:
    try:
        with socket.create_connection((MYSQL_HOST, MYSQL_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _mssql_reachable() -> bool:
    try:
        with socket.create_connection((MSSQL_HOST, MSSQL_PORT), timeout=1.0):
            return True
    except OSError:
        return False


# ── Driver Registration ──────────────────────────────────────────


class TestDriverRegistration:
    """All drivers are registered and discoverable by URL scheme."""

    def test_sqlite_registered(self):
        assert "sqlite" in _DRIVERS

    def test_postgresql_registered(self):
        assert "postgresql" in _DRIVERS

    def test_postgres_alias_registered(self):
        assert "postgres" in _DRIVERS

    def test_pgsql_alias_registered(self):
        # pgsql:// is the PDO / Laravel / Doctrine scheme name (issue #58)
        assert "pgsql" in _DRIVERS
        assert _DRIVERS["pgsql"] is _DRIVERS["postgres"]

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


# ── Connection URL → Adapter Selection ───────────────────────────


class TestConnectionURLAdapterSelection:
    """The Database class routes a connection URL scheme to the right
    adapter class. This is real framework logic (``_create_adapter`` reads
    the URL scheme and looks it up in ``_DRIVERS``) — exercised here without
    needing a live server for engines that aren't provisioned.
    """

    def test_postgresql_url_selects_postgres_adapter(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        db = Database.__new__(Database)
        db.url = "postgresql://alice:secret@db.example.com:5433/myapp"
        db.username = ""
        db.password = ""
        assert db._create_adapter().__class__ is PostgreSQLAdapter

    def test_postgres_alias_url_selects_same_adapter(self):
        from tina4_python.database.postgres import PostgreSQLAdapter
        db = Database.__new__(Database)
        db.url = "postgres://alice:secret@db.example.com:5433/myapp"
        db.username = ""
        db.password = ""
        assert db._create_adapter().__class__ is PostgreSQLAdapter

    def test_mysql_url_selects_mysql_adapter(self):
        from tina4_python.database.mysql import MySQLAdapter
        db = Database.__new__(Database)
        db.url = "mysql://root:pass123@mysql-server:3307/shop"
        db.username = ""
        db.password = ""
        assert db._create_adapter().__class__ is MySQLAdapter

    def test_mssql_url_selects_mssql_adapter(self):
        from tina4_python.database.mssql import MSSQLAdapter
        db = Database.__new__(Database)
        db.url = "mssql://sa:MyPass@mssql-host:1434/warehouse"
        db.username = ""
        db.password = ""
        assert db._create_adapter().__class__ is MSSQLAdapter

    def test_firebird_url_selects_firebird_adapter(self):
        from tina4_python.database.firebird import FirebirdAdapter
        db = Database.__new__(Database)
        db.url = "firebird://SYSDBA:masterkey@fbhost:3050/var/lib/firebird/data/app.fdb"
        db.username = ""
        db.password = ""
        assert db._create_adapter().__class__ is FirebirdAdapter

    @pytest.mark.skipif(not _pg_reachable(), reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT}")
    def test_postgresql_url_connects_live(self):
        """A real PostgreSQL URL connects and the live adapter reports its type."""
        db = Database(_pg_url())
        try:
            assert db.get_database_type() == "postgresql"
            # The connection is genuinely usable — round-trip a trivial query.
            row = db.fetch_one("SELECT 1 AS one")
            assert row["one"] == 1
        finally:
            db.close()

    def test_sqlite_url_connects_and_reports_type(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(f"sqlite:///{db_path}")
        try:
            assert db.get_database_type() == "sqlite"
            # The file path was parsed and a live connection opened — prove it
            # works end to end with a real query.
            row = db.fetch_one("SELECT 1 AS one")
            assert row["one"] == 1
        finally:
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
    """Every adapter must implement the full DatabaseAdapter interface.

    This is a single consolidated rename/parity guard: it asserts the WHOLE
    expected method set exists on each adapter in one loop, so a future rename
    or dropped method fails loudly across all four engines. The real BEHAVIOUR
    of these methods is exercised against live engines elsewhere:
    ``TestSQLiteCRUD`` (insert/fetch/fetch_one/update/delete/commit/rollback/
    start_transaction/table_exists/get_tables/get_columns on live SQLite) and
    ``TestPostgreSQLLive`` (the same round-trip against a live PostgreSQL);
    ``_translate_sql`` / ``_supports_returning`` / ``get_database_type`` are
    covered by the per-dialect translation tests above.
    """

    # The complete interface the framework relies on (see DatabaseAdapter).
    INTERFACE = (
        "connect", "close", "execute", "execute_many",
        "fetch", "fetch_one", "insert", "update", "delete",
        "start_transaction", "commit", "rollback",
        "table_exists", "get_tables", "get_columns",
        "get_database_type", "_translate_sql", "_supports_returning",
    )

    @pytest.mark.parametrize("scheme", ["postgresql", "mysql", "mssql", "firebird"])
    def test_implements_full_interface(self, scheme):
        adapter_class = _DRIVERS[scheme]
        missing = [m for m in self.INTERFACE if not callable(getattr(adapter_class, m, None))]
        assert not missing, f"{adapter_class.__name__} missing methods: {missing}"


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


def _has_firebird_driver():
    """Either Firebird driver the adapter accepts, in its own preference order.

    The adapter tries `firebird.driver` FIRST and only falls back to legacy
    `fdb`. This gate used to import `fdb` alone, so the live Firebird class
    skipped green on any host that had the MODERN driver installed - which is
    what `pyproject.toml`'s `firebird` extra actually installs.
    """
    try:
        import firebird.driver  # noqa: F401
        return True
    except ImportError:
        try:
            import fdb  # noqa: F401
            return True
        except ImportError:
            return False


@pytest.mark.skipif(
    not (_has_psycopg2() and _pg_reachable()),
    reason=f"PostgreSQL not reachable at {PG_HOST}:{PG_PORT} (or psycopg2 missing)",
)
class TestPostgreSQLLive:
    """Live PostgreSQL round-trips against the provisioned container.

    Uses the canonical TINA4_TEST_PG_* convention (default localhost:55432,
    user/pass/db all "tina4") shared with the rest of the PG test suite — so
    this RUNS in CI (PostgreSQL is provisioned) rather than skipping. Older
    callers can still point TINA4_TEST_PG_* at a different instance.
    """

    @pytest.fixture
    def db(self):
        d = Database(_pg_url())
        d.execute("DROP TABLE IF EXISTS _tina4_drv_test")
        d.execute(
            "CREATE TABLE _tina4_drv_test "
            "(id SERIAL PRIMARY KEY, name VARCHAR(100), price NUMERIC(10,2))"
        )
        d.commit()
        yield d
        d.execute("DROP TABLE IF EXISTS _tina4_drv_test")
        d.commit()
        d.close()

    def test_database_type(self, db):
        assert db.get_database_type() == "postgresql"

    def test_insert_returns_real_serial_id(self, db):
        # SERIAL PK is auto-generated server-side; the adapter must surface it.
        first = db.insert("_tina4_drv_test", {"name": "Alpha", "price": 1.50})
        db.commit()
        second = db.insert("_tina4_drv_test", {"name": "Beta", "price": 2.50})
        db.commit()
        assert first.last_id == 1
        assert second.last_id == 2
        assert first.affected_rows == 1

    def test_fetch_one_round_trips_native_types(self, db):
        db.insert("_tina4_drv_test", {"name": "Gamma", "price": 9.99})
        db.commit()
        row = db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["Gamma"])
        assert row is not None
        assert row["name"] == "Gamma"
        # NUMERIC comes back as a real Decimal, not a string.
        from decimal import Decimal
        assert row["price"] == Decimal("9.99")

    def test_fetch_paginates_and_counts(self, db):
        db.insert("_tina4_drv_test", [
            {"name": "r1", "price": 1.0},
            {"name": "r2", "price": 2.0},
            {"name": "r3", "price": 3.0},
        ])
        db.commit()
        result = db.fetch("SELECT * FROM _tina4_drv_test ORDER BY id", limit=2)
        assert len(result.records) == 2
        assert result.count == 3

    def test_update_and_delete(self, db):
        db.insert("_tina4_drv_test", {"name": "Old", "price": 1.0})
        db.commit()
        db.update("_tina4_drv_test", {"name": "New"}, "name = %s", ["Old"])
        db.commit()
        assert db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["Old"]) is None
        assert db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["New"]) is not None
        db.delete("_tina4_drv_test", "name = %s", ["New"])
        db.commit()
        assert db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["New"]) is None

    def test_introspection_against_live_schema(self, db):
        assert db.table_exists("_tina4_drv_test") is True
        assert db.table_exists("_tina4_definitely_not_here") is False
        assert "_tina4_drv_test" in db.get_tables()
        col_names = [c["name"] for c in db.get_columns("_tina4_drv_test")]
        assert "id" in col_names
        assert "name" in col_names
        assert "price" in col_names

    def test_transaction_rollback_discards_writes(self, db):
        db.insert("_tina4_drv_test", {"name": "Kept", "price": 1.0})
        db.commit()
        db.start_transaction()
        db.insert("_tina4_drv_test", {"name": "Discarded", "price": 2.0})
        db.rollback()
        assert db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["Discarded"]) is None
        assert db.fetch_one("SELECT * FROM _tina4_drv_test WHERE name = %s", ["Kept"]) is not None


@pytest.mark.skipif(
    not (_has_mysql_connector() and _mysql_reachable()),
    reason=f"MySQL not reachable at {MYSQL_HOST}:{MYSQL_PORT} (or mysql-connector-python not installed)",
)
class TestMySQLLive:
    """Live MySQL round-trips against the provisioned container (#262).

    Defaults to localhost:3306 / tina4 / tina4_test; override via the
    TINA4_TEST_MYSQL_* env vars. Skips when nothing is listening — under
    TINA4_REQUIRE_SERVICES the conftest gate turns that into a failure.
    """

    @pytest.fixture
    def db(self):
        d = Database(f"mysql://{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}", MYSQL_USER, MYSQL_PASS)
        d.execute("DROP TABLE IF EXISTS _tina4_test")
        d.execute("CREATE TABLE _tina4_test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), active TINYINT)")
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

    def test_boolean_round_trips_as_0_1(self, db):
        # Locks in the cross-framework bind contract (#262): a raw Python bool
        # binds as 1/0, never crashing or stringifying. Mirrors the SQLite,
        # Ruby (mysql2) and Node (mysql2) boolean-coercion behaviour.
        db.execute("INSERT INTO _tina4_test (name, active) VALUES (%s, %s)", ["on", True])
        db.execute("INSERT INTO _tina4_test (name, active) VALUES (%s, %s)", ["off", False])
        db.commit()
        rows = db.fetch("SELECT active FROM _tina4_test ORDER BY id").records
        assert [r["active"] for r in rows] == [1, 0]

    def test_database_type(self, db):
        assert db.get_database_type() == "mysql"


@pytest.mark.skipif(
    not (_has_pymssql() and _mssql_reachable()),
    reason=f"MSSQL not reachable at {MSSQL_HOST}:{MSSQL_PORT} (or pymssql not installed)",
)
class TestMSSQLLive:
    """Live MSSQL round-trips against the provisioned container (#262).

    Defaults to localhost:1433 / sa / tina4_test; override via the
    TINA4_TEST_MSSQL_* env vars. Skips when nothing is listening — under
    TINA4_REQUIRE_SERVICES the conftest gate turns that into a failure.
    """

    @pytest.fixture
    def db(self):
        d = Database(f"mssql://{MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DB}", MSSQL_USER, MSSQL_PASS)
        d.execute("IF OBJECT_ID('_tina4_test','U') IS NOT NULL DROP TABLE _tina4_test")
        d.execute("CREATE TABLE _tina4_test (id INT IDENTITY(1,1) PRIMARY KEY, name VARCHAR(100), active BIT)")
        d.commit()
        yield d
        d.execute("IF OBJECT_ID('_tina4_test','U') IS NOT NULL DROP TABLE _tina4_test")
        d.commit()
        d.close()

    def test_insert_and_fetch(self, db):
        result = db.insert("_tina4_test", {"name": "MSSQLTest"})
        db.commit()
        assert result.last_id is not None

    def test_boolean_round_trips_as_bit(self, db):
        # Locks in the bind contract (#262): a raw Python bool binds to a BIT
        # column without stringifying to '' (the PG/MSSQL footgun). Mirrors the
        # Ruby (tiny_tds) boolean-coercion fix shipped in the same release.
        db.execute("INSERT INTO _tina4_test (name, active) VALUES (%s, %s)", ["on", True])
        db.execute("INSERT INTO _tina4_test (name, active) VALUES (%s, %s)", ["off", False])
        db.commit()
        rows = db.fetch("SELECT active FROM _tina4_test ORDER BY id").records
        assert [bool(r["active"]) for r in rows] == [True, False]

    def test_count_probe_survives_trailing_order_by(self, db):
        # Regression (#262): the row-count probe wraps the query in
        # SELECT COUNT(*) FROM (<sql>); SQL Server rejects an ORDER BY in that
        # derived-table subquery, so a query ending in ORDER BY silently
        # reported count=0 (rows were still correct). The probe now strips a
        # trailing top-level ORDER BY. This bug lived in the Python master too,
        # not only the PHP/Ruby/Node mirrors. Real MSSQL, no mocks.
        for i in range(3):
            db.execute("INSERT INTO _tina4_test (name) VALUES (%s)", [f"row{i}"])
        db.commit()
        ordered = db.fetch("SELECT id, name FROM _tina4_test ORDER BY id")
        assert ordered.count == 3 and len(ordered.records) == 3
        # paginated + ORDER BY keeps the ORDER BY for OFFSET/FETCH; count is full total
        paged = db.fetch("SELECT id, name FROM _tina4_test ORDER BY id", limit=2)
        assert paged.count == 3 and len(paged.records) == 2

    def test_database_type(self, db):
        assert db.get_database_type() == "mssql"


@pytest.mark.skipif(
    not _has_firebird_driver(),
    reason="neither firebird-driver nor fdb installed",
)
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
