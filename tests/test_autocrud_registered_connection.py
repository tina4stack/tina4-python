"""ADR-0069 addendum E: AutoCrud queries through the model's own connection.

A model can be bound to a connection other than the global default, either
directly (``_db = Database(...)``) or by name (``_db = "reporting"`` after
``bind_database(db, name="reporting")``). Every AutoCrud route - list, get,
create, update, delete - must read and write THAT connection, never the global
default.

Proof with two real SQLite files. The global default holds a decoy table with
one different row; the model's own connection holds the real rows. A handler
that fell back to the global connection would list the decoy, miss id 2, and
write into the wrong file. Each file is read back with the stdlib sqlite3
module, independent of the ORM.

NO MOCKS. Real SQLite files, the real Router, dispatched through the real
front controller by TestClient.
"""
from __future__ import annotations

import sqlite3

import pytest

import tina4_python.orm.model as orm_model
from tina4_python.core.router import Router
from tina4_python.crud import AutoCrud
from tina4_python.database import Database
from tina4_python.orm import ORM, IntegerField, StringField, bind_database
from tina4_python.test_client import TestClient

TABLE = "registered_conn_item"


def _make_database(path, rows):
    database = Database(f"sqlite:///{path}")
    database.execute(f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY, name VARCHAR(50))")
    for row in rows:
        database.insert(TABLE, row)
    database.commit()
    return database


def _names(path) -> dict[int, str]:
    with sqlite3.connect(path) as connection:
        return dict(connection.execute(f"SELECT id, name FROM {TABLE} ORDER BY id").fetchall())


@pytest.fixture(params=["direct", "named"])
def two_connections(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    global_path = tmp_path / "global.db"
    registered_path = tmp_path / "registered.db"
    global_db = _make_database(global_path, [{"id": 1, "name": "global-decoy"}])
    registered_db = _make_database(
        registered_path,
        [{"id": 1, "name": "registered-one"}, {"id": 2, "name": "registered-two"}],
    )
    bind_database(global_db)

    if request.param == "direct":
        binding = registered_db
    else:
        bind_database(registered_db, name="registered_conn")
        binding = "registered_conn"

    class RegisteredConnItem(ORM):
        table_name = TABLE
        _db = binding
        id = IntegerField(primary_key=True)
        name = StringField()

    Router.clear()
    AutoCrud.clear()
    AutoCrud.register(RegisteredConnItem, public=True)
    yield global_path, registered_path
    Router.clear()
    AutoCrud.clear()
    orm_model._database = None
    orm_model._databases.pop("registered_conn", None)
    global_db.close()
    registered_db.close()


def test_autocrud_list_uses_the_registered_connection(two_connections):
    global_path, registered_path = two_connections
    client = TestClient()

    listed = client.get(f"/api/{TABLE}")
    assert listed.status == 200, listed.text()
    assert [record["name"] for record in listed.json()["records"]] == [
        "registered-one", "registered-two",
    ]
    assert listed.json()["total"] == 2

    fetched = client.get(f"/api/{TABLE}/2")
    assert fetched.status == 200, fetched.text()
    assert fetched.json()["name"] == "registered-two"

    created = client.post(f"/api/{TABLE}", json={"id": 3, "name": "registered-three"})
    assert created.status == 201, created.text()
    updated = client.put(f"/api/{TABLE}/1", json={"name": "registered-renamed"})
    assert updated.status == 200, updated.text()
    deleted = client.delete(f"/api/{TABLE}/2")
    assert deleted.status in (200, 204), deleted.text()

    registered_rows = _names(registered_path)
    assert registered_rows[1] == "registered-renamed"
    assert 2 not in registered_rows
    assert list(registered_rows.values())[-1] == "registered-three"
    # The global default was never touched.
    assert _names(global_path) == {1: "global-decoy"}
