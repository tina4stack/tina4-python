# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tina4 Core — Router, Server, Request, Response, Middleware.
"""
The HTTP engine. Zero dependencies — asyncio + stdlib only.

    from tina4_python.core import Router, Request, Response, run

    @Router.get("/api/hello")
    async def hello(request, response):
        return response.json({"message": "Hello, World!"})

    run()
"""
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.router import (
    Router, get, post, put, patch, delete, any_method,
    noauth, secured, middleware, cached, websocket,
)
from tina4_python.core.middleware import CorsMiddleware, RateLimiter
from tina4_python.core.cache import Cache
from tina4_python.core.events import on, off, emit, emit_async, once, listeners, events, clear as clear_events
from tina4_python.core.server import discover_routes, run, resolve_config, handle, start, stop

__all__ = [
    "Request", "Response", "Router",
    "get", "post", "put", "patch", "delete", "any_method", "websocket",
    "noauth", "secured", "middleware", "cached",
    "CorsMiddleware", "RateLimiter",
    "Cache",
    "on", "off", "emit", "emit_async", "once", "listeners", "events", "clear_events",
    "discover_routes", "run", "resolve_config", "handle", "start", "stop",
]
