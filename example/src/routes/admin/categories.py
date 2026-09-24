# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
from tina4_python.core.router import get, post, noauth, middleware
from src.orm.category import Category
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin/categories")
async def admin_category_list(request, response):
    categories = Category.all(order_by="name")
    return response(render("admin/categories.twig", {
        "categories": [c.to_dict() for c in categories],
    }, request))


@noauth()
@middleware(AdminAuth)
@post("/admin/categories")
async def admin_create_category(request, response):
    name = request.body.get("name", "")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    Category.create(name=name, slug=slug)
    request.session.flash("success", "Category created")
    return response.redirect("/admin/categories")
