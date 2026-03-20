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
from tina4_python.debug import Log


# Global route registry
_routes: list[dict] = []


class Router:
    """Route registry and matcher."""

    @staticmethod
    def add(method: str, path: str, handler, **options):
        """Register a route handler.

        Auth defaults:
        - GET routes are public by default
        - POST/PUT/PATCH/DELETE require auth by default
        - Use @noauth() to make a write route public
        - Use @secured() to protect a GET route
        """
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

        _routes.append({
            "method": m,
            "path": path,
            "pattern": pattern,
            "param_names": param_names,
            "handler": handler,
            "middleware": options.get("middleware", []),
            "auth_required": auth_required,
            "cached": options.get("cached", False),
            "cache_max_age": options.get("cache_max_age", 60),
        })
        Log.debug(f"Route registered: {m} {path} (auth={'required' if auth_required else 'public'})")

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
