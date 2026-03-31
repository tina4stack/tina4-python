# Built-in MCP dev tools — auto-registered when TINA4_DEBUG=true + localhost.
"""
24 built-in tools for AI-assisted development. These expose the framework's
internals to MCP clients (Claude Code, Cursor, etc.) for inspection,
querying, file editing, and management.

Security:
    - Only active when TINA4_DEBUG=true AND running on localhost
    - File operations sandboxed to project directory
    - database_execute available on localhost only
    - TINA4_MCP_REMOTE=true to enable on remote servers (opt-in)
"""
import os
import json
import re
from pathlib import Path


def register_dev_tools(server):
    """Register all built-in dev tools on the given McpServer."""

    project_root = Path(os.getcwd()).resolve()

    def _safe_path(rel_path: str) -> Path:
        """Resolve a path and ensure it's within the project directory."""
        resolved = (project_root / rel_path).resolve()
        if not str(resolved).startswith(str(project_root)):
            raise ValueError(f"Path escapes project directory: {rel_path}")
        return resolved

    def _redact_env(key: str, value: str) -> str:
        """Redact sensitive environment variable values."""
        sensitive = ("secret", "password", "token", "key", "credential", "api_key")
        if any(s in key.lower() for s in sensitive):
            return "***REDACTED***"
        return value

    # ── Database Tools ──────────────────────────────────────────

    def database_query(sql: str, params: str = "[]") -> dict:
        """Execute a read-only SQL query (SELECT) and return results."""
        from tina4_python.orm.model import ORM
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        param_list = json.loads(params) if isinstance(params, str) else params
        result = db.fetch(sql, param_list)
        return {"records": result.to_array(), "count": result.count}

    def database_execute(sql: str, params: str = "[]") -> dict:
        """Execute arbitrary SQL (INSERT/UPDATE/DELETE/DDL). Localhost only."""
        from tina4_python.orm.model import ORM
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        param_list = json.loads(params) if isinstance(params, str) else params
        result = db.execute(sql, param_list)
        db.commit()
        return {"success": True, "affected_rows": result.count if hasattr(result, "count") else 0}

    def database_tables() -> list:
        """List all database tables."""
        from tina4_python.orm.model import ORM
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        return db.get_tables()

    def database_columns(table: str) -> list:
        """Get column definitions for a table."""
        from tina4_python.orm.model import ORM
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        return db.get_columns(table)

    # ── Route Tools ─────────────────────────────────────────────

    def route_list() -> list:
        """List all registered routes with methods and paths."""
        from tina4_python.core.router import Router
        routes = []
        for route in Router._routes:
            routes.append({
                "method": route.get("method", ""),
                "path": route.get("path", ""),
                "auth_required": route.get("auth_required", False),
            })
        return routes

    def route_test(method: str, path: str, body: str = "", headers: str = "{}") -> dict:
        """Call a route and return the response (status, body, headers)."""
        from tina4_python.test_client import TestClient
        client = TestClient()
        header_dict = json.loads(headers) if isinstance(headers, str) else headers
        method = method.upper()
        if method == "GET":
            r = client.get(path, headers=header_dict)
        elif method == "POST":
            r = client.post(path, body=body, headers=header_dict)
        elif method == "PUT":
            r = client.put(path, body=body, headers=header_dict)
        elif method == "DELETE":
            r = client.delete(path, headers=header_dict)
        else:
            return {"error": f"Unsupported method: {method}"}
        return {"status": r.status, "body": r.text(), "content_type": r.content_type}

    def swagger_spec() -> dict:
        """Return the full OpenAPI 3.0.3 JSON specification."""
        from tina4_python.swagger import Swagger
        return Swagger.generate()

    # ── Template Tools ──────────────────────────────────────────

    def template_render(template: str, data: str = "{}") -> str:
        """Render a template string with the given data."""
        from tina4_python.frond import Frond
        engine = Frond("src/templates")
        ctx = json.loads(data) if isinstance(data, str) else data
        return engine.render_string(template, ctx)

    # ── File Tools ──────────────────────────────────────────────

    def file_read(path: str) -> str:
        """Read a project file. Path is relative to project root."""
        p = _safe_path(path)
        if not p.exists():
            return f"File not found: {path}"
        if not p.is_file():
            return f"Not a file: {path}"
        return p.read_text(encoding="utf-8", errors="replace")

    def file_write(path: str, content: str) -> dict:
        """Write or update a project file. Path is relative to project root."""
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"written": str(p.relative_to(project_root)), "bytes": len(content.encode())}

    def file_list(path: str = ".") -> list:
        """List files in a directory. Path is relative to project root."""
        p = _safe_path(path)
        if not p.exists():
            return {"error": f"Directory not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}
        entries = []
        for entry in sorted(p.iterdir()):
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
        return entries

    def asset_upload(filename: str, content: str, encoding: str = "utf-8") -> dict:
        """Upload a file to src/public/. Content is text or base64 for binary."""
        target = _safe_path(f"src/public/{filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "base64":
            import base64
            target.write_bytes(base64.b64decode(content))
        else:
            target.write_text(content, encoding="utf-8")
        return {"uploaded": str(target.relative_to(project_root)), "bytes": target.stat().st_size}

    # ── Migration Tools ─────────────────────────────────────────

    def migration_status() -> list:
        """List pending and completed migrations."""
        from tina4_python.orm.model import ORM
        from tina4_python.migration.runner import MigrationRunner
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        runner = MigrationRunner(db)
        return runner.status() if hasattr(runner, "status") else {"info": "Migration status not available"}

    def migration_create(description: str) -> dict:
        """Create a new migration file."""
        from tina4_python.migration import create_migration
        filename = create_migration(description)
        return {"created": filename}

    def migration_run() -> dict:
        """Run all pending migrations."""
        from tina4_python.orm.model import ORM
        from tina4_python.migration import migrate
        db = ORM._database
        if db is None:
            return {"error": "No database connection"}
        result = migrate(db)
        return {"result": str(result)}

    # ── Queue Tools ─────────────────────────────────────────────

    def queue_status(topic: str = "default") -> dict:
        """Get queue size by status."""
        try:
            from tina4_python.queue import Queue
            q = Queue(topic=topic)
            return {
                "topic": topic,
                "pending": q.size("pending"),
                "completed": q.size("completed"),
                "failed": q.size("failed"),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Session/Cache Tools ─────────────────────────────────────

    def session_list() -> list:
        """List active sessions."""
        session_dir = Path("data/sessions")
        if not session_dir.exists():
            return []
        sessions = []
        for f in session_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append({"id": f.stem, "data": data})
            except (json.JSONDecodeError, OSError):
                sessions.append({"id": f.stem, "error": "corrupt"})
        return sessions

    def cache_stats() -> dict:
        """Get response cache statistics."""
        try:
            from tina4_python.cache import cache_stats as _stats
            return _stats()
        except Exception as e:
            return {"error": str(e)}

    # ── ORM Tools ───────────────────────────────────────────────

    def orm_describe() -> list:
        """List all ORM models with their fields and types."""
        from tina4_python.orm.model import ORM
        models = []
        for cls in ORM.__subclasses__():
            fields = []
            for name, field in cls._fields.items():
                fields.append({
                    "name": name,
                    "type": type(field).__name__,
                    "primary_key": getattr(field, "primary_key", False),
                })
            models.append({
                "class": cls.__name__,
                "table": getattr(cls, "table_name", cls.__name__.lower()),
                "fields": fields,
            })
        return models

    # ── Debugging Tools ─────────────────────────────────────────

    def log_tail(lines: int = 50) -> list:
        """Read recent log entries."""
        log_file = Path("logs/debug.log")
        if not log_file.exists():
            return []
        all_lines = log_file.read_text(errors="replace").splitlines()
        return all_lines[-lines:]

    def error_log(limit: int = 20) -> list:
        """Recent errors/exceptions with stack traces."""
        try:
            from tina4_python.dev_admin import DevAdmin
            if hasattr(DevAdmin, "broken_tracker"):
                return DevAdmin.broken_tracker.get(limit=limit)
        except Exception:
            pass
        return []

    def env_list() -> dict:
        """List environment variables (sensitive values redacted)."""
        return {k: _redact_env(k, v) for k, v in sorted(os.environ.items())}

    # ── Data Tools ──────────────────────────────────────────────

    def seed_table(table: str, count: int = 10) -> dict:
        """Seed a table with fake data."""
        try:
            from tina4_python.seeder import seed_table as _seed
            from tina4_python.orm.model import ORM
            db = ORM._database
            if db is None:
                return {"error": "No database connection"}
            inserted = _seed(db, table, count)
            return {"table": table, "inserted": inserted}
        except Exception as e:
            return {"error": str(e)}

    # ── System Tools ────────────────────────────────────────────

    def system_info() -> dict:
        """Framework version, Python version, uptime, project path."""
        import sys
        import platform
        return {
            "framework": "tina4-python",
            "version": _get_version(),
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(project_root),
            "debug": os.environ.get("TINA4_DEBUG", "false"),
        }

    def _get_version():
        try:
            from tina4_python import __version__
            return __version__
        except ImportError:
            return "unknown"

    # ── Register all tools ──────────────────────────────────────

    tools = [
        ("database_query", database_query, "Execute a read-only SQL query (SELECT)"),
        ("database_execute", database_execute, "Execute arbitrary SQL (INSERT/UPDATE/DELETE/DDL)"),
        ("database_tables", database_tables, "List all database tables"),
        ("database_columns", database_columns, "Get column definitions for a table"),
        ("route_list", route_list, "List all registered routes"),
        ("route_test", route_test, "Call a route and return the response"),
        ("swagger_spec", swagger_spec, "Return the OpenAPI 3.0.3 JSON spec"),
        ("template_render", template_render, "Render a template string with data"),
        ("file_read", file_read, "Read a project file"),
        ("file_write", file_write, "Write or update a project file"),
        ("file_list", file_list, "List files in a directory"),
        ("asset_upload", asset_upload, "Upload a file to src/public/"),
        ("migration_status", migration_status, "List pending and completed migrations"),
        ("migration_create", migration_create, "Create a new migration file"),
        ("migration_run", migration_run, "Run all pending migrations"),
        ("queue_status", queue_status, "Get queue size by status"),
        ("session_list", session_list, "List active sessions"),
        ("cache_stats", cache_stats, "Get response cache statistics"),
        ("orm_describe", orm_describe, "List all ORM models with fields and types"),
        ("log_tail", log_tail, "Read recent log entries"),
        ("error_log", error_log, "Recent errors and exceptions"),
        ("env_list", env_list, "List environment variables (secrets redacted)"),
        ("seed_table", seed_table, "Seed a table with fake data"),
        ("system_info", system_info, "Framework version, Python version, project info"),
    ]

    for name, handler, description in tools:
        server.register_tool(name, handler, description)
