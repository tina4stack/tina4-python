import sys
import os
import pytest
from unittest import mock

# Make tina4_python importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from tina4_python.ORM import (
    IntegerField, StringField, DateTimeField, TextField,
    BlobField, NumericField, ForeignKeyField, ORM, orm as orm_initializer
)


# ✅ Shared mock database connection
@pytest.fixture
def mock_dba():
    dba = mock.Mock()
    dba.table_exists.return_value = True  # ✅ Simulate existing tables
    dba.get_next_id.return_value = 101
    dba.fetch_one.return_value = {"count_records": 0}
    dba.insert.return_value = True
    dba.update.return_value = True
    dba.commit.return_value = True
    dba.execute.return_value = mock.Mock(error=None)
    dba.fetch.return_value = mock.Mock(records=[{"id": 1, "first_name": "John"}], count=1)
    return dba


def test_integer_field_properties():
    field = IntegerField(column_name="age", primary_key=True, default_value=10, auto_increment=True)
    assert field.column_name == "age"
    assert field.primary_key is True
    assert int(field) == 10
    assert str(field) == "10"


def test_string_field_definition():
    field = StringField("username", default_value="guest", field_size=50)
    definition = field.get_definition()
    assert "varchar(50)" in definition
    assert "guest" in definition


def test_foreign_key_definition():
    user_field = IntegerField("id", primary_key=True)
    fk = ForeignKeyField(user_field, references_table=mock.Mock(__table_name__="users"))
    definition = fk.get_definition()
    assert "references users(id)" in definition


def test_orm_init_and_to_dict(mock_dba):
    class User(ORM):
        id = IntegerField(auto_increment=True, primary_key=True)
        first_name = StringField()
        last_name = StringField(default_value="Tester")

    User.__dba__ = mock_dba
    user = User({"firstName": "John"})
    data = user.to_dict()
    assert data["first_name"] == "John"
    assert data["last_name"] == "Tester"


def test_orm_save_insert(mock_dba):
    class User(ORM):
        id = IntegerField(auto_increment=True, primary_key=True)
        name = StringField()

    User.__dba__ = mock_dba
    user = User({"name": "Tina"})
    saved = user.save()
    assert saved is True


def test_orm_delete(mock_dba):
    class User(ORM):
        id = IntegerField(auto_increment=True, primary_key=True)
        name = StringField()

    User.__dba__ = mock_dba
    user = User({"name": "Tina", "id": 1})
    deleted = user.delete()
    assert deleted is True


def test_orm_select(mock_dba):
    class User(ORM):
        id = IntegerField(auto_increment=True, primary_key=True)
        first_name = StringField()

    User.__dba__ = mock_dba
    user = User()
    records = user.select("id,first_name", filter="id = ?", params=[1])
    assert isinstance(records.records, list)
    assert records.count == 1


def test_orm_initializer_creates_classes(tmp_path, mock_dba):
    # Create a fake Tina4 root path structure with one mock ORM file
    fake_root = tmp_path / "fake_project"
    orm_dir = fake_root / "src" / "orm"
    orm_dir.mkdir(parents=True)

    test_model_path = orm_dir / "test_model.py"
    test_model_path.write_text("class test_model:\n    __dba__ = None")

    # ✅ Patch the global `root_path` used inside `orm()` function
    with mock.patch.dict(orm_initializer.__globals__, {"root_path": str(fake_root)}):
        orm_initializer(mock_dba)

    assert test_model_path.exists()


def test_create_table_sql_generation(mock_dba):
    class User(ORM):
        id = IntegerField(primary_key=True, auto_increment=True)
        name = StringField()

    User.__dba__ = mock_dba
    user = User({"name": "Test"})
    sql = user.__create_table__("test_user")
    assert "create table" in sql.lower()
    assert "primary key" in sql.lower()
