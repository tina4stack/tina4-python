from tina4_python.orm import ORM, IntegerField, FloatField, ForeignKeyField
from src.orm.order import Order
from src.orm.product import Product


class OrderItem(ORM):
    table_name = "order_items"

    id = IntegerField(primary_key=True, auto_increment=True)
    order_id = ForeignKeyField(to=Order, related_name="items")
    product_id = ForeignKeyField(to=Product)
    quantity = IntegerField()
    unit_price = FloatField()
