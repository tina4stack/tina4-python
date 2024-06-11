#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
from tina4_python import Constant
from tina4_python.Debug import Debug
import tina4_python


def migrate(dba, delimiter=";"):
    """
    Migrates the database from the migrate folder
    :param delimiter: SQL delimiter
    :param dba: Database connection
    :return:
    """
    dba.execute(
        "create table if not exists tina4_migration(id integer, description varchar(200) default '', content blob, error_message blob, passed integer default 0, primary key(id))")

    Debug("Migrations found ", tina4_python.root_path + os.sep + "migrations", Constant.TINA4_LOG_INFO)
    dir_list = os.listdir(tina4_python.root_path + os.sep + "migrations")

    for file in dir_list:
        if '.sql' in file:
            Debug("Migration: Checking file", file, Constant.TINA4_LOG_INFO)
            sql_file = open(tina4_python.root_path + os.sep + "migrations" + os.sep + file)
            file_contents = sql_file.read()
            sql_file.close()
            try:
                dba.execute("delete from tina4_migration where description = ? and passed = ?", (file, 0))
                dba.commit()
                # check if migration exists in the database and has passed - no need to run the scripts below

                sql_check = "select * from tina4_migration where description = ? and passed = ?"
                query = dba.execute(sql_check, (file, 1))
                record = query.fetchone()

                if not record:
                    Debug("Migration: running migration for", file, Constant.TINA4_LOG_INFO)
                    # get each migration
                    script_content = file_contents.split(";")
                    for script in script_content:
                        dba.execute(script)
                    dba.commit()
                    dba.execute("insert into tina4_migration (description, content, passed) values (?, ?, 1) ",
                                (file, file_contents))
                    dba.commit()


            except Exception as e:
                dba.execute(
                    "insert into tina4_migration (description, content, passed, error_message) values (?, ?, 0, ?) ",
                    (file, file_contents, str(e)))
                dba.commit()

                Debug("Failed to run", file, e, Constant.TINA4_LOG_ERROR)
