from tina4_python.ORM import *

class User(ORM):
    __table_name__ = 'test_user'

    id = IntegerField(primary_key=True)
    title = StringField()
    first_name = StringField()
    last_name = StringField()
    email = TextField()
    balance = NumericField()
    age = IntegerField()
    date_created = DateTimeField()

