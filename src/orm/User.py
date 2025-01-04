from tina4_python.ORM import *

class User(ORM):
    __table_name__ = 'user'
    __primary_key__ = 'id'
    id = IntegerField(primary_key=True)
