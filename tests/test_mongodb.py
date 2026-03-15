"""Tests for MongoDB SQL translation layer and Database integration.

Covers:
  - SQLToMongo parser: SELECT, INSERT, UPDATE, DELETE, WHERE, ORDER BY, LIMIT, OFFSET
  - Live MongoDB tests via Database class (requires MongoDB on localhost:27017)
"""

import pytest
from tina4_python.SQLToMongo import SQLToMongo


# ---------------------------------------------------------------------------
# Unit tests for SQLToMongo.translate() — no database needed
# ---------------------------------------------------------------------------

class TestSQLToMongoSelect:
    """Test SELECT statement translation."""

    def test_simple_select_star(self):
        op = SQLToMongo.translate("SELECT * FROM users")
        assert op["type"] == "find"
        assert op["collection"] == "users"
        assert op["filter"] == {}

    def test_select_columns(self):
        op = SQLToMongo.translate("SELECT name, email FROM users")
        assert op["type"] == "find"
        assert op["collection"] == "users"
        assert "name" in op["projection"]
        assert "email" in op["projection"]

    def test_select_with_where_equals(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE name = ?", ["Alice"])
        assert op["filter"] == {"name": "Alice"}

    def test_select_with_where_gt(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age > ?", [30])
        assert op["filter"] == {"age": {"$gt": 30}}

    def test_select_with_where_gte(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age >= ?", [30])
        assert op["filter"] == {"age": {"$gte": 30}}

    def test_select_with_where_lt(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age < ?", [30])
        assert op["filter"] == {"age": {"$lt": 30}}

    def test_select_with_where_lte(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age <= ?", [30])
        assert op["filter"] == {"age": {"$lte": 30}}

    def test_select_with_where_ne(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE status != ?", ["deleted"])
        assert op["filter"] == {"status": {"$ne": "deleted"}}

    def test_select_with_where_and(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age > ? AND active = ?", [30, 1])
        # Should merge simple filters or use $and
        assert "age" in op["filter"] or "$and" in op["filter"]

    def test_select_with_where_or(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE name = ? OR name = ?", ["Alice", "Bob"])
        assert "$or" in op["filter"]

    def test_select_with_like(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE name LIKE ?", ["%alice%"])
        assert "$regex" in op["filter"]["name"]

    def test_select_with_in(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE status IN ('active', 'pending')")
        assert "$in" in op["filter"]["status"]

    def test_select_with_is_null(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE email IS NULL")
        assert op["filter"]["email"] is None

    def test_select_with_is_not_null(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE email IS NOT NULL")
        assert op["filter"]["email"] == {"$ne": None}

    def test_select_with_between(self):
        op = SQLToMongo.translate("SELECT * FROM users WHERE age BETWEEN ? AND ?", [18, 65])
        assert op["filter"]["age"] == {"$gte": 18, "$lte": 65}

    def test_select_with_order_by_asc(self):
        op = SQLToMongo.translate("SELECT * FROM users ORDER BY name ASC")
        assert op["sort"]["name"] == 1

    def test_select_with_order_by_desc(self):
        op = SQLToMongo.translate("SELECT * FROM users ORDER BY age DESC")
        assert op["sort"]["age"] == -1

    def test_select_with_limit_offset(self):
        op = SQLToMongo.translate("SELECT * FROM users LIMIT 10 OFFSET 20")
        assert op["limit"] == 10
        assert op["skip"] == 20

    def test_count_wrapper(self):
        """Pagination COUNT(*) wrapper should produce a count operation."""
        op = SQLToMongo.translate(
            "SELECT COUNT(*) AS count_records FROM (SELECT * FROM users WHERE active = 1) AS t"
        )
        assert op["type"] == "count"
        assert op["collection"] == "users"

    def test_pagination_wrapper(self):
        """Pagination wrapper should unwrap and add limit/skip."""
        op = SQLToMongo.translate(
            "SELECT * FROM (SELECT * FROM users WHERE active = 1) AS t LIMIT 10 OFFSET 20"
        )
        assert op["type"] == "find"
        assert op["collection"] == "users"
        assert op["limit"] == 10
        assert op["skip"] == 20

    def test_select_with_table_prefix(self):
        op = SQLToMongo.translate("SELECT u.name, u.email FROM users u")
        assert "name" in op.get("projection", {})
        assert "email" in op.get("projection", {})


class TestSQLToMongoInsert:
    """Test INSERT statement translation."""

    def test_simple_insert(self):
        op = SQLToMongo.translate(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            ["Alice", "alice@test.com"]
        )
        assert op["type"] == "insert"
        assert op["collection"] == "users"
        assert op["document"]["name"] == "Alice"
        assert op["document"]["email"] == "alice@test.com"

    def test_insert_with_returning(self):
        op = SQLToMongo.translate(
            "INSERT INTO users (name) VALUES (?) RETURNING id",
            ["Bob"]
        )
        assert op["type"] == "insert"
        assert op["returning"] == "id"

    def test_insert_numeric_values(self):
        op = SQLToMongo.translate(
            "INSERT INTO users (name, age) VALUES (?, ?)",
            ["Charlie", 30]
        )
        assert op["document"]["age"] == 30


class TestSQLToMongoUpdate:
    """Test UPDATE statement translation."""

    def test_simple_update(self):
        op = SQLToMongo.translate(
            "UPDATE users SET name = ? WHERE id = ?",
            ["Bob Updated", 1]
        )
        assert op["type"] == "update"
        assert op["collection"] == "users"
        assert op["update"] == {"$set": {"name": "Bob Updated"}}
        assert op["filter"] == {"id": 1}

    def test_update_multiple_columns(self):
        op = SQLToMongo.translate(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            ["Charlie", "c@test.com", 2]
        )
        assert op["update"]["$set"]["name"] == "Charlie"
        assert op["update"]["$set"]["email"] == "c@test.com"

    def test_update_with_returning(self):
        op = SQLToMongo.translate(
            "UPDATE users SET name = ? WHERE id = ? RETURNING *",
            ["Dave", 3]
        )
        assert op["returning"] == "*"


class TestSQLToMongoDelete:
    """Test DELETE statement translation."""

    def test_simple_delete(self):
        op = SQLToMongo.translate(
            "DELETE FROM users WHERE id = ?",
            [1]
        )
        assert op["type"] == "delete"
        assert op["collection"] == "users"
        assert op["filter"] == {"id": 1}

    def test_delete_with_returning(self):
        op = SQLToMongo.translate(
            "DELETE FROM users WHERE id = ? RETURNING *",
            [1]
        )
        assert op["returning"] == "*"

    def test_delete_no_where(self):
        op = SQLToMongo.translate("DELETE FROM users")
        assert op["filter"] == {}


class TestSQLToMongoDDL:
    """Test CREATE/DROP TABLE translation."""

    def test_create_table(self):
        op = SQLToMongo.translate("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        assert op["type"] == "create_collection"
        assert op["collection"] == "users"

    def test_create_if_not_exists(self):
        op = SQLToMongo.translate("CREATE TABLE IF NOT EXISTS users (id INTEGER)")
        assert op["type"] == "create_collection"
        assert op["collection"] == "users"

    def test_drop_table(self):
        op = SQLToMongo.translate("DROP TABLE users")
        assert op["type"] == "drop_collection"
        assert op["collection"] == "users"

    def test_drop_if_exists(self):
        op = SQLToMongo.translate("DROP TABLE IF EXISTS users")
        assert op["type"] == "drop_collection"


class TestSQLToMongoEdgeCases:
    """Edge cases and error handling."""

    def test_unsupported_statement(self):
        with pytest.raises(ValueError, match="Unsupported SQL"):
            SQLToMongo.translate("ALTER TABLE users ADD COLUMN age INTEGER")

    def test_like_to_regex_wildcard(self):
        regex = SQLToMongo._like_to_regex("%test%")
        assert ".*test.*" in regex

    def test_like_to_regex_single_char(self):
        regex = SQLToMongo._like_to_regex("test_")
        assert "test." in regex

    def test_resolve_null(self):
        val = SQLToMongo._resolve_value("NULL", {})
        assert val is None

    def test_resolve_boolean(self):
        assert SQLToMongo._resolve_value("TRUE", {}) is True
        assert SQLToMongo._resolve_value("FALSE", {}) is False

    def test_resolve_number(self):
        assert SQLToMongo._resolve_value("42", {}) == 42
        assert SQLToMongo._resolve_value("3.14", {}) == 3.14


# ---------------------------------------------------------------------------
# Live MongoDB tests — requires MongoDB on localhost:27017
# ---------------------------------------------------------------------------

@pytest.fixture
def mongo_db():
    try:
        from tina4_python.Database import Database
        db = Database("pymongo:localhost/27017:tina4_test")
    except (Exception, SystemExit):
        pytest.skip("MongoDB not available on localhost:27017")

    # Clean up test collection
    db.execute("DROP TABLE IF EXISTS test_users")
    db.execute("CREATE TABLE test_users (id INTEGER)")
    yield db

    # Cleanup
    db.execute("DROP TABLE test_users")
    db.close()


class TestMongoDBLive:
    """Live tests against a real MongoDB instance."""

    def test_insert_and_fetch(self, mongo_db):
        mongo_db.execute(
            "INSERT INTO test_users (id, name, email) VALUES (?, ?, ?)",
            [1, "Alice", "alice@test.com"]
        )
        result = mongo_db.fetch("SELECT * FROM test_users WHERE name = ?", ["Alice"])
        assert result.error is None
        assert result.count == 1
        assert result.records[0]["name"] == "Alice"

    def test_insert_and_fetch_all(self, mongo_db):
        for i, name in enumerate(["Bob", "Charlie", "Dave"], start=2):
            mongo_db.execute(
                "INSERT INTO test_users (id, name, email) VALUES (?, ?, ?)",
                [i, name, f"{name.lower()}@test.com"]
            )
        result = mongo_db.fetch("SELECT * FROM test_users", limit=100)
        assert result.error is None
        assert result.count >= 3

    def test_fetch_with_pagination(self, mongo_db):
        # Insert 10 users
        for i in range(1, 11):
            mongo_db.execute(
                "INSERT INTO test_users (id, name, email) VALUES (?, ?, ?)",
                [i + 100, f"User{i}", f"user{i}@test.com"]
            )
        result = mongo_db.fetch("SELECT * FROM test_users", limit=5, skip=0)
        assert result.error is None
        assert result.count <= 5
        assert result.total_count >= 10

    def test_fetch_with_where(self, mongo_db):
        mongo_db.execute(
            "INSERT INTO test_users (id, name, age) VALUES (?, ?, ?)",
            [200, "Young", 20]
        )
        mongo_db.execute(
            "INSERT INTO test_users (id, name, age) VALUES (?, ?, ?)",
            [201, "Old", 60]
        )
        result = mongo_db.fetch("SELECT * FROM test_users WHERE age > ?", [30])
        assert result.error is None
        assert all(r["age"] > 30 for r in result.records)

    def test_fetch_with_order_by(self, mongo_db):
        for i, name in enumerate(["Zebra", "Apple", "Mango"], start=300):
            mongo_db.execute(
                "INSERT INTO test_users (id, name) VALUES (?, ?)",
                [i, name]
            )
        result = mongo_db.fetch("SELECT * FROM test_users WHERE id >= 300 ORDER BY name ASC")
        assert result.error is None
        names = [r["name"] for r in result.records]
        assert names == sorted(names)

    def test_update(self, mongo_db):
        mongo_db.execute(
            "INSERT INTO test_users (id, name) VALUES (?, ?)",
            [400, "Before"]
        )
        mongo_db.execute(
            "UPDATE test_users SET name = ? WHERE id = ?",
            ["After", 400]
        )
        result = mongo_db.fetch("SELECT * FROM test_users WHERE id = ?", [400])
        assert result.records[0]["name"] == "After"

    def test_delete(self, mongo_db):
        mongo_db.execute(
            "INSERT INTO test_users (id, name) VALUES (?, ?)",
            [500, "ToDelete"]
        )
        mongo_db.execute(
            "DELETE FROM test_users WHERE id = ?",
            [500]
        )
        result = mongo_db.fetch("SELECT * FROM test_users WHERE id = ?", [500])
        assert result.count == 0

    def test_fetch_one(self, mongo_db):
        mongo_db.execute(
            "INSERT INTO test_users (id, name, email) VALUES (?, ?, ?)",
            [600, "FetchOne", "fetchone@test.com"]
        )
        record = mongo_db.fetch_one("SELECT * FROM test_users WHERE id = ?", [600])
        assert record is not None
        assert record["name"] == "FetchOne"

    def test_table_exists(self, mongo_db):
        assert mongo_db.table_exists("test_users") is True
        assert mongo_db.table_exists("nonexistent_collection") is False

    def test_get_next_id(self, mongo_db):
        mongo_db.execute("INSERT INTO test_users (id, name) VALUES (?, ?)", [900, "Last"])
        next_id = mongo_db.get_next_id("test_users", "id")
        assert next_id == 901

    def test_insert_via_helper(self, mongo_db):
        """Test the Database.insert() helper method."""
        result = mongo_db.insert("test_users", {"id": 700, "name": "Helper", "email": "h@test.com"})
        assert result is not False
        assert len(result.records) >= 1

    def test_update_via_helper(self, mongo_db):
        """Test the Database.update() helper method."""
        mongo_db.execute("INSERT INTO test_users (id, name) VALUES (?, ?)", [800, "OldName"])
        result = mongo_db.update("test_users", {"id": 800, "name": "NewName"})
        assert result is True
        record = mongo_db.fetch_one("SELECT * FROM test_users WHERE id = ?", [800])
        assert record["name"] == "NewName"

    def test_delete_via_helper(self, mongo_db):
        """Test the Database.delete() helper method."""
        mongo_db.execute("INSERT INTO test_users (id, name) VALUES (?, ?)", [801, "DelMe"])
        result = mongo_db.delete("test_users", {"id": 801})
        assert result is True

    def test_commit_no_error(self, mongo_db):
        """Commit should be a no-op for MongoDB (auto-commits)."""
        mongo_db.commit()  # Should not raise

    def test_rollback_no_error(self, mongo_db):
        """Rollback without active transaction should not raise."""
        mongo_db.rollback()  # Should not raise

    def test_search(self, mongo_db):
        """Test full-text search across columns."""
        mongo_db.execute(
            "INSERT INTO test_users (id, name, email) VALUES (?, ?, ?)",
            [1000, "SearchTest", "searchtest@example.com"]
        )
        result = mongo_db.fetch(
            "SELECT * FROM test_users",
            search="SearchTest",
            search_columns=["name", "email"]
        )
        assert result.error is None
        assert result.count >= 1
        assert any(r["name"] == "SearchTest" for r in result.records)
