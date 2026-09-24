# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import time
import logging

logger = logging.getLogger("store")


class RequestLogger:
    @staticmethod
    async def before(request, response):
        request._start_time = time.time()
        logger.info(f"--> {request.method} {request.url}")
        return request, response

    @staticmethod
    async def after(request, response):
        duration = (time.time() - getattr(request, "_start_time", time.time())) * 1000
        logger.info(f"<-- {request.method} {request.url} {response.status_code} {duration:.1f}ms")
        return request, response
