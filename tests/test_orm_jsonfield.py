# Tests for JSONField — a JSON-document ORM column (dict/list <-> JSON).
#
# NO MOCKS: every test runs against a REAL SQLite database on disk, exercising
# the full path create_table -> save (serialize) -> fetch -> validate (parse).
# The engine-aware DDL type and the native-JSON read normalization (PostgreSQL
# JSONB / MySQL JSON returning already-parsed objects) are additionally covered
# by the gated cross-engine suite in CI; the string-backed path is fully
# exercised here on SQLite.
from __future__ import annotations

import os
import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, IntegerField, StringField, JSONField


@pytest.fixture
def db():
    """A fresh SQLite file per test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite:///{path}")
    yield database
    try:
        database.close()
    except Exception:
        pass
    os.unlink(path)


class Doc(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    payload = JSONField()
    tags = JSONField()


class TestJSONFieldRoundTrip:
    def test_dict_round_trips_as_dict(self, db):
        bind_database(db)
        Doc.create_table()
        doc = Doc({"name": "click", "payload": {"x": 1, "nested": {"a": [1, 2, 3]}}})
        assert doc.save() is doc

        got = Doc.find(doc.id)
        assert isinstance(got.payload, dict)          # not a JSON string
        assert got.payload == {"x": 1, "nested": {"a": [1, 2, 3]}}
        assert got.payload["nested"]["a"] == [1, 2, 3]

    def test_list_round_trips_as_list(self, db):
        bind_database(db)
        Doc.create_table()
        doc = Doc({"name": "tagged", "tags": ["a", "b", "c"]})
        doc.save()

        got = Doc.find(doc.id)
        assert isinstance(got.tags, list)
        assert got.tags == ["a", "b", "c"]

    def test_none_round_trips_as_none(self, db):
        bind_database(db)
        Doc.create_table()
        doc = Doc({"name": "empty"})
        doc.save()

        got = Doc.find(doc.id)
        assert got.payload is None
        assert got.tags is None

    def test_update_replaces_json(self, db):
        bind_database(db)
        Doc.create_table()
        doc = Doc({"name": "v", "payload": {"v": 1}})
        doc.save()

        doc.payload = {"v": 2, "changed": True}
        doc.save()

        got = Doc.find(doc.id)
        assert got.payload == {"v": 2, "changed": True}

    def test_unicode_and_special_chars_survive(self, db):
        bind_database(db)
        Doc.create_table()
        body = {"emoji": "cafe ☕", "quote": 'he said "hi"', "slash": "a/b\\c"}
        doc = Doc({"name": "u", "payload": body})
        doc.save()

        assert Doc.find(doc.id).payload == body


class TestJSONFieldDDL:
    def test_sqlite_maps_to_text(self, db):
        bind_database(db)
        Doc.create_table()
        row = db.fetch_one(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='doc'"
        )
        ddl = row["sql"].upper()
        # Two JSON columns, both TEXT on SQLite (no native JSON type).
        assert "PAYLOAD TEXT" in ddl
        assert "TAGS TEXT" in ddl


class TestJSONFieldValidation:
    def test_json_string_is_parsed_on_read(self, db):
        # A raw JSON string in the column (as a text-backed engine returns)
        # is parsed to a Python object by validate().
        bind_database(db)
        Doc.create_table()
        db.execute(
            "INSERT INTO doc (name, payload) VALUES (?, ?)",
            ["raw", '{"from": "string"}'],
        )
        got = Doc.select_one("SELECT * FROM doc WHERE name = ?", ["raw"])
        assert got.payload == {"from": "string"}

    def test_non_serializable_value_fails_loud(self, db):
        bind_database(db)
        Doc.create_table()
        # A set is not JSON-serializable -> save() fails loud (returns False),
        # never silently drops the row.
        doc = Doc({"name": "bad"})
        doc.payload = {1, 2, 3}
        assert doc.save() is False
        assert doc.payload  # unchanged; nothing was persisted
        assert Doc.select_one("SELECT * FROM doc WHERE name = ?", ["bad"]) is None

    def test_invalid_json_string_rejected(self, db):
        field = JSONField()
        field.name = "payload"
        with pytest.raises(ValueError):
            field.validate("{not valid json")

    def test_scalar_rejected(self, db):
        field = JSONField()
        field.name = "payload"
        with pytest.raises(ValueError):
            field.validate(42)  # not a dict/list


class TestJSONFieldDefault:
    def test_mutable_default_not_shared_between_instances(self, db):
        class WithDefault(ORM):
            id = IntegerField(primary_key=True, auto_increment=True)
            meta = JSONField(default={})

        a = WithDefault()
        b = WithDefault()
        a.meta["only_a"] = True
        assert b.meta == {}, "instances must not alias the same default dict"
