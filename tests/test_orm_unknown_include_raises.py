"""Regression: a misspelt include= relationship name raises, not silently
ignored.

Bug 8d (book review). _eager_load did ``descriptor = cls._relationships.get(
rel_name); if descriptor is None: continue`` — so include=["autor"] (typo for
"author") loaded nothing and the caller saw an empty relationship with no
error. It now raises ValueError naming the unknown name and the known ones.

Real SQLite (temp file), no mock.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, ForeignKeyField, bind_database


_SUFFIX = uuid.uuid4().hex[:8]


class Author(ORM):
    table_name = f"authors_{_SUFFIX}"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


class Post(ORM):
    table_name = f"posts_{_SUFFIX}"
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    author_id = ForeignKeyField(to=Author, related_name="posts")


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    connection = Database(f"sqlite:///{path}")
    bind_database(connection)
    Author.create_table()
    Post.create_table()
    a = Author({"name": "Ann"}); a.save()
    Post({"title": "Hello", "author_id": a.id}).save()
    yield connection
    connection.close()
    os.unlink(path)


class TestUnknownIncludeRaises:
    def test_negative_unknown_include_raises(self, db):
        """A misspelt relationship name must raise ValueError naming it."""
        with pytest.raises(ValueError) as exc:
            Post.all(include=["autor"])   # typo for the belongs_to "author"
        msg = str(exc.value)
        assert "autor" in msg, "the error must name the bad relationship"
        assert "author" in msg, "the error must list the known relationships"

    def test_positive_correct_include_loads(self, db):
        """The correct name still eager-loads without error (control)."""
        posts = Post.all(include=["author"])
        assert len(posts) == 1
        assert posts[0].author is not None and posts[0].author.name == "Ann"

    def test_negative_unknown_nested_include_raises(self, db):
        """A misspelt name on the has_many side raises too."""
        with pytest.raises(ValueError):
            Author.all(include=["postz"])   # typo for "posts"
