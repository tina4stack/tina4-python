# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.orm import ORM, IntegerField, StringField, FloatField, ForeignKeyField
from src.orm.customer import Customer


class Order(ORM):
    table_name = "orders"
    id = IntegerField(primary_key=True, auto_increment=True)
    customer_id = ForeignKeyField(to=Customer, related_name="orders")
    status = StringField()
    total = FloatField()
    created_at = StringField()
    updated_at = StringField()
