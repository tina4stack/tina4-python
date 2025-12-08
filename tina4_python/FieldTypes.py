#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

import ast
import inspect
from datetime import datetime
from tina4_python.DatabaseTypes import MSSQL, POSTGRES, FIREBIRD

class BaseField:
    primary_key = False
    column_type = None
    default_value = None
    column_name = None
    auto_increment = False
    value = None
    field_size = None
    decimal_places = None
    protected_field = False

    def get_definition(self, database_type="generic"):
        return self.column_name.lower() + " not defined"

    def __eq__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other == self.value

    def __ne__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other != self.value

    def __add__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other + self.value

    def __mul__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other * self.value

    def __sub__(self, other):
        if self.value is None:
            self.value = self.default_value
        return self.value - other

    def __truediv__(self, other):
        if self.value is None:
            self.value = self.default_value
        return self.value / other

    def __str__(self):
        if self.value is None:
            self.value = self.default_value
        return str(self.value)

    def __int__(self):
        if self.value is None:
            self.value = self.default_value
        return int(self.value)

    def __float__(self):
        if self.value is None:
            self.value = self.default_value
        return float(self.value)

    def __init__(self, column_name=None, primary_key=False, default_value=None, auto_increment=False, field_size=None,
                 decimal_places=None, protected_field=False):
        self.primary_key = primary_key
        self.column_type = None
        if default_value is not None:
            self.default_value = default_value
        self.auto_increment = auto_increment
        self.protected_field = protected_field
        if field_size is not None:
            self.field_size = field_size
        if decimal_places is not None:
            self.decimal_places = decimal_places

        if column_name is None:
            frame = inspect.stack()[1]
            # Parse python syntax of the assignment line
            st = ast.parse(frame.code_context[0].strip())
            stmt = st.body[0]
            # Assume class being instanced as simple assign statement
            assert (isinstance(stmt, ast.Assign))
            # Parse the target the class is assigned to
            target = stmt.targets[0]
            self.column_name = target.id
        else:
            self.column_name = column_name


class DateTimeField(BaseField):
    column_type = datetime
    default_value = datetime.now()

    def get_definition(self, database_type="generic"):
        if database_type == MSSQL:
            return self.column_name.lower() + " datetime"
        else:
            return self.column_name.lower() + " timestamp"


class IntegerField(BaseField):
    column_type = int
    default_value = 0

    def get_definition(self, database_type="generic"):
        not_null = ""
        if self.primary_key:
            not_null = " not null"
        if database_type == MSSQL:
            return self.column_name.lower() + " integer identity(1,1)  " + not_null
        else:
            return self.column_name.lower() + " integer default " + str(self.default_value) + " " + not_null


class NumericField(BaseField):
    column_type = float
    default_value = 0.00
    field_size = 10
    decimal_places = 2

    def get_definition(self, database_type="generic"):
        not_null = ""
        if self.primary_key:
            not_null = " not null"

        return self.column_name.lower() + " numeric(" + str(self.field_size) + "," + str(
            self.decimal_places) + ") default " + str(self.default_value) + not_null


class StringField(BaseField):
    column_type = str
    default_value = ""
    field_size = 255

    def get_definition(self, database_type="generic"):
        not_null = ""
        if self.primary_key:
            not_null = " not null"

        return self.column_name.lower() + " varchar(" + str(self.field_size) + ") default '" + str(
            self.default_value) + "'" + not_null


class TextField(StringField):
    pass


class BlobField(BaseField):
    column_type = bytes
    default_value = None

    def get_definition(self, database_type="generic"):
        field_type = "blob"
        if database_type == MSSQL:
            field_type = "varbinary(max)"
        elif database_type == FIREBIRD:
            field_type = "blob sub_type 0"
        return self.column_name.lower() + " " + field_type


class JSONBField(BaseField):
    column_type = dict
    default_value = None

    def get_definition(self, database_type="generic"):
        field_type = "blob"
        if database_type == POSTGRES:
            field_type = "jsonb"
        elif database_type == MSSQL:
            field_type = "varbinary(max)"
        elif database_type == FIREBIRD:
            field_type = "blob sub_type 0"

        return self.column_name.lower() + " " + field_type

class ForeignKeyField:
    field_type = None
    references_table = None
    references_column = None
    primary_key = False
    foreign_key = True
    value = None
    default_value = None
    protected_field = False

    def __eq__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other == self.value

    def __ne__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other != self.value

    def __add__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other + self.value

    def __mul__(self, other):
        if self.value is None:
            self.value = self.default_value
        return other * self.value

    def __sub__(self, other):
        if self.value is None:
            self.value = self.default_value
        return self.value - other

    def __truediv__(self, other):
        if self.value is None:
            self.value = self.default_value
        return self.value / other

    def __str__(self):
        if self.value is None:
            self.value = self.default_value
        return str(self.value)

    def __init__(self, field_type=BaseField, references=None, column_name=None, default_value = None, protected_field=False):
        self.field_type = field_type
        self.references_table = references
        self.references_column = field_type.column_name
        self.default_value = default_value
        self.auto_increment = False
        self.protected_field = protected_field
        self.value = field_type

        if column_name is None:
            frame = inspect.stack()[1]
            # Parse python syntax of the assignment line
            st = ast.parse(frame.code_context[0].strip())
            stmt = st.body[0]
            # Assume class being instanced as simple assign statement
            assert (isinstance(stmt, ast.Assign))
            # Parse the target the class is assigned to
            target = stmt.targets[0]
            self.column_name = target.id
        else:
            self.column_name = column_name

    def get_definition(self, database_type="generic"):
        references_definition = self.field_type.get_definition(database_type).split(" ")
        # print("REFERENCES", references_definition, self.references_table.__table_name__, self.references_column)
        return self.column_name + " " + str(references_definition[1]) + " references " + self.references_table.__table_name__ + "(" + self.references_column + ") on update cascade on delete cascade"


def get_field_type_values(params):
    """
    Gets the base field type
    :param params:
    :return:
    """
    values = []
    for param in params:
        if isinstance(param, list):
            values.append(get_field_type_values(param))
        elif isinstance(param, (IntegerField, NumericField, BlobField, JSONBField, IntegerField, StringField, TextField, DateTimeField)):
            values.append(param.value)
        else:
            values.append(param)
    return values