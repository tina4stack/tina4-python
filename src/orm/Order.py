from tina4_python import ORM, IntegerField, StringField, NumericField

class Order(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    customer_id = IntegerField()
    total = NumericField()
    status = StringField()
