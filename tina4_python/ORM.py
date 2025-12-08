#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
from datetime import datetime, date
import ast
import json
import os
from tina4_python.Constant import TINA4_LOG_ERROR
from tina4_python.Debug import Debug
from tina4_python.FieldTypes import *


def find_all_sub_classes(a_class):
    return a_class.__subclasses__()


def orm(dba):
    from tina4_python import root_path
    Debug("Initializing ORM")
    orm_path = root_path + os.sep + "src" + os.sep + "orm"
    if not os.path.exists(orm_path):
        os.makedirs(orm_path)

    # load and assign
    for file in os.listdir(orm_path):
        if not file.endswith(".py"):
            continue
        mod_name = file.removesuffix(".py")
        if "__init__" not in mod_name and "__pycache__" not in mod_name and ".git" not in mod_name:
            # import and set the database object
            try:
                Debug('from src.orm.' + mod_name + ' import ' + mod_name)
                exec('from src.orm.' + mod_name + ' import ' + mod_name + "\n" + mod_name + ".__dba__ = dba")
            except Exception as e:
                Debug("Failed to import " + mod_name, str(e))
    classes = find_all_sub_classes(ORM)
    for a_class in classes:
        a_class.__dba__ = dba


def json_serialize(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    raise TypeError("Type %s not serializable" % type(obj))


class ORM:
    __table_name__ = None
    __dba__ = None
    __field_definitions__ = {}

    def __get_snake_case_name__(self, name):
        """
        Gets the table name
        :param name:
        :return:
        """
        if "_" in name:
            return name.lower()
        snake_case_name = ""
        counter = 0
        for c in name:
            if c.isupper() and counter > 0:
                snake_case_name = snake_case_name + "_" + c.lower()
            else:
                snake_case_name = snake_case_name + c.lower()
            counter += 1
        return snake_case_name

    def __init__(self, init_object=None, table_name=None):
        from tina4_python import root_path
        # save the initial declarations
        counter = 0
        self.__field_definitions__ = {}
        for key in dir(self):
            if not key.startswith('__') and not key.startswith('_') and key not in ['save', 'load', 'delete', 'to_json',
                                                                                    'to_dict', 'create_table', 'select',
                                                                                    'fetch', 'fetch_one']:
                self.__field_definitions__[key] = getattr(self, key)
                counter += 1

        if counter == 0:
            self.__field_definitions__["id"] = IntegerField(default_value=0, auto_increment=True, primary_key=True)

        class_name = self.__class__.__name__
        if self.__table_name__ is None:
            if table_name is None:
                self.__table_name__ = self.__get_snake_case_name__(class_name)
            else:
                self.__table_name__ = table_name.lower()

        if init_object is not None:
            self.__populate_orm(init_object)
        else:
            self.__populate_orm({})

        # Debug("Checking for", self.__table_name__, TINA4_LOG_INFO)
        if self.__dba__ is not None:
            self.__table_exists = self.__dba__.table_exists(self.__table_name__)
            if not self.__table_exists:
                sql = self.__create_table__(self.__table_name__)
                filename = root_path + os.sep + "migrations" + os.sep + "__" + self.__table_name__ + ".sql"
                os.makedirs(os.path.dirname(filename), exist_ok=True)
                #with open(filename, "w") as f:
                #    f.write(sql)
                #    f.close()
                Debug.warning("Create Table ? ", sql)
        else:
            self.__table_exists = False

    def __populate_orm(self, init_object):
        """
        Populates an ORM object from an input object, also transforms camel case objects to snake case ...
        :param init_object:
        :return:
        """
        for field, field_definition in self.__field_definitions__.items():
            if hasattr(self, field):
                setattr(self, field, None)
                try:
                    field_definition.value = None
                    setattr(self, field, field_definition)
                except Exception as e:
                    print("Could not set attribute for", field, str(e))

        if isinstance(init_object, str):
            init_object = json.loads(init_object)

        for key, value in init_object.items():
            snake_case_name = self.__get_snake_case_name__(key)
            if snake_case_name in self.__field_definitions__:
                try:
                    field_value = self.__field_definitions__[snake_case_name]
                    field_value.value = value
                    if hasattr(self, snake_case_name):
                        setattr(self, snake_case_name, field_value)
                except Exception as e:
                    print("Could not set value for", snake_case_name, str(e))

    def __get_primary_keys(self):
        primary_keys = []
        for key, value in self.__field_definitions__.items():
            if value.primary_key:
                primary_keys.append(key)

        return primary_keys

    def to_json(self):
        """
        Returns a json string
        :return:
        """
        return json.dumps(self.to_dict(), default=json_serialize)

    def __is_class(self, class_name):
        return str(type(class_name)).startswith("<class") and hasattr(class_name, '__weakref__')

    def to_dict(self):
        """
        Returns a Python dictionary
        :return:
        """
        # print(inspect.currentframe().f_back.f_code.co_qualname)
        data = {}

        for key, value in self.__field_definitions__.items():
            current_value = getattr(self, key)

            if current_value is not None and not isinstance(current_value,
                                                            ForeignKeyField) and value.auto_increment and self.__is_class(
                    current_value):
                if current_value.value is None:
                    new_id = self.__dba__.get_next_id(table_name=self.__table_name__, column_name=value.column_name)

                    if new_id is not None:
                        current_value.value = new_id
                    else:
                        current_value.value = current_value.default_value

                data[key] = current_value.value
            elif isinstance(value, IntegerField):
                data[key] = int(current_value)
            else:
                data[key] = str(current_value)

        return data

    def __str__(self):
        return self.to_json()

    def __create_table__(self, table_name, execute=False):
        if self.__dba__ is None:
            Debug.warning("Create Table", table_name, "database not assigned to ORM , use orm(dba)")
            return False
        sql = "create table " + table_name + " ("
        counter = 0
        for field, field_definition in self.__field_definitions__.items():
            if counter > 0:
                sql += ",\n"
            sql += "\t" + field_definition.get_definition(self.__dba__.database_engine)
            counter += 1

        primary_keys = self.__get_primary_keys()
        if primary_keys:
            sql += ",\n"
            sql += "\tprimary key (" + ",".join(primary_keys) + ")"
        sql += "\n);\n"

        if execute:
            self.__dba__.execute(sql)
            return None
        else:
            return sql

    def create_table(self):
        """
        Creates the table for the ORM structure
        :return:
        """
        return self.__create_table__(self.__table_name__, True)

    def __build_sql(self, column_names="*", join="", filter="", group_by="", having="", order_by=""):
        """
        Helper method to build the SQL query
        :param column_names:
        :param join:
        :param filter:
        :param group_by:
        :param having:
        :param order_by:
        :return:
        """
        if isinstance(column_names, str):
            if column_names in ("", "*"):
                cols = "*"
            else:
                cols = ",\n".join(c.strip() for c in column_names.split(','))
        else:
            cols = ",\n".join(column_names)

        group_by = [g.strip() for g in group_by.split(',')] if isinstance(group_by,
                                                                          str) and group_by else group_by if isinstance(
            group_by, list) else []
        having = [h.strip() for h in having.split(',')] if isinstance(having, str) and having else having if isinstance(
            having, list) else []
        order_by = [o.strip() for o in order_by.split(',')] if isinstance(order_by,
                                                                          str) and order_by else order_by if isinstance(
            order_by, list) else []

        sql = f"select {cols}\nfrom {self.__table_name__} as t"
        if join: sql += f"\n{join}"
        if filter: sql += f"\nwhere {filter}"
        if group_by: sql += "\ngroup by " + ", ".join(group_by)
        if having: sql += "\nhaving " + ", ".join(having)
        if order_by: sql += "\norder by " + ", ".join(order_by)
        return sql

    def fetch_one(self, column_names="*", filter="", params=[], join="", group_by="", having="", order_by=""):
        """
        Fetch one record from the database
        :param column_names:
        :param filter:
        :param params:
        :param join:
        :param group_by:
        :param having:
        :param order_by:
        :return:
        """
        sql = self.__build_sql(column_names, join, filter, group_by, having, order_by)
        return self.__dba__.fetch_one(sql, params=params)

    def fetch(self, column_names="*", filter="", params=[], join="", group_by="", having="", order_by="", limit=10,
              skip=0):
        """
        Fetch multiple records from the database
        :param column_names:
        :param filter:
        :param params:
        :param join:
        :param group_by:
        :param having:
        :param order_by:
        :param limit:
        :param skip:
        :return:
        """
        sql = self.__build_sql(column_names, join, filter, group_by, having, order_by)
        return self.__dba__.fetch(sql, params=params, limit=limit, skip=skip)

    def select(self, column_names="*", filter="", params=[], join="", group_by="", having="", order_by="", limit=10,
               skip=0):
        return self.fetch(column_names, filter, params, join, group_by, having, order_by, limit, skip)

    def load(self, query="", params=[]):
        """
        Loads a single record into the object based on the primary key or query if query is set
        :param query:
        :param params:
        :return:
        """
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
                sql += key + " = '" + str(values[key]) + "'"
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
                            if isinstance(self.__field_definitions__[key], JSONBField):
                                try:
                                    field_value.value = ast.literal_eval(value)
                                except Exception as e:
                                    field_value.value = value
                            else:
                                field_value.value = value

                            setattr(self, key, field_value)
                    return True
                else:
                    return False
            except Exception as e:
                Debug("ORM Load Error", str(e), TINA4_LOG_ERROR)
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
            return False
        # check if record exists
        data = self.to_dict()

        primary_keys = self.__get_primary_keys()
        sql = "select count(*) as \"count_records\" from " + self.__table_name__ + " where "
        counter = 0
        input_params = []
        for key in primary_keys:
            if counter > 0:
                sql += " and "
            sql += key + " = ?"
            input_params.append(data[key])
            counter += 1

        try:
            record = self.__dba__.fetch_one(sql, input_params)
            for key, value in data.items():
                if key in self.__field_definitions__:
                    if type(value) == JSONBField and (isinstance(value, dict) or isinstance(value, list)) or (
                            isinstance(value, str) and value.startswith("{") and value.endswith("}")):
                        data[key] = ast.literal_eval(value)

            if record["count_records"] == 0:
                result = self.__dba__.insert(self.__table_name__, data)
            else:
                result = self.__dba__.update(self.__table_name__, data)

            self.__dba__.commit()

            if result:
                self.load()

                return True
        except Exception as e:
            Debug.error("Error saving", str(e))
            return False

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
                sql += key + " = '" + str(values[key]) + "'"
                counter += 1
        else:
            sql = f"delete from {self.__table_name__} where {query}"

        result = False
        if self.__dba__ is not None:
            result = self.__dba__.execute(sql, params)

        if result.error is not None:
            self.__dba__.rollback()
            return False
        else:
            self.__dba__.commit()
            return True
