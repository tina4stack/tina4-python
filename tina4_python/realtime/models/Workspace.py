"""Workspace — the top-level container for channels (a "team" / "org")."""
from tina4_python.orm import ORM, IntegerField, StringField, DateTimeField


class Workspace(ORM):
    # Framework-owned table: the tina4_rt_ prefix keeps it clear of an app's
    # own domain tables (mirrors tina4_migration / tina4_sequences).
    table_name = "tina4_rt_workspaces"

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, max_length=200)
    created_at = DateTimeField()
