# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.core.router import get, noauth
from tina4_python.swagger import description, tags, example
from src.orm.category import Category


@noauth()
@tags("Categories")
@description("List all product categories")
@example([{"id": 1, "name": "Electronics", "slug": "electronics"}])
@get("/api/categories")
async def api_category_list(request, response):
    categories = Category.all(order_by="name")
    return response([c.to_dict() for c in categories], 200)
