#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import tina4_python
from tina4_python import *
from tina4_python.Database import Database

global dba_type
dba_type = "sqlite3:test2.db"


def test_route_match():
    assert Router.match('/url', '/url') == True, "Test if route matches"


def test_route_match_variable():
    assert Router.match('/url/hello', '/url/{name}') == True, "Test if route matches"


def database_connect(driver, username="", password=""):
    dba = Database(driver, username, password)
    return dba


def test_database_sqlite():
    dba = database_connect(dba_type)
    assert dba.database_engine == dba.SQLITE


def test_database_execute():
    dba = database_connect(dba_type)
    result = dba.execute("drop table if exists test_record")
    assert result.error is None
    result = dba.execute("insert into table with something")
    assert result.error != "", "There should be an error"
    result = dba.execute(
        "create table if not exists test_record(id integer not null, name varchar(200), image blob, primary key (id))")
    assert result.error is None
    result = dba.execute_many("insert into test_record (id, name) values (?, ?)",
                              [[5, "Hello1"], [6, "Hello2"], [7, "Hello3"]])
    dba.commit()
    assert result.error is None
    dba.close()


def test_database_insert():
    dba = database_connect(dba_type)
    result = dba.insert("test_record", {"name": "Test1"})
    assert result.error is None
    assert result.records[0]["id"] == 8
    result = dba.insert("test_record", [{"id": 2, "name": "Test2"}, {"id": 3, "name": "Test3"}])
    assert result.error is None
    result = dba.insert("test_record1", [{"id": 2, "name": "Test2"}, {"id": 3, "name": "Test3"}])
    assert result is False
    dba.commit()
    dba.close()



def test_database_update():
    dba = database_connect(dba_type)
    result = dba.update("test_record", {"id": 1, "name": "Test1Update"})
    assert result is True
    result = dba.update("test_record", [{"id": 2, "name": "Test2Update"}, {"id": 3, "name": "Test3Update"}])
    assert result is True
    dba.commit()
    result = dba.update("test_record", {"id": 1, "name1": "Test1Update"})
    assert result is False
    result = dba.update("test_record", [{"id": 2, "name": "Test2Update"}, {"id": 3, "name1": "Test3Update"}])
    assert result is False
    dba.close()


def test_database_fetch():
    dba = database_connect(dba_type)
    result = dba.fetch("select * from test_record", limit=3)
    assert result.count == 3
    assert result.records[1]["name"] == "Test3Update"
    assert result.records[2]["id"] == 5
    assert result.to_json() == '[{"id": 2, "name": "Test2Update", "image": null}, {"id": 3, "name": "Test3Update", "image": null}, {"id": 5, "name": "Hello1", "image": null}]'
    result = dba.fetch("select * from test_record", limit=3, skip=3)
    assert result.records[1]["name"] == "Hello3"
    result = dba.fetch("select * from test_record where id = ?", [3])
    assert result.records[0]["name"] == "Test3Update"
    result = dba.fetch_one("select * from test_record where id = ?", [2])
    assert result["name"] == "Test2Update"
    result = dba.fetch_one("select * from test_record where id = ?", [50])
    assert result is None
    dba.close()



def test_database_bytes_insert():
    dba = database_connect(dba_type)
    with open("./src/public/images/logo.png", "rb") as file:
        image_bytes = file.read()

    result = dba.update("test_record", {"id": 2, "name": "Test2Update", "image": image_bytes})
    dba.commit()
    result = dba.fetch("select * from test_record where id = 2", limit=3)

    assert isinstance(result.to_json(), object)


def test_database_delete():
    dba = database_connect(dba_type)
    result = dba.delete("test_record", {"id": 1, "name": "Test1Update"})
    dba.commit()
    result = dba.delete("test_record", [{"id": 3}, {"id": 4}])
    assert result is True
    dba.commit()
    result = dba.delete("test", [{"id": 12}, {"id": 13}])
    assert result is False

def test_password():
    auth = Auth(tina4_python.root_path)
    password = auth.hash_password("123456")
    valid = auth.check_password(password, "123456")
    assert valid == True, "Password check"
    password = auth.hash_password("12345678")
    valid = auth.check_password(password, "123456")
    assert valid == False, "Password check"

