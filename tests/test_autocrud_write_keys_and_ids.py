"""ADR-0069 addendum 3: AutoCrud write bodies and id routes.

autocrud_write_body_accepts_only_declared_fields
    A POST/PUT body writes a declared field given by its field name OR by its
    column (``field_mapping`` and ``Field(column=)``), resolved the same way as
    ``find()`` resolves filter keys. Every other key is dropped: an undeclared
    real column, a non-identifier key, ``is_deleted``, and the primary key
    (except a natural key on create).

Every row is read back with the stdlib sqlite3 module, independent of the ORM.
NO MOCKS: a real SQLite file, the real Router, dispatched through the real front
controller by TestClient.
"""
from __future__ import annotations

import sqlite3

import pytest

import tina4_python.orm.model as orm_model
from tina4_python.core.router import Router
from tina4_python.crud import AutoCrud
from tina4_python.database import Database
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
