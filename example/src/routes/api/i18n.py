# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.core.router import get, noauth


@noauth()
@get("/api/locale/{lang}")
async def switch_locale(lang, request, response):
    request.session.set("locale", lang)
    # Redirect back to the referring page, or home
    referer = request.headers.get("referer", "/")
    return response.redirect(referer)
