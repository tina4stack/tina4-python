# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
