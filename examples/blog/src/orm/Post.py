from tina4_python import ORM, IntegerField, StringField, TextField, DateTimeField


class Post(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    title = StringField()
    slug = StringField()
    content = TextField()
    author = StringField()
    created_at = DateTimeField()
