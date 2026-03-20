from tina4_python import ORM, IntegerField, StringField, DateTimeField

class Todo(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    completed = IntegerField(default=0)
    created_at = DateTimeField()
