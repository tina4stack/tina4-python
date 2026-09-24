# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Channel — a conversation stream inside a workspace.

``kind`` is one of ``public`` (any workspace member can join), ``private``
(explicit membership), or ``dm`` (a direct message between members).
"""
from tina4_python.orm import (
    ORM, IntegerField, StringField, DateTimeField, ForeignKeyField,
)
from tina4_python.realtime.models.Workspace import Workspace


class Channel(ORM):
    table_name = "tina4_rt_channels"

    id = IntegerField(primary_key=True, auto_increment=True)
    workspace_id = ForeignKeyField(to=Workspace, related_name="channels")
    name = StringField(required=True, max_length=200)
    kind = StringField(default="public", max_length=20)  # public | private | dm
    created_at = DateTimeField()
