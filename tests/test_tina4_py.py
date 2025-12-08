#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import pytest
from datetime import datetime

import tina4_python
from tina4_python import *
from tina4_python.DatabaseTypes import *
from tina4_python.Database import Database
from tina4_python.Migration import migrate
from tina4_python.ORM import ORM, IntegerField, StringField, DateTimeField, ForeignKeyField, TextField, orm, JSONBField, NumericField
from tina4_python.Queue import Config, Queue, Producer, Consumer

# Use SQLite for reliable, fast tests — works on every machine
DBA_TYPE = "sqlite3:test.db"
USERNAME = ""
PASSWORD = ""

def database_connect(driver=DBA_TYPE, username=USERNAME, password=PASSWORD):
    print(f"Connecting to {driver}")
    return Database(driver, username, password)

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

def test_database_sqlite():
    dba = database_connect()
    assert dba.database_engine == SQLITE

def test_database_execute():
    dba = database_connect()

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
    dba.close()

def test_database_insert():
    dba = database_connect()

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

    # Auto-increment
    result = dba.insert("test_record", {"name": "Auto1"})
    assert result.records[0]["id"] > 6

    result = dba.insert("test_record", {"name": "Auto2"})
    last_id = result.records[0]["id"]

    # NULL or empty id → auto-increment
    result = dba.insert("test_record", {"id": None, "name": "NullID"})
    assert result.records[0]["id"] == last_id + 1

    result = dba.insert("test_record", {"id": "", "name": "EmptyID"})
    assert result.records[0]["id"] == last_id + 2

    dba.commit()
    dba.close()

def test_database_update():
    dba = database_connect()

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

    dba.close()

def test_database_fetch():
    dba = database_connect()

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

    dba.close()

def test_database_bytes_insert():
    dba = database_connect()

    try:
        with open("./src/public/images/logo.png", "rb") as f:
            image = f.read()
        result = dba.update("test_record", {"id": 1, "image": image})
        dba.commit()

        result = dba.fetch("select image from test_record where id = 1")
        assert len(result.records[0]["image"]) > 100  # reasonable size
    except FileNotFoundError:
        print("logo.png not found — skipping image test")

    dba.close()

def test_database_delete():
    dba = database_connect()

    result = dba.delete("test_record", {"id": 1})
    assert result is True
    dba.commit()

    result = dba.delete("test_record", [{"id": 2}, {"id": 3}])
    assert result is True
    dba.commit()

    result = dba.delete("nonexistent", {"id": 1})
    assert result is False

    dba.close()

def test_password():
    auth = Auth(tina4_python.root_path)
    password = auth.hash_password("123456")
    assert auth.check_password(password, "123456") is True
    assert auth.check_password(password, "wrong") is False

def test_database_transactions():
    dba = database_connect()

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

    dba.close()

def test_orm():
    dba = database_connect()

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

    dba.close()

# Optional queue test — skip if no RabbitMQ
@pytest.mark.skip(reason="Requires RabbitMQ running")
def test_queues():
    config = Config()
    config.litequeue_database_name = "test_queue.db"
    config.prefix = "test"

    def callback(queue, err, data):
        print("Received:", data)

    queue = Queue(config)
    producer = Producer(queue, callback)
    producer.produce({"hello": "world"}, "test")

    consumer = Consumer(queue, callback)
    consumer.run(1, 1)  # run for 1 second

    assert True  # if we get here without crash → good