from tina4_python.orm import ORM, IntegerField, StringField


class Category(ORM):
    table_name = "categories"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    slug = StringField()
    description = StringField()
