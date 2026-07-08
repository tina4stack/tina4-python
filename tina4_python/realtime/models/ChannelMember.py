"""ChannelMember — a user's membership of a channel plus their read cursor.

``user_id`` is a string so it holds any identity shape the app puts in the JWT
(an integer id, a UUID, an email). ``last_read_at`` is the read-receipt cursor:
the timestamp of the newest message this member has seen.
"""
from tina4_python.orm import (
    ORM, IntegerField, StringField, DateTimeField, ForeignKeyField,
)
from tina4_python.realtime.models.Channel import Channel


class ChannelMember(ORM):
    table_name = "tina4_rt_channel_members"

    id = IntegerField(primary_key=True, auto_increment=True)
    channel_id = ForeignKeyField(to=Channel, related_name="members")
    user_id = StringField(required=True, max_length=128)
    role = StringField(default="member", max_length=20)  # member | admin | owner
    last_read_at = DateTimeField()
