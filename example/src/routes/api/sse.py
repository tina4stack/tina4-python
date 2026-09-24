# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import asyncio
import json
import queue
from tina4_python.core.router import get, middleware
from src.middleware.admin_auth import AdminAuth

# Thread-safe queue — simulator thread writes, async generator reads
_thread_queue = queue.Queue()
sales_queue = _thread_queue


async def sales_event_generator():
    while True:
        try:
            event = _thread_queue.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"
        except queue.Empty:
            await asyncio.sleep(1)


@middleware(AdminAuth)
@get("/api/events/sales")
async def sse_sales(request, response):
    return response.stream(sales_event_generator(), content_type="text/event-stream")
