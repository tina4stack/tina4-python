# Tests for SQL translation layer, RETURNING emulation, custom functions, caching
import time
import pytest
from tina4_python.database import Database, SQLTranslator
from tina4_python.core.cache import Cache


# ── SQLTranslator Tests ────────────────────────────────────────


class TestLimitTranslation:
    def test_limit_offset_to_rows(self):
        sql = "SELECT * FROM users LIMIT 10 OFFSET 5"
        assert SQLTranslator.limit_to_rows(sql) == "SELECT * FROM users ROWS 6 TO 15"

    def test_limit_only_to_rows(self):
        sql = "SELECT * FROM users LIMIT 10"
        assert SQLTranslator.limit_to_rows(sql) == "SELECT * FROM users ROWS 1 TO 10"

    def test_no_limit_unchanged(self):
        sql = "SELECT * FROM users WHERE id = 1"
        assert SQLTranslator.limit_to_rows(sql) == sql

    def test_limit_to_top(self):
        sql = "SELECT * FROM users LIMIT 10"
        assert SQLTranslator.limit_to_top(sql) == "SELECT TOP 10 * FROM users"

    def test_limit_offset_top_unchanged(self):
        sql = "SELECT * FROM users LIMIT 10 OFFSET 5"
        assert SQLTranslator.limit_to_top(sql) == sql  # OFFSET not supported by TOP


class TestBooleanTranslation:
    def test_true_false_to_int(self):
        sql = "SELECT * FROM users WHERE active = TRUE AND deleted = FALSE"
        result = SQLTranslator.boolean_to_int(sql)
        assert "1" in result
        assert "0" in result
        assert "TRUE" not in result
        assert "FALSE" not in result


class TestIlikeTranslation:
    def test_ilike_to_lower_like(self):
        sql = "SELECT * FROM users WHERE name ILIKE '%alice%'"
        result = SQLTranslator.ilike_to_like(sql)
        assert "LOWER(" in result
        assert "ILIKE" not in result


class TestConcatTranslation:
    def test_pipes_to_concat(self):
        sql = "'a' || 'b' || 'c'"
        result = SQLTranslator.concat_pipes_to_func(sql)
        assert result == "CONCAT('a', 'b', 'c')"

    def test_no_pipes_unchanged(self):
        sql = "SELECT * FROM users"
        assert SQLTranslator.concat_pipes_to_func(sql) == sql


class TestAutoIncrementSyntax:
    def test_mysql(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        result = SQLTranslator.auto_increment_syntax(sql, "mysql")
        assert "AUTO_INCREMENT" in result

    def test_postgresql(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        result = SQLTranslator.auto_increment_syntax(sql, "postgresql")
        assert "SERIAL PRIMARY KEY" in result

    def test_mssql(self):
        sql = "CREATE TABLE t (id INTEGER AUTOINCREMENT)"
        result = SQLTranslator.auto_increment_syntax(sql, "mssql")
        assert "IDENTITY(1,1)" in result

    def test_firebird_strips(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        result = SQLTranslator.auto_increment_syntax(sql, "firebird")
        assert "AUTOINCREMENT" not in result

    def test_sqlite_unchanged(self):
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        result = SQLTranslator.auto_increment_syntax(sql, "sqlite")
        assert result == sql


class TestPlaceholderStyle:
    def test_question_to_percent_s(self):
        sql = "SELECT * FROM users WHERE id = ? AND name = ?"
        result = SQLTranslator.placeholder_style(sql, "%s")
        assert result == "SELECT * FROM users WHERE id = %s AND name = %s"

    def test_question_to_numbered(self):
        sql = "SELECT * FROM users WHERE id = ? AND name = ?"
        result = SQLTranslator.placeholder_style(sql, ":")
        assert result == "SELECT * FROM users WHERE id = :1 AND name = :2"


# ── RETURNING Emulation Tests ──────────────────────────────────


class TestReturning:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "returning.db"
        d = Database(f"sqlite:///{db_path}")
        d.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        d.commit()
        yield d
        d.close()

    def test_insert_returning(self, db):
        result = db.execute(
            "INSERT INTO items (name) VALUES (?) RETURNING id, name",
            ["widget"]
        )
        db.commit()
        # Should get the inserted row back
        assert result.last_id == 1
        if result.records:
            assert result.records[0]["name"] == "widget"

    def test_insert_without_returning(self, db):
        result = db.execute("INSERT INTO items (name) VALUES (?)", ["plain"])
        db.commit()
        assert result.last_id == 1
        assert result.records == []


# ── SQLite Custom Function Tests ──────────────────────────────


class TestCustomFunctions:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "funcs.db"
        d = Database(f"sqlite:///{db_path}")
        yield d
        d.close()

    def test_register_and_use(self, db):
        db.register_function("double", 1, lambda x: x * 2)
        row = db.fetch_one("SELECT double(5) as result")
        assert row["result"] == 10

    def test_string_function(self, db):
        db.register_function("shout", 1, lambda s: s.upper() + "!")
        row = db.fetch_one("SELECT shout('hello') as result")
        assert row["result"] == "HELLO!"

    def test_multi_param_function(self, db):
        db.register_function("sum_two", 2, lambda a, b: a + b)
        row = db.fetch_one("SELECT sum_two(3, 7) as result")
        assert row["result"] == 10

    def test_function_in_query(self, db):
        db.execute("CREATE TABLE items (id INTEGER, price REAL)")
        db.execute("INSERT INTO items VALUES (1, 9.99)")
        db.commit()
        db.register_function("with_tax", 1, lambda p: round(p * 1.15, 2))
        row = db.fetch_one("SELECT with_tax(price) as total FROM items WHERE id = 1")
        assert row["total"] == 11.49

    def test_variadic_function(self, db):
        db.register_function("concat_all", -1, lambda *args: "".join(str(a) for a in args))
        row = db.fetch_one("SELECT concat_all('a', 'b', 'c') as result")
        assert row["result"] == "abc"


# ── Migration Block Delimiter Tests ───────────────────────────


class TestMigrationBlocks:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "block_test.db"
        d = Database(f"sqlite:///{db_path}")
        yield d
        d.close()

    @pytest.fixture
    def mig_dir(self, tmp_path):
        d = tmp_path / "migrations"
        d.mkdir()
        return d

    def test_dollar_delimited_block(self):
        from tina4_python.migration.runner import _split_statements
        sql = """
        CREATE TABLE t1 (id INTEGER);
        CREATE TRIGGER tr1 $$ BEGIN SELECT 1; END $$;
        INSERT INTO t1 (id) VALUES (1);
        """
        stmts = _split_statements(sql)
        assert len(stmts) == 3
        # The trigger statement should contain the $$ block intact
        assert "$$" in stmts[1]

    def test_double_slash_delimited_block(self):
        from tina4_python.migration.runner import _split_statements
        sql = """
        CREATE TABLE t1 (id INTEGER);
        CREATE PROCEDURE p1 // BEGIN SELECT 1; END //;
        """
        stmts = _split_statements(sql)
        assert len(stmts) == 2
        assert "//" in stmts[1]

    def test_block_with_semicolons_inside(self):
        from tina4_python.migration.runner import _split_statements
        sql = """
        CREATE TABLE t1 (id INTEGER);
        CREATE TRIGGER audit_log $$
            INSERT INTO log (msg) VALUES ('created');
            UPDATE counter SET n = n + 1;
        $$;
        """
        stmts = _split_statements(sql)
        assert len(stmts) == 2
        # The block should be preserved as one statement
        assert "INSERT INTO log" in stmts[1]
        assert "UPDATE counter" in stmts[1]


# ── Cache Tests ────────────────────────────────────────────────


class TestCache:
    def test_set_and_get(self):
        c = Cache()
        c.set("key", "value")
        assert c.get("key") == "value"

    def test_get_missing(self):
        c = Cache()
        assert c.get("nope") is None
        assert c.get("nope", "default") == "default"

    def test_ttl_expiry(self):
        c = Cache(default_ttl=1)
        c.set("key", "value", ttl=1)
        assert c.get("key") == "value"
        time.sleep(1.1)
        assert c.get("key") is None

    def test_delete(self):
        c = Cache()
        c.set("key", "value")
        assert c.delete("key") is True
        assert c.get("key") is None
        assert c.delete("key") is False

    def test_clear(self):
        c = Cache()
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size() == 0

    def test_has(self):
        c = Cache()
        c.set("key", "value")
        assert c.has("key") is True
        assert c.has("nope") is False

    def test_tags(self):
        c = Cache()
        c.set("user:1", {"name": "Alice"}, tags=["users"])
        c.set("user:2", {"name": "Bob"}, tags=["users"])
        c.set("post:1", {"title": "Hello"}, tags=["posts"])
        removed = c.clear_tag("users")
        assert removed == 2
        assert c.get("user:1") is None
        assert c.get("post:1") is not None

    def test_max_size_eviction(self):
        c = Cache(max_size=3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.set("d", 4)  # Should evict "a"
        assert c.get("a") is None
        assert c.get("d") == 4

    def test_sweep(self):
        c = Cache()
        c.set("short", "val", ttl=1)
        c.set("long", "val", ttl=300)
        time.sleep(1.1)
        removed = c.sweep()
        assert removed == 1
        assert c.get("long") == "val"

    def test_remember(self):
        c = Cache()
        calls = [0]

        def factory():
            calls[0] += 1
            return "computed"

        assert c.remember("key", 60, factory) == "computed"
        assert c.remember("key", 60, factory) == "computed"
        assert calls[0] == 1  # Factory only called once

    def test_query_key(self):
        k1 = Cache.query_key("SELECT * FROM users", [1])
        k2 = Cache.query_key("SELECT * FROM users", [1])
        k3 = Cache.query_key("SELECT * FROM users", [2])
        assert k1 == k2
        assert k1 != k3
        assert k1.startswith("query:")


class TestCacheWithDatabase:
    def test_cache_query_results(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'cache.db'}")
        db.execute("CREATE TABLE items (id INTEGER, name TEXT)")
        db.execute("INSERT INTO items VALUES (1, 'Widget')")
        db.commit()

        cache = Cache(default_ttl=60)
        key = Cache.query_key("SELECT * FROM items")

        result = cache.remember(key, 60, lambda: db.fetch("SELECT * FROM items"))
        assert result.records[0]["name"] == "Widget"

        # Second call hits cache, not DB
        cached = cache.get(key)
        assert cached.records[0]["name"] == "Widget"

        db.close()
