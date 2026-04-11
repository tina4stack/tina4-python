from tina4_python.orm import ORM, IntegerField, StringField, ForeignKeyField
from src.orm.product import Product


class CartItem(ORM):
    table_name = "cart_items"

    id = IntegerField(primary_key=True, auto_increment=True)
    session_id = StringField()
    product_id = ForeignKeyField(to=Product)
    quantity = IntegerField()
