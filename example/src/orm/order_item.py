# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.orm import ORM, IntegerField, FloatField, ForeignKeyField
from src.orm.order import Order
from src.orm.product import Product


class OrderItem(ORM):
    table_name = "order_items"

    id = IntegerField(primary_key=True, auto_increment=True)
    order_id = ForeignKeyField(to=Order, related_name="items")
    product_id = ForeignKeyField(to=Product)
    quantity = IntegerField()
    unit_price = FloatField()
