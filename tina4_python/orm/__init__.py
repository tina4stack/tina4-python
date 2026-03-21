# Tina4 ORM — SQL-first, zero dependencies.
"""
Active Record ORM with SQL-first paradigm.

    from tina4_python.orm import ORM, Field

    class User(ORM):
        table_name = "users"
        id = Field(int, primary_key=True)
        name = Field(str)
        email = Field(str)

    # SQL-first — you write the SQL, ORM maps results
    users = User.select("SELECT * FROM users WHERE active = ?", [1])
    user = User.find(1)
    user.name = "Updated"
    user.save()
"""
from tina4_python.orm.fields import (
    Field,
    IntegerField, StringField, BooleanField, FloatField,
    DateTimeField, TextField, BlobField, NumericField,
    IntField, StrField, BoolField,  # short aliases
)
from tina4_python.orm.model import ORM, orm_bind

__all__ = [
    "ORM", "orm_bind",
    "Field",
    # Verbose (preferred)
    "IntegerField", "StringField", "BooleanField", "FloatField",
    "DateTimeField", "TextField", "BlobField", "NumericField",
    # Short aliases (backwards compat)
    "IntField", "StrField", "BoolField",
]
