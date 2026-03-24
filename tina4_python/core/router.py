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


class Router:
    """Route registry and matcher."""

    # ── Group state (used by Router.group) ────────────────────────
    _group_prefix: str = ""
    _group_middleware: list = []

    @classmethod
    def group(cls, prefix: str, callback, middleware=None):
        """Register routes with a shared prefix and optional middleware.

        Saves/restores static prefix and middleware state around the
        callback so that nested groups concatenate correctly.

        Usage::

            Router.group("/api", lambda: [
                Router.get("/users", handler),
                Router.post("/users", handler),
            ], middleware=[auth_check])
        """
        prev_prefix = cls._group_prefix
        prev_middleware = list(cls._group_middleware)

        cls._group_prefix = prev_prefix + prefix.rstrip("/")
        cls._group_middleware = prev_middleware + (middleware or [])

        try:
            callback()
        finally:
            cls._group_prefix = prev_prefix
            cls._group_middleware = prev_middleware

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

        # Merge group middleware with route-level middleware
        if cls._group_middleware:
            route_mw = options.get("middleware", [])
            options["middleware"] = list(cls._group_middleware) + list(route_mw)

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
    def all() -> list[dict]:
        """Return all registered routes (for CLI listing and Swagger)."""
        return _routes

    @staticmethod
    def clear():
        """Clear all routes (for testing)."""
        _routes.clear()


def _compile_pattern(path: str) -> tuple[re.Pattern, list[str]]:
    """Convert a route path to a regex pattern.

    Supports:
        /api/users          → exact match
        /api/users/{id}     → named parameter (any non-slash chars)
        /api/files/{path:path}  → greedy (matches remaining path)
    """
    param_names = []
    regex_parts = []

    for segment in path.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
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

def get(path: str, **options):
    """Register a GET route."""
    def decorator(fn):
        Router.add("GET", path, fn, **options)
        return fn
    return decorator


def post(path: str, **options):
    """Register a POST route."""
    def decorator(fn):
        Router.add("POST", path, fn, **options)
        return fn
    return decorator


def put(path: str, **options):
    """Register a PUT route."""
    def decorator(fn):
        Router.add("PUT", path, fn, **options)
        return fn
    return decorator


def patch(path: str, **options):
    """Register a PATCH route."""
    def decorator(fn):
        Router.add("PATCH", path, fn, **options)
        return fn
    return decorator


def delete(path: str, **options):
    """Register a DELETE route."""
    def decorator(fn):
        Router.add("DELETE", path, fn, **options)
        return fn
    return decorator


def any_method(path: str, **options):
    """Register a route for any HTTP method."""
    def decorator(fn):
        Router.add("ANY", path, fn, **options)
        return fn
    return decorator


# ── Auth Decorators ────────────────────────────────────────────

def noauth():
    """Make a write route (POST/PUT/PATCH/DELETE) public — no auth required."""
    def decorator(fn):
        fn._noauth = True
        return fn
    return decorator


def secured():
    """Require auth on a GET route (which is public by default)."""
    def decorator(fn):
        fn._secured = True
        return fn
    return decorator


# ── Middleware Decorator ───────────────────────────────────────

def middleware(*middleware_classes):
    """Attach middleware classes to a route handler."""
    def decorator(fn):
        fn._middleware = list(middleware_classes)
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
