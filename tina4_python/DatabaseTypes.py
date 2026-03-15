#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Database driver identifiers and install instructions.

Maps short driver names to their Python module paths and provides
human-readable installation commands for each supported database.
"""

__all__ = [
    "SQLITE",
    "FIREBIRD", "FIREBIRD_INSTALL",
    "MYSQL", "MYSQL_INSTALL",
    "POSTGRES", "POSTGRES_INSTALL",
    "MSSQL", "MSSQL_INSTALL",
    "MONGODB", "MONGODB_INSTALL",
]

SQLITE = "sqlite3"
FIREBIRD = "firebird.driver"
FIREBIRD_INSTALL = "pip install firebird-driver or poetry add firebird-driver"
MYSQL = "mysql.connector"
MYSQL_INSTALL = "pip install mysql-connector-python or poetry add mysql-connector-python"
POSTGRES = "psycopg2"
POSTGRES_INSTALL = "pip install psycopg2-binary or poetry add psycopg2-binary"
MSSQL = "pymssql"
MSSQL_INSTALL = "pip install pymssql or poetry add pymssql"
MONGODB = "pymongo"
MONGODB_INSTALL = "pip install pymongo or poetry add pymongo"
