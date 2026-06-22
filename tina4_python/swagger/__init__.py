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

v3.13.40 — the generator now:
    - emits per-status responses (multiple @example_response accumulate),
    - documents in:query parameters from @description(query={...}),
    - turns ORM models into reusable components.schemas + $ref bodies
      (set handler._swagger_model = ModelClass; AutoCrud does this),
    - emits a top-level tags[] array, multi-server list, typed-param
      formats (uuid/slug/...), enums from field choices, and multipart
      request bodies (@example(..., content_type="multipart/form-data")),
    - converts wildcard/splat routes to spec-valid {wildcard} templating,
    - de-duplicates operationIds.
"""
import json
import os
import re
import functools


# ── Decorators ─────────────────────────────────────────────────
# These attach metadata to route handlers for Swagger generation.

# Every swagger attr a decorator may need to carry forward when it wraps a
# handler that another decorator already annotated.
_SWAGGER_ATTRS = (
    "_swagger_description", "_swagger_detail", "_swagger_params", "_swagger_query",
    "_swagger_summary", "_swagger_tags", "_swagger_example", "_swagger_example_content_type",
    "_swagger_example_response", "_swagger_example_responses", "_swagger_deprecated",
    "_swagger_model", "_swagger_model_list",
)


def _carry(fn, wrapper):
    """Copy any already-set swagger attrs from fn onto wrapper (idempotent)."""
    for attr in _SWAGGER_ATTRS:
        if hasattr(fn, attr) and not hasattr(wrapper, attr):
            setattr(wrapper, attr, getattr(fn, attr))


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

    ``detail`` is appended to the operation description; ``query`` becomes
    in:query parameters; ``params`` augments path-parameter descriptions.
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
        _carry(fn, wrapper)
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
        _carry(fn, wrapper)
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
        _carry(fn, wrapper)
        return wrapper
    return decorator


def example(data: dict | list, content_type: str = "application/json"):
    """Add a request body example.

    ``content_type`` defaults to ``application/json``. Pass
    ``content_type="multipart/form-data"`` to document a file-upload body;
    any field whose example value is ``bytes`` becomes a
    ``{type: string, format: binary}`` property.
    """
    def decorator(fn):
        fn._swagger_example = data
        fn._swagger_example_content_type = content_type
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._swagger_example = data
        wrapper._swagger_example_content_type = content_type
        _carry(fn, wrapper)
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
    handler accumulate into separate response entries in the spec.
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
        _carry(fn, wrapper)
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
        _carry(fn, wrapper)
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

    Cross-framework parity v3.12.4 — same rule across PHP/Ruby/Node. As of
    v3.13.40 this is wired into the server dispatch, so it genuinely gates
    whether /swagger is served (it was dead code before).
    """
    explicit = os.environ.get("TINA4_SWAGGER_ENABLED")
    if explicit is not None and explicit != "":
        return _swagger_truthy(explicit)
    return _swagger_truthy(os.environ.get("TINA4_DEBUG"))


# Path-param type token -> JSON Schema fragment. Mirrors the router's known
# type patterns so the documented contract matches what the router accepts.
_PARAM_TYPE_SCHEMA = {
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "number": {"type": "number"},
    "uuid": {"type": "string", "format": "uuid"},
    "slug": {"type": "string", "pattern": r"^[a-z0-9]+(?:-[a-z0-9]+)*$"},
    "alpha": {"type": "string", "pattern": r"^[A-Za-z]+$"},
    "alnum": {"type": "string", "pattern": r"^[A-Za-z0-9]+$"},
    "path": {"type": "string"},
    "string": {"type": "string"},
}


class Swagger:
    """OpenAPI 3.0.3 specification generator."""

    def __init__(self, title: str = None, version: str = None,
                 description: str = "", server_url: str = None,
                 contact_email: str = None, license_name: str = None,
                 contact_team: str = None, contact_url: str = None):
        self.title = title or os.environ.get("TINA4_SWAGGER_TITLE", "Tina4 API")
        self.version = version or os.environ.get("TINA4_SWAGGER_VERSION", "1.0.0")
        self.description = description or os.environ.get("TINA4_SWAGGER_DESCRIPTION", "")
        self.server_url = server_url or os.environ.get(
            "SWAGGER_DEV_URL", "http://localhost:7145"
        )
        # Contact block — name/url/email surface in OpenAPI `info.contact`. Empty
        # values are suppressed. Reads TINA4_SWAGGER_CONTACT_* with the legacy
        # SWAGGER_CONTACT_* as fallback — parity with PHP/Ruby/Node (the root
        # CLAUDE.md documented TEAM/URL that the code did not read before).
        self.contact_email = (
            contact_email
            if contact_email is not None
            else os.environ.get("TINA4_SWAGGER_CONTACT_EMAIL", "")
        )
        self.contact_team = (
            contact_team
            if contact_team is not None
            else (os.environ.get("TINA4_SWAGGER_CONTACT_TEAM")
                  or os.environ.get("SWAGGER_CONTACT_TEAM", ""))
        )
        self.contact_url = (
            contact_url
            if contact_url is not None
            else (os.environ.get("TINA4_SWAGGER_CONTACT_URL")
                  or os.environ.get("SWAGGER_CONTACT_URL", ""))
        )
        # License name surfaces in `info.license`. Empty string suppresses.
        self.license_name = (
            license_name
            if license_name is not None
            else os.environ.get("TINA4_SWAGGER_LICENSE", "")
        )

    def _servers(self) -> list[dict]:
        """Resolve the servers[] block.

        TINA4_SWAGGER_SERVERS (comma-separated URLs) wins and produces a
        multi-server list; otherwise a single entry from server_url.
        """
        raw = os.environ.get("TINA4_SWAGGER_SERVERS", "")
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if urls:
            return [{"url": u} for u in urls]
        return [{"url": self.server_url}]

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
        contact = {}
        if self.contact_team:
            contact["name"] = self.contact_team
        if self.contact_url:
            contact["url"] = self.contact_url
        if self.contact_email:
            contact["email"] = self.contact_email
        if contact:
            info["contact"] = contact
        if self.license_name:
            info["license"] = {"name": self.license_name}

        spec = {
            "openapi": "3.0.3",
            "info": info,
            "servers": self._servers(),
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

        models: dict[str, type] = {}   # name -> ORM model class, for components.schemas
        used_tags: list[str] = []      # insertion-ordered unique tags
        seen_ids: set[str] = set()     # operationId de-dup

        for route in routes:
            path = self._openapi_path(route["path"])
            method = route["method"].lower()
            handler = route.get("handler")

            if path not in spec["paths"]:
                spec["paths"][path] = {}

            operation = {
                "operationId": self._unique_operation_id(method, path, seen_ids),
                "responses": {
                    "200": {"description": "Successful response"},
                },
            }

            model = getattr(handler, "_swagger_model", None) if handler else None
            ref = None
            if model is not None and hasattr(model, "_fields"):
                models[model.__name__] = model
                ref = f"#/components/schemas/{model.__name__}"

            # Extract metadata from handler decorators
            if handler:
                desc = getattr(handler, "_swagger_description", None)
                detail = getattr(handler, "_swagger_detail", None)
                if desc is not None or detail:
                    operation["description"] = "\n\n".join(
                        p for p in (desc, detail) if p
                    )
                if hasattr(handler, "_swagger_summary"):
                    operation["summary"] = handler._swagger_summary
                if hasattr(handler, "_swagger_tags"):
                    operation["tags"] = handler._swagger_tags
                    for t in handler._swagger_tags:
                        if t not in used_tags:
                            used_tags.append(t)
                if hasattr(handler, "_swagger_deprecated"):
                    operation["deprecated"] = True

                # Request body — a $ref to the model schema (preferred), else
                # an inferred schema from @example. application/json unless the
                # example declares multipart/form-data.
                if method in ("post", "put", "patch"):
                    ct = getattr(handler, "_swagger_example_content_type", "application/json")
                    ex = getattr(handler, "_swagger_example", None)
                    media: dict = {}
                    if ref is not None:
                        media["schema"] = {"$ref": ref}
                    elif ex is not None:
                        media["schema"] = self._infer_schema(ex)
                    if ex is not None:
                        media["example"] = ex
                    if media:
                        operation["requestBody"] = {"content": {ct: media}}

                # Responses: model $ref (single or list), then any per-status
                # @example_response entries (explicit wins).
                if ref is not None:
                    is_list = getattr(handler, "_swagger_model_list", False)
                    schema = ({"type": "array", "items": {"$ref": ref}} if is_list
                              else {"$ref": ref})
                    operation["responses"]["200"] = {
                        "description": "Successful response",
                        "content": {"application/json": {"schema": schema}},
                    }
                resp_examples = getattr(handler, "_swagger_example_responses", None)
                if resp_examples:
                    for status_code, body in resp_examples.items():
                        operation["responses"][str(status_code)] = {
                            "description": "Successful response" if str(status_code).startswith("2") else "Response",
                            "content": {
                                "application/json": {
                                    "schema": self._infer_schema(body),
                                    "example": body,
                                }
                            },
                        }
                elif hasattr(handler, "_swagger_example_response") and ref is None:
                    # Legacy single-example back-compat (no per-status dict).
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

            # Parameters: path params (+ types) then query params from @description(query=)
            params = self._extract_path_params(route["path"])
            if handler:
                pdocs = getattr(handler, "_swagger_params", None) or {}
                for p in params:
                    if p["name"] in pdocs:
                        p["description"] = str(pdocs[p["name"]])
                qdocs = getattr(handler, "_swagger_query", None) or {}
                for qname, qdesc in qdocs.items():
                    params.append({
                        "name": qname,
                        "in": "query",
                        "required": False,
                        "description": str(qdesc),
                        "schema": {"type": "string"},
                    })
            if params:
                operation["parameters"] = params

            # Auth
            if route.get("auth_required", False):
                operation["security"] = [{"bearerAuth": []}]

            spec["paths"][path][method] = operation

        # components.schemas from any ORM models referenced by handlers
        if models:
            schemas = spec["components"].setdefault("schemas", {})
            for name, model_class in models.items():
                schemas[name] = self._model_schema(model_class)

        # top-level tags[] (name-only is valid OpenAPI; descriptions optional)
        if used_tags:
            spec["tags"] = [{"name": t} for t in used_tags]

        return spec

    def generate_json(self, routes: list[dict]) -> str:
        """Generate OpenAPI spec as JSON string."""
        return json.dumps(self.generate(routes), indent=2)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _segment_param(seg: str):
        """If a path segment is a parameter, return (name, type_token); else None.

        Handles ``{name}``, ``{name:type}`` and the splat ``*`` (-> name
        'wildcard', type 'path').
        """
        if seg == "*":
            return ("wildcard", "path")
        m = re.fullmatch(r"\{(\w+)(?::(\w+))?\}", seg)
        if m:
            return (m.group(1), m.group(2) or "string")
        return None

    @classmethod
    def _openapi_path(cls, path: str) -> str:
        """Convert a router path to a spec-valid OpenAPI path.

        ``/users/{id:int}`` -> ``/users/{id}``; the splat ``/files/*`` ->
        ``/files/{wildcard}`` (a bare ``*`` is not valid OpenAPI templating).
        """
        out = []
        for seg in path.split("/"):
            p = cls._segment_param(seg)
            out.append("{" + p[0] + "}" if p else seg)
        return "/".join(out)

    @staticmethod
    def _operation_id(method: str, path: str) -> str:
        """Generate operationId from method + path (pre-dedup)."""
        clean = (path.strip("/").replace("/", "_")
                 .replace("{", "").replace("}", "").replace("*", "wildcard"))
        return f"{method}_{clean}" if clean else method

    @classmethod
    def _unique_operation_id(cls, method: str, path: str, seen: set) -> str:
        """operationId, de-duplicated across the document (OpenAPI requires unique)."""
        base = cls._operation_id(method, path)
        oid = base
        n = 2
        while oid in seen:
            oid = f"{base}_{n}"
            n += 1
        seen.add(oid)
        return oid

    @classmethod
    def _extract_path_params(cls, path: str) -> list[dict]:
        """Extract path parameters and their typed schemas (incl. splat)."""
        params = []
        for seg in path.split("/"):
            p = cls._segment_param(seg)
            if not p:
                continue
            name, ptype = p
            schema = dict(_PARAM_TYPE_SCHEMA.get(ptype, {"type": "string"}))
            params.append({
                "name": name,
                "in": "path",
                "required": True,
                "schema": schema,
            })
        return params

    # ── ORM model -> JSON Schema ───────────────────────────────────

    @staticmethod
    def _field_schema(field) -> dict:
        """Map a single ORM Field to a JSON Schema property fragment."""
        from datetime import datetime
        ft = getattr(field, "field_type", str)
        if ft is int:
            schema = {"type": "integer"}
        elif ft is float:
            schema = {"type": "number"}
        elif ft is bool:
            schema = {"type": "boolean"}
        elif ft is datetime:
            schema = {"type": "string", "format": "date-time"}
        elif ft in (bytes, bytearray):
            schema = {"type": "string", "format": "byte"}
        else:
            schema = {"type": "string"}

        if getattr(field, "max_length", None) is not None and schema["type"] == "string":
            schema["maxLength"] = field.max_length
        if getattr(field, "min_length", None) is not None and schema["type"] == "string":
            schema["minLength"] = field.min_length
        if getattr(field, "min_value", None) is not None:
            schema["minimum"] = field.min_value
        if getattr(field, "max_value", None) is not None:
            schema["maximum"] = field.max_value
        if getattr(field, "regex_pattern", None):
            schema["pattern"] = field.regex_pattern
        if getattr(field, "choices", None):
            schema["enum"] = list(field.choices)
        if getattr(field, "primary_key", False) and getattr(field, "auto_increment", False):
            schema["readOnly"] = True
        return schema

    @classmethod
    def _model_schema(cls, model_class) -> dict:
        """Build a components.schemas object from an ORM model's fields."""
        props = {}
        required = []
        for name, field in model_class._fields.items():
            props[name] = cls._field_schema(field)
            if getattr(field, "required", False):
                required.append(name)
        schema = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema

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
        if isinstance(value, (bytes, bytearray)):
            return {"type": "string", "format": "binary"}
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
