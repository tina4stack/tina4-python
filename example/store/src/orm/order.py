from tina4_python.orm import ORM, IntegerField, StringField, FloatField, ForeignKeyField
from src.orm.customer import Customer


class Order(ORM):
    table_name = "orders"
    id = IntegerField(primary_key=True, auto_increment=True)
    customer_id = ForeignKeyField(to=Customer, related_name="orders")
    status = StringField()
    total = FloatField()
    created_at = StringField()
    updated_at = StringField()
