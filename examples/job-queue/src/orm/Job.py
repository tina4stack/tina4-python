from tina4_python import ORM, IntegerField, StringField, TextField, DateTimeField


class Job(ORM):
    id = IntegerField(primary_key=True, auto_increment=True)
    job_type = StringField()
    payload = TextField()
    status = StringField()
    result = TextField()
    created_at = DateTimeField()
