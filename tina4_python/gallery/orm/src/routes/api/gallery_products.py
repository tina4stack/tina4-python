# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Gallery: ORM — Product CRUD endpoints."""
from tina4_python.core.router import get, post, noauth


@get("/api/gallery/products")
async def gallery_list_products(request, response):
    return response({"products": [
        {"id": 1, "name": "Widget", "price": 9.99},
        {"id": 2, "name": "Gadget", "price": 24.99},
    ], "note": "Connect a database and deploy the ORM model for live data"})


@noauth()
@post("/api/gallery/products")
async def gallery_create_product(request, response):
    data = request.body or {}
    return response({"created": data, "id": 3}, 201)
