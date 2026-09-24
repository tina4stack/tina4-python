# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.orm import ORM, IntegerField, StringField


class Customer(ORM):
    table_name = "customers"
    soft_delete = True

    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    password_hash = StringField()
    role = StringField()
