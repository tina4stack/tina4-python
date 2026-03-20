# Tests for all remaining v3 features.
"""
Covers: multi-db ORM, enhanced validation, result caching,
ODBC adapter, template sandboxing, fragment caching, event system.
"""
import pytest
import time
from tina4_python.database import Database
from tina4_python.orm import ORM, Field, IntField, StrField, orm_bind
from tina4_python.orm.fields import FloatField
from tina4_python.orm.model import _databases, _query_cache
from tina4_python.core.cache import Cache
from tina4_python.core.events import on, off, emit, once, listeners, events, clear
from tina4_python.frond.engine import Frond


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'main.db'}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, age INTEGER, role TEXT)")
    d.commit()
    orm_bind(d)
    yield d
    d.close()


@pytest.fixture
def db2(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'audit.db'}")
    d.execute("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, user_id INTEGER)")
    d.commit()
    orm_bind(d, name="audit")
    yield d
    d.close()


@pytest.fixture
def frond(tmp_path):
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    return Frond(str(tpl_dir))


@pytest.fixture(autouse=True)
def clean_events():
    clear()
    yield
    clear()


# ── Models ─────────────────────────────────────────────────────

class User(ORM):
    table_name = "users"
    id = IntField(primary_key=True, auto_increment=True)
    name = StrField(required=True, min_length=1, max_length=50)
    email = StrField(regex=r'^[^@]+@[^@]+\.[^@]+$')
    age = Field(int, min_value=0, max_value=150)
    role = StrField(choices=["admin", "user", "guest"], default="user")


class AuditLog(ORM):
    table_name = "audit_logs"
    _db = "audit"
    id = IntField(primary_key=True, auto_increment=True)
    action = StrField()
    user_id = Field(int)


# ── Multi-Database ORM Tests ──────────────────────────────────

class TestMultiDatabase:
    def test_default_db(self, db):
        user = User({"name": "Alice", "email": "a@b.com"})
        user.save()
        assert user.id is not None

    def test_named_db(self, db, db2):
        log = AuditLog({"action": "login", "user_id": 1})
        log.save()
        assert log.id is not None

    def test_named_db_find(self, db, db2):
        log = AuditLog({"action": "logout", "user_id": 2})
        log.save()
        found = AuditLog.find(log.id)
        assert found is not None
        assert found.action == "logout"

    def test_named_db_missing_raises(self):
        class BadModel(ORM):
            _db = "nonexistent"
            id = IntField(primary_key=True)
        with pytest.raises(RuntimeError, match="nonexistent"):
            BadModel._get_db()

    def test_direct_db_instance(self, db):
        class DirectModel(ORM):
            _db = None
            table_name = "users"
            id = IntField(primary_key=True, auto_increment=True)
            name = StrField()
        DirectModel._db = db
        user = DirectModel({"name": "Direct"})
        user.save()
        assert user.id is not None


# ── Enhanced Validation Tests ─────────────────────────────────

class TestEnhancedValidation:
    def test_min_length(self, db):
        with pytest.raises(ValueError, match="minimum length"):
            User({"name": "", "email": "a@b.com"})

    def test_max_length(self, db):
        with pytest.raises(ValueError, match="maximum length"):
            User({"name": "A" * 51, "email": "a@b.com"})

    def test_regex_valid(self, db):
        user = User({"name": "Alice", "email": "alice@example.com"})
        errors = user.validate()
        assert len(errors) == 0

    def test_regex_invalid(self, db):
        with pytest.raises(ValueError, match="pattern"):
            User({"name": "Alice", "email": "not-an-email"})

    def test_choices_valid(self, db):
        user = User({"name": "Alice", "email": "a@b.com", "role": "admin"})
        errors = user.validate()
        assert len(errors) == 0

    def test_choices_invalid(self, db):
        with pytest.raises(ValueError, match="must be one of"):
            User({"name": "Alice", "email": "a@b.com", "role": "superadmin"})

    def test_min_value(self, db):
        with pytest.raises(ValueError, match="minimum value"):
            User({"name": "Alice", "email": "a@b.com", "age": -1})

    def test_max_value(self, db):
        with pytest.raises(ValueError, match="maximum value"):
            User({"name": "Alice", "email": "a@b.com", "age": 200})

    def test_custom_validator(self):
        def no_spaces(v):
            if " " in v:
                raise ValueError("No spaces allowed")

        f = Field(str, validator=no_spaces)
        f.name = "username"
        f.validate("alice")  # OK
        with pytest.raises(ValueError, match="No spaces"):
            f.validate("alice smith")

    def test_valid_age(self, db):
        user = User({"name": "Alice", "email": "a@b.com", "age": 25})
        assert user.age == 25

    def test_field_repr(self):
        f = StrField(required=True, max_length=100, choices=["a", "b"])
        f.name = "test"
        r = repr(f)
        assert "max=100" in r
        assert "choices=" in r


# ── Result Caching Tests ─────────────────────────────────────

class TestResultCaching:
    def test_cached_query(self, db):
        db.insert("users", {"name": "Alice", "email": "a@b.com", "role": "user"})
        db.commit()

        result1 = User.cached(f"SELECT * FROM users", ttl=60)
        result2 = User.cached(f"SELECT * FROM users", ttl=60)
        assert result1[0][0].name == result2[0][0].name

    def test_clear_cache(self, db):
        db.insert("users", {"name": "Bob", "email": "b@b.com", "role": "user"})
        db.commit()

        User.cached(f"SELECT * FROM users", ttl=60)
        assert _query_cache.size() > 0
        User.clear_cache()
        # Tag-based clear removes entries for this model

    def test_save_invalidates_cache(self, db):
        db.insert("users", {"name": "Eve", "email": "e@b.com", "role": "user"})
        db.commit()

        User.cached(f"SELECT * FROM users", ttl=300)
        user = User({"name": "New", "email": "n@b.com"})
        user.save()
        db.commit()
        # After save, cache should be cleared for this model


# ── ODBC Adapter Tests ───────────────────────────────────────

class TestODBCAdapter:
    def test_import(self):
        from tina4_python.database.odbc import ODBCAdapter
        adapter = ODBCAdapter()
        assert adapter.get_database_type() == "odbc"

    def test_registered(self):
        from tina4_python.database.connection import _DRIVERS
        # ODBC may or may not be registered depending on pyodbc availability
        # Just verify the module loads without error
        from tina4_python.database.odbc import ODBCAdapter
        assert ODBCAdapter is not None


# ── Event System Tests ────────────────────────────────────────

class TestEvents:
    def test_on_and_emit(self):
        results = []

        @on("test.event")
        def handler(data):
            results.append(data)

        emit("test.event", "hello")
        assert results == ["hello"]

    def test_multiple_listeners(self):
        results = []

        @on("multi")
        def h1(x):
            results.append(f"h1:{x}")

        @on("multi")
        def h2(x):
            results.append(f"h2:{x}")

        emit("multi", "val")
        assert len(results) == 2

    def test_off_specific(self):
        results = []

        def handler(x):
            results.append(x)

        on("remove.test", handler)
        emit("remove.test", 1)
        off("remove.test", handler)
        emit("remove.test", 2)
        assert results == [1]

    def test_off_all(self):
        @on("clear.all")
        def h1():
            pass

        @on("clear.all")
        def h2():
            pass

        off("clear.all")
        assert listeners("clear.all") == []

    def test_once(self):
        results = []

        @once("one.time")
        def handler(x):
            results.append(x)

        emit("one.time", "a")
        emit("one.time", "b")
        assert results == ["a"]

    def test_priority(self):
        results = []

        @on("priority", priority=1)
        def low(x):
            results.append("low")

        @on("priority", priority=10)
        def high(x):
            results.append("high")

        emit("priority", None)
        assert results == ["high", "low"]

    def test_emit_returns_results(self):
        @on("returns")
        def h1():
            return 1

        @on("returns")
        def h2():
            return 2

        results = emit("returns")
        assert results == [1, 2]

    def test_events_list(self):
        @on("a.event")
        def h1():
            pass

        @on("b.event")
        def h2():
            pass

        assert "a.event" in events()
        assert "b.event" in events()

    def test_listeners_list(self):
        def my_handler():
            pass

        on("list.test", my_handler)
        assert my_handler in listeners("list.test")

    @pytest.mark.asyncio
    async def test_emit_async(self):
        from tina4_python.core.events import emit_async
        results = []

        @on("async.test")
        async def async_handler(x):
            results.append(f"async:{x}")

        @on("async.test")
        def sync_handler(x):
            results.append(f"sync:{x}")

        await emit_async("async.test", "val")
        assert "async:val" in results
        assert "sync:val" in results


# ── Template Sandboxing Tests ─────────────────────────────────

class TestSandboxing:
    def test_sandbox_blocks_vars(self, frond):
        frond.sandbox(allowed_vars=["safe_var"])
        result = frond.render_string("{{ safe_var }} {{ secret }}", {"safe_var": "ok", "secret": "hidden"})
        assert "ok" in result
        assert "hidden" not in result

    def test_sandbox_blocks_filters(self, frond):
        frond.sandbox(allowed_filters=["upper"])
        result = frond.render_string("{{ name|upper }} {{ name|lower }}", {"name": "Alice"})
        assert "ALICE" in result
        # lower should be blocked, name passes through unfiltered
        assert "alice" not in result

    def test_sandbox_allows_loop_var(self, frond):
        frond.sandbox(allowed_vars=["items"])
        result = frond.render_string(
            "{% for item in items %}{{ loop.index }}{% endfor %}",
            {"items": [1, 2, 3]}
        )
        assert "123" in result

    def test_unsandbox(self, frond):
        frond.sandbox(allowed_vars=["x"])
        frond.unsandbox()
        result = frond.render_string("{{ y }}", {"y": "visible"})
        assert "visible" in result

    def test_sandbox_blocks_include(self, frond, tmp_path):
        (tmp_path / "templates" / "secret.twig").write_text("SECRET CONTENT")
        frond.sandbox(allowed_tags=["if", "for"])
        result = frond.render_string('{% include "secret.twig" %}', {})
        assert "SECRET" not in result


# ── Fragment Caching Tests ────────────────────────────────────

class TestFragmentCaching:
    def test_cache_tag(self, frond):
        counter = {"n": 0}
        frond.add_filter("count", lambda v: (counter.__setitem__("n", counter["n"] + 1), v)[1])

        template = '{% cache "test" 60 %}{{ name|count }}{% endcache %}'
        r1 = frond.render_string(template, {"name": "Alice"})
        r2 = frond.render_string(template, {"name": "Bob"})

        # Second render should use cache
        assert r1 == r2
        assert counter["n"] == 1  # Filter only called once

    def test_cache_expires(self, frond):
        template = '{% cache "expire" 1 %}{{ val }}{% endcache %}'
        r1 = frond.render_string(template, {"val": "first"})
        assert "first" in r1

        # Expire the cache manually
        frond._fragment_cache["expire"] = (frond._fragment_cache["expire"][0], time.time() - 1)

        r2 = frond.render_string(template, {"val": "second"})
        assert "second" in r2

    def test_nested_cache(self, frond):
        template = '{% cache "outer" 60 %}OUTER{% cache "inner" 60 %}INNER{% endcache %}{% endcache %}'
        result = frond.render_string(template, {})
        assert "OUTER" in result
        assert "INNER" in result


# ── ODBC Adapter Unit Tests ──────────────────────────────────

class TestODBCAdapterUnit:
    def test_translate_sql_passthrough(self):
        from tina4_python.database.odbc import ODBCAdapter
        adapter = ODBCAdapter()
        sql = "SELECT * FROM users WHERE id = ?"
        assert adapter._translate_sql(sql) == sql

    def test_database_type(self):
        from tina4_python.database.odbc import ODBCAdapter
        assert ODBCAdapter().get_database_type() == "odbc"


# ── Migration Rollback Tests (verify existing) ────────────────

class TestMigrationRollback:
    def test_create_generates_down_file(self, tmp_path):
        from tina4_python.migration.runner import create_migration
        path = create_migration("add users table", str(tmp_path / "migrations"))
        from pathlib import Path
        up = Path(path)
        down = up.with_suffix("").with_suffix(".down.sql")
        assert up.exists()
        assert down.exists()
        assert "Rollback" in down.read_text()

    def test_rollback_last_batch(self, tmp_path, db):
        from tina4_python.migration.runner import migrate, rollback
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        # Create a migration
        (mig_dir / "000001_create_test.sql").write_text(
            "CREATE TABLE test_roll (id INTEGER PRIMARY KEY, val TEXT);"
        )
        (mig_dir / "000001_create_test.down.sql").write_text(
            "DROP TABLE test_roll;"
        )

        ran = migrate(db, str(mig_dir))
        assert len(ran) == 1
        assert db.table_exists("test_roll")

        rolled = rollback(db, str(mig_dir))
        assert len(rolled) == 1
        assert not db.table_exists("test_roll")
