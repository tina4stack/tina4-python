#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib
import sqlite3

from tina4_python import Debug, Constant
from tina4_python.DatabaseResult import DatabaseResult


class Database:

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
        Debug("FETCH:", sql, "params", params, "limit", limit, "skip", skip, Constant.TINA4_LOG_DEBUG)
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
            Debug("FETCH:", "cursor description", cursor.description, "records", records, "rows", rows, "columns",
                  columns, Constant.TINA4_LOG_DEBUG)
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
        Debug("FETCHONE:", sql, "params", params, "skip", skip)
        # Calling the fetch method with limit as 1 and returning the result
        return self.fetch(sql, params=params, limit=1, skip=skip)

    def execute(self, sql, params=()):
        """
        Execute a query based on a sql statement
        :param sql:
        :param params:
        :return:
        """
        Debug("EXECUTE:", sql, "params", params)

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

    def start_transaction(self):
        try:
            if self.database_engine == "sqlite3" or self.database_engine == "postgres":
                cursor = self.dba.cursor()
                cursor.execute("BEGIN")
            elif self.database_engine == "firebird.driver":
                self.dba.transaction_manager().begin()
            elif self.database_engine == "mysql":
                self.dba.start_transaction()
        except Exception as e:
            Debug("START TRANSACTION ERROR:", str(e))

    def commit(self):
        self.dba.commit()

    def rollback(self):
        self.dba.rollback()

    def close(self):
        self.dba.close()
        pass

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

            if self.database_engine == "sqlite3" or self.database_engine == "firebird.driver":
                placeholders = ", ".join(['?'] * len(data))
            elif self.database_engine == "mysql" or self.database_engine == "postgres":
                placeholders = ", ".join(['%s'] * len(data))

            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
            cursor = self.dba.cursor()
            try:
                cursor.execute(sql, values)
            except Exception as e:
                Debug("INSERT ERROR:", str(e))
        elif isinstance(data, list):
            columns = ", ".join(data[0].keys())

            if self.database_engine == "sqlite3" or self.database_engine == "firebird.driver":
                placeholders = ", ".join(['?'] * len(data[0]))
            elif self.database_engine == "mysql" or self.database_engine == "postgres":
                placeholders = ", ".join(['%s'] * len(data[0]))

            values = [list(record.values()) for record in data]
            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
            cursor = self.dba.cursor()
            try:
                cursor.executemany(sql, values)
            except Exception as e:
                Debug("INSERT MANY ERROR:", str(e))

    def delete(self, table_name, filter):
        pass
