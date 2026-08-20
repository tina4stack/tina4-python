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

    def no_auth(self):
        """Mark this route as public — no authentication required."""
        self._route["auth_required"] = False
        return self

    def role(self, *names):
        """Require the caller to hold ONE of the named roles (OR). Reads the
        verified JWT ``roles`` claim. Implies auth (a guarded GET still needs a
        token). Stack ``.role()``/``.can()`` for AND. Feature 138 / ADR-0058."""
        if names:
            self._route.setdefault("required_roles", []).append(tuple(names))
            self._route["auth_required"] = True
        return self

    def can(self, *permissions):
        """Require the caller to hold ONE of the named permissions (OR). Reads
        the verified JWT ``permissions`` claim; granted-side wildcards (``posts.*``,
        ``*``) satisfy a concrete requirement. Implies auth. Feature 138."""
        if permissions:
            self._route.setdefault("required_perms", []).append(tuple(permissions))
            self._route["auth_required"] = True
        return self

    def cache(self):
        """Mark this route as cacheable."""
        self._route["cached"] = True
        return self

    def middleware(self, *middleware_classes):
        """Append middleware class(es) to this route.

        Usage::

            Router.post("/api/data", handler).middleware(AuthMiddleware)
            Router.get("/api/slow", handler).middleware(CacheMiddleware, LogMiddleware)
        """
        existing = self._route.get("middleware", [])
        self._route["middleware"] = list(existing) + list(middleware_classes)
        # Custom middleware means developer handles auth — disable built-in gate
        # unless .secure() was explicitly called.
        if not self._route.get("auth_required"):
            self._route["auth_required"] = False
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

    def _register(self, method: str, path: str, handler, **options) -> RouteRef:
        """Register one route with THIS group's prefix and middleware bound.

        Two bugs lived in the old shape, and both came from the group state
        being read off the CLASS while a RouteGroup carried its own copy:

        1. The verbs passed ``middleware=self._middleware`` AND ``Router.add``
           prepended ``cls._group_middleware``, so every group middleware was
           merged twice and RAN TWICE per request. A counter or a rate-limit
           bucket silently double-counted.
        2. ``RouteGroup.group`` built a correct nested prefix but nothing ever
           read it - registration used ``cls._group_prefix``, which the nested
           call never updated. A route declared at ``/api/admin/stats``
           silently registered at ``/api/stats``, which can land it inside a
           differently-protected prefix or collide with an existing route.

        Binding the class state to this group's own values for the duration of
        the call fixes both, and keeps ONE code path for prefix + middiddleware
        composition instead of two that must agree.
        """
        router = self._router
        previous_prefix = router._group_prefix
        previous_middleware = router._group_middleware
        router._group_prefix = self._prefix
        router._group_middleware = list(self._middleware)
        try:
            return router.add(method, path, handler, **options)
        finally:
            router._group_prefix = previous_prefix
            router._group_middleware = previous_middleware

    def get(self, path: str, handler, **options) -> RouteRef:
        return self._register("GET", path, handler, **options)

    def post(self, path: str, handler, **options) -> RouteRef:
        return self._register("POST", path, handler, **options)

    def put(self, path: str, handler, **options) -> RouteRef:
        return self._register("PUT", path, handler, **options)

    def patch(self, path: str, handler, **options) -> RouteRef:
        return self._register("PATCH", path, handler, **options)

    def delete(self, path: str, handler, **options) -> RouteRef:
        return self._register("DELETE", path, handler, **options)

    def any(self, path: str, handler, **options) -> RouteRef:
        return self._register("ANY", path, handler, **options)

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

        The callback **always** receives one positional argument: a RouteGroup
        object with get/post/put/patch/delete/any/group methods for registering
        routes under the shared prefix.  The callback must accept that argument::

            Router.group("/api", lambda group: [
                group.get("/users", list_handler),
                group.post("/users", create_handler),
                group.group("/admin", lambda admin: [
                    admin.get("/stats", stats_handler),
                ], middleware=[admin_check]),
            ], middleware=[auth_check])

        Using ``lambda:`` (no argument) will raise ``TypeError`` because the
        RouteGroup is always passed.  Always use ``lambda group:`` or a named
        function that accepts the group parameter.
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
        pattern, param_names, param_types = _compile_pattern(path)
        route = {
            "path": path,
            "pattern": pattern,
            "param_names": param_names,
            "param_types": param_types,
            "handler": handler,
            # A WS route is public by default (like GET). @secured() requires a
            # valid JWT on the upgrade. Read the flag here AND keep a back-ref so
            # @secured() applied AFTER @websocket() (the other decorator order)
            # can still flip it — mirrors the HTTP _route_ref pattern.
            "auth_required": bool(getattr(handler, "_secured", False)),
        }
        _ws_routes.append(route)
        try:
            handler._ws_route_ref = route
        except (AttributeError, TypeError):
            pass
        Log.debug(f"WebSocket route registered: {path} (auth={'required' if route['auth_required'] else 'public'})")

    @staticmethod
    def match_ws(path: str) -> tuple[dict | None, dict]:
        """Find a WebSocket route matching the given path. Returns (route, params)."""
        for route in _ws_routes:
            m = route["pattern"].match(path)
            if m:
                params = {}
                _types = route.get("param_types", {})
                for i, name in enumerate(route["param_names"]):
                    params[name] = _cast_param(m.group(i + 1), _types.get(name))
                return route, params
        return None, {}

    @staticmethod
    def all_ws() -> list[dict]:
        """Return all registered WebSocket routes."""
        return _ws_routes

    @staticmethod
    def get_web_socket_routes() -> list[dict]:
        """Return all registered WebSocket routes (parity alias for all_ws)."""
        return _ws_routes

    @classmethod
    def use(cls, middleware_class) -> None:
        """Register a global middleware class applied to every route.

        Equivalent to decorating every handler with @middleware(middleware_class).
        Delegates to the single ``Middleware`` global registry that the request
        dispatcher actually consults — mirrors PHP ``Router::use`` ->
        ``Middleware::use``, Ruby ``Router.use`` -> ``Middleware.use`` and the
        Node equivalent. (Before #55 this wrote to a private ``Router._global_middleware``
        list that nothing read, so globals registered via ``Router.use`` never ran.)

        Args:
            middleware_class: A class with before_*/after_* static methods.
        """
        from tina4_python.core.middleware import Middleware  # avoid circular import
        Middleware.use(middleware_class)

    @classmethod
    def get(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a GET route (imperative, non-decorator style)."""
        return cls.add("GET", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def post(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a POST route (imperative, non-decorator style)."""
        return cls.add("POST", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def put(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a PUT route (imperative, non-decorator style)."""
        return cls.add("PUT", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def patch(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a PATCH route (imperative, non-decorator style)."""
        return cls.add("PATCH", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def delete(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a DELETE route (imperative, non-decorator style)."""
        return cls.add("DELETE", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def head(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register an explicit HEAD route.

        By default the framework auto-handles HEAD by falling back to the GET
        route and stripping the body (RFC 9110 §9.3.2). Use this method only
        when you need a HEAD handler that does something different from GET —
        e.g. cheaper existence-check logic, custom validator headers without
        the cost of building the body.

        The framework still strips the response body for you on the way out —
        HEAD MUST NOT return content, even if your handler does, so we
        enforce that unconditionally rather than relying on developer care.
        """
        return cls.add("HEAD", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def options(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register an explicit OPTIONS route.

        By default the framework auto-handles OPTIONS by building an Allow
        header from every method registered for the path and returning 204
        (RFC 9110 §9.3.7). Use this method to take over that behaviour —
        e.g. to return a richer OPTIONS payload describing the resource.
        """
        return cls.add("OPTIONS", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def any(cls, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
        """Register a route for any HTTP method (imperative, non-decorator style)."""
        return cls.add("ANY", path, handler, middleware=middleware, swagger_meta=swagger_meta, template=template, **options)

    @classmethod
    def add(cls, method: str, path: str, handler, middleware: list = None, swagger_meta: dict = None, template: str = None, **options) -> "RouteRef":
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
        # Apply group prefix — normalized per RG-DEC-01 (PHP's grammar).
        if cls._group_prefix:
            path = _join_group_path(cls._group_prefix, path)

        # Merge group middleware with route-level middleware and handler-level middleware
        handler_mw = getattr(handler, "_middleware", [])
        route_mw = list(middleware or []) + list(options.get("middleware", []))
        combined_mw = list(cls._group_middleware) + list(handler_mw) + route_mw
        effective_middleware = combined_mw or []

        pattern, param_names, param_types = _compile_pattern(path)

        # Auth default: GET=public, writes=secured.
        #
        # Middleware is PURELY ADDITIVE and must NOT silently disable the
        # built-in Bearer-token gate. This used to carry an
        # ``elif effective_middleware: auth_required = False`` branch on the
        # reasoning that a route with custom middleware "handles auth itself".
        # Group middleware is merged into effective_middleware, so attaching an
        # ordinary logging or audit middleware to a GROUP silently made every
        # POST/PUT/PATCH/DELETE inside it PUBLIC - measured: an unauthenticated
        # POST to a grouped route returned 200 where the identical ungrouped
        # route returned 401. The developer's action (add request logging) had
        # no visible relationship to its effect (the gate disappeared).
        #
        # tina4-php, tina4-ruby and tina4-nodejs all key auth off the method and
        # the explicit flags, independent of middleware; Node's router.ts even
        # annotates it as "parity with PY-10-02". Python was the drift. Use
        # @noauth() to open a write route - that is the explicit spelling and it
        # already exists. ADR-0019.
        m = method.upper()
        if "auth_required" in options:
            auth_required = options["auth_required"]
        elif hasattr(handler, "_noauth"):
            auth_required = False
        elif hasattr(handler, "_secured"):
            auth_required = True
        elif hasattr(handler, "_required_roles") or hasattr(handler, "_required_perms"):
            # A role/permission guard (Feature 138) implies auth — a guarded GET
            # still requires a token. This branch only fires in the unusual
            # innermost-order case (guard BELOW @get); the documented order puts
            # the guard ABOVE, where it flips auth_required via the RouteRef.
            auth_required = True
        else:
            # GET, HEAD, OPTIONS, and ANY are public by default. HEAD and
            # OPTIONS are safe/idempotent introspection methods (RFC 9110
            # §9.2.1) — requiring auth on them breaks cache validators
            # and CORS preflight probes.
            auth_required = m not in ("GET", "HEAD", "OPTIONS", "ANY")

        route = {
            "method": m,
            "path": path,
            "pattern": pattern,
            "param_names": param_names,
            "param_types": param_types,
            "handler": handler,
            # Which module registered this route. Lets dev hot-reload purge a
            # changed module's OLD routes before re-importing it — otherwise a
            # renamed or deleted endpoint keeps serving its stale handler,
            # because replace-semantics only match an identical (method, path).
            "module": getattr(handler, "__module__", ""),
            "middleware": effective_middleware,
            "auth_required": auth_required,
            # RBAC guards (Feature 138): lists of OR-groups; AND across groups.
            # Populated here for the innermost-order case, and appended to by the
            # RouteRef.role()/.can() modifiers for the documented guard-above order.
            "required_roles": list(getattr(handler, "_required_roles", []) or []),
            "required_perms": list(getattr(handler, "_required_perms", []) or []),
            "cached": options.get("cached", False),
            "cache_max_age": options.get("cache_max_age", 60),
            "swagger_meta": swagger_meta or options.get("swagger_meta", {}),
            "template": template or options.get("template"),
        }
        # Replace semantics: re-registering the same (method, path) overwrites
        # the existing entry in place rather than appending a second one.
        # This is what makes dev hot-reload work — when a changed module is
        # re-imported, its @get("/x") decorator runs again with a fresh handler,
        # and ``match()`` returns the FIRST match, so a stale leftover would
        # otherwise shadow the new handler forever. Overwriting keeps the
        # registry free of duplicates and ensures the latest handler wins.
        # Distinct (method, path) pairs are untouched — only an exact dup
        # collapses onto the prior slot, preserving its position/order.
        for i, existing in enumerate(_routes):
            if existing["method"] == m and existing["path"] == path:
                _routes[i] = route
                Log.debug(f"Route replaced: {m} {path} (auth={'required' if auth_required else 'public'})")
                return RouteRef(route)
        _routes.append(route)
        Log.debug(f"Route registered: {m} {path} (auth={'required' if auth_required else 'public'})")
        return RouteRef(route)

    @staticmethod
    def match(method: str, path: str) -> tuple[dict | None, dict]:
        """Find a route matching method + path. Returns (route, params).

        RFC 9110 §9.3.2: HEAD is identical to GET except the response carries
        no body. If the app didn't register a dedicated HEAD route, we
        transparently match the GET route; the dispatcher strips the body on
        the way out, so the handler doesn't need to know HEAD even happened.
        """
        method_upper = method.upper()

        # First pass: exact method match (covers HEAD → explicit HEAD route too)
        for route in _routes:
            if route["method"] not in (method_upper, "ANY"):
                continue
            m = route["pattern"].match(path)
            if m:
                params = {}
                _types = route.get("param_types", {})
                for i, name in enumerate(route["param_names"]):
                    params[name] = _cast_param(m.group(i + 1), _types.get(name))
                return route, params

        # Second pass: HEAD auto-fallback to GET when no HEAD route registered
        if method_upper == "HEAD":
            for route in _routes:
                if route["method"] not in ("GET", "ANY"):
                    continue
                m = route["pattern"].match(path)
                if m:
                    params = {}
                    _types = route.get("param_types", {})
                    for i, name in enumerate(route["param_names"]):
                        params[name] = _cast_param(m.group(i + 1), _types.get(name))
                    return route, params

        return None, {}

    @staticmethod
    def methods_allowed_for_path(path: str) -> list[str]:
        """Return the list of HTTP methods registered for ``path``, in the
        order GET / POST / PUT / PATCH / DELETE / HEAD / OPTIONS. Used by
        the dispatcher to build the ``Allow:`` header on 405 / OPTIONS
        responses (RFC 9110 §10.2.1, §9.3.7).

        If GET is registered, HEAD is appended implicitly (the framework
        auto-falls-back HEAD to GET). OPTIONS is appended whenever the
        path has any registered method (the framework auto-handles OPTIONS).
        """
        # ANY routes count for every method but we don't enumerate them
        # individually — flag whether ANY matched and union it with the
        # concrete-method matches.
        method_order = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
        seen: set[str] = set()
        any_matched = False

        for route in _routes:
            if not route["pattern"].match(path):
                continue
            m = route["method"]
            if m == "ANY":
                any_matched = True
            elif m in method_order:
                seen.add(m)

        if any_matched:
            seen.update(method_order)

        # GET implies HEAD; any registered method implies OPTIONS.
        if seen:
            if "GET" in seen:
                seen.add("HEAD")
            seen.add("OPTIONS")

        return [m for m in method_order if m in seen]

    @staticmethod
    def get_routes() -> list[dict]:
        """Return all registered routes."""
        return _routes

    @staticmethod
    def list_routes() -> list[dict]:
        """Return all registered routes (debug-friendly)."""
        return _routes

    @staticmethod
    def remove_routes_for_module(module_name: str) -> int:
        """Drop every route registered by ``module_name``. Returns the count.

        Used by dev hot-reload BEFORE re-importing a changed module: its
        decorators then re-register whatever the file currently declares. Without
        this, replace-semantics only overwrite an identical (method, path), so a
        renamed or deleted endpoint would keep serving its stale handler until a
        full restart — you "remove" a route and it still answers.
        """
        if not module_name:
            return 0
        removed = 0
        for registry in (_routes, _ws_routes):
            keep = [r for r in registry if r.get("module") != module_name]
            removed += len(registry) - len(keep)
            registry[:] = keep
        return removed

    @staticmethod
    def clear():
        """Clear all routes (for testing)."""
        _routes.clear()
        _ws_routes.clear()


# Supported typed-parameter constraints. Keys are the type name written in
# the route pattern (e.g. ``{id:int}``); values are the regex that the param
# must match. Mirrored verbatim in PHP/Ruby/Node.js for cross-framework parity.
#
# Any type name that isn't in this table raises at route registration time —
# we never silently fall through to the default matcher, because a typo like
# ``{id:inetger}`` would otherwise match anything and create a security
# footgun (see tina4-book#125).
_TYPE_PATTERNS = {
    "string":   "[^/]+",                                         # default, any non-slash segment
    "int":      r"\d+",
    "integer":  r"\d+",
    "float":    r"[\d.]+",
    "number":   r"[\d.]+",
    "alpha":    "[A-Za-z]+",                                     # letters only
    "alnum":    "[A-Za-z0-9]+",                                  # letters + digits
    "slug":     "[a-z0-9-]+",                                    # URL slug
    "uuid":     "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "path":     ".+",                                            # greedy — matches remaining path
    ".*":       ".+",
}

# Type names whose captured value is coerced from str to a Python scalar before
# it reaches the handler. Mirrors Ruby's ``cast_param`` (lib/tina4/router.rb):
# ``int``/``integer`` → ``int``, ``float``/``number`` → ``float``. Every other
# type (string, alpha, alnum, slug, uuid, path) and untyped params stay ``str``.
_TYPE_CASTS = {
    "int":     int,
    "integer": int,
    "float":   float,
    "number":  float,
}


_SLASH_RUN = re.compile(r"/+")


def _join_group_path(prefix: str, path: str) -> str:
    """Join a route-group prefix with a route's own path.

    Feature 32 (RG-DEC-01): ports PHP's normalization grammar verbatim
    (``Tina4/Router.php`` ``addRoute`` — the reference) so Python converges
    with PHP/Ruby/Node instead of bare-concatenating. One separator between
    prefix and path, a single leading slash, no trailing slash, and any run
    of slashes collapsed to one — so ``group("/api")`` + ``get("users")``,
    ``get("/users")``, and ``group("/api/")`` + ``get("/users")`` all resolve
    to the SAME ``/api/users``. Before this fix, ``path = cls._group_prefix +
    path`` bare-concatenated, so ``group("/api")`` + ``get("users")`` silently
    mis-registered at ``/apiusers``.
    """
    full = prefix + "/" + path.lstrip("/")
    full = "/" + full.strip("/")
    return _SLASH_RUN.sub("/", full)


def _cast_param(value: str, type_hint: str | None):
    """Coerce a captured route param to its declared Python type.

    The URL regex already guarantees the segment matches the type's pattern
    (e.g. ``{id:int}`` only matches digits), so the cast normally can't fail.
    We still guard it: a coercion failure must never crash routing — fall back
    to the raw string, exactly as Ruby leaves unknown types untouched.
    """
    caster = _TYPE_CASTS.get(type_hint)
    if caster is None:
        return value
    try:
        return caster(value)
    except (TypeError, ValueError):
        return value


def _compile_pattern(path: str) -> tuple[re.Pattern, list[str], dict[str, str]]:
    """Convert a route path to a regex pattern.

    Supports:
        /api/users                → exact match
        /api/users/{id}           → named parameter (any non-slash chars)
        /api/users/{id:int}       → digits only
        /api/users/{name:alpha}   → letters only
        /api/users/{slug:slug}    → URL slug (a-z 0-9 -)
        /api/users/{id:uuid}      → UUID v4 format
        /api/files/{p:path}       → greedy (matches remaining path)
        /api/docs/*               → bare-wildcard catch-all (key "*")

    Returns ``(pattern, param_names, param_types)`` where ``param_types`` maps
    each declared name to its type hint (``"int"``, ``"float"``, …). Untyped
    params and the ``*`` wildcard are absent from the map. The map drives
    coercion in :meth:`Router.match` so typed params arrive at the handler as
    Python scalars (mirrors Ruby's ``cast_param``).

    Unknown type names raise ``ValueError`` at route registration time.
    """
    param_names = []
    param_types: dict[str, str] = {}
    regex_parts = []

    segments = path.strip("/").split("/")
    for segment in segments:
        if segment == "*":
            # Wildcard: matches the rest of the path (greedy)
            param_names.append("*")
            regex_parts.append("(.+)")
            break  # Nothing can follow a wildcard
        elif segment.startswith("{") and segment.endswith("}"):
            inner = segment[1:-1]
            if ":" in inner:
                name, type_hint = inner.split(":", 1)
                if type_hint not in _TYPE_PATTERNS:
                    raise ValueError(
                        f"Unknown param type {type_hint!r} in route {path!r}. "
                        f"Valid types: {', '.join(sorted(k for k in _TYPE_PATTERNS if k != '.*'))}."
                    )
                regex_parts.append("(" + _TYPE_PATTERNS[type_hint] + ")")
                param_types[name] = type_hint
            else:
                name = inner
                regex_parts.append("([^/]+)")
            param_names.append(name)
        else:
            regex_parts.append(re.escape(segment))

    pattern_str = "^/" + "/".join(regex_parts) + "/?$"
    return re.compile(pattern_str), param_names, param_types


# Decorator functions — the public API

def _resolve_string_middleware(name: str):
    """Resolve a string-form middleware spec to a class.

    Forms:
        "ResponseCache"        → tina4_python.cache.ResponseCache
        "ResponseCache:300"    → ResponseCache configured with max_age=300
        "RateLimit:10:60"      → RateLimit configured with limit=10, window=60

    Looks up the class in the registry of known middleware names. Unknown
    names raise ``ValueError`` so typos surface at decoration time instead
    of silently swallowing the middleware.
    """
    head, _, tail = name.partition(":")
    args = [int(a) if a.isdigit() else a for a in tail.split(":")] if tail else []

    # Lazy import to avoid circular deps
    from tina4_python.cache import ResponseCache
    from tina4_python.core.middleware import RateLimiter, CorsMiddleware

    registry = {
        "ResponseCache": ResponseCache,
        "RateLimit":     RateLimiter,
        "RateLimiter":   RateLimiter,
        "Cors":          CorsMiddleware,
        "CORS":          CorsMiddleware,
    }
    cls = registry.get(head)
    if cls is None:
        raise ValueError(
            f"Unknown middleware {head!r}. Known: {sorted(registry)}. "
            f"For custom middleware, pass the class directly to @middleware(MyMW)."
        )
    if args:
        # Parameterised form — try to instantiate with the args. Falls back
        # to returning the class with no args if the constructor disagrees.
        try:
            return cls(*args)
        except TypeError:
            return cls
    return cls


def _normalise_middleware_list(items):
    """Convert a mixed list of classes / strings / instances to classes/instances."""
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(_resolve_string_middleware(item))
        else:
            out.append(item)
    return out


def _register_route(method: str, path: str, fn, **options):
    """Common registration logic that preserves handler attributes on the returned ref.

    Accepts the docs-friendly kwargs:

      * ``description`` — short Swagger summary; same as stacking @description("...")
      * ``middleware``  — list of middleware (classes / instances / string specs)

    String-form middleware (e.g. ``"ResponseCache:300"``) is parsed into the
    matching class so callers don't need an import.
    """
    # description= shortcut — fold into Swagger metadata
    descr = options.pop("description", None)
    if descr:
        fn._swagger_description = descr

    # middleware= shortcut — accept inline list of mixed types
    inline_mw = options.pop("middleware", None)
    if inline_mw:
        normalised = _normalise_middleware_list(inline_mw)
        fn._middleware = list(getattr(fn, "_middleware", [])) + normalised

    ref = Router.add(method, path, fn, **options)
    # Propagate handler attributes to the wrapper so stacked decorators still work
    fn._route_ref = ref

    # If we folded in middleware via the kwarg, also push it into the route
    # dict so the dispatcher picks it up (mirrors what @middleware does).
    if inline_mw and hasattr(fn, "_route_ref"):
        existing = ref._route.get("middleware", [])
        ref._route["middleware"] = fn._middleware + existing
        # Custom middleware means developer handles auth — disable built-in
        # gate unless @secured() was explicitly set.
        if not getattr(fn, "_secured", False) and ref._route.get("auth_required"):
            ref._route["auth_required"] = False

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
        # update the route dict directly AND log the corrected state. The
        # documented decorator order puts @noauth() ABOVE @get/@post, which
        # means Python's bottom-up application runs @post first — so
        # `_register_route` fires its "auth=required" line for a route that
        # will be public a microsecond later. Without the corrective line
        # below, the earlier log reads as definitive and misleads anyone
        # reading startup output (issue #103: an AI reviewer drafted a false
        # critical-security finding after reading the misleading line).
        if hasattr(fn, "_route_ref"):
            route = fn._route_ref._route
            was_required = route.get("auth_required", False)
            route["auth_required"] = False
            if was_required:
                Log.debug(
                    f"Route auth updated: {route['method']} {route['path']} "
                    f"(auth=public via @noauth)"
                )
        return fn
    return decorator


def secured():
    """Require auth on a GET route (which is public by default)."""
    def decorator(fn):
        fn._secured = True
        # See @noauth() above: emit a corrective log line if we flip the flag
        # on an already-registered route so a reader of the startup log sees
        # the true final auth state after every decorator has applied
        # (issue #103).
        if hasattr(fn, "_route_ref"):
            route = fn._route_ref._route
            was_public = not route.get("auth_required", True)
            route["auth_required"] = True
            if was_public:
                Log.debug(
                    f"Route auth updated: {route['method']} {route['path']} "
                    f"(auth=required via @secured)"
                )
        # Same for a WebSocket route registered by @websocket() below this one.
        if hasattr(fn, "_ws_route_ref"):
            fn._ws_route_ref["auth_required"] = True
        return fn
    return decorator


# ── RBAC guards (Feature 138 / ADR-0058) ──────────────────────
# Claim-first authorization on top of the JWT auth gate. @role reads the verified
# `roles` claim, @can reads `permissions`. Multiple args are OR; stack guards for
# AND. A guard implies @secured. Roles and permissions are independent claims;
# the core never expands a role into permissions.

def role(*names):
    """Require the caller to hold ONE of the named roles (OR). Stack
    ``@role``/``@can`` for AND. Reads the verified JWT ``roles`` claim (a legacy
    singular ``role`` string is coerced). Implies ``@secured``."""
    group = tuple(names)

    def decorator(fn):
        fn._required_roles = getattr(fn, "_required_roles", []) + [group]
        if hasattr(fn, "_route_ref"):
            route = fn._route_ref._route
            route.setdefault("required_roles", []).append(group)
            was_public = not route.get("auth_required", True)
            route["auth_required"] = True
            if was_public:
                Log.debug(
                    f"Route auth updated: {route['method']} {route['path']} "
                    f"(auth=required via @role)"
                )
        return fn
    return decorator


def can(*permissions):
    """Require the caller to hold ONE of the named permissions (OR). Stack
    ``@role``/``@can`` for AND. Reads the verified JWT ``permissions`` claim;
    granted-side wildcards (``posts.*``, ``*``) satisfy a concrete requirement.
    Implies ``@secured``."""
    group = tuple(permissions)

    def decorator(fn):
        fn._required_perms = getattr(fn, "_required_perms", []) + [group]
        if hasattr(fn, "_route_ref"):
            route = fn._route_ref._route
            route.setdefault("required_perms", []).append(group)
            was_public = not route.get("auth_required", True)
            route["auth_required"] = True
            if was_public:
                Log.debug(
                    f"Route auth updated: {route['method']} {route['path']} "
                    f"(auth=required via @can)"
                )
        return fn
    return decorator


def _rbac_claim_list(subject, key, legacy=None):
    """Read a claim as a list of strings from the VERIFIED payload. Coerces a
    legacy singular string (``role`` -> ``["role"]``). Returns ``[]`` for a
    missing/None subject or claim."""
    if not isinstance(subject, dict):
        return []
    val = subject.get(key)
    out = []
    if isinstance(val, str) and val:
        out = [val]
    elif isinstance(val, (list, tuple)):
        out = [str(x) for x in val if x is not None and str(x) != ""]
    if not out and legacy:
        lv = subject.get(legacy)
        if isinstance(lv, str) and lv:
            out = [lv]
        elif isinstance(lv, (list, tuple)):
            out = [str(x) for x in lv if x is not None and str(x) != ""]
    return out


def _rbac_perm_granted(granted, required):
    """True if any GRANTED permission satisfies the concrete REQUIRED permission.
    Wildcards live only on the granted side: ``*`` grants everything; ``posts.*``
    grants ``posts.<anything...>`` on the dot boundary (never ``users.delete``)."""
    for g in granted:
        if g == "*" or g == required:
            return True
        if g.endswith(".*") and required.startswith(g[:-1]):
            return True
    return False


def rbac_authorized(subject, required_roles, required_perms):
    """Return True if the verified ``subject`` satisfies every guard group.

    AND across groups, OR within a group. ``required_roles`` / ``required_perms``
    are lists of OR-groups (each ``@role``/``@can`` adds one group). Roles read
    the ``roles`` claim (legacy singular ``role`` coerced); permissions read
    ``permissions`` with granted-side wildcards. A missing subject satisfies no
    group. Feature 138 / ADR-0058."""
    # NOTE: explicit loops, NOT any(...): this module shadows the builtin `any`
    # (a route helper), so `any(...)` here would resolve to the wrong callable.
    roles = _rbac_claim_list(subject, "roles", legacy="role")
    for group in (required_roles or []):
        matched = False
        for r in group:
            if r in roles:
                matched = True
                break
        if not matched:
            return False
    perms = _rbac_claim_list(subject, "permissions")
    for group in (required_perms or []):
        matched = False
        for req in group:
            if _rbac_perm_granted(perms, req):
                matched = True
                break
        if not matched:
            return False
    return True


# ── Middleware Decorator ───────────────────────────────────────

def middleware(*middleware_classes):
    """Attach middleware classes or functions to a route handler.

    Middleware is purely additive — it does NOT change the route's auth
    requirement. POST/PUT/PATCH/DELETE routes stay Bearer-token-gated by
    default. Use ``@noauth()`` to open a write route, ``@secured()`` to
    lock a read route. This rule is the same across all four Tina4
    frameworks (tina4-book#141, PY-10-02).
    """
    def decorator(fn):
        fn._middleware = list(middleware_classes)
        # If route was already registered (decorator applied after @get/@post),
        # update the route dict directly.
        if hasattr(fn, "_route_ref"):
            existing = fn._route_ref._route.get("middleware", [])
            fn._route_ref._route["middleware"] = list(middleware_classes) + existing
            # Intentionally does NOT touch route["auth_required"]. Prior
            # behaviour silently flipped it to False, creating an undocumented
            # auth bypass for any write route that added custom middleware.
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

    IMPORTANT: ``@template`` must sit BELOW the route decorator so the
    wrapper is registered (route decorators capture the current function
    reference when applied — a @template above @get never reaches the
    router). Correct order:

        @get("/dashboard")
        @template("pages/dashboard.twig")
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
