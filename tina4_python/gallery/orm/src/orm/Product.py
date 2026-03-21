"""Gallery: ORM — Product model."""
from tina4_python import ORM, IntegerField, StringField, NumericField


class Product(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    description = StringField()
    price = NumericField()
