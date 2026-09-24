# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ADR-0069 addendum 3: AutoCrud write bodies and id routes.

autocrud_write_body_accepts_only_declared_fields
    A POST/PUT body writes a declared field given by its field name OR by its
    column (``field_mapping`` and ``Field(column=)``), resolved the same way as
    ``find()`` resolves filter keys. Every other key is dropped: an undeclared
    real column, a non-identifier key, ``is_deleted``, and the primary key
    (except a natural key on create).

autocrud_id_route_addresses_only_that_row
    GET/PUT/DELETE /api/{table}/{id} on a non-first id read or change only that
    row. A non-numeric id is a 404 and changes nothing. (The URL id is bound as a
    parameter: find(pk) -> find_by_id.)

graphql_id_argument_addresses_only_that_row
    The ORM-generated GraphQL single-row query and the update/delete mutations
    touch only the addressed row; a non-matching id changes nothing.

Every row is read back with the stdlib sqlite3 module, independent of the ORM.
NO MOCKS: a real SQLite file, the real Router dispatched through the real front
controller by TestClient, and the real GraphQL executor in-process.
"""
from __future__ import annotations

import sqlite3

import pytest

import tina4_python.orm.model as orm_model
from tina4_python.core.router import Router
from tina4_python.crud import AutoCrud
from tina4_python.database import Database
from tina4_python.graphql import GraphQL
from tina4_python.orm import ORM, IntegerField, StringField
from tina4_python.test_client import TestClient

TABLE = "write_key_item"


class WriteKeyItem(ORM):
    table_name = TABLE
    soft_delete = True
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    display_name = StringField()
    remark = StringField(column="note_col")
    is_deleted = IntegerField(default=0)
    field_mapping = {"display_name": "label_text"}


@pytest.fixture
def crud(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "crud.db"
    database = Database(f"sqlite:///{path}")
    database.execute(
        f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(50),"
        " label_text VARCHAR(50), note_col VARCHAR(50), hidden_col VARCHAR(50),"
        " is_deleted INTEGER DEFAULT 0)"
    )
    database.commit()
    WriteKeyItem._db = database
    Router.clear()
    AutoCrud.clear()
    AutoCrud.register(WriteKeyItem, public=True)
    yield TestClient(), path
    Router.clear()
    AutoCrud.clear()
    WriteKeyItem._db = None
    orm_model._database = None
    database.close()


def _row(path, row_id) -> dict:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(f"SELECT * FROM {TABLE} WHERE id = ?", [row_id]).fetchone()
        return dict(row) if row else {}


def test_autocrud_write_body_accepts_only_declared_fields(crud):
    client, path = crud

    by_name = client.post(f"/api/{TABLE}", json={
        "name": "by-name", "display_name": "D1", "remark": "R1",
        "hidden_col": "undeclared", "na me": "not an identifier",
        "is_deleted": 1, "id": 99,
    })
    assert by_name.status == 201, by_name.text()
    first_id = by_name.json()["id"]
    assert first_id != 99
    first = _row(path, first_id)
    assert (first["name"], first["label_text"], first["note_col"]) == ("by-name", "D1", "R1"), first
    assert first["hidden_col"] is None and first["is_deleted"] == 0, first

    by_column = client.post(f"/api/{TABLE}", json={
        "name": "by-column", "label_text": "D2", "note_col": "R2", "hidden_col": "undeclared",
    })
    assert by_column.status == 201, by_column.text()
    second = _row(path, by_column.json()["id"])
    assert (second["label_text"], second["note_col"], second["hidden_col"]) == ("D2", "R2", None), second

    updated = client.put(f"/api/{TABLE}/{first_id}", json={
        "label_text": "D1-by-column", "hidden_col": "undeclared", "is_deleted": 1,
    })
    assert updated.status == 200, updated.text()
    first = _row(path, first_id)
    assert first["label_text"] == "D1-by-column", first
    assert first["hidden_col"] is None and first["is_deleted"] == 0, first


# ── id routes and GraphQL id arguments ─────────────────────────────────────

ID_TABLE = "id_route_item"


class IdRouteItem(ORM):
    table_name = ID_TABLE
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()


@pytest.fixture
def id_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "ids.db"
    database = Database(f"sqlite:///{path}")
    database.execute(f"CREATE TABLE {ID_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(50))")
    for row_id, name in ((1, "one"), (2, "two"), (3, "three")):
        database.insert(ID_TABLE, {"id": row_id, "name": name})
    database.commit()
    IdRouteItem._db = database
    Router.clear()
    AutoCrud.clear()
    yield path
    Router.clear()
    AutoCrud.clear()
    IdRouteItem._db = None
    orm_model._database = None
    database.close()


def _all_rows(path) -> list[tuple]:
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT id, name FROM {ID_TABLE} ORDER BY id").fetchall()


def test_autocrud_id_route_addresses_only_that_row(id_rows):
    path = id_rows
    AutoCrud.register(IdRouteItem, public=True)
    client = TestClient()

    fetched = client.get(f"/api/{ID_TABLE}/2")
    assert fetched.status == 200 and fetched.json()["name"] == "two", fetched.text()

    updated = client.put(f"/api/{ID_TABLE}/2", json={"name": "two-updated"})
    assert updated.status == 200, updated.text()
    assert _all_rows(path) == [(1, "one"), (2, "two-updated"), (3, "three")]

    deleted = client.delete(f"/api/{ID_TABLE}/2")
    assert deleted.status in (200, 204), deleted.text()
    assert _all_rows(path) == [(1, "one"), (3, "three")]

    for bad_id in ("abc", "2x", "1x"):
        assert client.get(f"/api/{ID_TABLE}/{bad_id}").status == 404, bad_id
        assert client.put(f"/api/{ID_TABLE}/{bad_id}", json={"name": "changed"}).status == 404, bad_id
        assert client.delete(f"/api/{ID_TABLE}/{bad_id}").status == 404, bad_id
    assert _all_rows(path) == [(1, "one"), (3, "three")]


def test_graphql_id_argument_addresses_only_that_row(id_rows):
    path = id_rows
    gql = GraphQL()
    gql.schema.from_orm(IdRouteItem)

    single = gql.execute('{ idrouteitem(id: "2") { id name } }')
    assert single["data"]["idrouteitem"]["name"] == "two", single

    updated = gql.execute('mutation { updateIdRouteItem(id: "2", name: "two-updated") { id name } }')
    assert updated["data"]["updateIdRouteItem"]["name"] == "two-updated", updated
    assert _all_rows(path) == [(1, "one"), (2, "two-updated"), (3, "three")]

    deleted = gql.execute('mutation { deleteIdRouteItem(id: "2") }')
    assert deleted["data"]["deleteIdRouteItem"] is True, deleted
    assert _all_rows(path) == [(1, "one"), (3, "three")]

    for bad_id in ("999", "abc", "1x"):
        assert gql.execute(f'{{ idrouteitem(id: "{bad_id}") {{ id }} }}')["data"]["idrouteitem"] is None
        missed = gql.execute(f'mutation {{ updateIdRouteItem(id: "{bad_id}", name: "changed") {{ id }} }}')
        assert missed["data"]["updateIdRouteItem"] is None, (bad_id, missed)
        missed = gql.execute(f'mutation {{ deleteIdRouteItem(id: "{bad_id}") }}')
        assert missed["data"]["deleteIdRouteItem"] is False, (bad_id, missed)
    assert _all_rows(path) == [(1, "one"), (3, "three")]
