# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Characterization tests for the complexity-round1 refactor.

These pin the CURRENT behaviour of the six functions that carried a cyclomatic
complexity of 40 or more before the refactor, so the behaviour-preserving
decomposition of each can be proven not to change anything a caller sees:

  - ORM.create_table   (orm/model.py)
  - ORM.save           (orm/model.py)
  - Ai._translate_message  (ai/client.py)
  - _resolve           (frond/engine.py)
  - _split_statements  (migration/runner.py)

The ASGI ``app`` entry point in core/server.py is characterised by the existing
real-HTTP contract suites (test_compression_etag_contract, test_file_upload_contract,
test_api_stream_contract, test_http_hardening_contract, test_asgi_bootstrap), which
boot a real uvicorn and drive it over a real socket. No mocks anywhere: the ORM
tests run against a real SQLite database.
"""
from __future__ import annotations

import tempfile

import pytest

from tina4_python.database import Database
from tina4_python.orm import bind_database, ORM
from tina4_python.orm.fields import (
    IntegerField,
    StringField,
    TextField,
    BooleanField,
    DateTimeField,
    NumericField,
    DecimalField,
    BlobField,
    JSONField,
)
from tina4_python.ai.client import Ai
from tina4_python.frond.engine import _resolve
from tina4_python.migration.runner import _split_statements


# ─────────────────────────────────────────────────────────────────────────
# Real SQLite fixture for the ORM (create_table / save) characterization.
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def sqlite_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = Database(f"sqlite:///{tmp.name}")
    bind_database(conn)
    yield conn
    conn.close()


# ─────────────────────────────────────────────────────────────────────────
# ORM.create_table — DDL generation across every field kind (real SQLite).
# ─────────────────────────────────────────────────────────────────────────
class CharAllFields(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(max_length=40)
    bio = TextField()
    active = BooleanField(default=True)
    score = NumericField()
    price = DecimalField(precision=8, scale=3)
    payload = BlobField()
    meta = JSONField()
    created = DateTimeField()
    label = StringField(default="tag")
    count = IntegerField(default=7)


def _column_types(db, table):
    return {c["name"]: (c["type"] or "").upper() for c in db.get_columns(table)}


def test_create_table_all_field_kinds_map_to_sqlite_types(sqlite_db):
    assert CharAllFields.create_table() is True
    assert sqlite_db.table_exists("charallfields") is True
    types = _column_types(sqlite_db, "charallfields")
    assert types["id"] == "INTEGER"
    assert types["name"] == "VARCHAR(40)"
    assert types["bio"] == "TEXT"
    assert types["active"] == "INTEGER"          # SQLite has no native bool
    assert types["score"] == "REAL"
    assert types["price"] == "DECIMAL(8,3)"
    assert types["payload"] == "BLOB"
    assert types["meta"] == "TEXT"               # JSONField -> TEXT on SQLite
    assert types["created"] == "DATETIME"


def test_create_table_is_idempotent_when_table_exists(sqlite_db):
    assert CharAllFields.create_table() is True
    # Second call short-circuits on table_exists and still returns True.
    assert CharAllFields.create_table() is True


def test_create_table_string_and_int_defaults_survive_round_trip(sqlite_db):
    CharAllFields.create_table()
    row = CharAllFields({"name": "x"})
    assert row.save() is not False
    fetched = CharAllFields.find({"name": "x"})
    assert len(fetched) == 1
    assert fetched[0].label == "tag"
    assert fetched[0].count == 7
    assert fetched[0].active in (1, True)


class CharCompositeKey(ORM):
    org = StringField(primary_key=True)
    code = StringField(primary_key=True)
    note = StringField()


def test_create_table_composite_key_is_table_level(sqlite_db):
    assert CharCompositeKey.create_table() is True
    row1 = CharCompositeKey({"org": "acme", "code": "a1", "note": "first"})
    assert row1.save() is not False
    row2 = CharCompositeKey({"org": "acme", "code": "a2", "note": "second"})
    assert row2.save() is not False
    all_rows = sqlite_db.fetch("SELECT * FROM charcompositekey ORDER BY code")
    assert all_rows.count == 2


class CharSoftDelete(ORM):
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()


def test_create_table_injects_is_deleted_for_soft_delete_model(sqlite_db):
    assert CharSoftDelete.create_table() is True
    types = _column_types(sqlite_db, "charsoftdelete")
    assert "is_deleted" in types
    assert types["is_deleted"] == "INTEGER"


# ─────────────────────────────────────────────────────────────────────────
# ORM.save — insert / update / natural key / validation / error hints.
# ─────────────────────────────────────────────────────────────────────────
class CharSaveModel(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)
    tally = IntegerField(default=0)


def test_save_inserts_then_updates_on_autoincrement(sqlite_db):
    CharSaveModel.create_table()
    obj = CharSaveModel({"name": "alpha"})
    assert obj.save() is obj                 # returns self on success
    assert obj.id is not None                # engine assigned the id
    first_id = obj.id
    obj.name = "alpha-2"
    assert obj.save() is obj
    assert obj.id == first_id                # update, not a second insert
    rows = sqlite_db.fetch("SELECT * FROM charsavemodel")
    assert rows.count == 1
    assert rows[0]["name"] == "alpha-2"


class CharNaturalKey(ORM):
    code = StringField(primary_key=True)
    label = StringField()


def test_save_natural_key_inserts_new_row_not_silent_update(sqlite_db):
    CharNaturalKey.create_table()
    assert CharNaturalKey({"code": "GC-100", "label": "one"}).save() is not False
    assert CharNaturalKey({"code": "GC-200", "label": "two"}).save() is not False
    rows = sqlite_db.fetch("SELECT * FROM charnaturalkey ORDER BY code")
    assert rows.count == 2


def test_save_validation_failure_returns_false_and_records_error(sqlite_db):
    CharSaveModel.create_table()
    obj = CharSaveModel({})                   # required 'name' missing
    result = obj.save()
    assert result is False
    assert obj.last_error is not None
    # No row was written — the invalid model never reached the driver.
    assert sqlite_db.fetch("SELECT * FROM charsavemodel").count == 0


class CharNoTable(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True)


def test_save_missing_table_returns_false_with_actionable_hint(sqlite_db):
    # create_table intentionally NOT called.
    obj = CharNoTable({"name": "x"})
    assert obj.save() is False
    assert obj.last_error is not None
    low = obj.last_error.lower()
    assert "does not exist" in low or "no such table" in low
    assert "create_table" in low             # the DX hint is preserved


# ─────────────────────────────────────────────────────────────────────────
# Ai._translate_message — every provider branch (ADR-0061).
# ─────────────────────────────────────────────────────────────────────────
def test_translate_openai_tool_message_to_anthropic():
    msg = {"role": "tool", "tool_call_id": "call_1", "content": "42"}
    out = Ai._translate_message("anthropic", msg)
    assert out == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "42"}
        ],
    }


def test_translate_tool_message_passthrough_openai():
    msg = {"role": "tool", "tool_call_id": "call_1", "content": "42", "extra": "dropped"}
    out = Ai._translate_message("openai", msg)
    assert out == {"role": "tool", "tool_call_id": "call_1", "content": "42"}


def test_translate_openai_tool_calls_to_anthropic_tool_use():
    msg = {
        "role": "assistant",
        "content": "thinking",
        "tool_calls": [
            {"id": "t1", "function": {"name": "add", "arguments": '{"a": 1}'}}
        ],
    }
    out = Ai._translate_message("anthropic", msg)
    assert out["role"] == "assistant"
    assert out["content"][0] == {"type": "text", "text": "thinking"}
    assert out["content"][1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "add",
        "input": {"a": 1},
    }


def test_translate_openai_tool_calls_bad_json_arguments_become_empty():
    msg = {
        "role": "assistant",
        "tool_calls": [{"id": "t1", "function": {"name": "add", "arguments": "not json"}}],
    }
    out = Ai._translate_message("anthropic", msg)
    assert out["content"][0]["input"] == {}


def test_translate_openai_tool_calls_passthrough_openai():
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "t1", "function": {"name": "add", "arguments": "{}"}}],
    }
    out = Ai._translate_message("openai", msg)
    assert out["tool_calls"] == msg["tool_calls"]
    assert out["content"] is None


def test_translate_anthropic_tool_result_split_for_openai():
    msg = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "R1"},
            {"type": "text", "text": "ignored"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "R2"},
        ],
    }
    out = Ai._translate_message("openai", msg)
    assert out == [
        {"role": "tool", "tool_call_id": "t1", "content": "R1"},
        {"role": "tool", "tool_call_id": "t2", "content": "R2"},
    ]


def test_translate_anthropic_tool_result_passthrough_anthropic():
    content = [{"type": "tool_result", "tool_use_id": "t1", "content": "R1"}]
    out = Ai._translate_message("anthropic", {"role": "user", "content": content})
    assert out == {"role": "user", "content": content}


def test_translate_anthropic_tool_use_folds_into_openai_tool_calls():
    msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "add", "input": {"a": 2}},
        ],
    }
    out = Ai._translate_message("openai", msg)
    assert out["role"] == "assistant"
    assert out["content"] == "hi"
    assert out["tool_calls"][0]["id"] == "t1"
    assert out["tool_calls"][0]["function"]["name"] == "add"
    assert out["tool_calls"][0]["function"]["arguments"] == '{"a": 2}'


def test_translate_string_content_passthrough():
    msg = {"role": "user", "content": "hello"}
    assert Ai._translate_message("anthropic", msg) == {"role": "user", "content": "hello"}
    assert Ai._translate_message("openai", msg) == {"role": "user", "content": "hello"}


def test_translate_multimodal_image_per_provider():
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "look"},
            {"type": "image", "source": "https://example.com/x.png"},
        ],
    }
    anth = Ai._translate_message("anthropic", msg)
    assert anth["content"][0] == {"type": "text", "text": "look"}
    assert anth["content"][1] == {
        "type": "image",
        "source": {"type": "url", "url": "https://example.com/x.png"},
    }
    oai = Ai._translate_message("openai", msg)
    assert oai["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/x.png"},
    }


def test_translate_none_content_preserved():
    msg = {"role": "assistant", "content": None}
    assert Ai._translate_message("openai", msg) == {"role": "assistant", "content": None}


# ─────────────────────────────────────────────────────────────────────────
# _resolve — literals, dotted paths, bracket access, method calls.
# ─────────────────────────────────────────────────────────────────────────
def test_resolve_string_literal():
    assert _resolve('"hello"', {}) == "hello"
    assert _resolve("'world'", {}) == "world"


def test_resolve_numeric_literals():
    assert _resolve("42", {}) == 42
    assert _resolve("3.14", {}) == 3.14


def test_resolve_boolean_and_null_literals():
    assert _resolve("true", {}) is True
    assert _resolve("false", {}) is False
    assert _resolve("null", {}) is None
    assert _resolve("none", {}) is None
    assert _resolve("None", {}) is None


def test_resolve_simple_variable_and_dotted_attr():
    class Box:
        def __init__(self):
            self.value = 5
    ctx = {"box": Box(), "name": "andre"}
    assert _resolve("name", ctx) == "andre"
    assert _resolve("box.value", ctx) == 5


def test_resolve_dict_dotted_path():
    ctx = {"user": {"profile": {"city": "cape town"}}}
    assert _resolve("user.profile.city", ctx) == "cape town"


def test_resolve_bracket_int_and_string_key():
    ctx = {"items": ["a", "b", "c"], "balances": {"9600.000": 12}}
    assert _resolve("items[0]", ctx) == "a"
    assert _resolve('balances["9600.000"]', ctx) == 12


def test_resolve_bracket_expression_key():
    ctx = {"items": ["a", "b", "c"], "i": 2}
    assert _resolve("items[i]", ctx) == "c"


def test_resolve_slice():
    ctx = {"items": [0, 1, 2, 3, 4]}
    assert _resolve("items[1:3]", ctx) == [1, 2]
    assert _resolve("items[:2]", ctx) == [0, 1]
    assert _resolve("items[3:]", ctx) == [3, 4]


def test_resolve_list_dot_index():
    ctx = {"items": [{"name": "x"}, {"name": "y"}]}
    assert _resolve("items.1.name", ctx) == "y"


def test_resolve_method_call_on_dict_and_object():
    class Widget:
        def label(self, prefix):
            return f"{prefix}-w"
    ctx = {"w": Widget(), "fns": {"greet": lambda: "hi"}}
    assert _resolve("w.label('a')", ctx) == "a-w"
    assert _resolve("fns.greet()", ctx) == "hi"


def test_resolve_missing_key_returns_none():
    assert _resolve("missing", {}) is None
    assert _resolve("a.b.c", {"a": {}}) is None
    assert _resolve("items[99]", {"items": [1]}) is None


# ─────────────────────────────────────────────────────────────────────────
# _split_statements — quote/comment/block aware scanner (issue #54).
# ─────────────────────────────────────────────────────────────────────────
def test_split_simple_statements():
    assert _split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_split_drops_empty_and_trims():
    assert _split_statements("  SELECT 1 ;; ; SELECT 2 ") == ["SELECT 1", "SELECT 2"]


def test_split_semicolon_inside_line_comment_does_not_split():
    sql = "SELECT 1 -- a ; b comment\n; SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].startswith("SELECT 1")
    assert stmts[1] == "SELECT 2"


def test_split_block_comment_stripped():
    sql = "SELECT 1 /* ; not a delimiter */ ; SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2


def test_split_semicolon_inside_string_literal_preserved():
    sql = "INSERT INTO t VALUES ('a;b'); SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert "'a;b'" in stmts[0]


def test_split_doubled_quote_escape_in_string():
    sql = "INSERT INTO t VALUES ('it''s; fine'); SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert "'it''s; fine'" in stmts[0]


def test_split_double_quoted_identifier_preserved():
    sql = 'CREATE TABLE "a;b" (id INT); SELECT 2'
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert '"a;b"' in stmts[0]


def test_split_dollar_block_keeps_inner_semicolons():
    sql = "CREATE FUNCTION f() AS $$ BEGIN a; b; END $$; SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert "a; b;" in stmts[0]


def test_split_slash_block_keeps_inner_semicolons():
    sql = "CREATE PROC p // a; b; // ; SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert "a; b;" in stmts[0]


def test_split_url_scheme_slashes_are_not_a_block():
    sql = "INSERT INTO t VALUES ('https://a.example/x'); SELECT 2"
    stmts = _split_statements(sql)
    assert len(stmts) == 2


def test_split_set_term_directive_consumed():
    sql = "SET TERM !! ; CREATE PROC p AS BEGIN a; b; END !! SET TERM ; !!"
    stmts = _split_statements(sql)
    # The SET TERM lines are consumed, the proc body survives as one statement.
    assert len(stmts) == 1
    assert "a; b;" in stmts[0]


def test_split_custom_delimiter():
    # A non-special delimiter splits normally (';' is the migration default;
    # '//' and '$$' are reserved as stored-proc block markers, so they are NOT
    # usable as a plain delimiter — that is the current, pinned behaviour).
    assert _split_statements("SELECT 1| SELECT 2", "|") == ["SELECT 1", "SELECT 2"]


def test_split_double_slash_delimiter_is_treated_as_block_marker():
    # Documents the reserved-marker interaction: with delimiter '//', the '//'
    # opens a stored-proc block instead of splitting, so nothing splits.
    assert _split_statements("SELECT 1// SELECT 2", "//") == ["SELECT 1// SELECT 2"]


def test_split_trailing_statement_without_delimiter():
    assert _split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]
