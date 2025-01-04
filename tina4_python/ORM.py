import base64
from datetime import datetime, date
import inspect
import ast
import json
import os
import tina4_python
from tina4_python.Debug import Debug


def orm(dba):
    Debug("Initializing ORM")
    orm_path = tina4_python.root_path+os.sep+"src"+os.sep+"orm"
    # load and assign

    for file in os.listdir(orm_path):
        mod_name = file.removesuffix(".py")
        if "__init__" not in mod_name and "__pycache__" not in mod_name:
            # import and set the database object
            Debug('from src.orm.'+mod_name+' import ' + mod_name)
            exec('from src.orm.'+mod_name+' import ' + mod_name)
            exec(mod_name+".__dba__ = dba")


class BaseField:
    primary_key = False
    column_type = None
    default_value = None
    column_name = None
    auto_increment = False

    def __init__(self, column_name=None, primary_key=False, default_value=None, auto_increment=False):
        self.primary_key = primary_key
        self.column_type = None
        self.default_value = default_value
        self.auto_increment = auto_increment

        if column_name  is None:
            frame = inspect.stack()[1]
            # Parse python syntax of the assignment line
            st = ast.parse(frame.code_context[0].strip())
            stmt = st.body[0]
            # Assume class being instanced as simple assign statement
            assert(isinstance(stmt, ast.Assign))
            # Parse the target the class is assigned to
            target = stmt.targets[0]
            self.column_name = target.id
        else:
            self.column_name = column_name

class DateTimeField(BaseField):
    column_type = datetime

class IntegerField(BaseField):
    column_type = int

class NumericField(BaseField):
    column_type = float

class StringField(BaseField):
    column_type = str

class TextField(BaseField):
    column_type = str

class BlobField(BaseField):
    column_type = bytes

class ForeignKeyField:
    field_type = None
    references_table = None
    references_column = None

    def __init__(self, field_type=BaseField, references_table=None):
        self.field_type = field_type
        self.references_table = references_table
        self.references_column = field_type.column_name

def json_serialize(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    raise TypeError ("Type %s not serializable" % type(obj))


class ORM:
    __table_name__ = None
    __primary_key__ = "id"
    __dba__ = None

    def __init__(self, init_object=None, table_name=None):
        class_name = self.__class__.__name__
        if self.__table_name__ is None:
            if table_name is None:
                self.__table_name__ = class_name.lower()
            else:
                self.__table_name__ = table_name.lower()
        if init_object is not None:
            self.populate_orm(init_object)
        print(self.__dba__, self.__table_name__, self.__primary_key__)

    def populate_orm(self, init_object):
        print("Populating ORM", init_object)
        pass

    def to_json(self):
        return json.dumps(self.__dict__, default=json_serialize)

    def to_dict(self):
        return self.__dict__

    def __str__(self):
        return self.to_json()

    def load(self, query="", params=[]):

        pass

    def save(self):
        # check if record exists

        # save or update record

        return False

    def delete(self):

        pass
