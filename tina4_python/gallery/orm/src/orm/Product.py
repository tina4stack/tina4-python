"""Gallery: ORM — Product model."""
from tina4_python.orm.fields import IntegerField, StringField


class Product:
    """Simple product model for the gallery demo."""
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    description = StringField()
    price = StringField()  # stored as string, format on display
