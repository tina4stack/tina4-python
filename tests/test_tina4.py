#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

import tina4_python
from tina4_python import tina4_auth, Constant
from tina4_python.Auth import Auth
from tina4_python.Router import Router
from tina4_python.DatabaseTypes import *
from tina4_python.Database import Database
from tina4_python.Migration import migrate
from tina4_python.ORM import ORM, IntegerField, StringField, DateTimeField, ForeignKeyField, TextField, orm, JSONBField, NumericField

# Use SQLite for reliable, fast tests — works on every machine
DBA_TYPE = "sqlite3:test.db"
USERNAME = ""
PASSWORD = ""


@pytest.fixture(scope="module")
def dba():
    """Single shared database connection for all DB tests in this module."""
    connection = Database(DBA_TYPE, USERNAME, PASSWORD)
    yield connection
    connection.close()


def test_auth_payload():
    auth = tina4_auth.get_token({"id": 1, "username": "hello", "date_created": datetime.now()})
    token = str(auth)
    assert token != "", "Token should not be empty"
    assert len(token.split(".")) == 3, "JWT should have 3 parts"

def test_route_match():
    assert Router.match('/url', '/url') is True, "Exact route should match"

def test_route_match_variable():
    assert Router.match('/url/hello', '/url/{name}') is True, "Route with variable should match"
    assert Router.match('/url/123', '/url/{id}') is True, "Route with number should match"

def test_database_sqlite(dba):
    assert dba.database_engine == SQLITE

def test_database_execute(dba):
    # Clean up
    dba.execute("drop table if exists test_record")
    dba.commit()

    # Invalid SQL should fail
    result = dba.execute("insert into table with something")
    assert result.error is not None, "Invalid SQL should have error"

    # Create table
    result = dba.execute("""
                         create table test_record (
                                                      id integer primary key,
                                                      name text,
                                                      image blob,
                                                      date_created timestamp default current_timestamp,
                                                      age numeric(10,2) default 0.00,
                                                      json_data text
                         )
                         """)
    assert result.error is None

    # Insert multiple
    result = dba.execute_many(
        "insert into test_record (id, name) values (?, ?)",
        [[1, "Hello1"], [2, "Hello2"], [3, "Hello3"]]
    )
    assert result.error is None
    dba.commit()

def test_database_insert(dba):
    # Clean
    dba.execute("delete from test_record where id >= 4")
    dba.commit()

    # Single insert
    result = dba.insert("test_record", {"id": 4, "name": "Test1"})
    assert result.error is None
    assert result.records[0]["id"] == 4

    # Multiple insert
    result = dba.insert("test_record", [
        {"id": 5, "name": "Test2"},
        {"id": 6, "name": "Test3"}
    ])
    assert result.error is None

    # Invalid table
    result = dba.insert("nonexistent_table", {"id": 99})
    assert result is False

    # Auto-increment (SQLite reuses gaps without AUTOINCREMENT keyword)
    result = dba.insert("test_record", {"name": "Auto1"})
    first_auto_id = result.records[0]["id"]
    assert first_auto_id > 0

    result = dba.insert("test_record", {"name": "Auto2"})
    last_id = result.records[0]["id"]
    assert last_id > first_auto_id

    # NULL or empty id → auto-increment
    result = dba.insert("test_record", {"id": None, "name": "NullID"})
    assert result.records[0]["id"] == last_id + 1

    result = dba.insert("test_record", {"id": "", "name": "EmptyID"})
    assert result.records[0]["id"] == last_id + 2

    dba.commit()

def test_database_update(dba):
    # Update single
    result = dba.update("test_record", {"id": 1, "name": "Updated1"})
    assert result is True

    # Update multiple
    result = dba.update("test_record", [{"id": 2, "name": "Updated2"}, {"id": 3, "name": "Updated3"}])
    assert result is True
    dba.commit()

    # Invalid column
    result = dba.update("test_record", {"id": 1, "nonexistent": "x"})
    assert result is False

def test_database_fetch(dba):
    result = dba.fetch("select * from test_record order by id", limit=3)
    assert result.count >= 3
    assert isinstance(result.records, list)
    assert isinstance(result.records[0], dict)

    result = dba.fetch("select * from test_record where id = ?", [1])
    assert len(result.records) == 1
    assert result.records[0]["name"] == "Updated1"

    result = dba.fetch_one("select * from test_record where id = ?", [1])
    assert result["name"] == "Updated1"

    result = dba.fetch_one("select * from test_record where id = ?", [999])
    assert result is None

    # Search
    result = dba.fetch("select * from test_record", search_columns=["name"], search="Updated")
    assert result.count >= 2

def test_database_bytes_insert(dba):
    try:
        with open("./src/public/images/logo.png", "rb") as f:
            image = f.read()
        result = dba.update("test_record", {"id": 1, "image": image})
        dba.commit()

        result = dba.fetch("select image from test_record where id = 1")
        assert len(result.records[0]["image"]) > 100  # reasonable size
    except FileNotFoundError:
        print("logo.png not found — skipping image test")

def test_database_delete(dba):
    result = dba.delete("test_record", {"id": 1})
    assert result is True
    dba.commit()

    result = dba.delete("test_record", [{"id": 2}, {"id": 3}])
    assert result is True
    dba.commit()

    result = dba.delete("nonexistent", {"id": 1})
    assert result is False

def test_password():
    auth = Auth(tina4_python.root_path)
    password = auth.hash_password("123456")
    assert auth.check_password(password, "123456") is True
    assert auth.check_password(password, "wrong") is False

def test_database_transactions(dba):
    dba.start_transaction()
    dba.insert("test_record", {"name": "TXN"})
    dba.rollback()

    result = dba.fetch("select * from test_record where name = 'TXN'")
    assert result.count == 0

    dba.start_transaction()
    dba.insert("test_record", {"name": "TXN2"})
    dba.commit()

    result = dba.fetch("select * from test_record where name = 'TXN2'")
    assert result.count == 1

def test_orm(dba):
    # Clean slate
    for table in ["tina4_migration", "test_user_item", "test_user"]:
        dba.execute(f"drop table if exists {table}")
    dba.commit()

    class TestUser(ORM):
        id = IntegerField(auto_increment=True, primary_key=True, default_value=1)
        first_name = StringField()
        last_name = StringField()
        email = TextField(default_value="test@test.com")
        title = StringField(default_value="Mr")
        moo=JSONBField(default_value={"name": "Moo"})
        balance = NumericField(default_value=0.00)
        age = IntegerField(default_value=0)
        date_created = DateTimeField()

    class TestUserItem(ORM):
        id = IntegerField(auto_increment=True, primary_key=True, default_value=1)
        name = StringField(default_value="Item 1")
        user_id = ForeignKeyField(IntegerField("id"), references=TestUser())
        date_created = DateTimeField()



    migrate(dba)
    orm(dba)

    TestUser().create_table()
    TestUserItem().create_table()

    # Create user
    user = TestUser()
    user.first_name = "Andre"
    user.last_name = "Cloete"
    user.save()

    assert user.id == 1

    # Load and verify
    user2 = TestUser()
    user2.load(f"id = ?", [1])
    assert user2.first_name == "Andre"

    # JSON field
    user.moo = {"hello": "world", "list": [1,2,3]}
    user.save()
    user.load()
    assert user.moo.value == {"hello": "world", "list": [1,2,3]}

    # Items
    item = TestUserItem()
    item.name = "Laptop"
    item.user_id = user.id
    item.save()

    assert item.id == 1


# --- Connection argument tests (mocked drivers) ---

def _mock_driver():
    """Create a mock database driver module with a connect() method."""
    mock_module = MagicMock()
    mock_module.__name__ = "mock_driver"
    mock_module.connect.return_value = MagicMock()
    return mock_module


@patch("importlib.import_module")
def test_firebird_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(FIREBIRD + ":localhost/3050:/tmp/TEST.FDB", "SYSDBA", "masterkey", charset="UTF8")
    mock_module.connect.assert_called_once_with(
        "localhost/3050:/tmp/TEST.FDB",
        user="SYSDBA",
        password="masterkey",
        charset="UTF8",
    )


@patch("importlib.import_module")
def test_firebird_no_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(FIREBIRD + ":localhost/3050:/tmp/TEST.FDB", "SYSDBA", "masterkey")
    mock_module.connect.assert_called_once_with(
        "localhost/3050:/tmp/TEST.FDB",
        user="SYSDBA",
        password="masterkey",
    )


@patch("importlib.import_module")
def test_mysql_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(MYSQL + ":localhost/3306:mydb", "root", "pass", charset="utf8mb4")
    mock_module.connect.assert_called_once_with(
        database="mydb",
        port=3306,
        host="localhost",
        user="root",
        password="pass",
        consume_results=True,
        charset="utf8mb4",
    )


@patch("importlib.import_module")
def test_mysql_no_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(MYSQL + ":localhost/3306:mydb", "root", "pass")
    mock_module.connect.assert_called_once_with(
        database="mydb",
        port=3306,
        host="localhost",
        user="root",
        password="pass",
        consume_results=True,
    )


@patch("importlib.import_module")
def test_postgres_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(POSTGRES + ":localhost/5432:mydb", "pg", "pass", charset="UTF8")
    mock_module.connect.assert_called_once_with(
        dbname="mydb",
        port=5432,
        host="localhost",
        user="pg",
        password="pass",
        client_encoding="UTF8",
    )


@patch("importlib.import_module")
def test_postgres_no_charset(mock_import):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    Database(POSTGRES + ":localhost/5432:mydb", "pg", "pass")
    mock_module.connect.assert_called_once_with(
        dbname="mydb",
        port=5432,
        host="localhost",
        user="pg",
        password="pass",
    )


@patch("importlib.import_module")
def test_charset_from_env(mock_import, monkeypatch):
    mock_module = _mock_driver()
    mock_import.return_value = mock_module
    monkeypatch.setenv("DATABASE_CHARSET", "WIN1252")
    Database(FIREBIRD + ":localhost/3050:/tmp/TEST.FDB", "SYSDBA", "masterkey")
    mock_module.connect.assert_called_once_with(
        "localhost/3050:/tmp/TEST.FDB",
        user="SYSDBA",
        password="masterkey",
        charset="WIN1252",
    )


# --- Router secured route tests ---

@pytest.mark.asyncio
async def test_secured_route_returns_403():
    """A secured GET route without a valid token must return HTTP 403."""
    # Save and restore global route table
    saved_routes = dict(tina4_python.tina4_routes)
    try:
        # Register a secured GET route
        async def _secret_handler(request, response):
            return response("secret data")

        Router.add(Constant.TINA4_GET, "/test-secured-403", _secret_handler)
        tina4_python.tina4_routes[_secret_handler]["secure"] = True

        result = await Router.get_result(
            "/test-secured-403",
            Constant.TINA4_GET,
            {"params": {}, "body": None},
            {"content-type": "text/html"},
            {},
        )
        assert result.http_code == Constant.HTTP_FORBIDDEN
    finally:
        tina4_python.tina4_routes = saved_routes
