# Tests for tina4_python.orm
import pytest
from tina4_python.database import Database
from tina4_python.orm import ORM, orm_bind, Field, IntField, StrField, BoolField
from tina4_python.orm import has_many, has_one, belongs_to


# ── Test Models ─────────────────────────────────────────────────


class User(ORM):
    table_name = "users"
    id = Field(int, primary_key=True, auto_increment=True)
    name = Field(str, required=True)
    email = Field(str)
    active = Field(bool, default=True)

    # Descriptor-based relationships
    posts = has_many("Post", foreign_key="user_id")
    profile = has_one("Profile", foreign_key="user_id")


class Post(ORM):
    table_name = "posts"
    id = Field(int, primary_key=True, auto_increment=True)
    title = Field(str, required=True)
    body = Field(str)
    user_id = Field(int)
    deleted_at = Field(str)
    soft_delete = True

    # Descriptor-based relationships
    author = belongs_to("User", foreign_key="user_id")
    comments = has_many("Comment", foreign_key="post_id")


class Comment(ORM):
    table_name = "comments"
    id = Field(int, primary_key=True, auto_increment=True)
    text = Field(str)
    post_id = Field(int)

    post = belongs_to("Post", foreign_key="post_id")


class Profile(ORM):
    table_name = "profiles"
    id = Field(int, primary_key=True, auto_increment=True)
    bio = Field(str)
    user_id = Field(int)

    owner = belongs_to("User", foreign_key="user_id")


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh database with test tables."""
    db_path = tmp_path / "orm_test.db"
    d = Database(f"sqlite:///{db_path}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, active INTEGER DEFAULT 1)")
    d.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT, user_id INTEGER, deleted_at TEXT)")
    d.execute("CREATE TABLE comments (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, post_id INTEGER)")
    d.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY AUTOINCREMENT, bio TEXT, user_id INTEGER)")
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


# ── Descriptor Relationship Tests ──────────────────────────────


class TestDescriptorRelationships:
    """Tests for descriptor-based ORM relationships (has_many, has_one, belongs_to)."""

    def test_has_many_lazy_load(self, db):
        user = User({"name": "Alice"}).save()
        db.commit()
        Post({"title": "P1", "user_id": user.id}).save()
        Post({"title": "P2", "user_id": user.id}).save()
        db.commit()

        # Lazy load via descriptor
        posts = user.posts
        assert len(posts) == 2
        assert posts[0].title in ("P1", "P2")

    def test_has_one_lazy_load(self, db):
        user = User({"name": "Bob"}).save()
        db.commit()
        Profile({"bio": "Hello", "user_id": user.id}).save()
        db.commit()

        profile = user.profile
        assert profile is not None
        assert profile.bio == "Hello"

    def test_belongs_to_lazy_load(self, db):
        user = User({"name": "Carol"}).save()
        db.commit()
        post = Post({"title": "Post1", "user_id": user.id}).save()
        db.commit()

        author = post.author
        assert author is not None
        assert author.name == "Carol"

    def test_relationship_cache(self, db):
        user = User({"name": "Dave"}).save()
        db.commit()
        Post({"title": "Cached", "user_id": user.id}).save()
        db.commit()

        # First access loads
        posts1 = user.posts
        # Second access returns cached
        posts2 = user.posts
        assert posts1 is posts2  # Same object reference

    def test_cache_clears_on_save(self, db):
        user = User({"name": "Eve"}).save()
        db.commit()
        Post({"title": "Before", "user_id": user.id}).save()
        db.commit()

        _ = user.posts  # Load cache
        assert "_rel_cache" in user.__dict__
        user.name = "Eve Updated"
        user.save()
        db.commit()
        assert user._rel_cache == {}

    def test_has_many_empty_descriptor(self, db):
        user = User({"name": "Lonely"}).save()
        db.commit()
        assert user.posts == []

    def test_has_one_none(self, db):
        user = User({"name": "NoProfile"}).save()
        db.commit()
        assert user.profile is None

    def test_nested_relationships(self, db):
        user = User({"name": "Frank"}).save()
        db.commit()
        post = Post({"title": "Post", "user_id": user.id}).save()
        db.commit()
        Comment({"text": "Nice!", "post_id": post.id}).save()
        Comment({"text": "Great!", "post_id": post.id}).save()
        db.commit()

        posts = user.posts
        assert len(posts) == 1
        comments = posts[0].comments
        assert len(comments) == 2


# ── Eager Loading Tests ────────────────────────────────────────


class TestEagerLoading:
    """Tests for eager loading with include parameter."""

    def test_eager_load_has_many(self, db):
        u1 = User({"name": "A"}).save()
        u2 = User({"name": "B"}).save()
        db.commit()
        Post({"title": "P1", "user_id": u1.id}).save()
        Post({"title": "P2", "user_id": u1.id}).save()
        Post({"title": "P3", "user_id": u2.id}).save()
        db.commit()

        users, _ = User.all(include=["posts"])
        assert len(users) == 2
        # Posts should be pre-loaded (no additional queries)
        for u in users:
            assert "posts" in u._rel_cache
        a = [u for u in users if u.name == "A"][0]
        b = [u for u in users if u.name == "B"][0]
        assert len(a.posts) == 2
        assert len(b.posts) == 1

    def test_eager_load_has_one(self, db):
        user = User({"name": "WithProfile"}).save()
        db.commit()
        Profile({"bio": "Bio text", "user_id": user.id}).save()
        db.commit()

        users, _ = User.where("name = ?", ["WithProfile"], include=["profile"])
        assert len(users) == 1
        assert users[0].profile is not None
        assert users[0].profile.bio == "Bio text"

    def test_eager_load_belongs_to(self, db):
        user = User({"name": "Parent"}).save()
        db.commit()
        Post({"title": "Child", "user_id": user.id}).save()
        db.commit()

        posts, _ = Post.where("title = ?", ["Child"], include=["author"])
        assert len(posts) == 1
        assert posts[0].author is not None
        assert posts[0].author.name == "Parent"

    def test_eager_load_nested(self, db):
        user = User({"name": "Deep"}).save()
        db.commit()
        post = Post({"title": "DeepPost", "user_id": user.id}).save()
        db.commit()
        Comment({"text": "C1", "post_id": post.id}).save()
        db.commit()

        users, _ = User.all(include=["posts.comments"])
        u = users[0]
        assert len(u.posts) == 1
        assert len(u.posts[0].comments) == 1
        assert u.posts[0].comments[0].text == "C1"

    def test_find_with_include(self, db):
        user = User({"name": "FindMe"}).save()
        db.commit()
        Post({"title": "Found", "user_id": user.id}).save()
        db.commit()

        found = User.find(user.id, include=["posts"])
        assert found is not None
        assert len(found.posts) == 1


# ── to_dict with Include Tests ─────────────────────────────────


class TestToDictInclude:
    """Tests for to_dict with include parameter."""

    def test_to_dict_with_has_many(self, db):
        user = User({"name": "Alice"}).save()
        db.commit()
        Post({"title": "Hello", "user_id": user.id}).save()
        db.commit()

        d = user.to_dict(include=["posts"])
        assert "posts" in d
        assert len(d["posts"]) == 1
        assert d["posts"][0]["title"] == "Hello"

    def test_to_dict_with_nested(self, db):
        user = User({"name": "Bob"}).save()
        db.commit()
        post = Post({"title": "Test", "user_id": user.id}).save()
        db.commit()
        Comment({"text": "Reply", "post_id": post.id}).save()
        db.commit()

        d = user.to_dict(include=["posts.comments"])
        assert "posts" in d
        assert "comments" in d["posts"][0]
        assert d["posts"][0]["comments"][0]["text"] == "Reply"

    def test_to_dict_with_belongs_to(self, db):
        user = User({"name": "Carol"}).save()
        db.commit()
        post = Post({"title": "Mine", "user_id": user.id}).save()
        db.commit()

        d = post.to_dict(include=["author"])
        assert "author" in d
        assert d["author"]["name"] == "Carol"

    def test_to_dict_none_relationship(self, db):
        user = User({"name": "NoProfile"}).save()
        db.commit()

        d = user.to_dict(include=["profile"])
        assert "profile" in d
        assert d["profile"] is None


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
