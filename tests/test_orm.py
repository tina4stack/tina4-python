# Tests for tina4_python.orm
import pytest
from tina4_python.database import Database
from tina4_python.orm import ORM, orm_bind, Field, IntField, StrField, BoolField


# ── Test Models ─────────────────────────────────────────────────


class User(ORM):
    table_name = "users"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str, required=True)
    email = Field(str)
    active = Field(bool, default=True)


class Post(ORM):
    table_name = "posts"
    id = Field(int, primary_key=True, auto_increment=True)
    title = Field(str, required=True)
    body = Field(str)
    user_id = Field(int)
    deleted_at = Field(str)
    soft_delete = True


class Comment(ORM):
    table_name = "comments"
    id = Field(int, primary_key=True, auto_increment=True)
    text = Field(str)
    post_id = Field(int)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh database with test tables."""
    db_path = tmp_path / "orm_test.db"
    d = Database(f"sqlite:///{db_path}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    d.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT, user_id INTEGER, deleted_at TEXT)")
    d.execute("CREATE TABLE comments (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, post_id INTEGER)")
    d.commit()
    orm_bind(d)
    yield d
    d.close()


# ── Field Tests ─────────────────────────────────────────────────


class TestFields:
    """Positive tests for field validation."""

    def test_str_field(self):
        f = Field(str, required=True)
        f.name = "test"
        assert f.validate("hello") == "hello"

    def test_int_field(self):
        f = Field(int)
        f.name = "test"
        assert f.validate("42") == 42

    def test_bool_from_int(self):
        f = Field(bool)
        f.name = "test"
        assert f.validate(1) is True
        assert f.validate(0) is False

    def test_default_value(self):
        f = Field(str, default="fallback")
        f.name = "test"
        assert f.validate(None) == "fallback"

    def test_required_field_with_value(self):
        f = Field(str, required=True)
        f.name = "test"
        assert f.validate("ok") == "ok"


class TestFieldsNegative:
    """Negative tests for field validation."""

    def test_required_field_none(self):
        f = Field(str, required=True)
        f.name = "test"
        with pytest.raises(ValueError, match="required"):
            f.validate(None)

    def test_invalid_type_conversion(self):
        f = Field(int)
        f.name = "test"
        with pytest.raises(ValueError, match="cannot convert"):
            f.validate("not_a_number")


# ── ORM CRUD Tests ──────────────────────────────────────────────


class TestORMCrud:
    """Positive tests for ORM CRUD operations."""

    def test_create_and_find(self, db):
        user = User({"name": "Alice", "email": "alice@test.com"})
        user.save()
        db.commit()

        found = User.find(user.id)
        assert found is not None
        assert found.name == "Alice"
        assert found.email == "alice@test.com"

    def test_auto_increment_id(self, db):
        u1 = User({"name": "First"}).save()
        u2 = User({"name": "Second"}).save()
        db.commit()
        assert u1.id == 1
        assert u2.id == 2

    def test_update(self, db):
        user = User({"name": "Bob"}).save()
        db.commit()
        user.name = "Bob Updated"
        user.save()
        db.commit()

        found = User.find(user.id)
        assert found.name == "Bob Updated"

    def test_delete(self, db):
        user = User({"name": "ToDelete"}).save()
        db.commit()
        uid = user.id
        user.delete()
        db.commit()

        assert User.find(uid) is None

    def test_all(self, db):
        User({"name": "A"}).save()
        User({"name": "B"}).save()
        User({"name": "C"}).save()
        db.commit()

        users, count = User.all()
        assert count == 3
        assert len(users) == 3

    def test_where(self, db):
        User({"name": "Active", "active": True}).save()
        User({"name": "Inactive", "active": False}).save()
        db.commit()

        users, count = User.where("active = ?", [1])
        assert count == 1
        assert users[0].name == "Active"

    def test_select_sql_first(self, db):
        User({"name": "Alice"}).save()
        User({"name": "Bob"}).save()
        db.commit()

        users, count = User.select("SELECT * FROM users ORDER BY name")
        assert users[0].name == "Alice"
        assert users[1].name == "Bob"

    def test_find_or_fail(self, db):
        user = User({"name": "Exists"}).save()
        db.commit()

        found = User.find_or_fail(user.id)
        assert found.name == "Exists"

    def test_to_dict(self, db):
        user = User({"name": "Alice", "email": "a@b.com"})
        d = user.to_dict()
        assert d["name"] == "Alice"
        assert d["email"] == "a@b.com"
        assert "id" in d

    def test_to_json(self, db):
        import json
        user = User({"name": "Alice"})
        data = json.loads(user.to_json())
        assert data["name"] == "Alice"

    def test_default_values(self, db):
        user = User({"name": "Test"})
        assert user.active is True  # Default from field definition


class TestORMCrudNegative:
    """Negative tests for ORM CRUD."""

    def test_find_nonexistent(self, db):
        assert User.find(9999) is None

    def test_find_or_fail_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            User.find_or_fail(9999)

    def test_delete_without_pk(self, db):
        user = User({"name": "NoPK"})
        with pytest.raises(ValueError, match="no primary key"):
            user.delete()

    def test_no_database_bound(self):
        import tina4_python.orm.model as orm_module
        old_db = orm_module._database
        orm_module._database = None
        try:
            with pytest.raises(RuntimeError, match="No database bound"):
                User.find(1)
        finally:
            orm_module._database = old_db


# ── Soft Delete Tests ───────────────────────────────────────────


class TestSoftDelete:
    """Tests for soft delete functionality."""

    def test_soft_delete(self, db):
        post = Post({"title": "My Post", "body": "Content"}).save()
        db.commit()
        pid = post.id

        post.delete()
        db.commit()

        # Should not appear in normal find
        assert Post.find(pid) is None

    def test_soft_delete_sets_deleted_at(self, db):
        post = Post({"title": "Deleted"}).save()
        db.commit()
        post.delete()
        db.commit()
        assert post.deleted_at is not None

    def test_with_trashed(self, db):
        post = Post({"title": "Trashed"}).save()
        db.commit()
        post.delete()
        db.commit()

        posts, count = Post.with_trashed()
        assert count == 1
        assert posts[0].title == "Trashed"

    def test_restore(self, db):
        post = Post({"title": "Restorable"}).save()
        db.commit()
        pid = post.id

        post.delete()
        db.commit()
        assert Post.find(pid) is None

        post.restore()
        db.commit()
        found = Post.find(pid)
        assert found is not None
        assert found.title == "Restorable"

    def test_force_delete(self, db):
        post = Post({"title": "Gone"}).save()
        db.commit()
        pid = post.id

        post.force_delete()
        db.commit()

        # Not even in trashed
        posts, _ = Post.with_trashed(f"id = ?", [pid])
        assert len(posts) == 0


# ── Relationship Tests ──────────────────────────────────────────


class TestRelationships:
    """Tests for ORM relationships."""

    def test_has_many(self, db):
        user = User({"name": "Author"}).save()
        db.commit()

        Post({"title": "Post 1", "user_id": user.id}).save()
        Post({"title": "Post 2", "user_id": user.id}).save()
        db.commit()

        posts = user.has_many(Post)
        assert len(posts) == 2

    def test_has_one(self, db):
        user = User({"name": "Solo"}).save()
        db.commit()
        Post({"title": "Only Post", "user_id": user.id}).save()
        db.commit()

        post = user.has_one(Post)
        assert post is not None
        assert post.title == "Only Post"

    def test_belongs_to(self, db):
        user = User({"name": "Parent"}).save()
        db.commit()
        post = Post({"title": "Child", "user_id": user.id}).save()
        db.commit()

        owner = post.belongs_to(User)
        assert owner is not None
        assert owner.name == "Parent"

    def test_has_many_empty(self, db):
        user = User({"name": "Lonely"}).save()
        db.commit()
        posts = user.has_many(Post)
        assert posts == []


# ── Scope Tests ─────────────────────────────────────────────────


class TestScopes:
    """Tests for reusable query scopes."""

    def test_scope_registration(self, db):
        User.scope("active_users", "active = ?", [1])

        User({"name": "Active", "active": True}).save()
        User({"name": "Inactive", "active": False}).save()
        db.commit()

        users, count = User.active_users()
        assert count == 1
        assert users[0].name == "Active"


# ── Validation Tests ────────────────────────────────────────────


class TestValidation:
    """Tests for field validation."""

    def test_valid_model(self, db):
        user = User({"name": "Valid"})
        errors = user.validate()
        assert errors == []

    def test_missing_required(self, db):
        user = User()  # name is required but not set
        errors = user.validate()
        assert len(errors) == 1
        assert "required" in errors[0]
