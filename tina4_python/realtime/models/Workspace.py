# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Workspace — the top-level container for channels (a "team" / "org")."""
from tina4_python.orm import ORM, IntegerField, StringField, DateTimeField


class Workspace(ORM):
    # Framework-owned table: the tina4_rt_ prefix keeps it clear of an app's
    # own domain tables (mirrors tina4_migration / tina4_sequences).
    table_name = "tina4_rt_workspaces"

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, max_length=200)
    created_at = DateTimeField()
