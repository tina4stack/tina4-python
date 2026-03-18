from tina4_python import ORM, IntegerField, StringField, TextField, NumericField


class Product(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    description = TextField()
    price = NumericField()
    category_id = IntegerField()
    stock = IntegerField()
