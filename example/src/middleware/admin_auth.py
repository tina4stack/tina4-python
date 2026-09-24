# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from tina4_python.auth import valid_token, get_payload


class AdminAuth:
    @staticmethod
    async def before(request, response):
        token = request.session.get("token")
        if not token or not valid_token(token):
            return response.redirect("/login")

        payload = get_payload(token)
        if payload.get("role") != "admin":
            return response({"error": "Forbidden: admin access required"}, status_code=403)

        return request, response
