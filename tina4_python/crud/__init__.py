# Tina4 Auto-CRUD — Auto-generate REST endpoints from ORM models.
"""
Discovers ORM models and registers CRUD routes automatically.

    from tina4_python.crud import AutoCrud
    from src.orm.user import User
    from src.orm.product import Product

    # Register individual models
    AutoCrud.register(User)
    AutoCrud.register(Product, prefix="/api/v2")

    # Or auto-discover all models in a directory
    AutoCrud.discover("src/orm", prefix="/api")

Generated endpoints per model:

    GET    /api/{table_name}       — list with pagination (limit, offset; also accepts page, per_page)
    GET    /api/{table_name}/{id}  — get single record by primary key
    POST   /api/{table_name}       — create new record
    PUT    /api/{table_name}/{id}  — update record by primary key
    DELETE /api/{table_name}/{id}  — delete record by primary key

Write routes (POST/PUT/DELETE) are SECURE BY DEFAULT — they require a valid
token, matching Tina4's framework-wide default (the router gates writes unless a
route is @noauth). Pass ``public=True`` to open them explicitly, e.g.
``AutoCrud.register(Note, public=True)``.
"""
import importlib
import inspect
import os
import sys

from tina4_python.core.router import Router
from tina4_python.debug import Log

# PAGE-DEC-01: the maximum per-page size the list handler will honour, no matter
# what a caller asks for via ?limit=/?per_page=. 100 is not an arbitrary pick -
# it is the SAME row cap ORM.all()/select()/where()/db.fetch() already default to
# ("the one row cap the whole family shares", tina4_python/orm/model.py), and the
# number Node's AutoCrud shares via its own DEFAULT_ROW_CAP constant. Without this
# a client could request the whole table in one query (?limit=1000000).
MAX_PER_PAGE = 100


# CRUD-MASS-ASSIGNMENT: the columns a write BODY is allowed to set. A client
# body is never trusted verbatim — only fields the model DECLARES pass
# through; `is_deleted` is never client-writable (soft-delete is mutated only
# by delete()/restore(), never by a POST/PUT body); and the primary key is
# never taken from the body except a genuinely natural (non-auto-increment)
# key on CREATE, where a caller-chosen key is the documented way to create a
# row. Everywhere else the PK is stripped: on an auto-increment CREATE the
# database assigns the id (a client-supplied id used to silently turn a
# create into an overwrite — or a no-op update reported as 201 — of an
# unrelated existing row); on UPDATE the row is addressed by the URL `{id}`
# alone, so a body copy of the PK can never redirect the write to a
# different row than the one the route matched.
def _allow_listed_data(model_class, data, *, is_create: bool) -> dict:
    if not isinstance(data, dict):
        return {}
    pk = model_class._get_pk()
    pk_field = model_class._fields.get(pk)
    strip_pk = pk_field is not None and (not is_create or pk_field.auto_increment)
    return {
        key: value
        for key, value in data.items()
        if key in model_class._fields
        and key != "is_deleted"
        and not (strip_pk and key == pk)
    }


class AutoCrud:
    """Auto-generate REST endpoints from ORM model classes."""

    # Track registered models for introspection
    _registered: dict[str, type] = {}

    @staticmethod
    def _build_example(model_class) -> dict:
        """Build a sample request body from ORM field definitions.

        Generates a dict with field names as keys and example values
        based on field types, suitable for Swagger request body examples.
        """
        from datetime import datetime

        example = {}
        for name, field in model_class._fields.items():
            if field.primary_key and field.auto_increment:
                continue  # Skip auto-generated PKs
            ft = field.field_type
            if ft == int:
                example[name] = 0
            elif ft == float:
                example[name] = 0.0
            elif ft == bool:
                example[name] = True
            elif ft == datetime:
                example[name] = "2024-01-01T00:00:00"
            else:
                example[name] = "string"
        return example

    @staticmethod
    def register(model_class, prefix: str = "/api", public: bool = False):
        """Register REST endpoints for a single ORM model class.

        Args:
            model_class: An ORM subclass with table_name and fields defined.
            prefix: URL prefix for the generated routes (default "/api").
            public: If True, the write routes (POST/PUT/DELETE) are OPEN (no auth).
                Default False keeps them **secure-by-default** — a valid token is
                required, matching the framework's write-gating.

        Returns:
            List of dicts describing the generated routes.

        Raises:
            ValueError: If the model has no table name.
        """
        table = model_class._get_table()
        if not table:
            raise ValueError(
                f"AutoCrud: {model_class.__name__} has no table_name set."
            )

        base_path = f"{prefix}/{table}"
        pk_field = model_class._get_pk()
        generated = []
        pretty_name = table.replace("_", " ").title()
        example_body = AutoCrud._build_example(model_class)

        # ── GET /api/{table} — list with pagination ──────────────
        async def list_handler(request, response, _cls=model_class):
            try:
                # Primary names: limit / offset
                # Compat names: per_page / page (PHP/Ruby/Node style)
                # Pagination is a QUERY-STRING concern, not a route param
                # (REQ-PARAM-POLLUTION, 3.13.99 — request.params is route-only).
                limit = int(request.query.get("limit", request.query.get("per_page", 10)))
                offset = int(request.query.get("offset", 0))
                # page/per_page compat: if page is provided, derive offset from it
                if "page" in request.query and "offset" not in request.query:
                    page = int(request.query.get("page", 1))
                    per_page = int(request.query.get("per_page", limit))
                    # PAGE-DEC-01: clamp page < 1 -> page 1 BEFORE deriving offset,
                    # so offset=(page-1)*per_page can never go negative (a page=0/
                    # negative request used to hand PostgreSQL a negative OFFSET -
                    # a driver error - and silently misbehave on SQLite, while the
                    # envelope reported page:0). Cap per_page BEFORE the same
                    # derivation so the offset lines up with the size actually used.
                    page = max(1, page)
                    per_page = min(per_page, MAX_PER_PAGE)
                    offset = (page - 1) * per_page
                    limit = per_page
                else:
                    limit = min(limit, MAX_PER_PAGE)  # PAGE-DEC-01: cap an oversized ?limit=
                    page = (offset // limit) + 1 if limit else 1
            except (ValueError, TypeError):
                limit = 10
                offset = 0
                page = 1

            records = _cls.all(limit=limit, offset=offset)
            total = _cls.count()
            total_pages = max(1, -(-total // limit)) if limit else 1
            record_dicts = [record.to_dict() for record in records]
            # The canonical ADR-0043 envelope: EXACTLY seven snake_case keys, no
            # duplicate or camelCase spellings, matching DatabaseResult.to_paginate().
            return response({
                "records": record_dicts,     # the page rows, verbatim (never re-sliced)
                "total": total,              # the true COUNT for the filter, NOT rows returned
                "page": page,                # floor(offset / limit) + 1
                "per_page": limit,           # the query's limit
                "total_pages": total_pages,  # ceil(total / per_page)
                "limit": limit,              # the SQL limit actually applied
                "offset": offset,            # the SQL offset actually applied
            })

        list_handler.__name__ = f"autocrud_list_{table}"
        list_handler.__qualname__ = f"autocrud_list_{table}"
        list_handler._swagger_summary = f"List all {pretty_name}"
        list_handler._swagger_tags = [table]
        list_handler._swagger_model = model_class
        list_handler._swagger_model_list = True
        Router.add("GET", base_path, list_handler)
        generated.append({"method": "GET", "path": base_path, "table": table})

        # ── GET /api/{table}/{id} — get single record ────────────
        async def get_handler(request, response, _cls=model_class):
            pk_value = request.param("id")
            record = _cls.find(pk_value)
            if record is None:
                return response({"error": "Not Found"}, 404)
            return response(record.to_dict())

        get_handler.__name__ = f"autocrud_get_{table}"
        get_handler.__qualname__ = f"autocrud_get_{table}"
        get_handler._swagger_summary = f"Get {pretty_name} by ID"
        get_handler._swagger_tags = [table]
        get_handler._swagger_model = model_class
        Router.add("GET", f"{base_path}/{{id}}", get_handler)
        generated.append({"method": "GET", "path": f"{base_path}/{{id}}", "table": table})

        # ── POST /api/{table} — create new record ────────────────
        async def create_handler(request, response, _cls=model_class):
            raw_data = request.body if isinstance(request.body, dict) else {}
            # CRUD-MASS-ASSIGNMENT: allow-list before the body ever reaches
            # the model (guards is_deleted + strips the PK — see above).
            data = _allow_listed_data(_cls, raw_data, is_create=True)
            try:
                record = _cls(data)
            except (ValueError, TypeError) as e:
                # A field that cannot even be COERCED to its declared type
                # (e.g. a string where an int is required) is a client input
                # error too — 422 with the cause, never an uncaught 500.
                return response({"error": "Validation failed", "detail": [str(e)]}, 422)
            # CRUD-VALIDATION-STATUS (CRUD-DEC-01): a validation failure is a
            # CLIENT error — 422 with the field errors, never a 500/400.
            errors = record.validate()
            if errors:
                return response({"error": "Validation failed", "detail": errors}, 422)
            try:
                saved = record.save()
            except Exception as e:
                return response({"error": "Failed to create record", "detail": str(e)}, 500)
            # save() is documented to never raise — it returns False on a
            # genuine driver failure (NOT NULL, duplicate key, ...). Honour
            # that contract so a failed save can never report 201.
            if saved is False:
                return response(
                    {"error": "Failed to create record", "detail": record.get_error() or "save failed"},
                    500,
                )
            return response(record.to_dict(), 201)

        create_handler.__name__ = f"autocrud_create_{table}"
        create_handler.__qualname__ = f"autocrud_create_{table}"
        if public:                       # secure-by-default; opt-in to public writes
            create_handler._noauth = True
        create_handler._swagger_summary = f"Create {pretty_name}"
        create_handler._swagger_tags = [table]
        create_handler._swagger_example = example_body
        create_handler._swagger_model = model_class
        Router.add("POST", base_path, create_handler)
        generated.append({"method": "POST", "path": base_path, "table": table})

        # ── PUT /api/{table}/{id} — update record ────────────────
        async def update_handler(request, response, _cls=model_class, _pk=pk_field):
            pk_value = request.param("id")
            record = _cls.find(pk_value)
            if record is None:
                return response({"error": "Not Found"}, 404)

            raw_data = request.body if isinstance(request.body, dict) else {}
            # CRUD-MASS-ASSIGNMENT: allow-list (guards is_deleted + strips the
            # PK — the row is addressed by the URL {id}, never by the body).
            data = _allow_listed_data(_cls, raw_data, is_create=False)
            # CRUD-PUT-NOVALIDATE: partial-update mode — only the keys the
            # caller supplied are touched (via coerce(), the same read-path
            # type coercion the constructor uses); every untouched field
            # keeps the value `find()` just loaded, which was already valid.
            # A value that cannot even be coerced (wrong type) is a 422, not
            # an uncaught exception (field.validate() used to raise here).
            try:
                record._populate(data)
            except (ValueError, TypeError) as e:
                return response({"error": "Validation failed", "detail": [str(e)]}, 422)

            # CRUD-VALIDATION-STATUS (CRUD-DEC-01): re-validates the WHOLE
            # record (untouched fields already satisfy their own rules, so
            # this is exactly a partial-update check) — 422 with field
            # errors, never a 500/400.
            errors = record.validate()
            if errors:
                return response({"error": "Validation failed", "detail": errors}, 422)

            try:
                saved = record.save()
            except Exception as e:
                return response({"error": "Failed to update record", "detail": str(e)}, 500)
            if saved is False:
                return response(
                    {"error": "Failed to update record", "detail": record.get_error() or "save failed"},
                    500,
                )
            return response(record.to_dict())

        update_handler.__name__ = f"autocrud_update_{table}"
        update_handler.__qualname__ = f"autocrud_update_{table}"
        if public:
            update_handler._noauth = True
        update_handler._swagger_summary = f"Update {pretty_name}"
        update_handler._swagger_tags = [table]
        update_handler._swagger_example = example_body
        update_handler._swagger_model = model_class
        Router.add("PUT", f"{base_path}/{{id}}", update_handler)
        generated.append({"method": "PUT", "path": f"{base_path}/{{id}}", "table": table})

        # ── DELETE /api/{table}/{id} — delete record ─────────────
        async def delete_handler(request, response, _cls=model_class):
            pk_value = request.param("id")
            record = _cls.find(pk_value)
            if record is None:
                return response({"error": "Not Found"}, 404)

            try:
                record.delete()
            except Exception as e:
                return response({"error": "Failed to delete record", "detail": str(e)}, 500)
            return response({"deleted": True})

        delete_handler.__name__ = f"autocrud_delete_{table}"
        delete_handler.__qualname__ = f"autocrud_delete_{table}"
        if public:
            delete_handler._noauth = True
        delete_handler._swagger_summary = f"Delete {pretty_name}"
        delete_handler._swagger_tags = [table]
        Router.add("DELETE", f"{base_path}/{{id}}", delete_handler)
        generated.append({"method": "DELETE", "path": f"{base_path}/{{id}}", "table": table})

        # Track registration
        AutoCrud._registered[table] = model_class
        Log.info(f"AutoCrud: registered {len(generated)} routes for {model_class.__name__} ({base_path})")

        return generated

    @staticmethod
    def discover(models_dir: str = "src/orm", prefix: str = "/api", public: bool = False):
        """Auto-discover all ORM models in a directory and register CRUD routes.

        Scans .py files in the given directory, imports them, and registers
        any ORM subclass found with AutoCrud.register().

        Args:
            models_dir: Path to the directory containing ORM model files.
            prefix: URL prefix for all generated routes.

        Returns:
            List of discovered model class names.
        """
        from tina4_python.orm.model import ORM

        discovered = []

        if not os.path.isdir(models_dir):
            Log.warning(f"AutoCrud.discover: directory '{models_dir}' not found")
            return discovered

        # Add parent directory to sys.path for imports
        abs_dir = os.path.abspath(models_dir)
        parent = os.path.dirname(abs_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        # Convert directory path to module path
        # e.g. "src/orm" -> "src.orm"
        module_base = abs_dir.replace(os.sep, ".")
        # Try relative module name from parent
        dir_name = os.path.basename(abs_dir)
        parent_name = os.path.basename(parent)
        module_prefix = f"{parent_name}.{dir_name}"

        for filename in sorted(os.listdir(models_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]  # Strip .py

            # Try importing the module
            try:
                full_module = f"{module_prefix}.{module_name}"
                mod = importlib.import_module(full_module)
            except (ImportError, ModuleNotFoundError):
                # Fallback: try direct import
                try:
                    spec = importlib.util.spec_from_file_location(
                        module_name,
                        os.path.join(abs_dir, filename),
                    )
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)
                except Exception as e:
                    Log.warning(f"AutoCrud.discover: failed to import {filename}: {e}")
                    continue

            # Find ORM subclasses in the module
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, ORM)
                    and attr is not ORM
                    and attr._get_table()  # Has a table name
                    and attr._get_table() not in AutoCrud._registered
                ):
                    AutoCrud.register(attr, prefix=prefix, public=public)
                    discovered.append(attr.__name__)

        if discovered:
            Log.info(f"AutoCrud.discover: found {len(discovered)} models in '{models_dir}': {', '.join(discovered)}")
        else:
            Log.info(f"AutoCrud.discover: no ORM models found in '{models_dir}'")

        return discovered

    @staticmethod
    def models() -> dict[str, type]:
        """Return all registered model classes, indexed by table name."""
        return dict(AutoCrud._registered)

    @staticmethod
    def generate_routes() -> list[dict]:
        """Return route definitions for all registered models.

        Routes are already registered during register()/discover() calls.
        This method returns the route metadata for introspection.
        """
        routes = []
        for table, model_class in AutoCrud._registered.items():
            base = f"/api/{table}"
            routes.append({"method": "GET", "path": base, "table": table})
            routes.append({"method": "GET", "path": f"{base}/{{id}}", "table": table})
            routes.append({"method": "POST", "path": base, "table": table})
            routes.append({"method": "PUT", "path": f"{base}/{{id}}", "table": table})
            routes.append({"method": "DELETE", "path": f"{base}/{{id}}", "table": table})
        return routes

    @staticmethod
    def clear():
        """Clear all registered models (useful for testing)."""
        AutoCrud._registered.clear()
