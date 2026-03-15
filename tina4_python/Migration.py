#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
import re
import sys

from tina4_python import ShellColors
from tina4_python import Constant
from tina4_python import Messages
from tina4_python.Debug import Debug
from tina4_python.Database import MSSQL, POSTGRES, FIREBIRD, MYSQL
import tina4_python


def _firebird_column_exists(dba, table_name, column_name):
    """Check if a column already exists in a Firebird table via RDB$RELATION_FIELDS.

    Uses a raw cursor to bypass the pagination layer (which wraps queries in
    subqueries with COUNT(*) OVER()) — system catalogue queries break when wrapped.
    """
    cursor = dba.dba.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM RDB$RELATION_FIELDS "
            "WHERE TRIM(RDB$RELATION_NAME) = ? AND TRIM(RDB$FIELD_NAME) = ?",
            [table_name.upper(), column_name.upper()],
        )
        row = cursor.fetchone()
        return row is not None
    finally:
        cursor.close()


def _is_idempotent_skip(dba, script):
    """
    Check if a DDL statement can be safely skipped because the change already exists.
    Returns True if the statement should be skipped (already applied), False otherwise.
    Currently handles:
      - Firebird: ALTER TABLE ... ADD <column> (no IF NOT EXISTS support)
    """
    if dba.database_engine != FIREBIRD:
        return False

    stripped = script.strip()
    # Match: ALTER TABLE <table> ADD <column> <datatype>...
    match = re.match(
        r"(?i)ALTER\s+TABLE\s+(\S+)\s+ADD\s+(\S+)\s+",
        stripped,
    )
    if match:
        table_name = match.group(1).strip('"')
        column_name = match.group(2).strip('"')
        if _firebird_column_exists(dba, table_name, column_name):
            Debug.info(
                ShellColors.bright_yellow,
                f"  Skipping (column already exists): ALTER TABLE {table_name} ADD {column_name}",
                ShellColors.end,
            )
            return True
    return False


def migrate(dba, delimiter=";", migration_folder="migrations"):
    """
    Migrates the database from the migrate folder
    :param delimiter: SQL delimiter
    :param dba: Database connection
    :param migration_folder: Alternative folder for migrations
    :return:
    """
    if dba.database_engine == MSSQL:
        if not dba.table_exists("tina4_migration"):
            dba.execute("create table tina4_migration(id integer identity(1,1) not null, description varchar(200) default '', content nvarchar(max), error_message nvarchar(max), passed integer default 0, primary key(id))")
        dba.execute("SET IDENTITY_INSERT tina4_migration ON")
    elif dba.database_engine == POSTGRES:
        dba.execute(
            "create table if not exists tina4_migration(id serial primary key, description varchar(200) default '', content text, error_message text, passed integer default 0)")
    elif dba.database_engine == MYSQL:
        dba.execute(
            "create table if not exists tina4_migration(id integer not null auto_increment, description varchar(200) default '', content text, error_message text, passed integer default 0, primary key(id))")
    elif dba.database_engine == FIREBIRD:
        if not dba.table_exists("tina4_migration"):
            dba.execute(
                "create table tina4_migration(id integer not null, description varchar(200) default '', content blob sub_type text, error_message blob sub_type text, passed integer default 0, primary key(id))")
    else:
        dba.execute(
            "create table if not exists tina4_migration(id integer not null, description varchar(200) default '', content blob, error_message blob, passed integer default 0, primary key(id))")

    Debug.info(ShellColors.bright_blue, Messages.MSG_MIGRATION_FOUND.format(path=tina4_python.root_path + os.sep + migration_folder), ShellColors.end)
    dir_list = os.listdir(tina4_python.root_path + os.sep + migration_folder)
    dir_list.sort()

    for file in dir_list:
        if '.sql' in file:
            Debug.info(ShellColors.green, Messages.MSG_MIGRATION_CHECKING.format(file=file), ShellColors.end)
            sql_file = open(tina4_python.root_path + os.sep + migration_folder + os.sep + file)
            file_contents = sql_file.read()
            sql_file.close()
            try:
                dba.execute("delete from tina4_migration where description = ? and passed = ?", [file, 0])
                dba.commit()
                # check if migration exists in the database and has passed - no need to run the scripts below

                sql_check = "select * from tina4_migration where description = ? and passed = ?"
                record = dba.fetch(sql_check, [file, 1])

                if record.count == 0:
                    Debug.info(ShellColors.bright_red, Messages.MSG_MIGRATION_RUNNING.format(file=file), ShellColors.end)
                    # get each migration
                    script_content = file_contents.split(";")

                    # all scripts need to pass
                    error = False
                    error_message = ""
                    for script in script_content:
                        if script.strip() != "":
                            # Skip DDL that is already applied (e.g. Firebird ALTER TABLE ADD)
                            if _is_idempotent_skip(dba, script):
                                continue
                            result = dba.execute(script)
                            if result.error is not None:
                                error = True
                                error_message = result.error
                                break

                    if not error:
                        Debug.info(ShellColors.bright_yellow, "Migration:", ShellColors.end, ShellColors.bright_green + Messages.MSG_MIGRATION_PASSED.format(file=file), ShellColors.end)
                        dba.commit()
                        next_id = dba.get_next_id("tina4_migration")
                        dba.execute("insert into tina4_migration (id, description, content, passed) values (?, ?, ?, 1) ",
                                    [next_id, file, file_contents])
                        dba.commit()
                    else:
                        # did not pass
                        Debug.info(ShellColors.bright_yellow, "Migration:", ShellColors.end, ShellColors.bright_red + Messages.MSG_MIGRATION_FAILED.format(file=file), error_message, ShellColors.end)
                        dba.rollback()
                        next_id = dba.get_next_id("tina4_migration")
                        dba.execute(
                            "insert into tina4_migration (id, description, content, passed, error_message) values (?, ?, ?, 0, ?) ",
                            [next_id, file, file_contents, str(error_message)])
                        dba.commit()
                        sys.exit(1)
            except Exception as e:
                next_id = dba.get_next_id("tina4_migration")
                dba.execute(
                    "insert into tina4_migration (id, description, content, passed, error_message) values (?, ?, ?, 0, ?) ",
                    [next_id, file, file_contents, str(e)])
                dba.commit()

                Debug.error(Messages.MSG_MIGRATION_ERROR.format(file=file), e)
                sys.exit(1)

    if dba.database_engine == MSSQL:
        dba.execute("SET IDENTITY_INSERT tina4_migration OFF")
