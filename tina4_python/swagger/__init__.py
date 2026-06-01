# Tina4 Swagger — OpenAPI 3.0.3 spec generator, zero dependencies.
"""
Auto-generates OpenAPI documentation from registered routes.

    from tina4_python.swagger import Swagger, description, tags, example

    swagger = Swagger(title="My API", version="1.0.0")
    spec = swagger.generate(router)

Decorators:
    @description("Create a user")
    @tags(["users"])
    @example({"name": "Alice"})
    @example_response({"id": 1, "name": "Alice"})
"""
import json
import os
import functools


# ── Decorators ─────────────────────────────────────────────────
# These attach metadata to route handlers for Swagger generation.

def description(text: str = "", detail: str = "", params: dict | None = None,
                query: dict | None = None):
    """Add a description, optional detail body, and parameter docs to a route.

    Backward-compatible: ``@description("Short summary")`` still works.

    The expanded form lets docs attach richer metadata in one decorator
    instead of stacking three:

        @description(
            "Create a new user",
            detail="Validates email + password strength before insert.",
            params={"id": "URL path — user id"},
            query={"include_inactive": "bool — include soft-deleted"},
        )
    """
    def decorator(fn):
        fn._swagger_description = text
        if detail:
            fn._swagger_detail = detail
        if params:
            fn._swagger_params = params
        if query:
            fn._swagger_query = query

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_description = text
        if detail:
            wrapper._swagger_detail = detail
        if params:
            wrapper._swagger_params = params
        if query:
            wrapper._swagger_query = query
        # Copy other swagger attrs
        for attr in ("_swagger_tags", "_swagger_example", "_swagger_example_response",
                      "_swagger_params", "_swagger_query", "_swagger_detail",
                      "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr) and not hasattr(wrapper, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


def summary(text: str):
    """Add a short summary to a route handler."""
    def decorator(fn):
        fn._swagger_summary = text
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_summary = text
        for attr in ("_swagger_description", "_swagger_tags", "_swagger_example",
                      "_swagger_example_response", "_swagger_params", "_swagger_deprecated"):
            if hasattr(fn, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


def tags(tag_list):
    """Add tags to a route handler.

    Accepts a list of strings ``@tags(["users", "admin"])`` OR a single
    string ``@tags("users")`` for the common one-tag case.
    """
    # Single-string form — docs and many existing call sites use this
    if isinstance(tag_list, str):
        tag_list = [tag_list]

    def decorator(fn):
        fn._swagger_tags = tag_list
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_tags = tag_list
        for attr in ("_swagger_description", "_swagger_example", "_swagger_example_response",
                      "_swagger_params", "_swagger_query", "_swagger_detail",
                      "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


def example(data: dict | list):
    """Add a request body example."""
    def decorator(fn):
        fn._swagger_example = data
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_example = data
        for attr in ("_swagger_description", "_swagger_tags", "_swagger_example_response",
                      "_swagger_params", "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


def example_response(status_or_data, data=None):
    """Add a response body example.

    Two forms, both accepted:

        @example_response({"id": 1, "name": "Alice"})         # status defaults to 200
        @example_response(201, {"id": 1, "name": "Alice"})    # explicit status

    When two args are passed, the first is the HTTP status code. Per-status
    examples are stored in ``_swagger_example_responses`` (dict keyed by
    status) so multiple ``@example_response(...)`` decorators on the same
    handler accumulate.
    """
    # Two-arg form: (status_code, data)
    if data is not None:
        status_code = int(status_or_data)
        body = data
    else:
        status_code = 200
        body = status_or_data

    def decorator(fn):
        # Multi-status accumulator. Keep the legacy single-example attr
        # in sync (last-write-wins) for back-compat with older swagger renderers.
        responses = getattr(fn, "_swagger_example_responses", {}) or {}
        responses[status_code] = body
        fn._swagger_example_responses = responses
        fn._swagger_example_response = body
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_example_responses = responses
        wrapper._swagger_example_response = body
        for attr in ("_swagger_description", "_swagger_tags", "_swagger_example",
                      "_swagger_params", "_swagger_query", "_swagger_detail",
                      "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr) and not hasattr(wrapper, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


def deprecated():
    """Mark a route as deprecated."""
    def decorator(fn):
        fn._swagger_deprecated = True
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_deprecated = True
        for attr in ("_swagger_description", "_swagger_tags", "_swagger_example",
                      "_swagger_example_response", "_swagger_params", "_swagger_summary"):
            if hasattr(fn, attr):
                setattr(wrapper, attr, getattr(fn, attr))
        return wrapper
    return decorator


# ── Swagger Generator ──────────────────────────────────────────

def _swagger_truthy(val) -> bool:
    return str(val or "").strip().lower() in ("true", "1", "yes", "on")


def is_enabled() -> bool:
    """Whether Swagger UI should be served.

    Resolution order:
        1. TINA4_SWAGGER_ENABLED env var — explicit on/off override.
        2. TINA4_DEBUG=true — implicit on for dev.
        3. Otherwise off (production default).

    Cross-framework parity v3.12.4 — same rule across PHP/Ruby/Node.
    """
    explicit = os.environ.get("TINA4_SWAGGER_ENABLED")
    if explicit is not None and explicit != "":
        return _swagger_truthy(explicit)
    return _swagger_truthy(os.environ.get("TINA4_DEBUG"))


class Swagger:
    """OpenAPI 3.0.3 specification generator."""

    def __init__(self, title: str = None, version: str = None,
                 description: str = "", server_url: str = None,
                 contact_email: str = None, license_name: str = None):
        self.title = title or os.environ.get("TINA4_SWAGGER_TITLE", "Tina4 API")
        self.version = version or os.environ.get("TINA4_SWAGGER_VERSION", "1.0.0")
        self.description = description or os.environ.get("TINA4_SWAGGER_DESCRIPTION", "")
        self.server_url = server_url or os.environ.get(
            "SWAGGER_DEV_URL", "http://localhost:7145"
        )
        # Contact email surfaces in the OpenAPI `info.contact` block. Empty
        # string suppresses the entry — same convention across frameworks.
        self.contact_email = (
            contact_email
            if contact_email is not None
            else os.environ.get("TINA4_SWAGGER_CONTACT_EMAIL", "")
        )
        # License name surfaces in `info.license`. Empty string suppresses.
        self.license_name = (
            license_name
            if license_name is not None
            else os.environ.get("TINA4_SWAGGER_LICENSE", "")
        )

    def generate(self, routes: list[dict]) -> dict:
        """Generate OpenAPI 3.0.3 spec from a list of route definitions.

        Each route dict should have:
            method, path, handler, auth_required (optional)
        """
        info = {
            "title": self.title,
            "version": self.version,
            "description": self.description,
        }
        if self.contact_email:
            info["contact"] = {"email": self.contact_email}
        if self.license_name:
            info["license"] = {"name": self.license_name}

        spec = {
            "openapi": "3.0.3",
            "info": info,
            "servers": [{"url": self.server_url}],
            "paths": {},
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    }
                }
            },
        }

        for route in routes:
            path = self._openapi_path(route["path"])
            method = route["method"].lower()
            handler = route.get("handler")

            if path not in spec["paths"]:
                spec["paths"][path] = {}

            operation = {
                "operationId": self._operation_id(method, path),
                "responses": {
                    "200": {"description": "Successful response"},
                },
            }

            # Extract metadata from handler decorators
            if handler:
                if hasattr(handler, "_swagger_description"):
                    operation["description"] = handler._swagger_description
                if hasattr(handler, "_swagger_summary"):
                    operation["summary"] = handler._swagger_summary
                if hasattr(handler, "_swagger_tags"):
                    operation["tags"] = handler._swagger_tags
                if hasattr(handler, "_swagger_deprecated"):
                    operation["deprecated"] = True

                # Request body from example
                if hasattr(handler, "_swagger_example") and method in ("post", "put", "patch"):
                    ex = handler._swagger_example
                    operation["requestBody"] = {
                        "content": {
                            "application/json": {
                                "schema": self._infer_schema(ex),
                                "example": ex,
                            }
                        }
                    }

                # Response example
                if hasattr(handler, "_swagger_example_response"):
                    ex = handler._swagger_example_response
                    operation["responses"]["200"] = {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": self._infer_schema(ex),
                                "example": ex,
                            }
                        },
                    }

            # Path parameters
            params = self._extract_path_params(route["path"])
            if params:
                operation["parameters"] = params

            # Auth
            if route.get("auth_required", False):
                operation["security"] = [{"bearerAuth": []}]

            spec["paths"][path][method] = operation

        return spec

    def generate_json(self, routes: list[dict]) -> str:
        """Generate OpenAPI spec as JSON string."""
        return json.dumps(self.generate(routes), indent=2)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _openapi_path(path: str) -> str:
        """Convert /users/{id:int} to /users/{id}"""
        import re
        return re.sub(r"\{(\w+):\w+\}", r"{\1}", path)

    @staticmethod
    def _operation_id(method: str, path: str) -> str:
        """Generate operationId from method + path."""
        clean = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        return f"{method}_{clean}" if clean else method

    @staticmethod
    def _extract_path_params(path: str) -> list[dict]:
        """Extract path parameters and their types."""
        import re
        params = []
        for m in re.finditer(r"\{(\w+)(?::(\w+))?\}", path):
            name = m.group(1)
            ptype = m.group(2) or "string"
            schema_type = {"int": "integer", "float": "number"}.get(ptype, "string")
            params.append({
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": schema_type},
            })
        return params

    @staticmethod
    def _infer_schema(value) -> dict:
        """Infer OpenAPI schema from a Python value."""
        if isinstance(value, dict):
            props = {}
            for k, v in value.items():
                props[k] = Swagger._infer_schema(v)
            return {"type": "object", "properties": props}
        if isinstance(value, list):
            if value:
                return {"type": "array", "items": Swagger._infer_schema(value[0])}
            return {"type": "array", "items": {}}
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number"}
        return {"type": "string"}


__all__ = [
    "Swagger", "is_enabled",
    "description", "summary", "tags",
    "example", "example_response", "deprecated",
]
