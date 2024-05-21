#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import importlib

class Database:

    def __init__(self, _connection_string, _username="", _password=""):
        """
        Initializes a database connection
        :param _connection_string:
        """
        # split out the connection string
        # driver:host/port:schema/path

        params = _connection_string.split(":")
        self.database_module = importlib.import_module(params[0])
        self.database_engine = params[0]
        self.database_path = params[1]
        self.username = _username
        self.password = _password

        print("LOADING", self.database_engine)
        if self.database_engine == "sqlite3":
            self.dba = self.database_module.connect(self.database_path)


        if self.database_engine == "firebird.driver":
            temp_params = self.database_path.split("/")
            self.host = temp_params[0]
            if len(temp_params) > 1:
                self.port = temp_params[1]
            else:
                self.port = 3050
            self.database_path = params[2]

            self.dba = self.database_module.connect(
                self.host+"/"+str(self.port)+":"+self.database_path,
                user=self.username,
                password=self.password
            )
            print(self.dba, self.host, self.database_path, self.username, self.port)


    def fetch(self, sql, params=(), limit=10, skip=0):
        # modify the select statement for limit and skip
        if self.database_engine == "firebird.driver":
            sql = f"select first {limit} skip {skip} * from ({sql})"
        elif self.database_engine == "sqlite3":
            sql = f"select * from ({sql}) limit {skip},{limit}"
        print("SQL", sql)
        cursor = self.dba.cursor()
        cursor.execute(sql, params)
        columns = [column[0].lower() for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        columns = [column for column in cursor.description]
        return rows, columns

    def __del__(self):

        pass




