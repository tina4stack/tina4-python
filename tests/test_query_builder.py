"""Comprehensive tests for QueryBuilder with a real SQLite database."""
import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.database.adapter import DatabaseResult
from tina4_python.query_builder import QueryBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Create a temporary SQLite database with a users table and 5 rows."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name

    dba = Database(f"sqlite:///{db_path}")

    dba.execute(
        "CREATE TABLE users ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT NOT NULL,"
        "  email TEXT NOT NULL,"
        "  age INTEGER NOT NULL,"
        "  active INTEGER NOT NULL DEFAULT 1"
        ")"
    )

    rows = [
        {"name": "Alice", "email": "alice@example.com", "age": 30, "active": 1},
        {"name": "Bob", "email": "bob@example.com", "age": 25, "active": 1},
        {"name": "Charlie", "email": "charlie@example.com", "age": 35, "active": 0},
        {"name": "Diana", "email": "diana@example.com", "age": 28, "active": 1},
        {"name": "Eve", "email": "eve@example.com", "age": 22, "active": 0},
    ]
    for row in rows:
        dba.insert("users", row)

    yield dba

    dba.close()
    os.unlink(db_path)


@pytest.fixture()
def db_with_orders(db):
    """Extend the users database with an orders table for join tests."""
    db.execute(
        "CREATE TABLE orders ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  user_id INTEGER NOT NULL,"
        "  amount REAL NOT NULL"
        ")"
    )
    db.insert("orders", {"user_id": 1, "amount": 99.99})
    db.insert("orders", {"user_id": 1, "amount": 49.50})
    db.insert("orders", {"user_id": 2, "amount": 200.00})
    return db


# ---------------------------------------------------------------------------
# 1. from_table() creates a QueryBuilder
# ---------------------------------------------------------------------------

class TestFromTable:
    def test_returns_query_builder(self, db):
        qb = QueryBuilder.from_table("users", db)
        assert isinstance(qb, QueryBuilder)

    def test_sets_table_name(self, db):
        qb = QueryBuilder.from_table("users", db)
        assert qb._table == "users"

    def test_default_columns_are_star(self, db):
        qb = QueryBuilder.from_table("users", db)
        assert qb._columns == ["*"]


# ---------------------------------------------------------------------------
# 2. select() sets columns
# ---------------------------------------------------------------------------

class TestSelect:
    def test_single_column(self, db):
        qb = QueryBuilder.from_table("users", db).select("name")
        assert qb._columns == ["name"]

    def test_multiple_columns(self, db):
        qb = QueryBuilder.from_table("users", db).select("id", "name", "email")
        assert qb._columns == ["id", "name", "email"]

    def test_no_args_keeps_default(self, db):
        qb = QueryBuilder.from_table("users", db).select()
        assert qb._columns == ["*"]

    def test_select_reflected_in_sql(self, db):
        sql = QueryBuilder.from_table("users", db).select("id", "name").to_sql()
        assert sql.startswith("SELECT id, name FROM users")


# ---------------------------------------------------------------------------
# 3. where() adds AND conditions
# ---------------------------------------------------------------------------

class TestWhere:
    def test_single_where(self, db):
        qb = QueryBuilder.from_table("users", db).where("active = ?", [1])
        assert len(qb._wheres) == 1
        assert qb._wheres[0] == ("AND", "active = ?")
        assert qb._params == [1]

    def test_multiple_where_chained_with_and(self, db):
        qb = (
            QueryBuilder.from_table("users", db)
            .where("active = ?", [1])
            .where("age > ?", [25])
        )
        sql = qb.to_sql()
        assert "WHERE active = ? AND age > ?" in sql

    def test_where_without_params(self, db):
        qb = QueryBuilder.from_table("users", db).where("active = 1")
        assert qb._params == []
        assert "WHERE active = 1" in qb.to_sql()


# ---------------------------------------------------------------------------
# 4. or_where() adds OR conditions
# ---------------------------------------------------------------------------

class TestOrWhere:
    def test_or_where_after_where(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .where("active = ?", [1])
            .or_where("age < ?", [25])
            .to_sql()
        )
        assert "WHERE active = ? OR age < ?" in sql

    def test_or_where_params_accumulated(self, db):
        qb = (
            QueryBuilder.from_table("users", db)
            .where("active = ?", [1])
            .or_where("age < ?", [25])
        )
        assert qb._params == [1, 25]


# ---------------------------------------------------------------------------
# 5. join() adds INNER JOIN
# ---------------------------------------------------------------------------

class TestJoin:
    def test_inner_join_sql(self, db_with_orders):
        sql = (
            QueryBuilder.from_table("users", db_with_orders)
            .join("orders", "orders.user_id = users.id")
            .to_sql()
        )
        assert "INNER JOIN orders ON orders.user_id = users.id" in sql

    def test_inner_join_executes(self, db_with_orders):
        result = (
            QueryBuilder.from_table("users", db_with_orders)
            .select("users.name", "orders.amount")
            .join("orders", "orders.user_id = users.id")
            .get()
        )
        assert isinstance(result, DatabaseResult)
        assert result.count >= 1


# ---------------------------------------------------------------------------
# 6. left_join() adds LEFT JOIN
# ---------------------------------------------------------------------------

class TestLeftJoin:
    def test_left_join_sql(self, db_with_orders):
        sql = (
            QueryBuilder.from_table("users", db_with_orders)
            .left_join("orders", "orders.user_id = users.id")
            .to_sql()
        )
        assert "LEFT JOIN orders ON orders.user_id = users.id" in sql

    def test_left_join_includes_unmatched(self, db_with_orders):
        result = (
            QueryBuilder.from_table("users", db_with_orders)
            .select("users.name", "orders.amount")
            .left_join("orders", "orders.user_id = users.id")
            .get()
        )
        # All 5 users should appear (some with NULL amount)
        assert result.count >= 5


# ---------------------------------------------------------------------------
# 7. group_by() adds GROUP BY
# ---------------------------------------------------------------------------

class TestGroupBy:
    def test_group_by_sql(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .select("active", "COUNT(*) as cnt")
            .group_by("active")
            .to_sql()
        )
        assert "GROUP BY active" in sql

    def test_group_by_executes(self, db):
        result = (
            QueryBuilder.from_table("users", db)
            .select("active", "COUNT(*) as cnt")
            .group_by("active")
            .get()
        )
        assert result.count == 2  # active=0, active=1


# ---------------------------------------------------------------------------
# 8. having() adds HAVING
# ---------------------------------------------------------------------------

class TestHaving:
    def test_having_sql(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .select("active", "COUNT(*) as cnt")
            .group_by("active")
            .having("COUNT(*) > ?", [1])
            .to_sql()
        )
        assert "HAVING COUNT(*) > ?" in sql

    def test_having_executes(self, db):
        result = (
            QueryBuilder.from_table("users", db)
            .select("active", "COUNT(*) as cnt")
            .group_by("active")
            .having("COUNT(*) > ?", [2])
            .get()
        )
        # active=1 has 3 rows, active=0 has 2 rows — only active=1 passes
        assert result.count == 1


# ---------------------------------------------------------------------------
# 9. order_by() adds ORDER BY
# ---------------------------------------------------------------------------

class TestOrderBy:
    def test_order_by_sql(self, db):
        sql = QueryBuilder.from_table("users", db).order_by("name ASC").to_sql()
        assert "ORDER BY name ASC" in sql

    def test_order_by_multiple(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .order_by("active DESC")
            .order_by("name ASC")
            .to_sql()
        )
        assert "ORDER BY active DESC, name ASC" in sql

    def test_order_by_affects_results(self, db):
        row = (
            QueryBuilder.from_table("users", db)
            .select("name")
            .order_by("name ASC")
            .first()
        )
        assert row is not None
        assert row["name"] == "Alice"

        row = (
            QueryBuilder.from_table("users", db)
            .select("name")
            .order_by("name DESC")
            .first()
        )
        assert row is not None
        assert row["name"] == "Eve"


# ---------------------------------------------------------------------------
# 10. limit() sets LIMIT and OFFSET
# ---------------------------------------------------------------------------

class TestLimit:
    def test_limit_restricts_results(self, db):
        result = QueryBuilder.from_table("users", db).limit(2).get()
        # records list is limited to 2, but count reflects total matching rows
        assert len(result.records) == 2

    def test_limit_with_offset(self, db):
        result = (
            QueryBuilder.from_table("users", db)
            .order_by("id ASC")
            .limit(2, offset=2)
            .get()
        )
        assert len(result.records) == 2
        # Should skip first 2 rows (Alice, Bob) and get Charlie, Diana
        names = [r["name"] for r in result.records]
        assert names == ["Charlie", "Diana"]

    def test_limit_stored_internally(self, db):
        qb = QueryBuilder.from_table("users", db).limit(10, offset=5)
        assert qb._limit_val == 10
        assert qb._offset_val == 5


# ---------------------------------------------------------------------------
# 11. to_sql() generates correct SQL string
# ---------------------------------------------------------------------------

class TestToSql:
    def test_basic_select_all(self, db):
        sql = QueryBuilder.from_table("users", db).to_sql()
        assert sql == "SELECT * FROM users"

    def test_full_query(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .select("name", "age")
            .where("active = ?", [1])
            .order_by("name ASC")
            .to_sql()
        )
        assert sql == "SELECT name, age FROM users WHERE active = ? ORDER BY name ASC"

    def test_to_sql_does_not_include_limit(self, db):
        """to_sql() should not embed LIMIT — it is passed to db.fetch() separately."""
        sql = QueryBuilder.from_table("users", db).limit(5).to_sql()
        assert "LIMIT" not in sql


# ---------------------------------------------------------------------------
# 12. Method chaining works (all methods return self)
# ---------------------------------------------------------------------------

class TestChaining:
    def test_all_methods_return_query_builder(self, db):
        qb = QueryBuilder.from_table("users", db)

        assert isinstance(qb.select("id"), QueryBuilder)
        assert isinstance(qb.where("id > ?", [0]), QueryBuilder)
        assert isinstance(qb.or_where("id < ?", [100]), QueryBuilder)
        assert isinstance(qb.join("orders", "1=1"), QueryBuilder)
        assert isinstance(qb.left_join("orders", "1=1"), QueryBuilder)
        assert isinstance(qb.group_by("id"), QueryBuilder)
        assert isinstance(qb.having("COUNT(*) > 0"), QueryBuilder)
        assert isinstance(qb.order_by("id"), QueryBuilder)
        assert isinstance(qb.limit(10), QueryBuilder)

    def test_fluent_chain(self, db):
        """A single chained expression should work without errors."""
        result = (
            QueryBuilder.from_table("users", db)
            .select("id", "name")
            .where("active = ?", [1])
            .order_by("name ASC")
            .limit(10)
            .get()
        )
        assert isinstance(result, DatabaseResult)
        assert result.count > 0


# ---------------------------------------------------------------------------
# 13. get() executes and returns DatabaseResult
# ---------------------------------------------------------------------------

class TestGet:
    def test_returns_database_result(self, db):
        result = QueryBuilder.from_table("users", db).get()
        assert isinstance(result, DatabaseResult)

    def test_returns_all_rows_with_default_limit(self, db):
        result = QueryBuilder.from_table("users", db).get()
        assert result.count == 5

    def test_returns_filtered_rows(self, db):
        result = (
            QueryBuilder.from_table("users", db)
            .where("active = ?", [1])
            .get()
        )
        assert result.count == 3

    def test_records_are_dicts(self, db):
        result = QueryBuilder.from_table("users", db).limit(1).get()
        assert isinstance(result.records[0], dict)
        assert "name" in result.records[0]


# ---------------------------------------------------------------------------
# 14. first() returns single dict or None
# ---------------------------------------------------------------------------

class TestFirst:
    def test_returns_dict(self, db):
        row = QueryBuilder.from_table("users", db).where("name = ?", ["Alice"]).first()
        assert isinstance(row, dict)
        assert row["name"] == "Alice"
        assert row["email"] == "alice@example.com"

    def test_returns_none_when_no_match(self, db):
        row = (
            QueryBuilder.from_table("users", db)
            .where("name = ?", ["NonExistent"])
            .first()
        )
        assert row is None


# ---------------------------------------------------------------------------
# 15. count() returns integer
# ---------------------------------------------------------------------------

class TestCount:
    def test_count_all(self, db):
        c = QueryBuilder.from_table("users", db).count()
        assert isinstance(c, int)
        assert c == 5

    def test_count_with_filter(self, db):
        c = QueryBuilder.from_table("users", db).where("active = ?", [1]).count()
        assert c == 3

    def test_count_with_no_match(self, db):
        c = QueryBuilder.from_table("users", db).where("age > ?", [100]).count()
        assert c == 0


# ---------------------------------------------------------------------------
# 16. exists() returns boolean
# ---------------------------------------------------------------------------

class TestExists:
    def test_exists_true(self, db):
        assert QueryBuilder.from_table("users", db).where("name = ?", ["Alice"]).exists() is True

    def test_exists_false(self, db):
        assert QueryBuilder.from_table("users", db).where("name = ?", ["Nobody"]).exists() is False


# ---------------------------------------------------------------------------
# 17. No database raises RuntimeError
# ---------------------------------------------------------------------------

class TestNoDatabaseError:
    def test_get_raises(self):
        qb = QueryBuilder.from_table("users")
        with pytest.raises((RuntimeError, AttributeError)):
            qb.get()

    def test_first_raises(self):
        qb = QueryBuilder.from_table("users")
        with pytest.raises((RuntimeError, AttributeError)):
            qb.first()

    def test_count_raises(self):
        qb = QueryBuilder.from_table("users")
        with pytest.raises((RuntimeError, AttributeError)):
            qb.count()

    def test_exists_raises(self):
        qb = QueryBuilder.from_table("users")
        with pytest.raises((RuntimeError, AttributeError)):
            qb.exists()


# ---------------------------------------------------------------------------
# 18. Complex query with multiple where + join + order + limit
# ---------------------------------------------------------------------------

class TestComplexQuery:
    def test_complex_sql_generation(self, db_with_orders):
        sql = (
            QueryBuilder.from_table("users", db_with_orders)
            .select("users.name", "SUM(orders.amount) as total")
            .join("orders", "orders.user_id = users.id")
            .where("users.active = ?", [1])
            .where("users.age > ?", [20])
            .group_by("users.name")
            .having("SUM(orders.amount) > ?", [50])
            .order_by("total DESC")
            .to_sql()
        )
        assert "SELECT users.name, SUM(orders.amount) as total FROM users" in sql
        assert "INNER JOIN orders ON orders.user_id = users.id" in sql
        assert "WHERE users.active = ? AND users.age > ?" in sql
        assert "GROUP BY users.name" in sql
        assert "HAVING SUM(orders.amount) > ?" in sql
        assert "ORDER BY total DESC" in sql

    def test_complex_query_executes(self, db_with_orders):
        result = (
            QueryBuilder.from_table("users", db_with_orders)
            .select("users.name", "SUM(orders.amount) as total")
            .join("orders", "orders.user_id = users.id")
            .where("users.active = ?", [1])
            .group_by("users.name")
            .having("SUM(orders.amount) > ?", [50])
            .order_by("total DESC")
            .limit(10)
            .get()
        )
        assert isinstance(result, DatabaseResult)
        assert result.count >= 1
        # Alice has orders totalling 149.49
        names = [r["name"] for r in result.records]
        assert "Alice" in names

    def test_mixed_where_and_or_where(self, db):
        sql = (
            QueryBuilder.from_table("users", db)
            .where("active = ?", [1])
            .or_where("age < ?", [25])
            .where("name != ?", ["Bob"])
            .to_sql()
        )
        assert "WHERE active = ? OR age < ? AND name != ?" in sql


# ---------------------------------------------------------------------------
# 19. Empty result returns properly
# ---------------------------------------------------------------------------

class TestEmptyResult:
    def test_count_zero(self, db):
        c = QueryBuilder.from_table("users", db).where("id = ?", [-999]).count()
        assert c == 0

    def test_exists_false(self, db):
        assert QueryBuilder.from_table("users", db).where("id = ?", [-999]).exists() is False

    def test_first_none(self, db):
        row = QueryBuilder.from_table("users", db).where("id = ?", [-999]).first()
        assert row is None

    def test_get_empty_records(self, db):
        result = QueryBuilder.from_table("users", db).where("id = ?", [-999]).get()
        assert result.records == []
        assert result.count == 0
