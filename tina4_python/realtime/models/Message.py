"""Message — one posted message in a channel.

``thread_id`` is nullable: NULL for a top-level message, or the id of the parent
message when this is a threaded reply. ``edited_at`` is NULL until an edit.
"""
from tina4_python.orm import (
    ORM, IntegerField, StringField, TextField, DateTimeField, ForeignKeyField,
)
from tina4_python.realtime.models.Channel import Channel


class Message(ORM):
    table_name = "tina4_rt_messages"

    id = IntegerField(primary_key=True, auto_increment=True)
    channel_id = ForeignKeyField(to=Channel, related_name="messages")
    user_id = StringField(required=True, max_length=128)
    body = TextField()
    thread_id = IntegerField()          # nullable: parent message id for a reply
    created_at = DateTimeField()
    edited_at = DateTimeField()         # nullable: set when the message is edited
