from tina4_python.ORM import *
from .User import User

class Log(ORM):
    __table_name__ = 'log_table'
    __primary_key__ = 'log_id'
    id = IntegerField(primary_key=True, auto_increment=True)
    date_created = DateTimeField(default_value=datetime.now())
    description = StringField("log_description")
    log_data = BlobField()
    user_id = ForeignKeyField(IntegerField("id"), references_table=User)