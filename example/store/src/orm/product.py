from tina4_python.orm import ORM, IntegerField, StringField, FloatField, BooleanField, ForeignKeyField
from src.orm.category import Category


class Product(ORM):
    table_name = "products"
    id = IntegerField(primary_key=True, auto_increment=True)
    category_id = ForeignKeyField(to=Category, related_name="products")
    name = StringField()
    slug = StringField()
    description = StringField()
    price = FloatField()
    stock = IntegerField()
    image_url = StringField()
    is_active = BooleanField()
