from tina4_python.ORM import *

class User(ORM):
    __table_name__ = 'user'

    id = IntegerField(primary_key=True)
