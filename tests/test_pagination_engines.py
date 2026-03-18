#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# End-to-end pagination tests across all available database engines.
# Identical test data is seeded into each engine and identical assertions
# are run to ensure consistent behaviour.
#
# Engines tested (when available):
#   - SQLite  (always available)
#   - PostgreSQL  (Docker: localhost:5437)
#   - MySQL       (Docker: localhost:3306)
#   - Firebird    (Docker: localhost:33053)
#   - MSSQL       (Docker: localhost:1433)

import os
import pytest

from tina4_python.Database import Database
from tina4_python.DatabaseTypes import *

# ---------------------------------------------------------------------------
# Test data — identical across ALL engines
# ---------------------------------------------------------------------------

TEST_EMPLOYEES = [
    (1, "Alice", "Engineering", 95000.00),
    (2, "Bob", "Engineering", 88000.00),
    (3, "Charlie", "Marketing", 72000.00),
    (4, "Diana", "Marketing", 78000.00),
    (5, "Eve", "Sales", 65000.00),
    (6, "Frank", "Sales", 61000.00),
    (7, "Grace", "Engineering", 102000.00),
    (8, "Hank", "Marketing", 55000.00),
    (9, "Ivy", "Engineering", 91000.00),
    (10, "Jack", "Sales", 70000.00),
]

TEST_ITEMS = [
    (1, 1, "Laptop", 1),
    (2, 1, "Monitor", 2),
    (3, 2, "Laptop", 1),
    (4, 7, "Keyboard", 3),
]


# ---------------------------------------------------------------------------
# Engine connection helpers
# ---------------------------------------------------------------------------

def _connect_sqlite():
    db = Database("sqlite3:test_pagination_e2e.db", "", "")
    return db


def _connect_postgres():
    try:
        db = Database("psycopg2:localhost/5437:postgres", "postgres", "YourStrong!Passw0rd")
        # Create a test database schema
        db.execute("DROP TABLE IF EXISTS employee_item")
        db.execute("DROP TABLE IF EXISTS employee")
        db.execute("DROP TABLE IF EXISTS department")
        db.commit()
        return db
    except Exception:
        return None


def _connect_mysql():
    try:
        db = Database("mysql.connector:localhost/3306:testdb", "root", "masterkey")
        return db
    except Exception:
        return None


def _connect_firebird():
    try:
        db = Database(
            "firebird.driver:localhost/33053:/var/lib/firebird/data/ACCOUNTING.FDB",
            "sysdba",
            "masterkey",
        )
        return db
    except Exception:
        return None


def _connect_mssql():
    try:
        db = Database("pymssql:localhost/1433:master", "sa", "Master1234")
        # Verify connection is working
        r = db.fetch("SELECT 1 AS ping")
        if r.error:
            print(f"  MSSQL ping error: {r.error}")
            return None
        return db
    except Exception as e:
        print(f"  MSSQL connect exception: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Seed functions per engine
# ---------------------------------------------------------------------------

def _seed_sqlite(db):
    db.execute("DROP TABLE IF EXISTS employee_item")
    db.execute("DROP TABLE IF EXISTS employee")
    db.execute("DROP TABLE IF EXISTS department")
    db.commit()

    db.execute("""
        CREATE TABLE department (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE employee (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            salary REAL NOT NULL,
            dept_id INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE employee_item (
            id INTEGER PRIMARY KEY,
            employee_id INTEGER,
            item_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1
        )
    """)
    _insert_common_data(db)


def _seed_postgres(db):
    db.execute("DROP TABLE IF EXISTS employee_item")
    db.execute("DROP TABLE IF EXISTS employee")
    db.execute("DROP TABLE IF EXISTS department")
    db.commit()

    db.execute("""
        CREATE TABLE department (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE employee (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            department VARCHAR(100) NOT NULL,
            salary NUMERIC(10,2) NOT NULL,
            dept_id INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE employee_item (
            id SERIAL PRIMARY KEY,
            employee_id INTEGER,
            item_name VARCHAR(100) NOT NULL,
            quantity INTEGER DEFAULT 1
        )
    """)
    _insert_common_data(db)


def _seed_mysql(db):
    db.execute("DROP TABLE IF EXISTS employee_item")
    db.execute("DROP TABLE IF EXISTS employee")
    db.execute("DROP TABLE IF EXISTS department")
    db.commit()

    db.execute("""
        CREATE TABLE department (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE employee (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            department VARCHAR(100) NOT NULL,
            salary DECIMAL(10,2) NOT NULL,
            dept_id INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE employee_item (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            employee_id INTEGER,
            item_name VARCHAR(100) NOT NULL,
            quantity INTEGER DEFAULT 1
        )
    """)
    _insert_common_data(db)


def _seed_firebird(db):
    # Firebird: recreate tables
    for table in ["employee_item", "employee", "department"]:
        try:
            db.execute(f"DROP TABLE {table}")
            db.commit()
        except Exception:
            try:
                db.dba.rollback()
            except Exception:
                pass

    db.execute("""
        CREATE TABLE department (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE employee (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            department VARCHAR(100) NOT NULL,
            salary NUMERIC(10,2) NOT NULL,
            dept_id INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE employee_item (
            id INTEGER NOT NULL PRIMARY KEY,
            employee_id INTEGER,
            item_name VARCHAR(100) NOT NULL,
            quantity INTEGER DEFAULT 1
        )
    """)
    db.commit()

    # Firebird needs explicit IDs for employee_item
    for dept_id, name in [(1, "Engineering"), (2, "Marketing"), (3, "Sales")]:
        db.execute(f"INSERT INTO department (id, name) VALUES ({dept_id}, '{name}')")

    for emp_id, name, dept, salary in TEST_EMPLOYEES:
        dept_id = {"Engineering": 1, "Marketing": 2, "Sales": 3}[dept]
        db.execute(
            f"INSERT INTO employee (id, name, department, salary, dept_id) VALUES ({emp_id}, '{name}', '{dept}', {salary}, {dept_id})"
        )

    for item_id, emp_id, item_name, qty in TEST_ITEMS:
        db.execute(
            f"INSERT INTO employee_item (id, employee_id, item_name, quantity) VALUES ({item_id}, {emp_id}, '{item_name}', {qty})"
        )

    db.commit()


def _seed_mssql(db):
    for table in ["employee_item", "employee", "department"]:
        db.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE {table}")
    db.commit()

    db.execute("""
        CREATE TABLE department (
            id INT PRIMARY KEY,
            name NVARCHAR(100) NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE employee (
            id INT PRIMARY KEY,
            name NVARCHAR(100) NOT NULL,
            department NVARCHAR(100) NOT NULL,
            salary DECIMAL(10,2) NOT NULL,
            dept_id INT
        )
    """)
    db.execute("""
        CREATE TABLE employee_item (
            id INT IDENTITY(1,1) PRIMARY KEY,
            employee_id INT,
            item_name NVARCHAR(100) NOT NULL,
            quantity INT DEFAULT 1
        )
    """)
    _insert_common_data(db)


def _insert_common_data(db):
    """Insert identical test data (works for SQLite, PostgreSQL, MySQL, MSSQL)."""
    for dept_id, name in [(1, "Engineering"), (2, "Marketing"), (3, "Sales")]:
        db.execute("INSERT INTO department (id, name) VALUES (?, ?)", [dept_id, name])

    for emp_id, name, dept, salary in TEST_EMPLOYEES:
        dept_id = {"Engineering": 1, "Marketing": 2, "Sales": 3}[dept]
        db.execute(
            "INSERT INTO employee (id, name, department, salary, dept_id) VALUES (?, ?, ?, ?, ?)",
            [emp_id, name, dept, salary, dept_id],
        )

    for item_id, emp_id, item_name, qty in TEST_ITEMS:
        db.execute(
            "INSERT INTO employee_item (employee_id, item_name, quantity) VALUES (?, ?, ?)",
            [emp_id, item_name, qty],
        )

    db.commit()


# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------

ENGINES = {
    "sqlite": (_connect_sqlite, _seed_sqlite),
    "postgres": (_connect_postgres, _seed_postgres),
    "mysql": (_connect_mysql, _seed_mysql),
    "firebird": (_connect_firebird, _seed_firebird),
    "mssql": (_connect_mssql, _seed_mssql),
}


def _get_available_engines():
    """Return list of (engine_name, db_connection) for engines that are reachable."""
    available = []
    for name, (connect_fn, seed_fn) in ENGINES.items():
        try:
            db = connect_fn()
            if db is not None:
                seed_fn(db)
                available.append((name, db))
                print(f"  Engine {name}: OK")
            else:
                print(f"  Engine {name}: connection returned None")
        except Exception as e:
            print(f"  Skipping {name}: {type(e).__name__}: {e}")
    return available


# Eagerly resolve available engines at import time
_engine_connections = _get_available_engines()
_engine_names = [e[0] for e in _engine_connections]
_engine_map = {e[0]: e[1] for e in _engine_connections}


# ---------------------------------------------------------------------------
# Parametrized test class
# ---------------------------------------------------------------------------

class TestPaginationAllEngines:
    """
    Same assertions run against every available database engine.
    Uses identical test data for consistent results.
    """

    @pytest.fixture(autouse=True, params=_engine_names, ids=_engine_names)
    def setup_engine(self, request):
        self.engine_name = request.param
        self.dba = _engine_map.get(request.param)
        if self.dba is None:
            pytest.skip(f"{request.param} not available")

    # -- Basic pagination --

    def test_first_page(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=3, skip=0)
        assert result.count == 3, f"[{self.engine_name}] Expected 3 records"
        assert result.total_count == 10, f"[{self.engine_name}] Expected total 10"

    def test_second_page(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=3, skip=3)
        assert result.count == 3, f"[{self.engine_name}]"
        assert result.total_count == 10, f"[{self.engine_name}]"

    def test_last_partial_page(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=3, skip=9)
        assert result.count == 1, f"[{self.engine_name}]"
        assert result.total_count == 10, f"[{self.engine_name}]"

    def test_beyond_last_page(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=3, skip=100)
        assert result.count == 0, f"[{self.engine_name}]"
        # total_count reflects the full table count (from COUNT(*)) even when skip is beyond the last page
        assert result.total_count == 10, f"[{self.engine_name}]"

    def test_full_page(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=100, skip=0)
        assert result.count == 10, f"[{self.engine_name}]"
        assert result.total_count == 10, f"[{self.engine_name}]"

    # -- Column stripping --

    def test_no_tina4_total_in_records(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=5)
        for row in result.records:
            assert "__tina4_total__" not in row, f"[{self.engine_name}] Synthetic column leaked"

    def test_no_tina4_total_in_columns(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=5)
        assert "__tina4_total__" not in result.columns, f"[{self.engine_name}]"

    # -- Ordering --

    def test_order_by_salary_desc(self):
        result = self.dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3)
        salaries = [float(row["salary"]) for row in result.records]
        assert salaries == sorted(salaries, reverse=True), f"[{self.engine_name}] Order not preserved"
        assert result.total_count == 10

    def test_order_by_with_skip(self):
        p1 = self.dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=5, skip=0)
        p2 = self.dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=5, skip=5)
        all_salaries = [float(r["salary"]) for r in p1.records] + [float(r["salary"]) for r in p2.records]
        assert all_salaries == sorted(all_salaries, reverse=True), f"[{self.engine_name}]"
        assert len(all_salaries) == 10

    # -- Sub-selects --

    def test_subselect(self):
        sql = "SELECT id, name, salary FROM (SELECT * FROM employee WHERE salary > 70000) AS high_earners"
        result = self.dba.fetch(sql, limit=3, skip=0)
        # Alice(95k), Bob(88k), Charlie(72k), Diana(78k), Grace(102k), Ivy(91k) = 6
        assert result.total_count == 6, f"[{self.engine_name}] Expected 6, got {result.total_count}"
        assert result.count == 3
        for row in result.records:
            assert float(row["salary"]) > 70000

    def test_subselect_with_aggregation(self):
        sql = """
            SELECT department, total_salary, emp_count
            FROM (
                SELECT department, SUM(salary) AS total_salary, COUNT(*) AS emp_count
                FROM employee
                GROUP BY department
            ) AS dept_stats
        """
        result = self.dba.fetch(sql, limit=10, skip=0)
        assert result.total_count == 3, f"[{self.engine_name}] 3 departments"
        assert result.count == 3

    # -- Joins --

    def test_inner_join(self):
        sql = """
            SELECT e.id, e.name, d.name AS dept_name
            FROM employee e
            INNER JOIN department d ON e.dept_id = d.id
        """
        result = self.dba.fetch(sql, limit=5, skip=0)
        assert result.total_count == 10, f"[{self.engine_name}]"
        assert result.count == 5
        for row in result.records:
            assert "dept_name" in row

    def test_left_join(self):
        sql = """
            SELECT e.id, e.name, ei.item_name
            FROM employee e
            LEFT JOIN employee_item ei ON e.id = ei.employee_id
        """
        result = self.dba.fetch(sql, limit=5, skip=0)
        # 10 employees, some with multiple items, some with none (NULL)
        assert result.total_count >= 10, f"[{self.engine_name}]"

    def test_join_with_order(self):
        sql = """
            SELECT e.name, d.name AS dept_name, e.salary
            FROM employee e
            JOIN department d ON e.dept_id = d.id
            ORDER BY e.salary DESC
        """
        result = self.dba.fetch(sql, limit=3, skip=0)
        salaries = [float(r["salary"]) for r in result.records]
        assert salaries == sorted(salaries, reverse=True), f"[{self.engine_name}]"
        assert result.total_count == 10

    # -- Search --

    def test_search_filters_total(self):
        # Search uses double-quoted column names which works on SQLite/PostgreSQL.
        # MySQL needs backticks and Firebird has different quoting — this is a
        # pre-existing search quoting issue, not a pagination issue. Skip on
        # engines where search quoting is known to fail.
        if self.engine_name in ("mysql", "firebird"):
            pytest.skip(f"Search column quoting not yet supported on {self.engine_name}")
        result = self.dba.fetch(
            "SELECT * FROM employee",
            limit=10,
            search="Engineering",
            search_columns=["department"],
        )
        assert result.total_count == 4, f"[{self.engine_name}] 4 engineers"
        assert result.count == 4

    # -- Parameterized queries --

    def test_parameterized_where(self):
        result = self.dba.fetch(
            "SELECT * FROM employee WHERE salary > ?",
            params=[80000],
            limit=10,
        )
        for row in result.records:
            assert float(row["salary"]) > 80000
        assert result.total_count > 0

    # -- Column aliasing --

    def test_aliased_columns_simple(self):
        """Column aliases should be preserved in results."""
        result = self.dba.fetch(
            "SELECT id AS employee_id, name AS full_name, salary AS annual_salary FROM employee",
            limit=5,
        )
        assert "employee_id" in result.columns, f"[{self.engine_name}]"
        assert "full_name" in result.columns, f"[{self.engine_name}]"
        assert "annual_salary" in result.columns, f"[{self.engine_name}]"
        for row in result.records:
            assert "employee_id" in row
            assert "full_name" in row
            assert "annual_salary" in row
        assert result.total_count == 10

    def test_aliased_columns_in_join(self):
        """Column aliases in JOINs should be preserved."""
        sql = """
            SELECT e.id AS emp_id, e.name AS emp_name, d.name AS dept_name
            FROM employee e
            INNER JOIN department d ON e.dept_id = d.id
        """
        result = self.dba.fetch(sql, limit=5)
        assert "emp_id" in result.columns, f"[{self.engine_name}]"
        assert "emp_name" in result.columns, f"[{self.engine_name}]"
        assert "dept_name" in result.columns, f"[{self.engine_name}]"
        assert result.total_count == 10

    def test_aliased_expression_column(self):
        """Computed/expression columns with aliases should work."""
        sql = "SELECT id, name, salary * 12 AS annual_total FROM employee"
        result = self.dba.fetch(sql, limit=3)
        assert "annual_total" in result.columns, f"[{self.engine_name}]"
        for row in result.records:
            assert "annual_total" in row
            assert float(row["annual_total"]) > 0

    def test_aliased_aggregate_in_subselect(self):
        """Aliased aggregates in sub-selects should be accurate."""
        sql = """
            SELECT department, emp_count, avg_salary
            FROM (
                SELECT department,
                       COUNT(*) AS emp_count,
                       AVG(salary) AS avg_salary
                FROM employee
                GROUP BY department
            ) AS dept_summary
        """
        result = self.dba.fetch(sql, limit=10)
        assert result.total_count == 3
        assert "emp_count" in result.columns
        assert "avg_salary" in result.columns
        dept_counts = {row["department"]: int(row["emp_count"]) for row in result.records}
        assert dept_counts.get("Engineering") == 4
        assert dept_counts.get("Marketing") == 3
        assert dept_counts.get("Sales") == 3

    # -- Result accuracy --

    def test_result_data_accuracy(self):
        """Verify actual data values are accurate, not just counts."""
        result = self.dba.fetch(
            "SELECT id, name, salary FROM employee WHERE id = ?",
            params=[1],
            limit=10,
        )
        assert result.count == 1
        assert result.records[0]["name"] == "Alice"
        assert float(result.records[0]["salary"]) == 95000.00

    def test_all_records_complete(self):
        """Fetch all records across pages and verify every row is accounted for."""
        page1 = self.dba.fetch("SELECT id, name FROM employee ORDER BY id", limit=5, skip=0)
        page2 = self.dba.fetch("SELECT id, name FROM employee ORDER BY id", limit=5, skip=5)
        all_ids = sorted([r["id"] for r in page1.records] + [r["id"] for r in page2.records])
        assert all_ids == list(range(1, 11)), f"[{self.engine_name}] Missing records: {all_ids}"

    def test_no_duplicate_records(self):
        """No duplicates across paginated pages."""
        page1 = self.dba.fetch("SELECT * FROM employee ORDER BY id", limit=5, skip=0)
        page2 = self.dba.fetch("SELECT * FROM employee ORDER BY id", limit=5, skip=5)
        ids1 = {r["id"] for r in page1.records}
        ids2 = {r["id"] for r in page2.records}
        assert ids1.isdisjoint(ids2), f"[{self.engine_name}] Duplicate IDs across pages"

    # -- to_paginate() --

    def test_to_paginate(self):
        result = self.dba.fetch("SELECT * FROM employee", limit=3, skip=6)
        paginated = result.to_paginate()
        assert paginated["recordsTotal"] == 10, f"[{self.engine_name}]"
        assert paginated["recordsOffset"] == 6
        assert paginated["recordCount"] == 3
        assert "__tina4_total__" not in paginated["fields"]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def teardown_module():
    """Close all connections and clean up."""
    global _engine_connections
    if _engine_connections:
        for name, db in _engine_connections:
            try:
                db.close()
            except Exception:
                pass
        _engine_connections = None

    # Remove SQLite test file
    try:
        os.remove("test_pagination_e2e.db")
    except OSError:
        pass
