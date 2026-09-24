# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Framework-owned chat data model for the realtime collaboration feature.

One class per file (Workspace, Channel, ChannelMember, Message, Attachment).
All tables carry the ``tina4_rt_`` prefix so they never collide with an app's
own domain tables, matching the ``tina4_migration`` / ``tina4_sequences``
convention. Tables are created on demand by ``realtime(features=["chat"])``
via each model's engine-aware ``create_table()``.
"""
from tina4_python.realtime.models.Workspace import Workspace
from tina4_python.realtime.models.Channel import Channel
from tina4_python.realtime.models.ChannelMember import ChannelMember
from tina4_python.realtime.models.Message import Message
from tina4_python.realtime.models.Attachment import Attachment

#: The chat tables, in dependency order (parents before children) so
#: create_table() runs cleanly and callers can iterate deterministically.
CHAT_MODELS = [Workspace, Channel, ChannelMember, Message, Attachment]

__all__ = [
    "Workspace", "Channel", "ChannelMember", "Message", "Attachment",
    "CHAT_MODELS",
]
