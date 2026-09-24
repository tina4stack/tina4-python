# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.orm import ORM, IntegerField, StringField


class Category(ORM):
    table_name = "categories"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    slug = StringField()
    description = StringField()
