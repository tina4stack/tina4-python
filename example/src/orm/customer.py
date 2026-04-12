from tina4_python.orm import ORM, IntegerField, StringField


class Customer(ORM):
    table_name = "customers"
    soft_delete = True

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    password_hash = StringField()
    role = StringField()
