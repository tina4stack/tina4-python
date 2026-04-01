from tina4_python import ORM, IntegerField, StringField

class User(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    role = StringField()
