from tina4_python import ORM, IntegerField, StringField, TextField, DateTimeField


class Comment(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    post_id = IntegerField()
    name = StringField()
    email = StringField()
    body = TextField()
    created_at = DateTimeField()
