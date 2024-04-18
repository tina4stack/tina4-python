#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os

from tina4_python.Debug import Debug

import tina4_python


def migrate(dba):
    """
    Migrates the database from the migrate folder
    :param dba:
    :return:
    """
    dba.execute(
        "create table if not exists tina4_migration(id integer, description varchar(200) default '', content blob, "
        "passed integer default 0, primary key(id))")

    Debug("Migrations found ", tina4_python.root_path + os.sep + "migrations")
    dir_list = os.listdir(tina4_python.root_path + os.sep + "migrations")

    for file in dir_list:
        if '.sql' in file:
            sql_file = open(tina4_python.root_path + os.sep + "migrations" + os.sep + file)
            content = sql_file.read()
            sql_file.close()
            try:
                dba.execute("delete from tina4_migration where description = ? and passed = ?", (file, 0))
                dba.commit()
                dba.execute("replace into tina4_migration (description, content, passed) values (?, ?, 1) ",
                            (file, content))
                dba.commit()
                dba.execute(content)
                dba.commit()
            except Exception as e:
                dba.execute("update tina4_migration set passed = ? where description = ?", (0, file))
                dba.commit()
                Debug("Failed to run", file, e)
