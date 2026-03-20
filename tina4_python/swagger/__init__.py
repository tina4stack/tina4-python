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

def description(text: str):
    """Add a description to a route handler."""
    def decorator(fn):
        fn._swagger_description = text
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_description = text
        # Copy other swagger attrs
        for attr in ("_swagger_tags", "_swagger_example", "_swagger_example_response",
                      "_swagger_params", "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr):
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


def tags(tag_list: list[str]):
    """Add tags to a route handler."""
    def decorator(fn):
        fn._swagger_tags = tag_list
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_tags = tag_list
        for attr in ("_swagger_description", "_swagger_example", "_swagger_example_response",
                      "_swagger_params", "_swagger_summary", "_swagger_deprecated"):
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


def example_response(data: dict | list):
    """Add a response body example."""
    def decorator(fn):
        fn._swagger_example_response = data
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_example_response = data
        for attr in ("_swagger_description", "_swagger_tags", "_swagger_example",
                      "_swagger_params", "_swagger_summary", "_swagger_deprecated"):
            if hasattr(fn, attr):
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

class Swagger:
    """OpenAPI 3.0.3 specification generator."""

    def __init__(self, title: str = None, version: str = None,
                 description: str = "", server_url: str = None):
        self.title = title or os.environ.get("SWAGGER_TITLE", "Tina4 API")
        self.version = version or os.environ.get("SWAGGER_VERSION", "1.0.0")
        self.description = description or os.environ.get("SWAGGER_DESCRIPTION", "")
        self.server_url = server_url or os.environ.get(
            "SWAGGER_DEV_URL", "http://localhost:7145"
        )

    def generate(self, routes: list[dict]) -> dict:
        """Generate OpenAPI 3.0.3 spec from a list of route definitions.

        Each route dict should have:
            method, path, handler, auth_required (optional)
        """
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": self.title,
                "version": self.version,
                "description": self.description,
            },
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
    "Swagger",
    "description", "summary", "tags",
    "example", "example_response", "deprecated",
]
