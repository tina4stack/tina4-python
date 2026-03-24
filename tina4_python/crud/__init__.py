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

    GET    /api/{table_name}       — list with pagination (limit, skip)
    GET    /api/{table_name}/{id}  — get single record by primary key
    POST   /api/{table_name}       — create new record
    PUT    /api/{table_name}/{id}  — update record by primary key
    DELETE /api/{table_name}/{id}  — delete record by primary key

All write routes (POST/PUT/DELETE) are registered with noauth so they
don't conflict with existing auth defaults. Add auth via middleware.
"""
import importlib
import inspect
import os
import sys

from tina4_python.core.router import Router
from tina4_python.debug import Log


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
    def register(model_class, prefix: str = "/api"):
        """Register REST endpoints for a single ORM model class.

        Args:
            model_class: An ORM subclass with table_name and fields defined.
            prefix: URL prefix for the generated routes (default "/api").

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
                limit = int(request.params.get("limit", 10))
                skip = int(request.params.get("skip", 0))
            except (ValueError, TypeError):
                limit = 10
                skip = 0

            records, total = _cls.all(limit=limit, skip=skip)
            return response({
                "data": [r.to_dict() for r in records],
                "total": total,
                "limit": limit,
                "skip": skip,
            })

        list_handler.__name__ = f"autocrud_list_{table}"
        list_handler.__qualname__ = f"autocrud_list_{table}"
        list_handler._swagger_summary = f"List all {pretty_name}"
        list_handler._swagger_tags = [table]
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
        Router.add("GET", f"{base_path}/{{id}}", get_handler)
        generated.append({"method": "GET", "path": f"{base_path}/{{id}}", "table": table})

        # ── POST /api/{table} — create new record ────────────────
        async def create_handler(request, response, _cls=model_class):
            data = request.body if isinstance(request.body, dict) else {}
            record = _cls(data)
            errors = record.validate()
            if errors:
                return response({"error": "Validation failed", "detail": errors}, 400)
            try:
                record.save()
            except Exception as e:
                return response({"error": "Failed to create record", "detail": str(e)}, 500)
            return response(record.to_dict(), 201)

        create_handler.__name__ = f"autocrud_create_{table}"
        create_handler.__qualname__ = f"autocrud_create_{table}"
        create_handler._noauth = True
        create_handler._swagger_summary = f"Create {pretty_name}"
        create_handler._swagger_tags = [table]
        create_handler._swagger_example = example_body
        Router.add("POST", base_path, create_handler)
        generated.append({"method": "POST", "path": base_path, "table": table})

        # ── PUT /api/{table}/{id} — update record ────────────────
        async def update_handler(request, response, _cls=model_class, _pk=pk_field):
            pk_value = request.param("id")
            record = _cls.find(pk_value)
            if record is None:
                return response({"error": "Not Found"}, 404)

            data = request.body if isinstance(request.body, dict) else {}
            for key, value in data.items():
                if key in record._fields:
                    field = record._fields[key]
                    setattr(record, key, field.validate(value))

            errors = record.validate()
            if errors:
                return response({"error": "Validation failed", "detail": errors}, 400)

            try:
                record.save()
            except Exception as e:
                return response({"error": "Failed to update record", "detail": str(e)}, 500)
            return response(record.to_dict())

        update_handler.__name__ = f"autocrud_update_{table}"
        update_handler.__qualname__ = f"autocrud_update_{table}"
        update_handler._noauth = True
        update_handler._swagger_summary = f"Update {pretty_name}"
        update_handler._swagger_tags = [table]
        update_handler._swagger_example = example_body
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
    def discover(models_dir: str = "src/orm", prefix: str = "/api"):
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
                    AutoCrud.register(attr, prefix=prefix)
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
    def clear():
        """Clear all registered models (useful for testing)."""
        AutoCrud._registered.clear()
