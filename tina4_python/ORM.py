import base64
from datetime import datetime, date
import inspect
import ast
import json
import os
import tina4_python
from tina4_python.Constant import TINA4_LOG_ERROR
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
    value = None

    def __str__(self):
        return str(self.value)

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
    default_value = 0

class NumericField(BaseField):
    column_type = float
    default_value = 0.00

class StringField(BaseField):
    column_type = str
    default_value = ""

class TextField(BaseField):
    column_type = str
    default_value = ""

class BlobField(BaseField):
    column_type = bytes
    default_value = None

class ForeignKeyField:
    field_type = None
    references_table = None
    references_column = None
    primary_key = False
    foreign_key = True
    value = None
    default_value = None

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
    __dba__ = None
    __field_definitions__ = {}

    def __init__(self, init_object=None, table_name=None):
        # save the initial declarations
        counter = 0
        for key in dir(self):
            if not key.startswith('__') and not key.startswith('_') and key not in ['save', 'load', 'delete', 'to_json', 'to_dict']:
                self.__field_definitions__[key] = getattr(self, key)
                counter += 1

        if counter == 0:
            self.__field_definitions__["id"] = IntegerField(default_value=0, auto_increment=True, primary_key=True)

        class_name = self.__class__.__name__
        if self.__table_name__ is None:
            if table_name is None:
                self.__table_name__ = class_name.lower()
            else:
                self.__table_name__ = table_name.lower()
        if init_object is not None:
            self.__populate_orm(init_object)
        print(self.__dba__, self.__table_name__)

    def __populate_orm(self, init_object):
        if isinstance(init_object, str):
            init_object = json.loads(init_object)

        for key,value in init_object.items():
            if key in self.__field_definitions__:
                field_value = self.__field_definitions__[key]
                field_value.value = value
                setattr(self, key, field_value)

    def __get_primary_keys(self):
        primary_keys = []
        for key,value in self.__field_definitions__.items():
            if value.primary_key:
                primary_keys.append(key)

        return primary_keys

    def to_json(self):

        return json.dumps(self.__dict__, default=json_serialize)

    def to_dict(self):
        data = {}
        for key, value in self.__field_definitions__.items():
            print ("DEFINITION", key, getattr(self, key), type(getattr(self, key)))
            if isinstance(value, IntegerField) or isinstance(value, DateTimeField) or isinstance(value, BlobField) or isinstance(value, TextField) or isinstance(value, StringField):

                # print ("HERE", value.value)
                if value.value is not None:
                    data[key] = value.value
                else:
                    data[key] = value.default_value

            else:
                print('OK', key , getattr(self, key))
                data[key] = getattr(self, key)

        return data

    def __str__(self):
        return self.to_json()

    def load(self, query="", params=[]):
        if query == "":
            sql = f"select * from {self.__table_name__} where "
            primary_keys = self.__get_primary_keys()
            values = self.to_dict()
            counter = 0
            for key in primary_keys:
                if counter > 0:
                    sql += " and "
                sql += key +" = '"+str(values[key])+"'"
                counter += 1
        else:
            sql = f"select * from {self.__table_name__} where {query}"

        if self.__dba__ is not None:
            record = self.__dba__.fetch_one(sql, params)
            try:
                if record:
                    for key, value in record.items():
                        if key in self.__field_definitions__:
                            field_value = self.__field_definitions__[key]
                            field_value.value = value
                            setattr(self, key, field_value)

            except Exception as e:
                Debug ("ORM Load Error", str(e), TINA4_LOG_ERROR)
        else:
            Debug("Database not initialized", TINA4_LOG_ERROR)
            return False

    def save(self):
        # check if record exists
        values = self.to_dict()
        primary_keys = self.__get_primary_keys()
        sql = "select count(*) as count_records from "+self.__table_name__+" where "
        counter = 0
        for key in primary_keys:
            if counter > 0:
                sql += " and "
            sql += key +" = '"+str(values[key])+"'"
            counter += 1

        print("SQL", sql, values)
        # save or update record

        return False

    def delete(self):

        pass
