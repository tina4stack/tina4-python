# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.orm import ORM, IntegerField, StringField, FloatField, BooleanField, ForeignKeyField
from src.orm.category import Category


class Product(ORM):
    table_name = "products"
    id = IntegerField(primary_key=True, auto_increment=True)
    category_id = ForeignKeyField(to=Category, related_name="products")
    name = StringField()
    slug = StringField()
    description = StringField()
    price = FloatField()
    stock = IntegerField()
    image_url = StringField()
    is_active = BooleanField()


# ── Named Scopes ─────────────────────────────────────────────
# Reusable query shortcuts: Product.active(), Product.low_stock(), Product.expensive()
Product.scope("active", "is_active = 1")
Product.scope("low_stock", "stock < 10 and is_active = 1")
Product.scope("expensive", "price > 100 and is_active = 1")
