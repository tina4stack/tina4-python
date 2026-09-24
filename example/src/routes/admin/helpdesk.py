# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.core.router import get, middleware
from src.app.template import render
from src.middleware.admin_auth import AdminAuth


@middleware(AdminAuth)
@get("/admin/helpdesk")
async def admin_helpdesk(request, response):
    return response(render("admin/helpdesk.twig", {}, request))
