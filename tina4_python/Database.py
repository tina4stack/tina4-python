#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib
import datetime

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

        if self.database_engine == self.SQLITE:
            self.dba = self.database_module.connect(self.database_path)
            self.port = None
            self.host = None

        if self.database_engine == self.FIREBIRD:
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
              Constant.TINA4_LOG_DEBUG)

    def current_timestamp(self):
        """
        Gets the current timestamp based on the database being used
        :return:
        """
        if self.database_engine == self.FIREBIRD:
            return datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        elif self.database_engine == self.SQLITE:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch(self, sql, params=[], limit=10, skip=0):
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
        if self.database_engine == self.FIREBIRD:
            sql = f"select first {limit} skip {skip} * from ({sql})"
        elif self.database_engine == self.SQLITE:
            sql = f"select * from ({sql}) limit {skip},{limit}"
        else:
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

    def fetch_one(self, sql, params=[], skip=0):
        """
        Fetch a single record based on a sql statement
        :param sql:
        :param params:
        :param skip:
        :return:
        """
        Debug("FETCHONE:", sql, "params", params, "skip", skip, Constant.TINA4_LOG_DEBUG)
        # Calling the fetch method with limit as 1 and returning the result
        record = self.fetch(sql, params=params, limit=1, skip=skip)
        if record.error is None and record.count == 1:
            return record.records[0]
        else:
            return None

    def execute(self, sql, params=()):
        """
        Execute a query based on a sql statement
        :param sql:
        :param params:
        :return:
        """
        Debug("EXECUTE:", sql, "params", params, Constant.TINA4_LOG_DEBUG)

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

        Debug("EXECUTE MANY:", sql, "params", params, Constant.TINA4_LOG_DEBUG)

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
            data = [data]

        if isinstance(data, list):
            columns = ", ".join(data[0].keys())
            # Checking which database engine is used to generate respective syntax for placeholders
            if self.database_engine in (self.SQLITE, self.FIREBIRD):
                placeholders = ", ".join(['?'] * len(data[0]))
            elif self.database_engine in (self.MYSQL, self.POSTGRES):
                placeholders = ", ".join(['%s'] * len(data[0]))
            else:
                placeholders = ", ".join(['?'] * len(data))

            values = [list(record.values()) for record in data]
            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
            Debug("SQL:", sql, Constant.TINA4_LOG_DEBUG)

            result = self.execute_many(sql, values)

            if result.error is None:
                return True
            else:
                Debug("INSERT ERROR:", result.error, Constant.TINA4_LOG_ERROR)
                return False

    def delete(self, table_name, filter=None):
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
        else:
            placeholder = "?"

        if filter is not None:
            # Updating a single record - record passed in is a dictionary
            if isinstance(filter, dict):
                filter = [filter]

            # Updating multiple records - records passed in is a list
            if isinstance(filter, list):
                for record in filter:
                    pk_value = []
                    condition_records = []

                    for column, value in record.items():
                        condition_records.append(f"{column} = {placeholder}")
                        pk_value.append(value)

                    condition_records = " and ".join(condition_records)

                    sql = f"DELETE FROM {table_name} WHERE {condition_records}"
                    Debug("SQL:", sql, Constant.TINA4_LOG_DEBUG)

                    params = pk_value

                    result = self.execute(sql, params)
                    if result.error is not None:
                        break

                if result.error is None:
                    return True
                else:
                    Debug("DELETE ERROR:", result.error, Constant.TINA4_LOG_ERROR)
                    return False

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
        else:
            placeholder = "?"

        if records is not None:
            # Updating a single record - record passed in is a dictionary
            if isinstance(records, dict):
                records = [records]

            # Updating multiple records - records passed in is a list
            if isinstance(records, list):
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
                    Debug("SQL:", sql, Constant.TINA4_LOG_DEBUG)

                    params = set_values + [pk_value]

                    result = self.execute(sql, params)
                    if result.error is not None:
                        break

                if result.error is None:
                    return True
                else:
                    Debug("UPDATE ERROR:", result.error, Constant.TINA4_LOG_ERROR)
                    return False
