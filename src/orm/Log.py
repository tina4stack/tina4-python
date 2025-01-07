from tina4_python.ORM import *
from .User import User

class Log(ORM):
    __table_name__ = 'test_record'
    id = IntegerField(primary_key=True, auto_increment=True)
    date_created = DateTimeField(default_value=datetime.now())
    description = StringField("name")
    log_data = BlobField()
    some_id = IntegerField(primary_key=True)
    user_id = ForeignKeyField(IntegerField("id"), references_table=User)