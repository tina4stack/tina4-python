#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
import os
import re
import sys
import importlib
import json
from decimal import Decimal
from tina4_python import Debug, Constant
from tina4_python.Constant import TINA4_LOG_ERROR
from tina4_python.DatabaseResult import DatabaseResult
from tina4_python.DatabaseTypes import *
from tina4_python.FieldTypes import get_field_type_values
import datetime

class Database:

    def __init__(self, _connection_string, _username="", _password=""):
        """
        Initializes a database connection
        :param _connection_string:
        """
        # split out the connection string
        # driver:host/port:schema/path
        params = _connection_string.split(":", 1)

        try:
            if _connection_string is None:
                _connection_string = os.environ.get("DATABASE_PATH", None)
            if _username == "":
                _username = os.environ.get("DATABASE_USERNAME", "")
            if _password == "":
                _password = os.environ.get("DATABASE_USERNAME", "")

            if _connection_string is None:
                raise Exception("Database connection string is missing, try declaring DATABASE_PATH in the .env file.")

            self.database_module = importlib.import_module(params[0])
        except Exception:
            install_message = "Please implement " + params[0] + " in Database.py and make a pull request!"
            if params[0] == SQLITE:
                install_message = "Your python is missing the sqlite3 module, please reinstall or update"
            elif params[0] == MYSQL:
                install_message = "Your python is missing the mysql module, please install with " + MYSQL_INSTALL
            elif params[0] == POSTGRES:
                install_message = "Your python is missing the postgres module, please install with " + POSTGRES_INSTALL
            elif params[0] == FIREBIRD:
                install_message = "Your python is missing the firebird module, please install with " + FIREBIRD_INSTALL
            elif params[0] == MSSQL:
                install_message = "Your python is missing the mssql module, please install with " + MSSQL_INSTALL

            sys.exit("Could not load database driver for " + params[0] + "\n" + install_message)


        self.database_engine = params[0]
        self.database_path = params[1]
        self.username = _username
        self.password = _password

        if self.database_engine == SQLITE:
            self.dba = self.database_module.connect(self.database_path)
            self.port = None
            self.host = None

            # we need to register data adapters for sqlite3 due to deprecations in python3.12
            def adapt_date_iso(val):
                """Adapt datetime.date to ISO 8601 date."""
                return val.isoformat()

            def adapt_datetime_iso(val):
                """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
                return val.isoformat()

            def adapt_datetime_epoch(val):
                """Adapt datetime.datetime to Unix timestamp."""
                return int(val.timestamp())

            self.database_module.register_adapter(datetime.date, adapt_date_iso)
            self.database_module.register_adapter(datetime.datetime, adapt_datetime_iso)
            self.database_module.register_adapter(datetime.datetime, adapt_datetime_epoch)

            def convert_date(val):
                """Convert ISO 8601 date to datetime.date object."""
                return datetime.date.fromisoformat(val.decode())

            def convert_datetime(val):
                """Convert ISO 8601 datetime to datetime.datetime object."""
                return datetime.datetime.fromisoformat(val.decode())

            def convert_timestamp(val):
                """Convert Unix epoch timestamp to datetime.datetime object."""
                return datetime.datetime.fromtimestamp(int(val))

            self.database_module.register_converter("date", convert_date)
            self.database_module.register_converter("datetime", convert_datetime)
            self.database_module.register_converter("timestamp", convert_timestamp)
        else:
            # <host>/<port>:<file>
            temp_params = self.database_path.split(":", 1)
            host_port = temp_params[0].split("/", 1)
            self.host = host_port[0]
            if len(host_port) > 1:
                self.port = int(host_port[1])
            else:
                self.port = 3050

            self.database_path = temp_params[1]

            if self.database_engine == FIREBIRD:
                self.dba = self.database_module.connect(
                    self.host + "/" + str(self.port) + ":" + self.database_path,
                    user=self.username,
                    password=self.password
                )
            elif self.database_engine == MYSQL:
                self.dba = self.database_module.connect(
                    database=self.database_path,
                    port=self.port,
                    host=self.host,
                    user=self.username,
                    password=self.password,
                    consume_results=True
                )
            elif self.database_engine == POSTGRES:
                self.dba = self.database_module.connect(
                    dbname=self.database_path,
                    port=self.port,
                    host=self.host,
                    user=self.username,
                    password=self.password
                )
            elif self.database_engine == MSSQL:
                self.dba = self.database_module.connect(
                    server=self.host,
                    port=self.port,
                    user=self.username,
                    password=self.password,
                    database=self.database_path
                )
                self.dba.autocommit(False)
            else:
                sys.exit("Could not load database driver for " + params[0])

        Debug.debug("DATABASE:", self.database_module.__name__, self.host, self.port, self.database_path, self.username)

    def table_exists(self, table_name):
        """
        Checks if a table exists in the database
        :param str table_name: Name of the table
        :return: bool : True if table exists, else False
        """

        if self.database_engine == MSSQL:
            sql = "select count(*) as count_table from sys.tables WHERE name = '" + table_name.upper() + "'"
        elif self.database_engine == SQLITE:
            sql = "SELECT count(*) as count_table FROM sqlite_master WHERE type='table' AND name='" + table_name + "'"
        elif self.database_engine == MYSQL:
            sql = "SELECT count(*) as count_table FROM information_schema.tables WHERE table_schema = '" + self.database_path + "' AND table_name = '" + table_name + "'"
        elif self.database_engine == POSTGRES:
            sql = """SELECT count(*) as count_table FROM pg_catalog.pg_class c
                        JOIN   pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        WHERE  c.relname = '""" + table_name + """'
                        AND    c.relkind = 'r'        """
        elif self.database_engine == FIREBIRD:
            sql = "SELECT count(*) as count_table FROM RDB$RELATIONS WHERE RDB$RELATION_NAME = upper('" + table_name + "')"
        else:
            return False

        try:
            record = self.fetch_one(sql)
        except Exception as e:
            raise Exception(f"Error checking if table {table_name} exists: " + str(e))

        if record:
            if record["count_table"] > 0:
                return True
            else:
                return False
        else:
            return False

    def get_next_id(self, table_name, column_name="id"):
        """
        Gets the next id using max method in sql for databases which don't have good sequences
        :param str table_name: Name of the table
        :param str column_name: Name of the column in that table to increment
        :return: int : The next id in the sequence
        """
        try:
            sql = "select max(" + column_name + ") as \"max_id\" from " + table_name
            record = self.fetch_one(sql)
            if record["max_id"] is None:
                record = {"max_id": 0}

            next_id = int(record["max_id"]) + 1
            return next_id
        except Exception as e:
            Debug.error("Get next id", str(e))
            return None

    def database_exists(self, database_name):

        return True

    def current_timestamp(self):
        """
        Gets the current timestamp based on the database being used
        :return:
        """
        if self.database_engine == FIREBIRD:
            return datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        elif self.database_engine == SQLITE:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_database_result(self, cursor, counter, limit, skip, sql):
        """
        Get database results
        :param sql:
        :param cursor:
        :param counter:
        :param limit:
        :param skip:
        :return:
        """
        columns = [column[0].lower() for column in cursor.description]
        records = cursor.fetchall()
        rows = [dict(zip(columns, row)) for row in records]
        cursor.close()
        return DatabaseResult(rows, columns, None, counter, limit, skip, sql, self)

    def is_json(self, myjson):
        """
        Checks if a JSON string is valid
        :param myjson:
        :return:
        """
        try:
            json.loads(myjson)
        except Exception:
            return False
        return True

    def check_connected(self):
        """
        Checks if the database connection is established
        :return:
        """
        if self.database_engine == MYSQL:
            self.dba.ping(reconnect=True, attempts=1, delay=0)
        else:
            # implement other database requirements if needed
            pass

    def fetch(self, sql, params=None, limit=10, skip=0, search=None, search_columns=None):
        """
        Enhanced fetch with optional full-text search + correct pagination
        :param sql:
        :param params:
        :param limit:
        :param skip:
        :param search:
        :param search_columns:
        :return:
        """
        if params is None:
            params = []
        if params is list:
            params = params.copy()
        else:
            params = list(params)

        self.check_connected()

        final_sql = sql
        final_params = params

        if search and search.strip():
            search = search.strip()

            # which columns are searchable?
            cols = search_columns or getattr(self, "columns", None)
            if not cols:
                # fallback – try to extract column names from SELECT
                m = re.search(r"SELECT\s+([\s\S]*?)\s+FROM", final_sql, re.I)
                if m:
                    raw = re.split(r',\s*(?=[a-zA-Z_`"\[\]])', m.group(1))
                    cols = []
                    for c in raw:
                        name = c.strip().split()[-1].split(".")[-1]
                        name = re.sub(r'^[`"\[\(].*[`"\]\)]$', '', name).strip('`"[]')
                        if name and name != "*":
                            cols.append(name)

            if cols:
                if self.database_engine == "POSTGRES":
                    like_op = "LIKE"
                else:
                    like_op = "LIKE"

                conditions = []
                for col in cols:
                    col_name = f'"{col}"' if " " not in col else col
                    conditions.append(f"cast({col_name} as varchar(1000)) {like_op} ?")
                    final_params.append(f"%{search}%")

                where_clause = " WHERE (" + " OR ".join(conditions) + ")"
                final_sql = sql + where_clause

        # 3. TOTAL COUNT (with the same filter!)
        count_sql = f"SELECT COUNT(*) AS count_records FROM ({final_sql}) AS t"
        counter = self.dba.cursor()
        try:
            counter.execute(self.parse_place_holders(count_sql), final_params)
            total = counter.fetchone()[0]
        except Exception as e:
            Debug.error ("COUNT ERROR", count_sql, final_params, str(e))
            total = 0
        finally:
            counter.close()

        # 4. FINAL PAGINATION – applied AFTER the filter
        if self.database_engine == "FIREBIRD":
            final_sql = f"SELECT FIRST {limit} SKIP {skip} * FROM ({final_sql}) AS t"
        elif self.database_engine in ("MYSQL", "SQLITE"):
            final_sql = f"SELECT * FROM ({final_sql}) AS t LIMIT {limit} OFFSET {skip}"
        elif self.database_engine == "POSTGRES":
            final_sql = f"SELECT * FROM ({final_sql}) AS t LIMIT {limit} OFFSET {skip}"
        elif self.database_engine == "MSSQL":
            # MSSQL needs ORDER BY for OFFSET/FETCH
            inner = final_sql.strip()
            if not re.search(r"\border\s+by\b", inner, re.I):
                inner += " ORDER BY (SELECT NULL)"
            final_sql = f"SELECT * FROM ({inner}) AS t OFFSET {skip} ROWS FETCH NEXT {limit} ROWS ONLY"
        else:
            final_sql = f"SELECT * FROM ({final_sql}) AS t LIMIT {limit} OFFSET {skip}"

        final_sql = self.parse_place_holders(final_sql)

        # 5. Execute the real query
        cursor = self.dba.cursor()
        try:
            cursor.execute(final_sql, final_params)
            return self.get_database_result(cursor, total, limit, skip, final_sql)
        except Exception as e:
            Debug.error("FETCH ERROR", final_sql, final_params, str(e))
            return DatabaseResult(None, [], str(e))
        finally:
            cursor.close()

    def fetch_one(self, sql, params=[], skip=0):
        """
        Fetch a single record based on a sql statement, take note that BLOB and byte record data is converted into base64 automatically
        :param str sql: A plain SQL statement or one with params in it designated by ?
        :param list params: A list of params in order of precedence
        :param int skip: Offset of records to skip
        :return: dict : A dictionary containing the single record
        """
        # Calling the fetch method with limit as 1 and returning the result
        record = self.fetch(sql, params=params, limit=1, skip=skip)
        if record.error is None and record.count == 1:
            data = {}
            for key in record.records[0]:
                if isinstance(record.records[0][key], Decimal):
                    data[key] = float(record.records[0][key])
                if isinstance(record.records[0][key], (datetime.date, datetime.datetime)):
                    data[key] = record.records[0][key].isoformat()
                if isinstance(record.records[0][key], bytes):
                    data[key] = base64.b64encode(record.records[0][key]).decode('utf-8')
                else:
                    if isinstance(record.records[0][key], str) and self.is_json(record.records[0][key]):
                        data[key] = json.loads(record.records[0][key])
                    else:
                        data[key] = record.records[0][key]
            return data
        else:
            return None

    def parse_place_holders(self, sql):
        """
        Sanitizes a sql statement to replace param chars with the appropriate placeholders
        MYSQL expects %s and firebird, posgres and sqlite expect ?
        :param sql:
        :return:
        """
        if self.database_engine == MYSQL or self.database_engine == POSTGRES or self.database_engine == MSSQL:
            return sql.replace("?", "%s")
        else:
            return sql.replace("%s", "?")

    def execute(self, sql, params=None):
        """
        Execute a query based on a sql statement
        :param str sql: A plain SQL statement or one with params in it designated by ?
        :param list params: A list of params in order of precedence
        :return: DatabaseResult
        """
        if params is None:
            params = {}

        self.check_connected()
        sql = self.parse_place_holders(sql)
        cursor = self.dba.cursor()
        # Running an execute statement and committing any changes to the database
        try:
            params = get_field_type_values(params)
            cursor.execute(sql, params)
            if "returning" in sql.lower():
                return self.get_database_result(cursor, 1, 1, 0, sql)
            else:
                # see if we are mysql and if we are insert statement to get the last record
                if "insert" in sql.lower() and (self.database_engine == MYSQL or self.database_engine == MSSQL):
                    return DatabaseResult([{"id": cursor.lastrowid}], [], None, 1, 1, 0, sql, self)

                # On success return an empty result set with no error
                return DatabaseResult(None, [], None, 0, 0, 0, sql, self)
        except Exception as e:
            Debug.error("EXECUTE ERROR:", sql, str(e))
            # Return the error in the result
            return DatabaseResult(None, [], str(e))
        finally:
            cursor.close()

    def execute_many(self, sql, params=[]):
        """
        Execute a query based on a single sql statement with a different number of params
        :param sql: A plain SQL statement or one with params in it designated by ?
        :param params: A list of params in order of precedence
        :return: DatabaseResult
        """
        self.check_connected()
        sql = self.parse_place_holders(sql)
        cursor = self.dba.cursor()
        # Running an execute statement and committing any changes to the database
        try:
            params = get_field_type_values(params)
            cursor.executemany(sql, params)
            # On success return an empty result set with no error
            return DatabaseResult(None, [], None)
        except Exception as e:
            Debug.error("EXECUTE MANY ERROR:", sql, str(e))
            # Return the error in the result
            return DatabaseResult(None, [], str(e))
        finally:
            cursor.close()

    def start_transaction(self):
        """
        Starts a transaction
        :return:
        """
        try:
            self.check_connected()
            if self.database_engine == SQLITE:
                self.dba.execute("BEGIN TRANSACTION")
            elif self.database_engine == FIREBIRD:
                self.dba.begin()
            elif self.database_engine == MYSQL:
                self.dba.start_transaction()
            elif self.database_engine == MSSQL:
                self.dba.execute("BEGIN TRANSACTION")
            elif self.database_engine == POSTGRES:
                self.dba.rollback()  # start fresh
            else:
                Debug.error("START TRANSACTION ERROR:", "Database engine unrecognised/not supported")
        except Exception as e:
            Debug.error("START TRANSACTION ERROR:", str(e))

    def commit(self):
        """
        Commit transaction
        :return:
        """
        try:
            self.dba.commit()
        except Exception as e:
            Debug.error("COMMIT TRANSACTION ERROR:", str(e))

    def rollback(self):
        """
        Rollback transaction
        :return:
        """
        try:
            self.dba.rollback()
        except Exception as e:
            Debug.error("ROLLBACK TRANSACTION ERROR:", str(e))

    def close(self):
        """
        Close database connection
        :return:
        """
        try:
            self.dba.close()
        except Exception as e:
            Debug.error("DATABASE CLOSE ERROR:", str(e))

    def sanitize(self, record):
        """
        Changes dictionaries and list values into json for updating and inserting
        :param record:
        :return:
        """
        for key in record:
            if isinstance(record[key], list) or isinstance(record[key], dict):
                record[key] = json.dumps(record[key])
        return record

    def insert(self, table_name, data:dict|list, primary_key="id"):
        """
        Insert data based on table name and data provided - single or multiple records
        :param str table_name: Name of table
        :param None data: List or Dictionary containing the data to be inserted
        :param str primary_key: The name of the primary key of the table
        """
        if isinstance(data, dict):
            data = [data]

        if isinstance(data, list):
            records = DatabaseResult()

            result = None
            for record in data:
                columns = ", ".join(data[0].keys())
                placeholders = ", ".join(['?'] * len(data[0]))

                pk_key = primary_key in columns
                if not pk_key or (
                        primary_key in columns and (record[primary_key] is None or record[primary_key] == "")):
                    if primary_key not in columns:
                        columns += f", {primary_key}"
                        placeholders += ", ?"
                    record[primary_key] = self.get_next_id(table_name, primary_key)

                sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

                if self.database_engine == FIREBIRD or self.database_engine == SQLITE or self.database_engine == POSTGRES:
                    sql += f" returning ({primary_key})"

                record = self.sanitize(record)
                if self.database_engine == MSSQL:
                    self.execute(f"SET IDENTITY_INSERT {table_name} ON")
                result = self.execute(sql, list(record.values()))
                if self.database_engine == MSSQL:
                    self.execute(f"SET IDENTITY_INSERT {table_name} OFF")
                records.records += result.records
                if result.error is not None:
                    Debug.error("INSERT ERROR:", sql, result.error)
                    return False

            records.columns = result.columns
            records.count = len(records.records)
            records.sql = sql
            records.dba = self

            return records
        else:
            return False

    def delete(self, table_name, filter=None):
        """
        Delete data based on table name and filter provided - single or multiple filters
        :param str table_name: Name of table
        :param str filter: Expression for deleting records
        """
        placeholder = "?"

        if filter is not None:
            # Updating a single record - record passed in is a dictionary
            if isinstance(filter, dict):
                filter = [filter]

            # Updating multiple records - records passed in is a list
            if isinstance(filter, list):
                sql = ""
                result = None
                for record in filter:
                    pk_value = []
                    condition_records = []

                    for column, value in record.items():
                        condition_records.append(f"{column} = {placeholder}")
                        pk_value.append(value)

                    condition_records = " and ".join(condition_records)

                    sql = f"DELETE FROM {table_name} WHERE {condition_records}"

                    params = pk_value

                    result = self.execute(sql, params)
                    if result.error is not None:
                        break

                if result.error is None:
                    return True
                else:
                    Debug.error("DELETE ERROR:", sql, result.error)
                    return False

        return False

    def update(self, table_name, data:dict|list, primary_key="id"):
        """
        Update data based on table name and record/primary key provided - single or multiple records
        :param str table_name: Name of table
        :param None data: List or Dictionary containing the data to be inserted
        :param str primary_key: The name of the primary key of the table
        """
        placeholder = "?"

        if data is not None:
            # Updating a single record - record passed in is a dictionary
            if isinstance(data, dict):
                data = [data]

            # Updating multiple records - records passed in is a list
            if isinstance(data, list):
                sql = ""
                result = None
                for record in data:
                    pk_value = None
                    condition_records = ""
                    set_clause_list = []
                    set_values = []

                    for column, value in record.items():
                        if column == primary_key:
                            condition_records = f"{column} = {placeholder}"
                            pk_value = value
                        else:
                            set_clause_list.append(f"{column} = {placeholder}")
                            if isinstance(value, list) or isinstance(value, dict):
                                set_values.append(json.dumps(value))
                            else:
                                set_values.append(value)

                    set_clause = ", ".join(set_clause_list)

                    sql = f"UPDATE {table_name} SET {set_clause} WHERE {condition_records}"

                    params = set_values + [pk_value]

                    if self.database_engine == MSSQL:
                        self.execute(f"SET IDENTITY_UPDATE {table_name} ON")
                    result = self.execute(sql, params)
                    if self.database_engine == MSSQL:
                        self.execute(f"SET IDENTITY_UPDATE {table_name} OFF")
                    if result.error is not None:
                        break

                if result.error is None:
                    return True
                else:
                    Debug.error("UPDATE ERROR:", sql, result.error)
                    return False

        return False
