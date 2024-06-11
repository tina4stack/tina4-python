#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib

from tina4_python import Debug, Constant
from tina4_python.DatabaseResult import DatabaseResult


class Database:
    SQLITE = "sqlite3"
    FIREBIRD = "firebird.driver"
    MYSQL = "mysql"
    POSTGRES = "postgres"

    def __init__(self, _connection_string, _username="", _password=""):
        """
        Initializes a database connection
        :param _connection_string:
        """
        # split out the connection string
        # driver:host/port:schema/path

        params = _connection_string.split(":", 1)
        self.database_module = importlib.import_module(params[0])

        self.database_engine = params[0]
        self.database_path = params[1]
        self.username = _username
        self.password = _password

        if self.database_engine == "sqlite3":
            self.dba = self.database_module.connect(self.database_path)
            self.port = None
            self.host = None

        if self.database_engine == "firebird.driver":
            # <host>/<port>:<file>
            temp_params = self.database_path.split(":", 1)
            host_port = temp_params[0].split("/", 1)
            self.host = host_port[0]
            if len(host_port) > 1:
                self.port = int(host_port[1])
            else:
                self.port = 3050

            self.database_path = temp_params[1]

            self.dba = self.database_module.connect(
                self.host + "/" + str(self.port) + ":" + self.database_path,
                user=self.username,
                password=self.password
            )

        Debug("DATABASE:", self.database_module, self.host, self.port, self.database_path, self.username,
              Constant.TINA4_LOG_INFO)

    def fetch(self, sql, params=(), limit=10, skip=0):
        """
        Fetch records based on a sql statement
        :param sql:
        :param params:
        :param limit:
        :param skip:
        :return:
        """
        Debug("FETCH:", sql, "params", params, "limit", limit, "skip", skip, Constant.TINA4_LOG_INFO)
        # modify the select statement for limit and skip
        if self.database_engine == "firebird.driver":
            sql = f"select first {limit} skip {skip} * from ({sql})"
        elif self.database_engine == "sqlite3":
            sql = f"select * from ({sql}) limit {skip},{limit}"

        cursor = self.dba.cursor()
        try:
            cursor.execute(sql, params)
            columns = [column[0].lower() for column in cursor.description]
            records = cursor.fetchall()
            rows = [dict(zip(columns, row)) for row in records]
            columns = [column for column in cursor.description]
            return DatabaseResult(rows, columns, None)
        except Exception as e:
            return DatabaseResult(None, [], str(e))

    def fetch_one(self, sql, params=(), skip=0):
        """
        Fetch a single record based on a sql statement
        :param sql:
        :param params:
        :param skip:
        :return:
        """
        Debug("FETCHONE:", sql, "params", params, "skip", skip, Constant.TINA4_LOG_INFO)
        # Calling the fetch method with limit as 1 and returning the result
        return self.fetch(sql, params=params, limit=1, skip=skip)

    def execute(self, sql, params=()):
        """
        Execute a query based on a sql statement
        :param sql:
        :param params:
        :return:
        """
        Debug("EXECUTE:", sql, "params", params, Constant.TINA4_LOG_INFO)

        cursor = self.dba.cursor()
        # Running an execute statement and committing any changes to the database
        try:
            cursor.execute(sql, params)
            # On success return an empty result set with no error
            return DatabaseResult(None, [], None)

        except Exception as e:
            Debug("EXECUTE ERROR:", str(e), Constant.TINA4_LOG_ERROR)
            # Return the error in the result
            return DatabaseResult(None, [], str(e))

    def execute_many(self, sql, params=()):
        """
        Execute a query based on a single sql statement with a different number of params
        :param sql:
        :param params:
        :return:
        """

        Debug("EXECUTE MANY:", sql, "params", params, Constant.TINA4_LOG_INFO)

        cursor = self.dba.cursor()
        # Running an execute statement and committing any changes to the database
        try:
            cursor.executemany(sql, params)
            # On success return an empty result set with no error
            return DatabaseResult(None, [], None)

        except Exception as e:
            Debug("EXECUTE MANY ERROR:", str(e), Constant.TINA4_LOG_ERROR)
            # Return the error in the result
            return DatabaseResult(None, [], str(e))

    def start_transaction(self):
        try:
            if self.database_engine in (self.SQLITE, self.POSTGRES):
                self.dba.execute("BEGIN TRANSACTION")
            elif self.database_engine == self.FIREBIRD:
                self.dba.begin()
            elif self.database_engine == self.MYSQL:
                self.dba.start_transaction()
            else:
                Debug("START TRANSACTION ERROR:", "Database engine unrecognised/not supported",
                      Constant.TINA4_LOG_ERROR)
        except Exception as e:
            Debug("START TRANSACTION ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def commit(self):
        try:
            self.dba.commit()
        except Exception as e:
            Debug("COMMIT TRANSACTION ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def rollback(self):
        try:
            self.dba.rollback()
        except Exception as e:
            Debug("ROLLBACK TRANSACTION ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def close(self):
        try:
            self.dba.close()
        except Exception as e:
            Debug("DATABASE CLOSE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def insert(self, table_name, data):
        """
        Insert data based on table name and data provided - single or multiple records
        :param table_name:
        :param data:
        """
        if isinstance(data, dict):
            keys = [key for key in data]
            columns = ", ".join(keys)
            values = [value for value in data.values()]
            # Checking which database engine is used to generate respective syntax for placeholders
            if self.database_engine in (self.SQLITE, self.FIREBIRD):
                placeholders = ", ".join(['?'] * len(data))
            elif self.database_engine in (self.MYSQL, self.POSTGRES):
                placeholders = ", ".join(['%s'] * len(data))

            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

            try:
                self.execute(sql, values)
            except Exception as e:
                Debug("INSERT ERROR:", str(e), Constant.TINA4_LOG_ERROR)
        elif isinstance(data, list):
            columns = ", ".join(data[0].keys())
            # Checking which database engine is used to generate respective syntax for placeholders
            if self.database_engine in (self.SQLITE, self.FIREBIRD):
                placeholders = ", ".join(['?'] * len(data[0]))
            elif self.database_engine in (self.MYSQL, self.POSTGRES):
                placeholders = ", ".join(['%s'] * len(data[0]))

            values = [list(record.values()) for record in data]
            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

            try:
                self.execute_many(sql, values)
            except Exception as e:
                Debug("INSERT ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def delete(self, table_name, records=None, primary_key="id", filter=None):
        """
        Delete data based on table name and filter provided - single or multiple filters
        :param table_name:
        :param records:
        :param primary_key:
        :param filter:
        """

        if self.database_engine in (self.SQLITE, self.FIREBIRD):
            placeholder = "?"
        elif self.database_engine in (self.MYSQL, self.POSTGRES):
            placeholder = "%s"

        if records is not None:
            pk_value = None
            condition_records = ""

            # Delete a single record - record passed in is a dictionary

            if isinstance(records, dict):
                for column, value in records.items():
                    if column == primary_key:
                        condition_records = f"{column} = {placeholder}"
                        pk_value = value

                sql = f"DELETE FROM {table_name} WHERE {condition_records}"

                try:
                    self.execute(sql, [pk_value])
                except Exception as e:
                    Debug("DELETE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

            # Delete multiple records - records passed in is a list

            elif isinstance(records, list):
                placeholders = ", ".join([placeholder] * len(records))
                pk_values = []
                conditions_records = ""

                for record in records:
                    for column, value in record.items():
                        if column == primary_key:
                            conditions_records = f"{column} in ({placeholders})"
                            pk_values.append(value)

                sql = f"DELETE FROM {table_name} WHERE {conditions_records}"

                try:
                    self.execute(sql, pk_values)
                except Exception as e:
                    Debug("DELETE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

        # Delete a record by a single filter - filter passed in is a dictionary

        if isinstance(filter, dict):
            column = list(filter.keys())[0]
            value = list(filter.values())[0]

            condition = f"{column} = {placeholder}"

            sql = f"DELETE FROM {table_name} WHERE {condition}"

            try:
                self.execute(sql, [value])
            except Exception as e:
                Debug("DELETE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

        # Delete multiple records by multiple filters - filters passed in is a list

        elif isinstance(filter, list):
            for item in filter:
                column = list(item.keys())[0]
                value = list(item.values())[0]

                condition = f"{column} = {placeholder}"

                sql = f"DELETE FROM {table_name} WHERE {condition}"

                try:
                    self.execute(sql, [value])
                except Exception as e:
                    Debug("DELETE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

    def update(self, table_name, records, primary_key="id"):
        """
        Update data based on table name and record/primary key provided - single or multiple records
        :param table_name:
        :param records:
        :param primary_key:
        """

        if self.database_engine in (self.SQLITE, self.FIREBIRD):
            placeholder = "?"
        elif self.database_engine in (self.MYSQL, self.POSTGRES):
            placeholder = "%s"

        if records is not None:
            pk_value = None
            condition_records = ""
            set_clause_list = []
            set_values = []

            # Updating a single record - record passed in is a dictionary

            if isinstance(records, dict):
                for column, value in records.items():
                    if column == primary_key:
                        condition_records = f"{column} = {placeholder}"
                        pk_value = value
                    else:
                        set_clause_list.append(f"{column} = {placeholder}")
                        set_values.append(value)

                set_clause = ", ".join(set_clause_list)

                sql = f"UPDATE {table_name} SET {set_clause} WHERE {condition_records}"

                params = set_values + [pk_value]

                try:
                    self.execute(sql, params)
                except Exception as e:
                    Debug("UPDATE ERROR:", str(e), Constant.TINA4_LOG_ERROR)

            # Updating multiple records - records passed in is a list

            elif isinstance(records, list):
                for record in records:
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
                            set_values.append(value)

                    set_clause = ", ".join(set_clause_list)

                    sql = f"UPDATE {table_name} SET {set_clause} WHERE {condition_records}"

                    params = set_values + [pk_value]

                    try:
                        self.execute(sql, params)
                    except Exception as e:
                        Debug("UPDATE ERROR:", str(e), Constant.TINA4_LOG_ERROR)
