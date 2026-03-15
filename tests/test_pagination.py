#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# Comprehensive pagination tests — covers window-function approach,
# sub-selects, joins, ordering, edge cases, and engine-specific SQL generation.

import pytest
from unittest.mock import patch, MagicMock

from tina4_python.Database import Database
from tina4_python.DatabaseTypes import *


# ---------------------------------------------------------------------------
# Shared test data setup — identical across all engines
# ---------------------------------------------------------------------------

TEST_RECORDS = [
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


@pytest.fixture(scope="module")
def dba():
    """SQLite database seeded with consistent test data for pagination tests."""
    db = Database("sqlite3:test_pagination.db", "", "")

    # Create tables
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
    db.execute("INSERT INTO department (id, name) VALUES (1, 'Engineering')")
    db.execute("INSERT INTO department (id, name) VALUES (2, 'Marketing')")
    db.execute("INSERT INTO department (id, name) VALUES (3, 'Sales')")

    db.execute("""
        CREATE TABLE employee (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            salary REAL NOT NULL,
            dept_id INTEGER REFERENCES department(id)
        )
    """)

    db.execute("""
        CREATE TABLE employee_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER REFERENCES employee(id),
            item_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1
        )
    """)

    for emp_id, name, dept, salary in TEST_RECORDS:
        dept_id = {"Engineering": 1, "Marketing": 2, "Sales": 3}[dept]
        db.execute(
            "INSERT INTO employee (id, name, department, salary, dept_id) VALUES (?, ?, ?, ?, ?)",
            [emp_id, name, dept, salary, dept_id],
        )

    # Items for join tests
    db.execute("INSERT INTO employee_item (employee_id, item_name, quantity) VALUES (1, 'Laptop', 1)")
    db.execute("INSERT INTO employee_item (employee_id, item_name, quantity) VALUES (1, 'Monitor', 2)")
    db.execute("INSERT INTO employee_item (employee_id, item_name, quantity) VALUES (2, 'Laptop', 1)")
    db.execute("INSERT INTO employee_item (employee_id, item_name, quantity) VALUES (7, 'Keyboard', 3)")

    db.commit()
    yield db
    db.close()

    import os
    try:
        os.remove("test_pagination.db")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Basic pagination
# ---------------------------------------------------------------------------

class TestBasicPagination:
    def test_first_page(self, dba):
        """First page of 3 should return 3 records with total 10."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=0)
        assert result.count == 3
        assert result.total_count == 10

    def test_second_page(self, dba):
        """Second page should skip first 3 and return next 3."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=3)
        assert result.count == 3
        assert result.total_count == 10

    def test_last_partial_page(self, dba):
        """Last page may have fewer records than limit."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=9)
        assert result.count == 1
        assert result.total_count == 10

    def test_beyond_last_page(self, dba):
        """Skipping past all records returns empty but total_count reflects real count."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=100)
        assert result.count == 0
        assert result.total_count == 10

    def test_limit_larger_than_data(self, dba):
        """If limit is larger than dataset, return all records."""
        result = dba.fetch("SELECT * FROM employee", limit=100, skip=0)
        assert result.count == 10
        assert result.total_count == 10

    def test_single_record_limit(self, dba):
        """Limit=1 should return exactly one record with correct total."""
        result = dba.fetch("SELECT * FROM employee", limit=1, skip=0)
        assert result.count == 1
        assert result.total_count == 10


# ---------------------------------------------------------------------------
# __tina4_total__ column stripping
# ---------------------------------------------------------------------------

class TestColumnStripping:
    def test_total_column_not_in_records(self, dba):
        """The synthetic __tina4_total__ column must not appear in records."""
        result = dba.fetch("SELECT * FROM employee", limit=5)
        for row in result.records:
            assert "__tina4_total__" not in row

    def test_total_column_not_in_columns(self, dba):
        """The synthetic column must not appear in the columns list."""
        result = dba.fetch("SELECT * FROM employee", limit=5)
        assert "__tina4_total__" not in result.columns

    def test_columns_match_original(self, dba):
        """Returned columns should match the original query columns."""
        result = dba.fetch("SELECT id, name, salary FROM employee", limit=5)
        assert result.columns == ["id", "name", "salary"]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_order_by_salary_desc(self, dba):
        """ORDER BY should be respected in paginated results."""
        result = dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3)
        salaries = [row["salary"] for row in result.records]
        assert salaries == sorted(salaries, reverse=True)
        assert result.total_count == 10

    def test_order_by_name_asc(self, dba):
        """Alphabetical ordering should work with pagination."""
        result = dba.fetch("SELECT * FROM employee ORDER BY name ASC", limit=5)
        names = [row["name"] for row in result.records]
        assert names == sorted(names)
        assert result.total_count == 10

    def test_order_by_with_skip(self, dba):
        """ORDER BY + SKIP should return correct page in order."""
        page1 = dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3, skip=0)
        page2 = dba.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3, skip=3)

        all_salaries = [r["salary"] for r in page1.records] + [r["salary"] for r in page2.records]
        assert all_salaries == sorted(all_salaries, reverse=True)

    def test_multi_column_order(self, dba):
        """Multi-column ORDER BY should work correctly."""
        result = dba.fetch("SELECT * FROM employee ORDER BY department, salary DESC", limit=10)
        assert result.total_count == 10
        assert result.count == 10


# ---------------------------------------------------------------------------
# Sub-selects
# ---------------------------------------------------------------------------

class TestSubSelects:
    def test_subselect_in_from(self, dba):
        """Pagination should work on sub-selects."""
        sql = "SELECT id, name, salary FROM (SELECT * FROM employee WHERE salary > 70000) AS high_earners"
        result = dba.fetch(sql, limit=3, skip=0)
        assert result.total_count == 6  # Alice(95k), Bob(88k), Diana(78k), Charlie(72k), Grace(102k), Ivy(91k)
        assert result.count == 3
        for row in result.records:
            assert row["salary"] > 70000

    def test_subselect_with_order(self, dba):
        """Sub-select with ORDER BY should paginate correctly."""
        sql = "SELECT * FROM (SELECT * FROM employee WHERE department = 'Engineering') AS eng ORDER BY salary DESC"
        result = dba.fetch(sql, limit=2, skip=0)
        assert result.total_count == 4  # Grace, Alice, Ivy, Bob
        assert result.count == 2
        assert result.records[0]["salary"] >= result.records[1]["salary"]

    def test_subselect_with_aggregation(self, dba):
        """Sub-select with GROUP BY should work."""
        sql = """
            SELECT department, total_salary, emp_count
            FROM (
                SELECT department, SUM(salary) AS total_salary, COUNT(*) AS emp_count
                FROM employee
                GROUP BY department
            ) AS dept_stats
        """
        result = dba.fetch(sql, limit=10, skip=0)
        assert result.total_count == 3  # 3 departments
        assert result.count == 3

    def test_nested_subselect(self, dba):
        """Double-nested sub-select should work."""
        sql = """
            SELECT * FROM (
                SELECT * FROM (
                    SELECT id, name, salary FROM employee WHERE salary > 60000
                ) AS inner_q WHERE salary < 100000
            ) AS outer_q
        """
        result = dba.fetch(sql, limit=5, skip=0)
        for row in result.records:
            assert 60000 < row["salary"] < 100000
        assert result.total_count == result.count or result.total_count > 0

    def test_correlated_subselect_in_where(self, dba):
        """Correlated sub-select in WHERE clause."""
        sql = """
            SELECT e.* FROM employee e
            WHERE e.salary > (SELECT AVG(salary) FROM employee)
        """
        result = dba.fetch(sql, limit=10, skip=0)
        avg_salary = sum(r[3] for r in TEST_RECORDS) / len(TEST_RECORDS)
        for row in result.records:
            assert row["salary"] > avg_salary


# ---------------------------------------------------------------------------
# Joins
# ---------------------------------------------------------------------------

class TestJoins:
    def test_inner_join(self, dba):
        """INNER JOIN should paginate correctly."""
        sql = """
            SELECT e.id, e.name, d.name AS dept_name
            FROM employee e
            INNER JOIN department d ON e.dept_id = d.id
        """
        result = dba.fetch(sql, limit=5, skip=0)
        assert result.total_count == 10
        assert result.count == 5
        for row in result.records:
            assert "dept_name" in row

    def test_left_join(self, dba):
        """LEFT JOIN should paginate correctly."""
        sql = """
            SELECT e.id, e.name, ei.item_name
            FROM employee e
            LEFT JOIN employee_item ei ON e.id = ei.employee_id
        """
        result = dba.fetch(sql, limit=5, skip=0)
        assert result.total_count > 10  # Some employees have multiple items

    def test_join_with_where(self, dba):
        """JOIN + WHERE filter should work."""
        sql = """
            SELECT e.name, ei.item_name, ei.quantity
            FROM employee e
            INNER JOIN employee_item ei ON e.id = ei.employee_id
            WHERE ei.quantity > 1
        """
        result = dba.fetch(sql, limit=10, skip=0)
        for row in result.records:
            assert row["quantity"] > 1

    def test_join_with_order(self, dba):
        """JOIN + ORDER BY should work."""
        sql = """
            SELECT e.name, d.name AS dept_name, e.salary
            FROM employee e
            JOIN department d ON e.dept_id = d.id
            ORDER BY e.salary DESC
        """
        result = dba.fetch(sql, limit=3, skip=0)
        salaries = [r["salary"] for r in result.records]
        assert salaries == sorted(salaries, reverse=True)
        assert result.total_count == 10


# ---------------------------------------------------------------------------
# Search with pagination
# ---------------------------------------------------------------------------

class TestSearchPagination:
    def test_search_reduces_total(self, dba):
        """Search should filter results and total count should reflect the filter."""
        result = dba.fetch(
            "SELECT * FROM employee",
            limit=10,
            search="Engineering",
            search_columns=["department"],
        )
        assert result.total_count == 4  # 4 engineers
        assert result.count == 4

    def test_search_with_pagination(self, dba):
        """Search + pagination: page through filtered results."""
        result = dba.fetch(
            "SELECT * FROM employee",
            limit=2,
            skip=0,
            search="Engineering",
            search_columns=["department"],
        )
        assert result.count == 2
        assert result.total_count == 4

    def test_search_no_match(self, dba):
        """Search that matches nothing should return 0 results."""
        result = dba.fetch(
            "SELECT * FROM employee",
            limit=10,
            search="NonexistentDepartment",
            search_columns=["department"],
        )
        assert result.count == 0
        assert result.total_count == 0


# ---------------------------------------------------------------------------
# Parameterized queries
# ---------------------------------------------------------------------------

class TestParameterizedPagination:
    def test_with_params(self, dba):
        """Parameterized WHERE clause should work with pagination."""
        result = dba.fetch(
            "SELECT * FROM employee WHERE salary > ?",
            params=[80000],
            limit=3,
            skip=0,
        )
        for row in result.records:
            assert row["salary"] > 80000
        assert result.total_count > 0

    def test_with_multiple_params(self, dba):
        """Multiple parameters should work."""
        result = dba.fetch(
            "SELECT * FROM employee WHERE department = ? AND salary > ?",
            params=["Engineering", 90000],
            limit=10,
        )
        for row in result.records:
            assert row["department"] == "Engineering"
            assert row["salary"] > 90000


# ---------------------------------------------------------------------------
# to_paginate() integration
# ---------------------------------------------------------------------------

class TestPaginateOutput:
    def test_to_paginate_structure(self, dba):
        """to_paginate() should return all expected keys."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=0)
        paginated = result.to_paginate()

        assert "recordsTotal" in paginated
        assert "recordsOffset" in paginated
        assert "recordCount" in paginated
        assert "recordsFiltered" in paginated
        assert "fields" in paginated
        assert "data" in paginated
        assert "dataError" in paginated

    def test_to_paginate_values(self, dba):
        """to_paginate() should have correct values."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=6)
        paginated = result.to_paginate()

        assert paginated["recordsTotal"] == 10
        assert paginated["recordsOffset"] == 6
        assert paginated["recordCount"] == 3
        assert paginated["recordsFiltered"] == 10
        assert paginated["dataError"] is None
        assert "__tina4_total__" not in paginated["fields"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_table(self, dba):
        """Fetch from an empty result set."""
        dba.execute("CREATE TABLE IF NOT EXISTS empty_table (id INTEGER PRIMARY KEY, name TEXT)")
        dba.commit()
        result = dba.fetch("SELECT * FROM empty_table", limit=10)
        assert result.count == 0
        assert result.total_count == 0
        dba.execute("DROP TABLE IF EXISTS empty_table")
        dba.commit()

    def test_select_star(self, dba):
        """SELECT * should work correctly."""
        result = dba.fetch("SELECT * FROM employee", limit=5)
        assert result.count == 5
        assert "id" in result.columns
        assert "name" in result.columns

    def test_select_specific_columns(self, dba):
        """SELECT with specific columns should not include extra columns."""
        result = dba.fetch("SELECT id, name FROM employee", limit=5)
        assert result.columns == ["id", "name"]
        assert len(result.records[0]) == 2

    def test_skip_zero(self, dba):
        """skip=0 should start from the beginning."""
        result = dba.fetch("SELECT * FROM employee ORDER BY id", limit=1, skip=0)
        assert result.records[0]["id"] == 1

    def test_limit_zero_like_behavior(self, dba):
        """limit=0 edge case — depends on engine but shouldn't crash."""
        # SQLite LIMIT 0 returns 0 rows
        result = dba.fetch("SELECT * FROM employee", limit=0, skip=0)
        assert result.count == 0

    def test_distinct_query(self, dba):
        """SELECT DISTINCT should paginate correctly."""
        result = dba.fetch("SELECT DISTINCT department FROM employee", limit=10)
        assert result.total_count == 3
        departments = {row["department"] for row in result.records}
        assert departments == {"Engineering", "Marketing", "Sales"}

    def test_count_with_group_by(self, dba):
        """GROUP BY queries should have correct total count."""
        result = dba.fetch(
            "SELECT department, COUNT(*) AS cnt FROM employee GROUP BY department",
            limit=2,
            skip=0,
        )
        assert result.total_count == 3  # 3 groups
        assert result.count == 2

    def test_where_clause_with_like(self, dba):
        """LIKE in WHERE should work."""
        result = dba.fetch(
            "SELECT * FROM employee WHERE name LIKE ?",
            params=["%a%"],
            limit=10,
        )
        for row in result.records:
            assert "a" in row["name"].lower()


# ---------------------------------------------------------------------------
# Engine-specific SQL generation (mocked drivers)
# ---------------------------------------------------------------------------

def _mock_driver():
    """Create a mock database driver module with a connect() method."""
    mock_module = MagicMock()
    mock_module.__name__ = "mock_driver"
    mock_conn = MagicMock()
    mock_module.connect.return_value = mock_conn

    # Set up cursor mock to return reasonable data
    mock_cursor = MagicMock()
    mock_cursor.description = [("__tina4_total__",), ("id",), ("name",)]
    mock_cursor.fetchall.return_value = [(5, 1, "Test")]
    mock_conn.cursor.return_value = mock_cursor

    return mock_module, mock_conn, mock_cursor


class TestFirebirdSQLGeneration:
    @patch("importlib.import_module")
    def test_firebird_uses_first_skip(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(FIREBIRD + ":localhost/3050:/tmp/TEST.FDB", "SYSDBA", "masterkey")

        db.fetch("SELECT * FROM employee", limit=5, skip=10)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "FIRST 5" in executed_sql
        assert "SKIP 10" in executed_sql

    @patch("importlib.import_module")
    def test_firebird_with_order_by(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(FIREBIRD + ":localhost/3050:/tmp/TEST.FDB", "SYSDBA", "masterkey")

        db.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3, skip=0)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "FIRST 3" in executed_sql
        assert "SKIP 0" in executed_sql
        assert "ORDER BY salary DESC" in executed_sql


class TestMSSQLGeneration:
    @patch("importlib.import_module")
    def test_mssql_uses_offset_fetch(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(MSSQL + ":localhost/1433:testdb", "sa", "pass")

        db.fetch("SELECT * FROM employee", limit=5, skip=10)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "OFFSET 10 ROWS" in executed_sql
        assert "FETCH NEXT 5 ROWS ONLY" in executed_sql
        # MSSQL needs ORDER BY for OFFSET
        assert "ORDER BY" in executed_sql

    @patch("importlib.import_module")
    def test_mssql_preserves_order_by(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(MSSQL + ":localhost/1433:testdb", "sa", "pass")

        db.fetch("SELECT * FROM employee ORDER BY salary DESC", limit=3, skip=0)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY salary DESC" in executed_sql.upper() or "order by salary desc" in executed_sql.lower()
        assert "OFFSET 0 ROWS" in executed_sql
        assert "FETCH NEXT 3 ROWS ONLY" in executed_sql

    @patch("importlib.import_module")
    def test_mssql_adds_default_order_when_missing(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(MSSQL + ":localhost/1433:testdb", "sa", "pass")

        db.fetch("SELECT * FROM employee", limit=5, skip=0)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY (SELECT NULL)" in executed_sql


class TestMySQLGeneration:
    @patch("importlib.import_module")
    def test_mysql_uses_limit_offset(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(MYSQL + ":localhost/3306:testdb", "root", "pass")

        db.fetch("SELECT * FROM employee", limit=5, skip=10)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "LIMIT 5" in executed_sql
        assert "OFFSET 10" in executed_sql


class TestPostgresGeneration:
    @patch("importlib.import_module")
    def test_postgres_uses_limit_offset(self, mock_import):
        mock_module, mock_conn, mock_cursor = _mock_driver()
        mock_import.return_value = mock_module
        db = Database(POSTGRES + ":localhost/5432:testdb", "pg", "pass")

        db.fetch("SELECT * FROM employee", limit=5, skip=10)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "LIMIT 5" in executed_sql
        assert "OFFSET 10" in executed_sql


class TestSQLiteGeneration:
    def test_sqlite_uses_limit_offset(self, dba):
        """Verify SQLite uses LIMIT/OFFSET (live, not mocked)."""
        result = dba.fetch("SELECT * FROM employee", limit=3, skip=2)
        assert result.count == 3
        assert result.total_count == 10
