"""Attachment — a file linked to a channel (and optionally a message).

``storage_key`` is the key the StorageBackend put/get the bytes under; the row
carries only metadata, never the blob. ``channel_id`` scopes the file for
permission checks (a download is allowed only to a member of that channel).
``message_id`` is NULL until the file is attached to a posted message.
``thumb_key`` is NULL until a preview is generated.
"""
from tina4_python.orm import (
    ORM, IntegerField, StringField, ForeignKeyField,
)
from tina4_python.realtime.models.Channel import Channel
from tina4_python.realtime.models.Message import Message


class Attachment(ORM):
    table_name = "tina4_rt_attachments"

    id = IntegerField(primary_key=True, auto_increment=True)
    channel_id = ForeignKeyField(to=Channel, related_name="attachments")
    message_id = ForeignKeyField(to=Message, related_name="attachments")  # nullable
    storage_key = StringField(required=True, max_length=255)
    filename = StringField(max_length=255)
    mime = StringField(max_length=128)
    size = IntegerField()
    thumb_key = StringField(max_length=255)   # nullable: preview key
