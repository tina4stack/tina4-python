#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Built-in MCP (Model Context Protocol) server for Tina4-Python.

Embeds an MCP server directly into the running web application, allowing
any tool-driven LLM (Claude, Cursor, Copilot, etc.) to interact with
the project — reading logs, managing files, inspecting routes, querying
databases, and optionally modifying code.

Activation:
    - **Debug mode**: MCP is always enabled (like jurigged).
    - **Production**: Set ``TINA4_MCP=true`` in ``.env``.

Authentication:
    Every request to the MCP endpoint must include:
    ``Authorization: Bearer <API_KEY>``

Granular permissions (all default ``true`` in debug, ``false`` in production):
    - ``TINA4_MCP_LOGS``        — Read logs, list routes, server info
    - ``TINA4_MCP_FILES_READ``  — Read project files, search, list dirs
    - ``TINA4_MCP_FILES_WRITE`` — Write templates, public assets, scss
    - ``TINA4_MCP_CODE_WRITE``  — Write routes, app, orm (dangerous)
    - ``TINA4_MCP_DB_READ``     — SELECT queries, list tables
    - ``TINA4_MCP_DB_WRITE``    — INSERT/UPDATE/DELETE, migrations
    - ``TINA4_MCP_QUEUE``       — Queue produce/peek
"""

__all__ = [
    "create_mcp_server",
    "get_mcp_asgi_app",
    "mcp_auth_middleware",
]

import fnmatch
import inspect
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import tina4_python
from tina4_python.Debug import Debug

# ---------------------------------------------------------------------------
# Permission system
# ---------------------------------------------------------------------------

# Track server start time for uptime calculation
_server_start_time = time.time()

# Dev mode flag — mirrors __init__.py's _dev_mode
_is_dev = os.getenv("TINA4_DEBUG_LEVEL", "").strip().upper() in ("ALL", "DEBUG",
    "[TINA4_LOG_ALL]", "[TINA4_LOG_DEBUG]")


def _perm(name: str) -> bool:
    """Check whether a permission toggle is enabled.

    In dev mode, permissions default to ``true``.
    In production, permissions default to ``false``.
    """
    env_key = f"TINA4_MCP_{name}"
    default = "true" if _is_dev else "false"
    return os.getenv(env_key, default).strip().lower() in ("true", "1", "yes")


def _require_perm(name: str, tool_name: str) -> None:
    """Raise if permission is disabled."""
    if not _perm(name):
        raise PermissionError(
            f"Tool '{tool_name}' requires TINA4_MCP_{name}=true in .env"
        )


# ---------------------------------------------------------------------------
# File safety
# ---------------------------------------------------------------------------

# Directories where content writes are allowed (TINA4_MCP_FILES_WRITE)
_CONTENT_WRITE_DIRS = {"src/templates", "src/public", "src/scss", "migrations"}

# Additional directories unlocked by TINA4_MCP_CODE_WRITE
_CODE_WRITE_DIRS = {"src/routes", "src/app", "src/orm"}

# Directories allowed for reading (TINA4_MCP_FILES_READ)
_READABLE_DIRS = {"src", "migrations", "logs"}

# Read-only individual files
_READABLE_FILES = {"app.py", "pyproject.toml", "README.md", "CLAUDE.md"}

# Always blocked — never readable or writable
_BLOCKED_DIRS = {"secrets", ".git", "tina4_python", "__pycache__", "node_modules",
                 "sessions", ".venv", "venv", ".env"}

# Sensitive env var patterns (values are redacted)
_SENSITIVE_PATTERN = re.compile(
    r"(SECRET|PASSWORD|PRIVATE|CREDENTIAL|TOKEN|API_KEY)", re.IGNORECASE
)

# Max file size for reads (1 MB)
_MAX_READ_BYTES = 1_048_576


def _get_root() -> Path:
    """Return the project root path."""
    return Path(tina4_python.root_path)


def _resolve_path(relative_path: str) -> Path:
    """Resolve a relative path safely against the project root.

    Raises ValueError for path traversal or blocked paths.
    """
    root = _get_root()
    # Normalise and resolve
    clean = relative_path.replace("\\", "/").lstrip("/")
    resolved = (root / clean).resolve()

    # Block path traversal
    if not str(resolved).startswith(str(root)):
        raise ValueError(f"Path traversal detected: {relative_path}")

    # Check against blocked dirs
    rel_to_root = resolved.relative_to(root)
    parts = rel_to_root.parts
    if parts:
        top_dir = parts[0]
        if top_dir in _BLOCKED_DIRS or top_dir.startswith("."):
            raise ValueError(f"Access denied: {relative_path}")

    return resolved


def _check_readable(relative_path: str) -> Path:
    """Validate a path is readable and return its resolved Path."""
    resolved = _resolve_path(relative_path)
    root = _get_root()
    rel = resolved.relative_to(root)
    rel_str = str(rel).replace("\\", "/")

    # Check individual readable files
    if rel_str in _READABLE_FILES:
        return resolved

    # Check readable directories
    for read_dir in _READABLE_DIRS:
        if rel_str.startswith(read_dir + "/") or rel_str == read_dir:
            return resolved

    raise ValueError(f"Read access denied: {relative_path}")


def _check_writable(relative_path: str) -> Path:
    """Validate a path is writable and return its resolved Path."""
    resolved = _resolve_path(relative_path)
    root = _get_root()
    rel = resolved.relative_to(root)
    rel_str = str(rel).replace("\\", "/")

    # Check content write dirs (FILES_WRITE permission)
    for write_dir in _CONTENT_WRITE_DIRS:
        if rel_str.startswith(write_dir + "/") or rel_str == write_dir:
            return resolved

    # Check code write dirs (CODE_WRITE permission — checked by caller)
    if _perm("CODE_WRITE"):
        for write_dir in _CODE_WRITE_DIRS:
            if rel_str.startswith(write_dir + "/") or rel_str == write_dir:
                return resolved

    raise ValueError(
        f"Write access denied: {relative_path}. "
        f"Writable dirs: {', '.join(sorted(_CONTENT_WRITE_DIRS | (_CODE_WRITE_DIRS if _perm('CODE_WRITE') else set())))}"
    )


# ---------------------------------------------------------------------------
# MCP Server Creation
# ---------------------------------------------------------------------------

def create_mcp_server(root_path: str):
    """Create and configure the FastMCP server with all tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        name="tina4",
        stateless_http=True,
    )

    _register_diagnostic_tools(mcp, root_path)
    _register_file_read_tools(mcp, root_path)
    _register_file_write_tools(mcp, root_path)
    _register_template_tools(mcp, root_path)
    _register_project_tools(mcp, root_path)
    _register_db_tools(mcp, root_path)
    _register_queue_tools(mcp, root_path)

    return mcp


def get_mcp_asgi_app(mcp_server):
    """Return the ASGI application from the MCP server."""
    return mcp_server.streamable_http_app()


def mcp_auth_middleware(asgi_app):
    """ASGI middleware that validates API_KEY before forwarding to MCP."""

    async def middleware(scope, receive, send):
        if scope["type"] == "http":
            # Extract Authorization header
            headers = dict(scope.get("headers", []))
            auth_value = headers.get(b"authorization", b"").decode()
            token = ""
            if auth_value.startswith("Bearer "):
                token = auth_value[7:].strip()
            elif auth_value:
                token = auth_value.strip()

            if not tina4_python.tina4_auth.valid(token):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"www-authenticate", b"Bearer"],
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": json.dumps({
                        "jsonrpc": "2.0",
                        "error": {"code": -32000, "message": "Unauthorized — provide Authorization: Bearer <API_KEY>"}
                    }).encode(),
                })
                return

        await asgi_app(scope, receive, send)

    return middleware


# ---------------------------------------------------------------------------
# Category A: Diagnostic Tools (TINA4_MCP_LOGS)
# ---------------------------------------------------------------------------

def _register_diagnostic_tools(mcp, root_path: str):

    @mcp.tool()
    def get_logs(lines: int = 100, level: str = "", search: str = "") -> dict:
        """Read recent entries from the application debug log.

        Args:
            lines: Number of lines to return from the tail (default 100).
            level: Filter by log level — DEBUG, INFO, WARNING, ERROR.
            search: Filter lines containing this substring.
        """
        _require_perm("LOGS", "get_logs")
        log_file = Path(root_path) / "logs" / "debug.log"
        if not log_file.exists():
            return {"lines": [], "total": 0, "file": str(log_file)}

        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            return {"error": str(e)}

        # Filter by level
        if level:
            level_upper = level.upper()
            all_lines = [l for l in all_lines if level_upper in l]

        # Filter by search
        if search:
            all_lines = [l for l in all_lines if search in l]

        # Tail
        total = len(all_lines)
        result_lines = all_lines[-lines:] if lines < total else all_lines

        return {"lines": result_lines, "total": total, "file": str(log_file)}

    @mcp.tool()
    def get_server_info() -> dict:
        """Get current server status and configuration."""
        _require_perm("LOGS", "get_server_info")
        return {
            "version": os.getenv("VERSION", "unknown"),
            "project_name": os.getenv("PROJECT_NAME", "unknown"),
            "debug_level": os.getenv("TINA4_DEBUG_LEVEL", "unknown"),
            "dev_mode": _is_dev,
            "python_version": sys.version,
            "root_path": str(root_path),
            "uptime_seconds": round(time.time() - _server_start_time, 1),
            "route_count": len(tina4_python.tina4_routes),
            "mcp_permissions": {
                "LOGS": _perm("LOGS"),
                "FILES_READ": _perm("FILES_READ"),
                "FILES_WRITE": _perm("FILES_WRITE"),
                "CODE_WRITE": _perm("CODE_WRITE"),
                "DB_READ": _perm("DB_READ"),
                "DB_WRITE": _perm("DB_WRITE"),
                "QUEUE": _perm("QUEUE"),
            },
        }

    @mcp.tool()
    def list_routes(method: str = "", search: str = "") -> dict:
        """List all registered routes with their methods, auth, and handler info.

        Args:
            method: Filter by HTTP method (GET, POST, etc.).
            search: Filter by path substring.
        """
        _require_perm("LOGS", "list_routes")
        routes = []
        for cb, data in tina4_python.tina4_routes.items():
            for route_path in data.get("routes", []):
                for meth in data.get("methods", []):
                    if method and meth.upper() != method.upper():
                        continue
                    if search and search.lower() not in route_path.lower():
                        continue

                    handler_file = ""
                    handler_line = 0
                    try:
                        handler_file = inspect.getfile(cb)
                        handler_line = inspect.getsourcelines(cb)[1]
                    except (TypeError, OSError):
                        pass

                    routes.append({
                        "path": route_path,
                        "method": meth,
                        "handler_name": getattr(cb, "__name__", str(cb)),
                        "handler_file": handler_file,
                        "handler_line": handler_line,
                        "secure": data.get("secure", False),
                        "noauth": data.get("noauth", False),
                        "has_swagger": data.get("swagger") is not None,
                        "cached": data.get("cached", False),
                    })

        return {"routes": routes, "count": len(routes)}

    @mcp.tool()
    def get_env(keys: list = None) -> dict:
        """Read environment variables (sensitive values are redacted).

        Args:
            keys: Specific keys to read. If omitted, returns all safe variables.
        """
        _require_perm("LOGS", "get_env")
        result = {}
        source = os.environ

        if keys:
            source = {k: os.environ.get(k, "") for k in keys}

        for key, value in source.items():
            # Skip internal Python/system vars
            if key.startswith("_") or key.startswith("VIRTUAL_ENV"):
                continue
            # Redact sensitive values
            if _SENSITIVE_PATTERN.search(key):
                if key == "API_KEY" and value:
                    result[key] = value[:8] + "..." if len(value) > 8 else "***"
                else:
                    result[key] = "***REDACTED***"
            else:
                result[key] = value

        return {"variables": result}

    @mcp.tool()
    def get_swagger_spec() -> dict:
        """Return the full OpenAPI 3.0 JSON specification for this application."""
        _require_perm("LOGS", "get_swagger_spec")
        from tina4_python.Swagger import Swagger

        class _FakeRequest:
            def __init__(self):
                self.headers = {
                    "host": os.getenv("HOST_NAME", "localhost:7145"),
                    "x-forwarded-proto": "http",
                }

        return Swagger.get_json(_FakeRequest())


# ---------------------------------------------------------------------------
# Category B: File Reading Tools (TINA4_MCP_FILES_READ)
# ---------------------------------------------------------------------------

def _register_file_read_tools(mcp, root_path: str):

    @mcp.tool()
    def read_file(path: str, offset: int = 0, limit: int = 0) -> dict:
        """Read the contents of a project file.

        Args:
            path: Relative path from project root (e.g. 'src/routes/users.py').
            offset: Line number to start from (0-based).
            limit: Max lines to return (0 = all).
        """
        _require_perm("FILES_READ", "read_file")
        resolved = _check_readable(path)

        if not resolved.exists():
            return {"error": f"File not found: {path}"}
        if not resolved.is_file():
            return {"error": f"Not a file: {path}"}
        if resolved.stat().st_size > _MAX_READ_BYTES:
            return {"error": f"File too large ({resolved.stat().st_size} bytes, max {_MAX_READ_BYTES})"}

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": str(e)}

        lines = content.splitlines(keepends=True)
        total = len(lines)

        if offset > 0:
            lines = lines[offset:]
        if limit > 0:
            lines = lines[:limit]

        return {
            "path": path,
            "content": "".join(lines),
            "total_lines": total,
            "offset": offset,
            "lines_returned": len(lines),
        }

    @mcp.tool()
    def list_directory(path: str = "src", recursive: bool = False, pattern: str = "") -> dict:
        """List files and directories at a given path.

        Args:
            path: Relative path from project root (default 'src').
            recursive: Include subdirectories recursively.
            pattern: Glob pattern to filter (e.g. '*.py', '*.twig').
        """
        _require_perm("FILES_READ", "list_directory")
        resolved = _check_readable(path)

        if not resolved.exists():
            return {"error": f"Directory not found: {path}"}
        if not resolved.is_dir():
            return {"error": f"Not a directory: {path}"}

        entries = []
        root = _get_root()

        if recursive:
            items = sorted(resolved.rglob("*"))
        else:
            items = sorted(resolved.iterdir())

        for item in items:
            # Skip blocked dirs
            rel = item.relative_to(root)
            parts = rel.parts
            if any(p in _BLOCKED_DIRS or p.startswith(".") for p in parts):
                continue

            if pattern and not fnmatch.fnmatch(item.name, pattern):
                continue

            try:
                stat = item.stat()
                entries.append({
                    "name": str(rel).replace("\\", "/"),
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
            except OSError:
                continue

        return {"path": path, "entries": entries, "count": len(entries)}

    @mcp.tool()
    def search_files(pattern: str, path: str = "src", file_pattern: str = "", max_results: int = 50) -> dict:
        """Search for a text pattern across project files (like grep).

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search in (default 'src').
            file_pattern: Glob filter for filenames (e.g. '*.py').
            max_results: Maximum matches to return (default 50).
        """
        _require_perm("FILES_READ", "search_files")
        resolved = _check_readable(path)

        if not resolved.exists() or not resolved.is_dir():
            return {"error": f"Directory not found: {path}"}

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        matches = []
        root = _get_root()
        truncated = False

        for file_path in sorted(resolved.rglob("*")):
            if not file_path.is_file():
                continue

            # Skip blocked
            rel = file_path.relative_to(root)
            if any(p in _BLOCKED_DIRS or p.startswith(".") for p in rel.parts):
                continue

            # Apply file pattern filter
            if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
                continue

            # Skip binary files
            if file_path.stat().st_size > _MAX_READ_BYTES:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append({
                        "file": str(rel).replace("\\", "/"),
                        "line": line_num,
                        "content": line.rstrip()[:200],  # Limit line length
                    })
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if truncated:
                break

        return {"matches": matches, "total": len(matches), "truncated": truncated}

    @mcp.tool()
    def get_project_structure(max_depth: int = 4) -> dict:
        """Return the full project directory tree.

        Args:
            max_depth: Maximum directory depth (default 4).
        """
        _require_perm("FILES_READ", "get_project_structure")
        root = _get_root()

        def _walk(dir_path: Path, depth: int) -> dict:
            name = dir_path.name or str(dir_path)
            node = {"name": name, "type": "dir", "children": []}

            if depth >= max_depth:
                return node

            try:
                items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return node

            for item in items:
                # Skip blocked
                if item.name in _BLOCKED_DIRS or item.name.startswith("."):
                    continue
                if item.name == "__pycache__":
                    continue

                if item.is_dir():
                    node["children"].append(_walk(item, depth + 1))
                else:
                    node["children"].append({
                        "name": item.name,
                        "type": "file",
                        "size": item.stat().st_size,
                    })

            return node

        return _walk(root, 0)

    @mcp.tool()
    def get_route_handler(path: str, method: str = "GET") -> dict:
        """Get the full source code of a specific route handler.

        Args:
            path: The URL path of the route (e.g. '/api/users').
            method: HTTP method (default 'GET').
        """
        _require_perm("FILES_READ", "get_route_handler")
        method_upper = method.upper()

        for cb, data in tina4_python.tina4_routes.items():
            routes = data.get("routes", [])
            methods = data.get("methods", [])

            if method_upper not in methods:
                continue

            for route in routes:
                if route.rstrip("/") == path.rstrip("/"):
                    try:
                        source = inspect.getsource(cb)
                        file_path = inspect.getfile(cb)
                        line = inspect.getsourcelines(cb)[1]
                    except (TypeError, OSError) as e:
                        return {"error": f"Cannot inspect handler: {e}"}

                    return {
                        "handler_name": cb.__name__,
                        "file": file_path,
                        "line": line,
                        "source": source,
                        "methods": methods,
                        "routes": routes,
                    }

        return {"error": f"No route found for {method} {path}"}

    @mcp.tool()
    def list_orm_models() -> dict:
        """List all ORM models with their fields, table names, and source files."""
        _require_perm("FILES_READ", "list_orm_models")
        from tina4_python.ORM import ORM

        models = []

        def _collect(cls):
            for sub in cls.__subclasses__():
                info = {"class_name": sub.__name__, "fields": [], "file": "", "table_name": ""}

                try:
                    info["file"] = inspect.getfile(sub)
                except (TypeError, OSError):
                    pass

                # Try to get table name
                if hasattr(sub, "__table_name__"):
                    info["table_name"] = sub.__table_name__
                elif hasattr(sub, "table_name"):
                    info["table_name"] = sub.table_name

                # Collect fields from class annotations or attributes
                annotations = getattr(sub, "__annotations__", {})
                for field_name, field_type in annotations.items():
                    if not field_name.startswith("_"):
                        info["fields"].append({
                            "name": field_name,
                            "type": str(field_type),
                        })

                models.append(info)
                _collect(sub)  # Recurse for subclasses of subclasses

        _collect(ORM)
        return {"models": models, "count": len(models)}


# ---------------------------------------------------------------------------
# Category C/D: File Write Tools (TINA4_MCP_FILES_WRITE / TINA4_MCP_CODE_WRITE)
# ---------------------------------------------------------------------------

def _register_file_write_tools(mcp, root_path: str):

    @mcp.tool()
    def write_file(path: str, content: str, create_directories: bool = True) -> dict:
        """Write or overwrite a file in the project.

        Writable directories depend on permissions:
        - FILES_WRITE: src/templates/, src/public/, src/scss/, migrations/
        - CODE_WRITE: additionally src/routes/, src/app/, src/orm/

        Args:
            path: Relative path from project root.
            content: Full file content to write.
            create_directories: Create parent dirs if missing (default true).
        """
        _require_perm("FILES_WRITE", "write_file")
        resolved = _check_writable(path)

        if create_directories:
            resolved.parent.mkdir(parents=True, exist_ok=True)

        created = not resolved.exists()
        resolved.write_text(content, encoding="utf-8")

        return {
            "path": path,
            "bytes_written": len(content.encode("utf-8")),
            "created": created,
        }

    @mcp.tool()
    def edit_file(path: str, start_line: int, end_line: int, new_content: str) -> dict:
        """Apply a targeted edit to a file (replace a range of lines).

        Args:
            path: Relative path from project root.
            start_line: First line to replace (1-based).
            end_line: Last line to replace (inclusive, 1-based).
            new_content: Replacement text for those lines.
        """
        _require_perm("FILES_WRITE", "edit_file")
        resolved = _check_writable(path)

        if not resolved.exists():
            return {"error": f"File not found: {path}"}

        lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
        total = len(lines)

        if start_line < 1 or end_line < start_line or start_line > total:
            return {"error": f"Invalid line range: {start_line}-{end_line} (file has {total} lines)"}

        # Replace the range (1-based inclusive → 0-based slice)
        new_lines = new_content.splitlines(keepends=True)
        if new_content and not new_content.endswith("\n"):
            # Ensure trailing newline on last replacement line
            if new_lines:
                new_lines[-1] = new_lines[-1] + "\n"

        end = min(end_line, total)
        lines[start_line - 1:end] = new_lines

        resolved.write_text("".join(lines), encoding="utf-8")

        return {
            "path": path,
            "lines_replaced": end - start_line + 1,
            "new_total_lines": len(lines),
        }

    @mcp.tool()
    def delete_file(path: str) -> dict:
        """Delete a file from the project.

        Args:
            path: Relative path from project root.
        """
        _require_perm("FILES_WRITE", "delete_file")
        resolved = _check_writable(path)

        if not resolved.exists():
            return {"error": f"File not found: {path}"}
        if resolved.is_dir():
            return {"error": "Cannot delete directories — only files"}
        if resolved.name == "__init__.py":
            return {"error": "Cannot delete __init__.py files"}

        resolved.unlink()
        return {"path": path, "deleted": True}

    @mcp.tool()
    def rename_file(old_path: str, new_path: str) -> dict:
        """Rename or move a file within the project.

        Args:
            old_path: Current relative path.
            new_path: New relative path.
        """
        _require_perm("FILES_WRITE", "rename_file")
        resolved_old = _check_writable(old_path)
        resolved_new = _check_writable(new_path)

        if not resolved_old.exists():
            return {"error": f"File not found: {old_path}"}
        if resolved_new.exists():
            return {"error": f"Destination already exists: {new_path}"}

        resolved_new.parent.mkdir(parents=True, exist_ok=True)
        resolved_old.rename(resolved_new)

        return {"old_path": old_path, "new_path": new_path, "renamed": True}


# ---------------------------------------------------------------------------
# Category E: Template Tools (TINA4_MCP_FILES_READ)
# ---------------------------------------------------------------------------

def _register_template_tools(mcp, root_path: str):

    @mcp.tool()
    def render_template(template: str, data: dict = None) -> dict:
        """Render a Twig template with given data and return the HTML output.

        Args:
            template: Template file path relative to src/templates/.
            data: Template variables (default empty dict).
        """
        _require_perm("FILES_READ", "render_template")
        from tina4_python.Template import Template

        if data is None:
            data = {}

        try:
            html = Template.render_twig_template(template, data)
            return {"html": html, "template": template}
        except Exception as e:
            return {"error": str(e), "template": template}

    @mcp.tool()
    def list_templates() -> dict:
        """List all template files with their inheritance structure."""
        _require_perm("FILES_READ", "list_templates")
        templates_dir = Path(root_path) / "src" / "templates"

        if not templates_dir.exists():
            return {"templates": [], "count": 0}

        templates = []
        extends_re = re.compile(r'{%\s*extends\s+["\']([^"\']+)["\']\s*%}')
        block_re = re.compile(r'{%\s*block\s+(\w+)')
        include_re = re.compile(r'{%\s*include\s+["\']([^"\']+)["\']\s*%}')

        for tpl_file in sorted(templates_dir.rglob("*.twig")):
            rel = tpl_file.relative_to(templates_dir)
            try:
                content = tpl_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            extends_match = extends_re.search(content)
            blocks = block_re.findall(content)
            includes = include_re.findall(content)

            templates.append({
                "path": str(rel).replace("\\", "/"),
                "extends": extends_match.group(1) if extends_match else None,
                "blocks": blocks,
                "includes": includes,
            })

        return {"templates": templates, "count": len(templates)}

    @mcp.tool()
    def get_template_info(template: str) -> dict:
        """Get detailed information about a specific template.

        Args:
            template: Template file path relative to src/templates/.
        """
        _require_perm("FILES_READ", "get_template_info")
        tpl_path = Path(root_path) / "src" / "templates" / template

        if not tpl_path.exists():
            return {"error": f"Template not found: {template}"}

        try:
            content = tpl_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": str(e)}

        extends_re = re.compile(r'{%\s*extends\s+["\']([^"\']+)["\']\s*%}')
        block_re = re.compile(r'{%\s*block\s+(\w+)')
        include_re = re.compile(r'{%\s*include\s+["\']([^"\']+)["\']\s*%}')
        var_re = re.compile(r'{{\s*(\w+)')
        filter_re = re.compile(r'\|\s*(\w+)')

        extends_match = extends_re.search(content)

        return {
            "path": template,
            "extends": extends_match.group(1) if extends_match else None,
            "blocks": block_re.findall(content),
            "includes": include_re.findall(content),
            "variables_used": list(set(var_re.findall(content))),
            "filters_used": list(set(filter_re.findall(content))),
            "content": content,
            "lines": len(content.splitlines()),
        }


# ---------------------------------------------------------------------------
# Category F: Database Tools (TINA4_MCP_DB_READ / TINA4_MCP_DB_WRITE)
# ---------------------------------------------------------------------------

def _register_db_tools(mcp, root_path: str):

    def _get_db():
        """Try to find the active Database instance."""
        from tina4_python.ORM import ORM
        if hasattr(ORM, '_db') and ORM._db is not None:
            return ORM._db
        # Check if a Database was instantiated via tina4_python globals
        if hasattr(tina4_python, 'tina4_database'):
            return tina4_python.tina4_database
        return None

    @mcp.tool()
    def db_query(sql: str, params: list = None, limit: int = 50) -> dict:
        """Execute a read-only SQL query against the application database.

        Only SELECT statements are allowed.

        Args:
            sql: SQL SELECT query.
            params: Bound parameters (default empty).
            limit: Max rows to return (default 50).
        """
        _require_perm("DB_READ", "db_query")
        if params is None:
            params = []

        # Safety: only allow SELECT
        clean = sql.strip().upper()
        if not clean.startswith("SELECT") and not clean.startswith("WITH"):
            return {"error": "Only SELECT queries are allowed. Use db_execute for writes."}

        # Block dangerous keywords even in subqueries
        for blocked in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"):
            if blocked in clean:
                return {"error": f"Blocked keyword '{blocked}' in query."}

        db = _get_db()
        if db is None:
            return {"error": "No database connection available."}

        try:
            result = db.execute(sql, params)
            records = []
            if hasattr(result, 'records') and result.records:
                for row in result.records[:limit]:
                    if hasattr(row, '__dict__'):
                        records.append({k: v for k, v in row.__dict__.items() if not k.startswith('_')})
                    elif isinstance(row, dict):
                        records.append(row)
                    else:
                        records.append(str(row))

            fields = []
            if hasattr(result, 'fields'):
                fields = result.fields

            return {
                "records": records,
                "fields": fields,
                "count": len(records),
                "truncated": hasattr(result, 'records') and result.records and len(result.records) > limit,
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def db_tables() -> dict:
        """List all database tables with their column definitions."""
        _require_perm("DB_READ", "db_tables")
        db = _get_db()
        if db is None:
            return {"error": "No database connection available."}

        try:
            # Try SQLite first
            result = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = []
            if hasattr(result, 'records') and result.records:
                for row in result.records:
                    table_name = row.get("name", "") if isinstance(row, dict) else str(row)
                    if table_name.startswith("sqlite_"):
                        continue
                    col_result = db.execute(f"PRAGMA table_info({table_name})")
                    columns = []
                    if hasattr(col_result, 'records') and col_result.records:
                        for col in col_result.records:
                            if isinstance(col, dict):
                                columns.append({
                                    "name": col.get("name", ""),
                                    "type": col.get("type", ""),
                                    "nullable": not col.get("notnull", False),
                                    "primary_key": bool(col.get("pk", 0)),
                                })
                    tables.append({"name": table_name, "columns": columns})
            return {"tables": tables, "count": len(tables)}
        except Exception:
            # Fallback for other databases
            try:
                result = db.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = []
                if hasattr(result, 'records') and result.records:
                    for row in result.records:
                        table_name = row.get("table_name", "") if isinstance(row, dict) else str(row)
                        tables.append({"name": table_name, "columns": []})
                return {"tables": tables, "count": len(tables)}
            except Exception as e:
                return {"error": str(e)}

    @mcp.tool()
    def db_execute(sql: str, params: list = None, confirm: bool = False) -> dict:
        """Execute a write SQL statement (INSERT, UPDATE, DELETE).

        Blocks DROP, ALTER, TRUNCATE for safety.

        Args:
            sql: SQL statement.
            params: Bound parameters.
            confirm: Must be true to execute — forces acknowledgment of the write.
        """
        _require_perm("DB_WRITE", "db_execute")
        if params is None:
            params = []

        if not confirm:
            return {"error": "Set confirm=true to execute write operations."}

        clean = sql.strip().upper()
        for blocked in ("DROP", "ALTER", "TRUNCATE"):
            if clean.startswith(blocked):
                return {"error": f"Blocked: {blocked} statements are not allowed."}

        db = _get_db()
        if db is None:
            return {"error": "No database connection available."}

        try:
            result = db.execute(sql, params)
            return {
                "success": True,
                "rows_affected": getattr(result, 'count', 0) if result else 0,
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def run_migration(dry_run: bool = True) -> dict:
        """Run pending database migrations.

        Args:
            dry_run: If true, list pending migrations without executing (default true).
        """
        _require_perm("DB_WRITE", "run_migration")
        migrations_dir = Path(root_path) / "migrations"

        if not migrations_dir.exists():
            return {"error": "No migrations directory found."}

        pending = sorted(f.name for f in migrations_dir.glob("*.sql"))

        if dry_run:
            return {"pending": pending, "executed": [], "dry_run": True}

        # Execute migrations
        db = _get_db()
        if db is None:
            return {"error": "No database connection available."}

        executed = []
        errors = []
        for migration_file in pending:
            try:
                sql = (migrations_dir / migration_file).read_text(encoding="utf-8")
                db.execute(sql)
                executed.append(migration_file)
            except Exception as e:
                errors.append({"file": migration_file, "error": str(e)})
                break  # Stop on first error

        return {
            "pending": [f for f in pending if f not in executed],
            "executed": executed,
            "errors": errors,
            "dry_run": False,
        }


# ---------------------------------------------------------------------------
# Category G: Project Operations
# ---------------------------------------------------------------------------

def _register_project_tools(mcp, root_path: str):

    @mcp.tool()
    def compile_scss() -> dict:
        """Trigger SCSS compilation manually."""
        _require_perm("FILES_WRITE", "compile_scss")
        # Call the compile_scss function from __init__
        try:
            tina4_python.compile_scss()
            return {"success": True, "message": "SCSS compilation triggered"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def trigger_reload(type: str = "reload") -> dict:
        """Send a reload notification to all connected browser clients.

        Only works in dev mode.

        Args:
            type: Either 'reload' (full page) or 'css-reload' (stylesheet only).
        """
        _require_perm("LOGS", "trigger_reload")
        if not _is_dev:
            return {"error": "trigger_reload only works in debug/dev mode"}

        try:
            from tina4_python.DevReload import _notify_clients
            _notify_clients(type)
            return {"type": type, "success": True}
        except ImportError:
            return {"error": "DevReload not available"}
        except Exception as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Category H: Queue Tools (TINA4_MCP_QUEUE)
# ---------------------------------------------------------------------------

def _register_queue_tools(mcp, root_path: str):

    @mcp.tool()
    def queue_produce(topic: str, data: dict, user_id: str = "") -> dict:
        """Send a message to a named queue.

        Args:
            topic: Queue topic name.
            data: Message payload.
            user_id: Optional producer user ID.
        """
        _require_perm("QUEUE", "queue_produce")
        try:
            from tina4_python.Queue import Queue
            queue = Queue(topic=topic, user_id=user_id)
            result = queue.produce(data)
            return {"topic": topic, "success": True, "result": str(result)}
        except ImportError:
            return {"error": "Queue module not available."}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def queue_peek(topic: str, limit: int = 10) -> dict:
        """Peek at messages in a queue without consuming them.

        Args:
            topic: Queue topic name.
            limit: Max messages to peek (default 10).
        """
        _require_perm("QUEUE", "queue_peek")
        try:
            from tina4_python.Queue import Queue
            queue = Queue(topic=topic)
            messages = []
            for _ in range(limit):
                msg = queue.consume(acknowledge=False)
                if msg is None:
                    break
                messages.append(str(msg))
            return {"topic": topic, "messages": messages, "count": len(messages)}
        except ImportError:
            return {"error": "Queue module not available."}
        except Exception as e:
            return {"error": str(e)}
