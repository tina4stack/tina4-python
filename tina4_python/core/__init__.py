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
    noauth, secured, middleware, cached,
)
from tina4_python.core.middleware import CorsMiddleware, RateLimiter
from tina4_python.core.cache import Cache
from tina4_python.core.events import on, off, emit, emit_async, once, listeners, events, clear as clear_events
from tina4_python.core.server import run

__all__ = [
    "Request", "Response", "Router",
    "get", "post", "put", "patch", "delete", "any_method",
    "noauth", "secured", "middleware", "cached",
    "CorsMiddleware", "RateLimiter",
    "Cache",
    "on", "off", "emit", "emit_async", "once", "listeners", "events", "clear_events",
    "run",
]
