#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
from datetime import datetime, date
import inspect
import sys
import ast
import json
import os
import tina4_python
from tina4_python.Constant import TINA4_LOG_ERROR, TINA4_LOG_INFO
from tina4_python.Debug import Debug


def find_all_sub_classes(a_class):
    return a_class.__subclasses__()

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
    classes = find_all_sub_classes (ORM)
    for a_class in classes:
        a_class.__dba__ = dba


class BaseField:
    primary_key = False
    column_type = None
    default_value = None
    column_name = None
    auto_increment = False
    value = None
    field_size=None
    decimal_places=None

    def get_definition(self):
        return self.column_name.lower()+" not defined"

    def __eq__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other == self.value

    def __ne__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other != self.value

    def __add__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other + self.value

    def __mul__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other * self.value

    def __sub__(self, other):
        if self.value is None:
            self.value = self.default_value
        return  self.value - other

    def __truediv__(self, other):
        if self.value is None:
            self.value = self.default_value
        return  self.value / other

    def __str__(self):
        if self.value is None:
            self.value = self.default_value
        return str(self.value)

    def __int__(self):
        if self.value is None:
            self.value = self.default_value
        return int(self.value)

    def __float__(self):
        if self.value is None:
            self.value = self.default_value
        return float(self.value)

    def __init__(self, column_name=None, primary_key=False, default_value=None, auto_increment=False, field_size=None, decimal_places=None):
        self.primary_key = primary_key
        self.column_type = None
        if default_value is not None:
            self.default_value = default_value
        self.auto_increment = auto_increment
        if field_size is not None:
            self.field_size = field_size
        if decimal_places is not None:
            self.decimal_places = decimal_places

        if column_name is None:
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
    default_value = datetime.now()

    def get_definition(self):
        return self.column_name.lower()+" timestamp";

class IntegerField(BaseField):
    column_type = int
    default_value = 0

    def get_definition(self):
        not_null = ""
        if self.primary_key:
            not_null = " not null"
        return self.column_name.lower()+" integer default "+str(self.default_value)+" "+not_null

class NumericField(BaseField):
    column_type = float
    default_value = 0.00
    field_size = 10
    decimal_places = 2

    def get_definition(self):
        not_null = ""
        if self.primary_key:
            not_null = " not null"

        return self.column_name.lower()+" numeric("+str(self.field_size)+","+str(self.decimal_places)+") default "+str(self.default_value)+not_null

class StringField(BaseField):
    column_type = str
    default_value = ""
    field_size = 255
    def get_definition(self):
        not_null = ""
        if self.primary_key:
            not_null = " not null"

        return self.column_name.lower()+" varchar("+str(self.field_size)+") default '"+str(self.default_value)+"'"+not_null


class TextField(StringField):
    pass

class BlobField(BaseField):
    column_type = bytes
    default_value = None
    def get_definition(self):
        field_type = "blob"
        return self.column_name.lower()+" "+field_type


class ForeignKeyField:
    field_type = None
    references_table = None
    references_column = None
    primary_key = False
    foreign_key = True
    value = None
    default_value = None

    def __init__(self, field_type=BaseField, references_table=None, column_name=None):
        self.field_type = field_type
        self.references_table = references_table
        self.references_column = field_type.column_name
        if column_name is None:
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

    def get_definition(self):
        references_definition = self.field_type.get_definition().split(" ")
        return self.column_name+" "+references_definition[1]+" references "+self.references_table.__table_name__+"("+self.references_column+") on update cascade on delete cascade"

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

    def __get_table_name__(self, name):
        """
        Gets the table name
        :param name:
        :return:
        """
        if "_" in name:
            return name.lower()
        table_name = ""
        counter = 0
        for c in name:
            if c.isupper() and counter > 0 :
                table_name = table_name + "_"+c.lower()
            else:
                table_name = table_name + c.lower()
            counter += 1
        return table_name

    def __init__(self, init_object=None, table_name=None):
        # save the initial declarations
        counter = 0
        self.__field_definitions__ = {}
        for key in dir(self):
            if not key.startswith('__') and not key.startswith('_') and key not in ['save', 'load', 'delete', 'to_json', 'to_dict']:
                self.__field_definitions__[key] = getattr(self, key)
                counter += 1

        if counter == 0:
            self.__field_definitions__["id"] = IntegerField(default_value=0, auto_increment=True, primary_key=True)

        class_name = self.__class__.__name__
        if self.__table_name__ is None:
            if table_name is None:
                self.__table_name__ = self.__get_table_name__(class_name)
            else:
                self.__table_name__ = table_name.lower()
        if init_object is not None:
            self.__populate_orm(init_object)

        Debug("Checking for ", self.__table_name__, TINA4_LOG_INFO)
        if self.__dba__:
            self.__table_exists = self.__dba__.table_exists(self.__table_name__)
            if not self.__table_exists:
                sql = self.__create_table__(self.__table_name__)
                filename = tina4_python.root_path+os.sep+"migrations"+os.sep+"__"+self.__table_name__+".sql"
                os.makedirs(os.path.dirname(filename), exist_ok=True)
                with open(filename, "w") as f:
                    f.write(sql)
                    f.close()
            Debug("Table Exists ", self.__table_exists, TINA4_LOG_INFO)

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
        return json.dumps(self.to_dict(), default=json_serialize)

    def to_dict(self):
        data = {}
        for key, value in self.__field_definitions__.items():
            value = getattr(self, key)
            if isinstance(value, ForeignKeyField) or isinstance(value, IntegerField) or isinstance(value, DateTimeField) or isinstance(value, BlobField) or isinstance(value, TextField) or isinstance(value, StringField):
                if value.value is not None:
                    data[key] = value.value
                else:
                    if value.auto_increment:
                        # get the max value from table add one
                        sql = "select max("+value.column_name+") as max_id from "+self.__table_name__
                        record = self.__dba__.fetch_one(sql)
                        if record["max_id"] is None:
                            record = {"max_id": 0}
                        data[key] = int(record["max_id"])+1
                        setattr(self, key, data[key])
                    else:
                        data[key] = value.default_value
            else:
                data[key] = value
        return data

    def __str__(self):
        return self.to_json()

    def __create_table__(self, table_name, execute=False):
        sql = "create table "+self.__table_name__+" ("
        counter = 0
        for field, field_definition in self.__field_definitions__.items():
            if counter > 0:
                sql += ",\n"
            sql += "\t"+field_definition.get_definition()
            counter += 1

        primary_keys = self.__get_primary_keys()
        if primary_keys:
            sql += ",\n"
            sql += "\tprimary key ("+",".join(primary_keys)+")"
        sql += "\n);\n"

        if execute:
            self.__dba__.execute(sql)
        else:
            return sql

    def load(self, query="", params=[]):
        if not self.__table_exists:
            Debug("ORM: Load Error - Table", self.__table_name__, "does not exist", TINA4_LOG_ERROR)
            return False
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
        """
        Saves the ORM object to the database
        :return:
        """
        if not self.__table_exists:
            Debug("ORM: Save Error - Table", self.__table_name__, "does not exist", TINA4_LOG_ERROR)
            print (self.__create_table__(self.__table_name__))
            return False
        # check if record exists
        values = self.to_dict()
        primary_keys = self.__get_primary_keys()
        sql = "select count(*) as count_records from "+self.__table_name__+" where "
        counter = 0
        input_params = []
        for key in primary_keys:
            if counter > 0:
                sql += " and "
            sql += key +" = ?"
            input_params.append(values[key])
            counter += 1

        record = self.__dba__.fetch_one(sql, input_params)

        data = self.to_dict()
        if record["count_records"] == 0:
            result = self.__dba__.insert(self.__table_name__, data)
        else:
            result = self.__dba__.update(self.__table_name__, data)

        self.__dba__.commit()
        if result:
            self.load()

        print(result)
        return result

    def delete(self, query="", params=[]):
        if not self.__table_exists:
            Debug("ORM: Load Error - Table", self.__table_name__, "does not exist", TINA4_LOG_ERROR)
            return False
        if query == "":
            sql = f"delete from {self.__table_name__} where "
            primary_keys = self.__get_primary_keys()
            values = self.to_dict()
            counter = 0
            for key in primary_keys:
                if counter > 0:
                    sql += " and "
                sql += key +" = '"+str(values[key])+"'"
                counter += 1
        else:
            sql = f"delete from {self.__table_name__} where {query}"

        if self.__dba__ is not None:
            result = self.__dba__.delete(sql, params)

        if result.error is not None:
            return False
        else:
            return True
