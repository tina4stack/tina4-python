# Tina4 Router — Decorator-based route registration with pattern matching.
"""
Routes are registered via decorators. Pattern matching supports dynamic params.

    @get("/api/users")
    async def list_users(request, response):
        return response.json([])

    @get("/api/users/{id}")
    async def get_user(request, response):
        user_id = request.param("id")
        return response.json({"id": user_id})

    @post("/api/users")
    async def create_user(request, response):
        return response.status(201).json(request.body)
"""
import re
import functools
from tina4_python.debug import Log


# Global route registry
_routes: list[dict] = []

# Global WebSocket route registry
_ws_routes: list[dict] = []


class RouteRef:
    """Thin wrapper around a registered route dict, enabling chained modifiers.

    Usage::

        Router.get("/api/data", handler).secure().cache()
    """

    __slots__ = ("_route",)

    def __init__(self, route: dict):
        self._route = route

    def secure(self):
        """Mark this route as requiring bearer-token authentication."""
        self._route["auth_required"] = True
        return self

    def cache(self, max_age: int | None = None):
        """Mark this route as cacheable.

        Args:
            max_age: Optional TTL override in seconds.
        """
        self._route["cached"] = True
        if max_age is not None:
            self._route["cache_max_age"] = max_age
        return self


class RouteGroup:
    """A group of routes sharing a common prefix and middleware.

    Passed to the callback in Router.group(). Supports nesting.

    Usage::

        Router.group("/api", lambda group: [
            group.get("/users", list_handler),
            group.post("/users", create_handler),
            group.group("/admin", lambda admin: [
                admin.get("/stats", stats_handler),
            ], middleware=[admin_check]),
        ], middleware=[auth_check])
    """

    def __init__(self, router_cls, prefix: str, middleware: list = None):
        self._router = router_cls
        self._prefix = prefix
        self._middleware = middleware or []

    def get(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("GET", path, handler, middleware=self._middleware, **options)

    def post(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("POST", path, handler, middleware=self._middleware, **options)

    def put(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("PUT", path, handler, middleware=self._middleware, **options)

    def patch(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("PATCH", path, handler, middleware=self._middleware, **options)

    def delete(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("DELETE", path, handler, middleware=self._middleware, **options)

    def any(self, path: str, handler, **options) -> RouteRef:
        return self._router.add("ANY", path, handler, middleware=self._middleware, **options)

    def group(self, prefix: str, callback, middleware=None):
        merged = list(self._middleware) + (middleware or [])
        nested = RouteGroup(self._router, self._prefix + prefix.rstrip("/"), merged)
        callback(nested)


class Router:
    """Route registry and matcher."""

    # ── Group state (used by Router.group) ────────────────────────
    _group_prefix: str = ""
    _group_middleware: list = []

    @classmethod
    def group(cls, prefix: str, callback, middleware=None):
        """Register routes with a shared prefix and optional middleware.

        The callback receives a RouteGroup object with get/post/put/patch/
        delete/any/group methods for registering routes under the prefix.

        Usage::

            Router.group("/api", lambda group: [
                group.get("/users", list_handler),
                group.post("/users", create_handler),
                group.group("/admin", lambda admin: [
                    admin.get("/stats", stats_handler),
                ], middleware=[admin_check]),
            ], middleware=[auth_check])
        """
        prev_prefix = cls._group_prefix
        prev_middleware = list(cls._group_middleware)

        cls._group_prefix = prev_prefix + prefix.rstrip("/")
        cls._group_middleware = prev_middleware + (middleware or [])

        try:
            group = RouteGroup(cls, cls._group_prefix, list(cls._group_middleware))
            callback(group)
        finally:
            cls._group_prefix = prev_prefix
            cls._group_middleware = prev_middleware

    @classmethod
    def websocket(cls, path: str, handler) -> None:
        """Register a WebSocket route (imperative, non-decorator style).

        The handler signature is::

            async def handler(connection, event, data):
                ...

        Where:
        - ``connection`` is a :class:`WebSocketConnection`
        - ``event`` is ``"open"``, ``"message"``, or ``"close"``
        - ``data`` is the message payload (str for message, None for open/close)
        """
        pattern, param_names = _compile_pattern(path)
        route = {
            "path": path,
            "pattern": pattern,
            "param_names": param_names,
            "handler": handler,
        }
        _ws_routes.append(route)
        Log.debug(f"WebSocket route registered: {path}")

    @staticmethod
    def match_ws(path: str) -> tuple[dict | None, dict]:
        """Find a WebSocket route matching the given path. Returns (route, params)."""
        for route in _ws_routes:
            m = route["pattern"].match(path)
            if m:
                params = {}
                for i, name in enumerate(route["param_names"]):
                    params[name] = m.group(i + 1)
                return route, params
        return None, {}

    @staticmethod
    def all_ws() -> list[dict]:
        """Return all registered WebSocket routes."""
        return _ws_routes

    @classmethod
    def get(cls, path: str, handler, **options) -> "RouteRef":
        """Register a GET route (imperative, non-decorator style)."""
        return cls.add("GET", path, handler, **options)

    @classmethod
    def post(cls, path: str, handler, **options) -> "RouteRef":
        """Register a POST route (imperative, non-decorator style)."""
        return cls.add("POST", path, handler, **options)

    @classmethod
    def put(cls, path: str, handler, **options) -> "RouteRef":
        """Register a PUT route (imperative, non-decorator style)."""
        return cls.add("PUT", path, handler, **options)

    @classmethod
    def patch(cls, path: str, handler, **options) -> "RouteRef":
        """Register a PATCH route (imperative, non-decorator style)."""
        return cls.add("PATCH", path, handler, **options)

    @classmethod
    def delete(cls, path: str, handler, **options) -> "RouteRef":
        """Register a DELETE route (imperative, non-decorator style)."""
        return cls.add("DELETE", path, handler, **options)

    @classmethod
    def any(cls, path: str, handler, **options) -> "RouteRef":
        """Register a route for any HTTP method (imperative, non-decorator style)."""
        return cls.add("ANY", path, handler, **options)

    @classmethod
    def add(cls, method: str, path: str, handler, **options) -> "RouteRef":
        """Register a route handler.

        Auth defaults:
        - GET routes are public by default
        - POST/PUT/PATCH/DELETE require auth by default
        - Use @noauth() to make a write route public
        - Use @secured() to protect a GET route

        Returns a :class:`RouteRef` so callers can chain ``.secure()`` /
        ``.cache()``::

            Router.get("/api/data", handler).secure().cache()
        """
        # Apply group prefix
        if cls._group_prefix:
            path = cls._group_prefix + path

        # Merge group middleware with route-level middleware and handler-level middleware
        handler_mw = getattr(handler, "_middleware", [])
        route_mw = options.get("middleware", [])
        combined_mw = list(cls._group_middleware) + list(handler_mw) + list(route_mw)
        if combined_mw:
            options["middleware"] = combined_mw

        pattern, param_names = _compile_pattern(path)

        # Auth default: GET=public, writes=secured
        m = method.upper()
        if "auth_required" in options:
            auth_required = options["auth_required"]
        elif hasattr(handler, "_noauth"):
            auth_required = False
        elif hasattr(handler, "_secured"):
            auth_required = True
        else:
            auth_required = m not in ("GET", "ANY")

        route = {
            "method": m,
            "path": path,
            "pattern": pattern,
            "param_names": param_names,
            "handler": handler,
            "middleware": options.get("middleware", []),
            "auth_required": auth_required,
            "cached": options.get("cached", False),
            "cache_max_age": options.get("cache_max_age", 60),
        }
        _routes.append(route)
        Log.debug(f"Route registered: {m} {path} (auth={'required' if auth_required else 'public'})")
        return RouteRef(route)

    @staticmethod
    def match(method: str, path: str) -> tuple[dict | None, dict]:
        """Find a route matching method + path. Returns (route, params)."""
        for route in _routes:
            if route["method"] not in (method.upper(), "ANY"):
                continue
            m = route["pattern"].match(path)
            if m:
                params = {}
                for i, name in enumerate(route["param_names"]):
                    params[name] = m.group(i + 1)
                return route, params

        return None, {}

    @staticmethod
    def get_routes() -> list[dict]:
        """Return all registered routes."""
        return _routes

    @staticmethod
    def list_routes() -> list[dict]:
        """Return all registered routes (debug-friendly)."""
        return _routes

    @staticmethod
    def clear():
        """Clear all routes (for testing)."""
        _routes.clear()
        _ws_routes.clear()


def _compile_pattern(path: str) -> tuple[re.Pattern, list[str]]:
    """Convert a route path to a regex pattern.

    Supports:
        /api/users          → exact match
        /api/users/{id}     → named parameter (any non-slash chars)
        /api/files/{path:path}  → greedy (matches remaining path)
    """
    param_names = []
    regex_parts = []

    segments = path.strip("/").split("/")
    for i, segment in enumerate(segments):
        if segment == "*":
            # Wildcard: matches the rest of the path (greedy)
            param_names.append("*")
            regex_parts.append("(.+)")
            break  # Nothing can follow a wildcard
        elif segment.startswith("{") and segment.endswith("}"):
            inner = segment[1:-1]
            if ":" in inner:
                name, type_hint = inner.split(":", 1)
                if type_hint == "path":
                    regex_parts.append("(.+)")
                elif type_hint == "int":
                    regex_parts.append("(\\d+)")
                elif type_hint == "float":
                    regex_parts.append("([\\d.]+)")
                else:
                    regex_parts.append("([^/]+)")
            else:
                name = inner
                regex_parts.append("([^/]+)")
            param_names.append(name)
        else:
            regex_parts.append(re.escape(segment))

    pattern_str = "^/" + "/".join(regex_parts) + "/?$"
    return re.compile(pattern_str), param_names


# Decorator functions — the public API

def _register_route(method: str, path: str, fn, **options):
    """Common registration logic that preserves handler attributes on the returned ref."""
    ref = Router.add(method, path, fn, **options)
    # Propagate handler attributes to the wrapper so stacked decorators still work
    fn._route_ref = ref
    return fn


def get(path: str, **options):
    """Register a GET route."""
    def decorator(fn):
        return _register_route("GET", path, fn, **options)
    return decorator


def post(path: str, **options):
    """Register a POST route."""
    def decorator(fn):
        return _register_route("POST", path, fn, **options)
    return decorator


def put(path: str, **options):
    """Register a PUT route."""
    def decorator(fn):
        return _register_route("PUT", path, fn, **options)
    return decorator


def patch(path: str, **options):
    """Register a PATCH route."""
    def decorator(fn):
        return _register_route("PATCH", path, fn, **options)
    return decorator


def delete(path: str, **options):
    """Register a DELETE route."""
    def decorator(fn):
        return _register_route("DELETE", path, fn, **options)
    return decorator


def any_method(path: str, **options):
    """Register a route for any HTTP method."""
    def decorator(fn):
        return _register_route("ANY", path, fn, **options)
    return decorator

# Alias — @any() is the standard name across all Tina4 frameworks
any = any_method


def websocket(path: str):
    """Register a WebSocket route.

    Usage::

        @websocket("/ws/chat/{room}")
        async def chat(connection, event, data):
            if event == "message":
                await connection.broadcast(data)
            elif event == "open":
                await connection.send(f"Welcome to {connection.params['room']}")
    """
    def decorator(fn):
        Router.websocket(path, fn)
        return fn
    return decorator


# ── Auth Decorators ────────────────────────────────────────────

def noauth():
    """Make a write route (POST/PUT/PATCH/DELETE) public — no auth required."""
    def decorator(fn):
        fn._noauth = True
        # If route was already registered (decorator applied after @get/@post),
        # update the route dict directly.
        if hasattr(fn, "_route_ref"):
            fn._route_ref._route["auth_required"] = False
        return fn
    return decorator


def secured():
    """Require auth on a GET route (which is public by default)."""
    def decorator(fn):
        fn._secured = True
        # If route was already registered (decorator applied after @get/@post),
        # update the route dict directly.
        if hasattr(fn, "_route_ref"):
            fn._route_ref._route["auth_required"] = True
        return fn
    return decorator


# ── Middleware Decorator ───────────────────────────────────────

def middleware(*middleware_classes):
    """Attach middleware classes to a route handler."""
    def decorator(fn):
        fn._middleware = list(middleware_classes)
        # If route was already registered (decorator applied after @get/@post),
        # update the route dict directly.
        if hasattr(fn, "_route_ref"):
            existing = fn._route_ref._route.get("middleware", [])
            fn._route_ref._route["middleware"] = list(middleware_classes) + existing
        return fn
    return decorator


# ── Caching Decorator ──────────────────────────────────────────

def cached(max_age: int = 60):
    """Cache the response of this route."""
    def decorator(fn):
        fn._cached = True
        fn._cache_max_age = max_age
        return fn
    return decorator


# ── Template Decorator ────────────────────────────────────────

def template(template_name: str):
    """Auto-render a dict return value through a Frond/Twig template.

    Usage:
        @template("pages/dashboard.twig")
        @get("/dashboard")
        async def dashboard(request, response):
            return {"title": "Dashboard", "items": get_items()}

    If the handler returns a dict, it is rendered through the named
    template via ``response.render(template_name, data)`` and the
    resulting HTML response is returned.  Any other return type
    (e.g. an already-built Response) is passed through unchanged.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(request, response, *args, **kwargs):
            result = await fn(request, response, *args, **kwargs)
            if isinstance(result, dict):
                return response.render(template_name, result)
            return result
        return wrapper
    return decorator
