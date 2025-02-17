#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import pytest
from datetime import datetime
from pika.adapters.blocking_connection import BlockingChannel
import tina4_python
from tina4_python import *
from tina4_python.DatabaseTypes import *
from tina4_python.Database import Database
from tina4_python.Migration import migrate
from tina4_python.ORM import ORM, IntegerField, StringField, DateTimeField, ForeignKeyField, TextField, orm
from tina4_python.Queue import Config, Queue, Producer, Consumer

global dba_type
# docker run --name my-mysql -e MYSQL_ROOT_PASSWORD=secret -p 33066:3306 -d mysql:latest
# docker run --name my-firebird -e ISC_PASSWORD=masterkey  -e FIREBIRD_DATABASE=TEST.FDB -p 30500:3050 -d jacobalberty/firebird:latest
# docker run --name my-mssql -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=Password123 -e MSSQL_PID=Developer -p 14333:1433 mcr.microsoft.com/mssql/server:2022-latest
dba_type = "mysql.connector:localhost/33066:test"

dba_type = "psycopg2:localhost/5432:test"
user_name = "postgres"
password = "password"
dba_type = "sqlite3:test3.db"
dba_type = "mysql.connector:localhost/33066:test"
user_name = "root"
password = "secret"
dba_type = "sqlite3:test3.db"


dba_type = "firebird.driver:localhost/30500:/firebird/data/TEST.FDB"
user_name = "sysdba"
password = "masterkey"
dba_type = "sqlite3:test3.db"

dba_type = "pymssql:localhost/14333:tempdb"
user_name = "sa"
password = "Password123"
dba_type = "sqlite3:test3.db"



def test_auth_payload():
    auth = tina4_auth.get_token({"id": 1, "username": "hello", "date_created": datetime.now()})
    assert str(auth)

def test_route_match():
    assert Router.match('/url', '/url') == True, "Test if route matches"


def test_route_match_variable():
    assert Router.match('/url/hello', '/url/{name}') == True, "Test if route matches"


def database_connect(driver, username="root", password="secret"):
    print("Connecting", driver)
    dba = Database(driver, username, password)
    return dba


def test_database_sqlite():
    dba_type = "sqlite3:test2.db"
    dba = database_connect(dba_type, user_name, password)
    assert dba.database_engine == SQLITE

@pytest.mark.skip
def test_database_mysql():
    dba_type = "mysql.connector:localhost/33066:test"
    dba = database_connect(dba_type)
    assert dba.database_engine == MYSQL

@pytest.mark.skip
def test_database_posgresql():
    dba_type = "psycopg2:localhost/5432:test"
    dba = database_connect(dba_type, "postgres", "password")
    assert dba.database_engine == dba.POSTGRES

@pytest.mark.skip
def test_database_mssql():
    dba_type = "pymssql:localhost/14333:tempdb"
    dba = database_connect(dba_type, "sa", "Password123")
    assert dba.database_engine == MSSQL

def test_database_execute():
    dba = database_connect(dba_type, user_name, password)
    if "firebird" or "mssql" in dba_type:
        if dba.table_exists("test_record"):
            result = dba.execute("drop table test_record")
            dba.commit()
            assert result.error is None
    else:
        result = dba.execute("drop table if exists test_record")
        assert result.error is None
        dba.commit()

    result = dba.execute("insert into table with something")
    assert result.error != "", "There should be an error"
    dba.commit()

    if "pymssql" in dba_type:
        result = dba.execute(
            "create table test_record(id integer identity(1,1) not null, name varchar(200), image varbinary(max), date_created datetime default CURRENT_TIMESTAMP,  age numeric (10,2) default 0.00, primary key(id))"
        )
        dba.execute("SET IDENTITY_INSERT test_record ON")
        dba.commit()
    elif "mysql" in dba_type:
        result = dba.execute(
            "create table if not exists test_record(id integer not null auto_increment, name varchar(200), image longblob, date_created timestamp default CURRENT_TIMESTAMP,  age numeric (10,2) default 0.00, primary key (id))")
    elif "psycopg2" in dba_type:
        result = dba.execute(
            "create table if not exists test_record(id serial primary key, name varchar(200), image bytea, date_created timestamp default CURRENT_TIMESTAMP,  age numeric (10,2) default 0.00)")
    elif "firebird" in dba_type:
        result = dba.execute(
            "create table test_record(id integer not null, name varchar(200), image blob sub_type 0, date_created timestamp default 'now', age numeric (10,2) default 0.00, primary key (id))\n")
    else:
        result = dba.execute(
            "create table if not exists test_record(id integer not null, name varchar(200), image blob, date_created timestamp default CURRENT_TIMESTAMP, age numeric (10,2) default 0.00, primary key (id))\n")
    dba.commit()
    assert result.error is None
    result = dba.execute_many("insert into test_record (id, name) values (?, ?)",
                              [[1, "Hello1"], [2, "Hello2"], [3, "Hello3"]])
    dba.commit()
    assert result.error is None
    dba.close()


def test_database_insert():
    dba = database_connect(dba_type, user_name, password)
    result = dba.insert("test_record", {"id": 4, "name": "Test1"})
    print("TEST RESULT", result)
    assert result.error is None
    print(result)
    assert result.records[0]["id"] == 4
    result = dba.insert("test_record", [{"id": 5, "name": "Test2"}, {"id": 6, "name": "Test3"}])
    assert result.error is None
    dba.commit()
    result = dba.insert("test_record1", [{"id": 7, "name": "Test2"}, {"id": 8, "name": "Test3"}])
    assert result is False
    dba.rollback()
    result = dba.insert("test_record", [{"id": 9, "name": {"id": 1}}, {"id": 10, "name": ["me", "myself", "I"]}])
    assert result.records == [{"id": 9}, {"id": 10}]
    dba.commit()
    dba.close()


def test_database_update():
    dba = database_connect(dba_type, user_name, password)
    result = dba.update("test_record", {"id": 1, "name": "Test1Update"})
    assert result is True
    result = dba.update("test_record", [{"id": 2, "name": "Test2Update"}, {"id": 3, "name": "Test3Update"}])
    assert result is True
    dba.commit()
    result = dba.update("test_record", {"id": 1, "name1": "Test1Update"})
    assert result is False
    dba.rollback()
    result = dba.update("test_record", [{"id": 2, "name": "Test2Update"}, {"id": 3, "name1": "Test3Update"}])
    assert result is False
    dba.rollback()
    result = dba.update("test_record", [{"id": 10, "name": {"id": 2}}, {"id": 11, "name": ["me1", "myself2", "I3"]}])
    assert result is True
    dba.commit()

    dba.close()


def test_database_fetch():
    dba = database_connect(dba_type, user_name, password)

    result = dba.fetch("select id, name, image from test_record order by id", limit=3)
    print(result)
    assert result.count == 3
    assert result.records[1]["name"] == "Test2Update"
    assert result.records[2]["id"] == 3
    assert result.to_json() == '[{"id": 1, "name": "Test1Update", "image": null}, {"id": 2, "name": "Test2Update", "image": null}, {"id": 3, "name": "Test3Update", "image": null}]'
    result = dba.fetch("select * from test_record order by id", limit=3, skip=3)

    for record in result:
        assert  isinstance(record, dict)

    assert result.records[1]["name"] == "Test2"
    result = dba.fetch("select * from test_record where id = ?", [3])
    assert result.records[0]["name"] == "Test3Update"
    result = dba.fetch_one("select * from test_record where id = ?", [2])
    assert result["name"] == "Test2Update"
    result = dba.fetch_one("select * from test_record where id = ?", [50])
    assert result is None
    result = dba.fetch("select * from test_record where id < 3")
    assert result.to_paginate()["recordsTotal"] == 2

    dba.close()


def test_database_bytes_insert():
    dba = database_connect(dba_type, user_name, password)
    with open("./src/public/images/logo.png", "rb") as file:
        image_bytes = file.read()

    result = dba.update("test_record", {"id": 2, "name": "Test2Update", "image": image_bytes})
    dba.commit()
    result = dba.fetch("select * from test_record where id = 2", limit=3)

    assert isinstance(result.to_json(), object)
    dba.close()


def test_database_delete():
    dba = database_connect(dba_type, user_name, password)

    result = dba.delete("test_record", {"id": 1, "name": "Test1Update"})
    assert result is True
    dba.commit()
    result = dba.delete("test_record", [{"id": 3}, {"id": 4}])

    assert result is True
    dba.commit()
    result = dba.delete("test", [{"id": 12}, {"id": 13}])
    assert result is False
    # dba.rollback()
    dba.close()


def test_password():
    auth = Auth(tina4_python.root_path)
    password = auth.hash_password("123456")
    valid = auth.check_password(password, "123456")
    assert valid == True, "Password check"
    password = auth.hash_password("12345678")
    valid = auth.check_password(password, "123456")
    assert valid == False, "Password check"


def test_database_transactions():
    dba = database_connect(dba_type, user_name, password)

    dba.start_transaction()

    dba.insert("test_record", [{"id": 1000, "name": "NEW ONE"}])

    dba.rollback()

    result = dba.fetch("select * from test_record where name = 'NEW ONE'")

    assert result.count == 0

    dba.start_transaction()

    dba.insert("test_record", [{"id": 1000, "name": "NEW ONE"}])

    dba.commit()

    result = dba.fetch("select * from test_record where name = 'NEW ONE'")

    assert result.count == 1

    dba.close()


def test_orm():
    dba = database_connect(dba_type, user_name, password)

    if dba.table_exists("tina4_migration"):
        dba.execute("drop table tina4_migration")
        dba.commit()

    if dba.table_exists("test_user_item"):
        dba.execute("drop table test_user_item")
        dba.commit()
    if dba.table_exists("test_user"):
        dba.execute("drop table test_user")
        dba.commit()

    class TestUser(ORM):
        id = IntegerField(auto_increment=True, primary_key=True, default_value=1)
        first_name = StringField()
        last_name = StringField()
        email = TextField(default_value="test@test.com")
        title = StringField(default_value="Mr")
        date_created = DateTimeField()

    class TestUserItem(ORM):
        id = IntegerField(auto_increment=True, primary_key=True, default_value=1)
        name = StringField(default_value="Item 1")
        user_id = ForeignKeyField(IntegerField("id"), references_table=TestUser())
        date_created = DateTimeField()

    migrate(dba)
    # attach the database connection
    orm(dba)

    print("START")


    user = TestUser({"firstName": "First Name 1", "lastName": "Last Name 1"})
    user.save()

    assert int(user.id) == 1

    test_id = int(user.id)

    print("FIRST ID", user.to_dict())

    user = TestUser()
    user.first_name = "First Name 2"
    user.last_name = "Last Name 2"
    user.save()

    sql = "select * from test_user"
    result = dba.fetch(sql)

    assert result.count == 2


    print ("SECOND ID", user.to_dict())

    assert int(user.id) == int(test_id)+1

    print("END", test_id+1, user.id)

    assert user.id == 2

    assert user.id * 5 == 10

    counter = 0
    for item_value in ["Item 1", "Item 2"]:
        item = TestUserItem()
        # print ("TEST USER ITEM", item.to_dict())
        # item.id = counter+1
        item.name = item_value
        item.user_id = user.id
        item.save()


        print ("USER ITEM ", int(item.id))

        counter += 1

    for item_value in ["Item 3", "Item 4"]:
        item = TestUserItem({"user_id": user.id})
        item.name = item_value
        assert item.save() == True

    user1 = TestUser()
    user1.load("id = ?", [1])

    assert user1.__field_definitions__["id"] == 1
    assert user1.id == 1

    sql = "select * from test_user_item"
    result = dba.fetch(sql)

    assert result.count == 4

    user1.delete()

    sql = "select * from test_user"
    result = dba.fetch(sql)

    assert result.count == 1

    dba.close()

@pytest.mark.skip
def test_queues():
    """
    Tests the queue functionality
    :return:
    """
    config = Config()
    config.litequeue_database_name = "test_queue.db"
    config.prefix = "dev"
    # config.queue_type = "kafka"

    def call_me(queue_, err, data):
        if data is not None and data.status == 1:
            if not isinstance(queue_, BlockingChannel):
                # queue_.done(data.message_id)
                pass
            else:
                queue_.basic_ack(data.delivery_tag)
        print("RESULT", err, data)

    queue = Queue(config)

    producer = Producer(queue, call_me)
    producer.produce({"name": "Andre"}, "andre")
    producer.produce({"moo": "Cow"}, "andre")

    consumer = Consumer(queue, call_me, acknowledge=False)
    consumer.run(1, 20)

    assert queue.config.queue_type != "kafka"

