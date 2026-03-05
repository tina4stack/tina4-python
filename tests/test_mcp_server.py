#
# Tina4 - This is not a framework.
# Copyright 2007 - present Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# Comprehensive test suite for the built-in MCP server
#

import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import tina4_python
from tina4_python.McpServer import (
    _perm, _require_perm, _resolve_path, _check_readable, _check_writable,
    _get_root, _CONTENT_WRITE_DIRS, _CODE_WRITE_DIRS, _BLOCKED_DIRS,
    create_mcp_server, get_mcp_asgi_app, mcp_auth_middleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _save_env(monkeypatch):
    """Ensure env vars are restored after each test."""
    yield


@pytest.fixture
def root_path():
    return tina4_python.root_path


# ---------------------------------------------------------------------------
# Permission system
# ---------------------------------------------------------------------------

class TestPermissions:

    def test_dev_mode_defaults_true(self, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG_LEVEL", "ALL")
        monkeypatch.delenv("TINA4_MCP_LOGS", raising=False)
        # Since _is_dev is computed at import time, we test _perm directly
        # by patching the module-level flag
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = True
        try:
            assert _perm("LOGS") is True
            assert _perm("FILES_READ") is True
            assert _perm("CODE_WRITE") is True
        finally:
            mcp_mod._is_dev = orig

    def test_prod_mode_defaults_false(self, monkeypatch):
        monkeypatch.delenv("TINA4_MCP_LOGS", raising=False)
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            assert _perm("LOGS") is False
            assert _perm("FILES_WRITE") is False
        finally:
            mcp_mod._is_dev = orig

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_LOGS", "true")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            assert _perm("LOGS") is True
        finally:
            mcp_mod._is_dev = orig

    def test_explicit_false(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_LOGS", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = True
        try:
            assert _perm("LOGS") is False
        finally:
            mcp_mod._is_dev = orig

    def test_require_perm_raises(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_LOGS", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            with pytest.raises(PermissionError, match="TINA4_MCP_LOGS"):
                _require_perm("LOGS", "get_logs")
        finally:
            mcp_mod._is_dev = orig

    def test_require_perm_passes(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_LOGS", "true")
        _require_perm("LOGS", "get_logs")  # Should not raise


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

class TestPathSafety:

    def test_resolve_normal_path(self):
        resolved = _resolve_path("src/routes/test.py")
        assert str(resolved).endswith("src/routes/test.py")

    def test_block_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_path("../../etc/passwd")

    def test_block_secrets(self):
        with pytest.raises(ValueError, match="denied"):
            _resolve_path("secrets/private.key")

    def test_block_git(self):
        with pytest.raises(ValueError, match="denied"):
            _resolve_path(".git/config")

    def test_block_dotfiles(self):
        with pytest.raises(ValueError, match="denied"):
            _resolve_path(".env")

    def test_block_tina4_framework(self):
        with pytest.raises(ValueError, match="denied"):
            _resolve_path("tina4_python/Router.py")

    def test_block_pycache(self):
        with pytest.raises(ValueError, match="denied"):
            _resolve_path("__pycache__/foo.pyc")

    def test_readable_src(self):
        resolved = _check_readable("src/routes/test.py")
        assert "src/routes/test.py" in str(resolved)

    def test_readable_app_py(self):
        resolved = _check_readable("app.py")
        assert "app.py" in str(resolved)

    def test_readable_pyproject(self):
        resolved = _check_readable("pyproject.toml")
        assert "pyproject.toml" in str(resolved)

    def test_readable_logs(self):
        resolved = _check_readable("logs/debug.log")
        assert "logs/debug.log" in str(resolved)

    def test_unreadable_secrets(self):
        with pytest.raises(ValueError):
            _check_readable("secrets/private.key")

    def test_writable_templates(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_CODE_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            resolved = _check_writable("src/templates/test.twig")
            assert "src/templates/test.twig" in str(resolved)
        finally:
            mcp_mod._is_dev = orig

    def test_writable_public(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_CODE_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            resolved = _check_writable("src/public/css/style.css")
            assert "src/public/css/style.css" in str(resolved)
        finally:
            mcp_mod._is_dev = orig

    def test_code_dir_blocked_without_code_write(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_CODE_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            with pytest.raises(ValueError, match="Write access denied"):
                _check_writable("src/routes/users.py")
        finally:
            mcp_mod._is_dev = orig

    def test_code_dir_allowed_with_code_write(self, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_CODE_WRITE", "true")
        resolved = _check_writable("src/routes/users.py")
        assert "src/routes/users.py" in str(resolved)

    def test_writable_rejects_framework_code(self):
        with pytest.raises(ValueError):
            _check_writable("tina4_python/Router.py")

    def test_writable_rejects_env(self):
        with pytest.raises(ValueError):
            _check_writable(".env")


# ---------------------------------------------------------------------------
# MCP Server creation
# ---------------------------------------------------------------------------

class TestMcpServerCreation:

    def test_create_server_returns_fastmcp(self, root_path):
        from mcp.server.fastmcp import FastMCP
        server = create_mcp_server(root_path)
        assert isinstance(server, FastMCP)

    def test_get_asgi_app_is_callable(self, root_path):
        server = create_mcp_server(root_path)
        asgi_app = get_mcp_asgi_app(server)
        assert callable(asgi_app)

    def test_auth_middleware_wraps_app(self, root_path):
        server = create_mcp_server(root_path)
        asgi_app = get_mcp_asgi_app(server)
        wrapped = mcp_auth_middleware(asgi_app)
        assert callable(wrapped)
        assert wrapped is not asgi_app


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class TestAuthMiddleware:

    @pytest.mark.asyncio
    async def test_rejects_no_auth(self, root_path):
        """Request without Authorization header should get 401."""
        server = create_mcp_server(root_path)
        asgi_app = get_mcp_asgi_app(server)
        wrapped = mcp_auth_middleware(asgi_app)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [],
            "query_string": b"",
        }

        responses = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            responses.append(message)

        await wrapped(scope, receive, send)

        assert len(responses) >= 1
        assert responses[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_rejects_wrong_key(self, root_path, monkeypatch):
        """Request with wrong API key should get 401."""
        monkeypatch.setenv("API_KEY", "correct_key_12345")

        server = create_mcp_server(root_path)
        asgi_app = get_mcp_asgi_app(server)
        wrapped = mcp_auth_middleware(asgi_app)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [[b"authorization", b"Bearer wrong_key"]],
            "query_string": b"",
        }

        responses = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            responses.append(message)

        await wrapped(scope, receive, send)

        assert responses[0]["status"] == 401


# ---------------------------------------------------------------------------
# Diagnostic Tools
# ---------------------------------------------------------------------------

class TestDiagnosticTools:

    def setup_method(self):
        """Enable all permissions for tool tests."""
        os.environ["TINA4_MCP_LOGS"] = "true"

    def test_get_server_info(self, root_path):
        server = create_mcp_server(root_path)
        # Find and call the tool directly
        from tina4_python.McpServer import _register_diagnostic_tools
        # Use mcp tool registry to test
        info = None
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "get_server_info":
                info = tool_func.fn()
                break
        assert info is not None
        assert "version" in info
        assert "python_version" in info
        assert "uptime_seconds" in info
        assert "mcp_permissions" in info
        assert "route_count" in info

    def test_list_routes(self, root_path):
        server = create_mcp_server(root_path)
        result = None
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "list_routes":
                result = tool_func.fn()
                break
        assert result is not None
        assert "routes" in result
        assert "count" in result
        # The swagger routes should be registered
        assert result["count"] > 0

    def test_list_routes_filter_by_method(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "list_routes":
                result = tool_func.fn(method="GET")
                break
        for route in result["routes"]:
            assert route["method"] == "GET"

    def test_get_env(self, root_path, monkeypatch):
        monkeypatch.setenv("PROJECT_NAME", "TestProject")
        monkeypatch.setenv("API_KEY", "abcdef1234567890")

        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "get_env":
                result = tool_func.fn()
                break
        assert "variables" in result
        assert result["variables"]["PROJECT_NAME"] == "TestProject"
        # API_KEY should be redacted
        assert "abcdef12..." == result["variables"]["API_KEY"]

    def test_get_env_redacts_secrets(self, root_path, monkeypatch):
        monkeypatch.setenv("SECRET", "super_secret_value")
        monkeypatch.setenv("DATABASE_PASSWORD", "db_pass_123")

        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "get_env":
                result = tool_func.fn()
                break

        assert result["variables"]["SECRET"] == "***REDACTED***"
        assert result["variables"]["DATABASE_PASSWORD"] == "***REDACTED***"

    def test_get_swagger_spec(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "get_swagger_spec":
                result = tool_func.fn()
                break
        assert result["openapi"] == "3.0.3"
        assert "paths" in result
        assert "info" in result


# ---------------------------------------------------------------------------
# File Read Tools
# ---------------------------------------------------------------------------

class TestFileReadTools:

    def setup_method(self):
        os.environ["TINA4_MCP_FILES_READ"] = "true"

    def test_read_file_exists(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "read_file":
                result = tool_func.fn(path="pyproject.toml")
                break
        assert "content" in result
        assert "tina4-python" in result["content"]
        assert result["total_lines"] > 0

    def test_read_file_not_found(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "read_file":
                result = tool_func.fn(path="src/nonexistent.py")
                break
        assert "error" in result

    def test_read_file_with_offset_limit(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "read_file":
                result = tool_func.fn(path="pyproject.toml", offset=0, limit=3)
                break
        assert result["lines_returned"] == 3

    def test_list_directory(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "list_directory":
                result = tool_func.fn(path="src")
                break
        assert "entries" in result
        assert result["count"] > 0

    def test_list_directory_with_pattern(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "list_directory":
                result = tool_func.fn(path="src", recursive=True, pattern="*.py")
                break
        for entry in result["entries"]:
            assert entry["name"].endswith(".py") or entry["type"] == "dir"

    def test_search_files(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "search_files":
                result = tool_func.fn(pattern="def ", path="src", file_pattern="*.py", max_results=5)
                break
        assert "matches" in result
        # Should find at least some function definitions

    def test_get_project_structure(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "get_project_structure":
                result = tool_func.fn(max_depth=2)
                break
        assert result["type"] == "dir"
        assert "children" in result
        # Should have src as a child
        child_names = [c["name"] for c in result["children"]]
        assert "src" in child_names

    def test_list_orm_models(self, root_path):
        server = create_mcp_server(root_path)
        for tool_name, tool_func in server._tool_manager._tools.items():
            if tool_name == "list_orm_models":
                result = tool_func.fn()
                break
        assert "models" in result
        assert "count" in result


# ---------------------------------------------------------------------------
# File Write Tools
# ---------------------------------------------------------------------------

class TestFileWriteTools:

    def setup_method(self):
        os.environ["TINA4_MCP_FILES_WRITE"] = "true"
        os.environ["TINA4_MCP_FILES_READ"] = "true"
        os.environ["TINA4_MCP_CODE_WRITE"] = "true"

    def test_write_and_read_file(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}

        test_path = "src/templates/mcp_test_write.twig"
        test_content = "<h1>MCP Test</h1>\n<p>{{ message }}</p>\n"

        # Write
        result = tools["write_file"].fn(path=test_path, content=test_content)
        assert result["created"] is True
        assert result["bytes_written"] > 0

        # Read back
        read_result = tools["read_file"].fn(path=test_path)
        assert read_result["content"] == test_content

        # Cleanup
        tools["delete_file"].fn(path=test_path)

    def test_edit_file(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}

        test_path = "src/templates/mcp_test_edit.twig"
        original = "line1\nline2\nline3\nline4\n"

        # Write original
        tools["write_file"].fn(path=test_path, content=original)

        # Edit lines 2-3
        result = tools["edit_file"].fn(path=test_path, start_line=2, end_line=3, new_content="replaced2\nreplaced3")
        assert result["lines_replaced"] == 2

        # Read and verify
        read_result = tools["read_file"].fn(path=test_path)
        assert "replaced2" in read_result["content"]
        assert "replaced3" in read_result["content"]
        assert "line1" in read_result["content"]
        assert "line4" in read_result["content"]

        # Cleanup
        tools["delete_file"].fn(path=test_path)

    def test_delete_file(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}

        test_path = "src/templates/mcp_test_delete.twig"
        tools["write_file"].fn(path=test_path, content="temp")

        result = tools["delete_file"].fn(path=test_path)
        assert result["deleted"] is True

        # Verify gone
        read_result = tools["read_file"].fn(path=test_path)
        assert "error" in read_result

    def test_rename_file(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}

        old_path = "src/templates/mcp_test_rename_old.twig"
        new_path = "src/templates/mcp_test_rename_new.twig"
        tools["write_file"].fn(path=old_path, content="rename test")

        result = tools["rename_file"].fn(old_path=old_path, new_path=new_path)
        assert result["renamed"] is True

        # Old gone, new exists
        assert "error" in tools["read_file"].fn(path=old_path)
        read_new = tools["read_file"].fn(path=new_path)
        assert "rename test" in read_new["content"]

        # Cleanup
        tools["delete_file"].fn(path=new_path)

    def test_write_to_code_dir_rejected_without_permission(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_CODE_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(ValueError, match="Write access denied"):
                tools["write_file"].fn(path="src/routes/hack.py", content="# evil")
        finally:
            mcp_mod._is_dev = orig

    def test_cannot_delete_init_py(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["delete_file"].fn(path="src/templates/__init__.py")
        # Should either error (not found or blocked)
        assert "error" in result


# ---------------------------------------------------------------------------
# Template Tools
# ---------------------------------------------------------------------------

class TestTemplateTools:

    def setup_method(self):
        os.environ["TINA4_MCP_FILES_READ"] = "true"

    def test_list_templates(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["list_templates"].fn()
        assert "templates" in result
        assert "count" in result

    def test_get_template_info(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}

        # First, list to find an available template
        templates = tools["list_templates"].fn()
        if templates["count"] > 0:
            tpl_name = templates["templates"][0]["path"]
            result = tools["get_template_info"].fn(template=tpl_name)
            assert "content" in result
            assert "lines" in result

    def test_get_template_info_not_found(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["get_template_info"].fn(template="nonexistent.twig")
        assert "error" in result


# ---------------------------------------------------------------------------
# Permission gating integration
# ---------------------------------------------------------------------------

class TestPermissionGating:
    """Verify that tools respect their permission gates."""

    def test_logs_tool_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_LOGS", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["get_logs"].fn()
        finally:
            mcp_mod._is_dev = orig

    def test_files_read_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_FILES_READ", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["read_file"].fn(path="src/routes/test.py")
        finally:
            mcp_mod._is_dev = orig

    def test_files_write_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_FILES_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["write_file"].fn(path="src/templates/test.twig", content="test")
        finally:
            mcp_mod._is_dev = orig

    def test_db_read_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_DB_READ", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["db_query"].fn(sql="SELECT 1")
        finally:
            mcp_mod._is_dev = orig

    def test_db_write_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_DB_WRITE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["db_execute"].fn(sql="DELETE FROM users", confirm=True)
        finally:
            mcp_mod._is_dev = orig

    def test_queue_blocked(self, root_path, monkeypatch):
        monkeypatch.setenv("TINA4_MCP_QUEUE", "false")
        import tina4_python.McpServer as mcp_mod
        orig = mcp_mod._is_dev
        mcp_mod._is_dev = False
        try:
            server = create_mcp_server(root_path)
            tools = {name: func for name, func in server._tool_manager._tools.items()}
            with pytest.raises(PermissionError):
                tools["queue_produce"].fn(topic="test", data={"msg": "hi"})
        finally:
            mcp_mod._is_dev = orig


# ---------------------------------------------------------------------------
# DB Tools safety
# ---------------------------------------------------------------------------

class TestDbToolsSafety:

    def setup_method(self):
        os.environ["TINA4_MCP_DB_READ"] = "true"
        os.environ["TINA4_MCP_DB_WRITE"] = "true"

    def test_db_query_blocks_insert(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_query"].fn(sql="INSERT INTO users VALUES (1, 'test')")
        assert "error" in result
        assert "SELECT" in result["error"]

    def test_db_query_blocks_delete(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_query"].fn(sql="DELETE FROM users")
        assert "error" in result

    def test_db_query_blocks_drop_in_subquery(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_query"].fn(sql="SELECT * FROM users; DROP TABLE users")
        assert "error" in result
        assert "DROP" in result["error"]

    def test_db_execute_requires_confirm(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_execute"].fn(sql="INSERT INTO users VALUES (1)", confirm=False)
        assert "error" in result
        assert "confirm" in result["error"].lower()

    def test_db_execute_blocks_drop(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_execute"].fn(sql="DROP TABLE users", confirm=True)
        assert "error" in result
        assert "DROP" in result["error"]

    def test_db_execute_blocks_alter(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_execute"].fn(sql="ALTER TABLE users ADD COLUMN evil TEXT", confirm=True)
        assert "error" in result

    def test_db_execute_blocks_truncate(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_execute"].fn(sql="TRUNCATE TABLE users", confirm=True)
        assert "error" in result

    def test_db_query_no_db_returns_error(self, root_path):
        server = create_mcp_server(root_path)
        tools = {name: func for name, func in server._tool_manager._tools.items()}
        result = tools["db_query"].fn(sql="SELECT 1")
        assert "error" in result
        assert "database" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tool completeness
# ---------------------------------------------------------------------------

class TestToolCompleteness:
    """Verify all expected tools are registered."""

    def test_all_tools_registered(self, root_path):
        server = create_mcp_server(root_path)
        tool_names = set(server._tool_manager._tools.keys())

        expected = {
            # Diagnostics
            "get_logs", "get_server_info", "list_routes", "get_env", "get_swagger_spec",
            # File read
            "read_file", "list_directory", "search_files", "get_project_structure",
            "get_route_handler", "list_orm_models",
            # File write
            "write_file", "edit_file", "delete_file", "rename_file",
            # Templates
            "render_template", "list_templates", "get_template_info",
            # Database
            "db_query", "db_tables", "db_execute", "run_migration",
            # Project ops
            "compile_scss", "trigger_reload",
            # Queue
            "queue_produce", "queue_peek",
        }

        missing = expected - tool_names
        assert missing == set(), f"Missing tools: {missing}"

    def test_tool_count(self, root_path):
        server = create_mcp_server(root_path)
        assert len(server._tool_manager._tools) >= 26
