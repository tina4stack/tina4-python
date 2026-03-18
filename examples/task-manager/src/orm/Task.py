from tina4_python import ORM, IntegerField, StringField, TextField, DateTimeField


class Task(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    user_id = IntegerField()
    title = StringField()
    description = TextField()
    status = StringField()
    due_date = DateTimeField()
    created_at = DateTimeField()
