#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Active Record ORM module for Tina4 Python.

This module provides an Active Record-style ORM that maps Python classes to
database tables. Each ORM subclass represents a single database table, and
each instance represents a single row. Table names are derived automatically
from the class name using snake_case conversion (e.g., ``UserProfile`` becomes
``user_profile``), or can be set explicitly via ``__table_name__``.

Field definitions use typed descriptors (``IntegerField``, ``StringField``,
etc.) declared as class attributes. If no fields are declared, a default
``id`` IntegerField with auto-increment and primary key is created.

Typical usage::

    from tina4_python import ORM, IntegerField, StringField
    from tina4_python.Database import Database
    from tina4_python.ORM import orm

    # Initialize the database and bind it to all ORM subclasses
    orm(Database("sqlite3:app.db"))

    # Define a model
    class Customer(ORM):
        id    = IntegerField(primary_key=True, auto_increment=True)
        name  = StringField()
        email = StringField()

    # Create and persist a record
    customer = Customer({"name": "Alice", "email": "alice@example.com"})
    customer.save()

    # Load an existing record
    customer = Customer()
    if customer.load("email = ?", ["alice@example.com"]):
        print(customer.name.value)

    # Query multiple records
    result = Customer().fetch(filter="name like ?", params=["%Ali%"], limit=20)
"""

__all__ = ["ORM", "orm", "find_all_sub_classes"]

import ast
import base64
from datetime import date
import json
import os
from tina4_python.Constant import TINA4_LOG_ERROR
from tina4_python.FieldTypes import *


def find_all_sub_classes(a_class):
    """Return all direct subclasses of the given class.

    This is used during ORM initialization to discover all user-defined
    model classes so their ``__dba__`` attribute can be set to the active
    database connection.

    Args:
        a_class: The parent class whose direct subclasses are returned.

    Returns:
        list: A list of class objects that directly subclass ``a_class``.
    """
    return a_class.__subclasses__()


def orm(dba):
    """Initialize the ORM layer by binding a database connection to all models.

    This function should be called once at application startup (typically in
    ``app.py``). It performs two tasks:

    1. Scans the ``src/orm/`` directory for Python modules, imports each one,
       and sets its ``__dba__`` class attribute to the provided database
       connection.
    2. Iterates over all discovered ``ORM`` subclasses (including those
       registered outside ``src/orm/``) and assigns them the same database
       connection.

    After calling this function every ORM subclass can perform database
    operations (``save``, ``load``, ``fetch``, etc.) without needing an
    explicit database reference.

    Args:
        dba: A ``tina4_python.Database.Database`` instance that provides the
            database connection used by all ORM models.

    Example::

        from tina4_python.Database import Database
        from tina4_python.ORM import orm

        orm(Database("sqlite3:app.db"))
    """
    import importlib
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
                module = importlib.import_module('src.orm.' + mod_name)
                orm_class = getattr(module, mod_name)
                orm_class.__dba__ = dba
            except Exception as e:
                Debug("Failed to import " + mod_name, str(e))
    classes = find_all_sub_classes(ORM)
    for a_class in classes:
        a_class.__dba__ = dba


def json_serialize(obj):
    """Custom JSON serializer for types not handled by the default encoder.

    Used as the ``default`` argument to ``json.dumps`` when converting ORM
    instances to JSON. Handles ``datetime``/``date`` objects (via ISO-8601)
    and ``bytes`` objects (via Base64 encoding).

    Args:
        obj: The object to serialize.

    Returns:
        str: An ISO-8601 date string for date/datetime objects, or a
            Base64-encoded string for bytes objects.

    Raises:
        TypeError: If ``obj`` is not a supported type.
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    raise TypeError("Type %s not serializable" % type(obj))


class ORM:
    """Active Record ORM base class for Tina4 Python.

    Subclass ``ORM`` to define a database-backed model. Each subclass maps to
    a single database table. Declare columns as class-level field descriptors
    (``IntegerField``, ``StringField``, etc.) and the ORM handles table
    creation, querying, inserting, updating, and deleting automatically.

    Table name resolution (in priority order):
        1. The ``__table_name__`` class attribute, if set explicitly.
        2. The ``table_name`` keyword passed to ``__init__``.
        3. Automatic snake_case conversion of the class name
           (e.g., ``OrderItem`` -> ``order_item``).

    The database connection is stored on the class-level ``__dba__`` attribute
    and is shared by all instances. It is normally assigned by calling the
    module-level ``orm(dba)`` function at startup.

    Class Attributes:
        __table_name__: Explicit table name override. ``None`` means
            auto-derive from the class name.
        __dba__: The shared ``Database`` instance. Set by ``orm(dba)``.
        __field_definitions__: Dict mapping field names to their
            ``FieldType`` descriptor instances. Populated in ``__init__``.

    Example::

        from tina4_python import ORM, IntegerField, StringField

        class Product(ORM):
            id    = IntegerField(primary_key=True, auto_increment=True)
            name  = StringField()
            price = IntegerField(default_value=0)

        # After orm(dba) has been called:
        p = Product({"name": "Widget", "price": 999})
        p.save()
    """
    __table_name__ = None
    __dba__ = None
    __field_definitions__ = {}

    def __get_snake_case_name__(self, name):
        """Convert a CamelCase or mixed-case name to snake_case.

        If the name already contains underscores it is simply lowered.
        Otherwise each uppercase letter (after the first character) is
        preceded by an underscore. Used to derive table names from class
        names and to map incoming camelCase JSON keys to snake_case fields.

        Args:
            name: The string to convert (e.g., ``"UserProfile"``).

        Returns:
            str: The snake_case equivalent (e.g., ``"user_profile"``).
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
        """Initialize an ORM instance, optionally populating it from data.

        During construction the following steps occur:

        1. All public, non-method attributes (the field descriptors) are
           collected into ``__field_definitions__``. If no fields are found
           a default ``id`` IntegerField is created.
        2. The table name is resolved (see class docstring for precedence).
        3. If ``init_object`` is provided its key/value pairs are mapped onto
           the matching fields (camelCase keys are converted to snake_case).
        4. If a database connection is available and the table does not yet
           exist, a ``CREATE TABLE`` SQL statement is generated (and logged
           as a warning).

        Args:
            init_object: Optional initial data to populate the instance.
                Can be a ``dict`` or a JSON string. Keys are matched to
                field names after snake_case conversion.
            table_name: Optional explicit table name. Overrides automatic
                derivation from the class name.

        Example::

            user = User({"name": "Alice", "email": "alice@example.com"})
            empty_user = User()
        """
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
        """Populate field values from a dict or JSON string.

        First resets all fields to ``None``, then iterates over the
        key/value pairs in ``init_object``, converts each key to
        snake_case, and assigns matching field values. This allows
        incoming camelCase JSON payloads to map seamlessly to
        snake_case Python field names.

        Args:
            init_object: A ``dict`` or JSON string whose keys correspond
                (after snake_case conversion) to the model's field names.
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
        """Return a list of field names that are marked as primary keys.

        Iterates over ``__field_definitions__`` and collects the names of
        all fields whose ``primary_key`` attribute is ``True``.

        Returns:
            list[str]: Field names that form the composite (or single)
                primary key for this model's table.
        """
        primary_keys = []
        for key, value in self.__field_definitions__.items():
            if value.primary_key:
                primary_keys.append(key)

        return primary_keys

    def to_json(self):
        """Serialize the ORM instance to a JSON string.

        Converts all field values to a dict via ``to_dict()`` and then
        serializes the dict to JSON using ``json_serialize`` as the
        fallback serializer for non-standard types (dates, bytes).

        Returns:
            str: A JSON-encoded string representation of this instance.

        Example::

            user = User({"name": "Alice"})
            print(user.to_json())  # '{"id": 1, "name": "Alice"}'
        """
        return json.dumps(self.to_dict(), default=json_serialize)

    def __is_class(self, class_name):
        """Check whether the given value is a user-defined class instance.

        Uses a heuristic: the string representation of the type starts
        with ``"<class"`` and the object has a ``__weakref__`` attribute.
        This distinguishes field descriptor objects from plain scalar
        values.

        Args:
            class_name: The value to test.

        Returns:
            bool: ``True`` if the value appears to be a class instance.
        """
        return str(type(class_name)).startswith("<class") and hasattr(class_name, '__weakref__')

    def to_dict(self):
        """Convert the ORM instance to a plain Python dictionary.

        Iterates over all defined fields and extracts their current values.
        Auto-increment fields that have no value yet will be assigned the
        next available ID from the database. ``IntegerField`` values are
        cast to ``int``; all other values are cast to ``str``.

        Returns:
            dict: A mapping of field names to their current scalar values.

        Example::

            user = User({"name": "Alice"})
            user.to_dict()  # {"id": 1, "name": "Alice"}
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
                try:
                    data[key] = int(current_value)
                except Exception as e:
                    Debug.error("Could not save", current_value, "to", key)
            else:
                data[key] = str(current_value)

        return data

    def __str__(self):
        return self.to_json()

    def __create_table__(self, table_name, execute=False):
        """Generate (and optionally execute) a CREATE TABLE SQL statement.

        Builds DDL from the model's ``__field_definitions__``, including
        column types and a composite primary key clause when applicable.

        Args:
            table_name: The name of the table to create.
            execute: If ``True``, execute the SQL against the database
                immediately. If ``False`` (default), return the SQL string
                without executing.

        Returns:
            str or None or False: The SQL string when ``execute`` is
                ``False``; ``None`` when the statement is executed
                successfully; ``False`` if no database connection exists.
        """
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
        """Create the database table for this model if it does not exist.

        Executes the DDL generated by ``__create_table__`` against the
        bound database connection. Column definitions and primary keys
        are derived from the model's field descriptors.

        Returns:
            None or False: ``None`` on success; ``False`` if no database
                connection is available.
        """
        return self.__create_table__(self.__table_name__, True)

    def __build_sql(self, column_names="*", join="", filter="", group_by="", having="", order_by=""):
        """Build a SELECT SQL query string from individual clauses.

        Assembles a complete SQL statement targeting this model's table
        (aliased as ``t``). All clause arguments are optional; omitted
        clauses are simply left out of the generated SQL.

        Args:
            column_names: Columns to select. Accepts ``"*"``, a
                comma-separated string, or a list of column expressions.
            join: A raw SQL JOIN clause (e.g.,
                ``"join orders o on o.user_id = t.id"``).
            filter: A WHERE condition string (without the ``WHERE``
                keyword).
            group_by: GROUP BY columns as a comma-separated string or
                list.
            having: HAVING conditions as a comma-separated string or
                list.
            order_by: ORDER BY columns as a comma-separated string or
                list.

        Returns:
            str: The assembled SQL query string.
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

    def fetch_one(self, column_names="*", filter="", params=None, join="", group_by="", having="", order_by=""):
        """Fetch a single record from the database.

        Builds a SELECT query via ``__build_sql`` and delegates to the
        database adapter's ``fetch_one`` method. Useful when you expect
        exactly one result (e.g., lookup by unique key).

        Args:
            column_names: Columns to select (``"*"``, comma string, or
                list). Defaults to ``"*"``.
            filter: WHERE clause (without the ``WHERE`` keyword).
            params: List of bind-parameter values for placeholders (``?``)
                in the filter.
            join: Raw SQL JOIN clause.
            group_by: GROUP BY columns.
            having: HAVING conditions.
            order_by: ORDER BY columns.

        Returns:
            dict or None: A single record as a dictionary, or ``None`` if
                no matching row is found.

        Example::

            row = User().fetch_one(filter="email = ?",
                                   params=["alice@example.com"])
        """
        if params is None:
            params = []
        sql = self.__build_sql(column_names, join, filter, group_by, having, order_by)
        return self.__dba__.fetch_one(sql, params=params)

    def fetch(self, column_names="*", filter="", params=None, join="", group_by="", having="", order_by="", limit=10,
              skip=0):
        """Fetch multiple records from the database with pagination.

        Builds a SELECT query and delegates to the database adapter's
        ``fetch`` method. Supports limit/offset pagination.

        Args:
            column_names: Columns to select (``"*"``, comma string, or
                list). Defaults to ``"*"``.
            filter: WHERE clause (without the ``WHERE`` keyword).
            params: List of bind-parameter values for ``?`` placeholders.
            join: Raw SQL JOIN clause.
            group_by: GROUP BY columns.
            having: HAVING conditions.
            order_by: ORDER BY columns.
            limit: Maximum number of rows to return. Defaults to ``10``.
            skip: Number of rows to skip (offset). Defaults to ``0``.

        Returns:
            A database result object with helper methods such as
            ``to_json()``, ``to_array()``, ``to_paginate()``, and
            ``to_csv()``. Access rows via ``result.records``.

        Example::

            result = Product().fetch(
                filter="price > ?", params=[100],
                order_by="price desc", limit=20
            )
            for row in result.records:
                print(row["name"])
        """
        if params is None:
            params = []
        sql = self.__build_sql(column_names, join, filter, group_by, having, order_by)
        return self.__dba__.fetch(sql, params=params, limit=limit, skip=skip)

    def select(self, column_names="*", filter="", params=None, join="", group_by="", having="", order_by="", limit=10,
               skip=0):
        """Alias for ``fetch()`` -- query multiple records with pagination.

        Provided for convenience and readability. All arguments are
        forwarded directly to ``fetch()``.

        Args:
            column_names: Columns to select. Defaults to ``"*"``.
            filter: WHERE clause (without ``WHERE``).
            params: Bind-parameter values for ``?`` placeholders.
            join: Raw SQL JOIN clause.
            group_by: GROUP BY columns.
            having: HAVING conditions.
            order_by: ORDER BY columns.
            limit: Maximum rows to return. Defaults to ``10``.
            skip: Row offset. Defaults to ``0``.

        Returns:
            A database result object (same as ``fetch()``).
        """
        return self.fetch(column_names, filter, params, join, group_by, having, order_by, limit, skip)

    def load(self, query="", params=None):
        """Load a single database record into this ORM instance.

        When called without arguments the record is located using the
        current values of the primary key field(s). When ``query`` is
        provided it is used as a WHERE clause instead, allowing lookup
        by arbitrary columns.

        On success the instance's field values are replaced with the
        data from the database row. ``JSONBField`` values are
        automatically parsed from their stored string representation.

        Args:
            query: Optional WHERE clause (without the ``WHERE`` keyword).
                If empty, the primary key values already set on the
                instance are used to locate the row.
            params: List of bind-parameter values for ``?`` placeholders
                in ``query``.

        Returns:
            bool: ``True`` if a matching record was found and loaded;
                ``False`` if no record was found, the table does not
                exist, or the database is not initialized.

        Example::

            user = User()
            user.id.value = 42
            if user.load():
                print(user.name.value)

            # Or load by a custom query:
            user = User()
            if user.load("email = ?", ["alice@example.com"]):
                print(user.name.value)
        """
        if params is None:
            params = []
        if not self.__table_exists:
            Debug("ORM: Load Error - Table", self.__table_name__, "does not exist", TINA4_LOG_ERROR)
            return False

        if query == "":
            sql = f"select * from {self.__table_name__} where "
            primary_keys = self.__get_primary_keys()
            values = self.to_dict()
            params = []
            counter = 0
            for key in primary_keys:
                if counter > 0:
                    sql += " and "
                sql += key + " = ?"
                params.append(values[key])
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
        """Persist this ORM instance to the database (insert or update).

        Determines whether a row with the current primary key(s) already
        exists. If it does the row is updated; otherwise a new row is
        inserted. After a successful write the transaction is committed
        and ``load()`` is called to refresh the instance with any
        database-generated values (e.g., auto-increment IDs, defaults).

        ``JSONBField`` values are serialized before writing.

        Returns:
            bool: ``True`` on success; ``False`` if the table does not
                exist or an error occurs during the operation.

        Example::

            user = User({"name": "Alice", "email": "alice@example.com"})
            if user.save():
                print("Saved with id", user.id.value)
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

    def delete(self, query="", params=None):
        """Delete one or more records from the database.

        When called without arguments the row matching the current primary
        key value(s) is deleted. When ``query`` is provided it is used as
        a WHERE clause, allowing bulk or conditional deletes.

        On success the transaction is committed; on failure it is rolled
        back.

        Args:
            query: Optional WHERE clause (without the ``WHERE`` keyword).
                If empty, the instance's primary key values are used.
            params: List of bind-parameter values for ``?`` placeholders
                in ``query``.

        Returns:
            bool: ``True`` if the delete succeeded and was committed;
                ``False`` if the table does not exist or an error
                occurred (transaction is rolled back).

        Example::

            user = User()
            user.id.value = 42
            user.delete()

            # Or delete by a custom query:
            User().delete("active = ?", [False])
        """
        if params is None:
            params = []
        if not self.__table_exists:
            Debug("ORM: Load Error - Table", self.__table_name__, "does not exist", TINA4_LOG_ERROR)
            return False
        if query == "":
            sql = f"delete from {self.__table_name__} where "
            primary_keys = self.__get_primary_keys()
            values = self.to_dict()
            params = []
            counter = 0
            for key in primary_keys:
                if counter > 0:
                    sql += " and "
                sql += key + " = ?"
                params.append(values[key])
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
