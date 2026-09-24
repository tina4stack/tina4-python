# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Gallery: REST API — simple JSON endpoints."""
from tina4_python.core.router import get, post, noauth


@get("/api/gallery/hello")
async def gallery_hello(request, response):
    return response({"message": "Hello from Tina4!", "method": "GET"})


@get("/api/gallery/hello/{name}")
async def gallery_hello_name(name, request, response):
    return response({"message": f"Hello {name}!", "method": "GET"})


@noauth()
@post("/api/gallery/hello")
async def gallery_hello_post(request, response):
    data = request.body or {}
    return response({"echo": data, "method": "POST"}, 201)
