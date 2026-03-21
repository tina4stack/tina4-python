"""Gallery: ORM — Product model."""
from tina4_python.orm.fields import IntegerField, StringField, NumericField


class Product:
    """Simple product model for the gallery demo."""
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    description = StringField()
    price = NumericField()
