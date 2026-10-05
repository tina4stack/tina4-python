# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Regression tests for tina4-php#271 (dev MCP tool rough edges), Python reference.

No mocks: a real McpServer with the real dev tools, driven through the real
JSON-RPC ``tools/call`` path (``handle_message``), against a real SQLite
database that includes an EMPTY table and real registered routes.

  P1 database_columns reports schema columns for an empty table; missing table errors.
  P2 tool arguments are validated against the input schema before the call.
  P3 route_list carries each route's middleware names.
  P4 a route file added while running registers and shows up in route_list.
"""
import json
import os
import sys
import textwrap

import pytest


class AuditMiddleware:
    """Real middleware class attached to a noauth route in the tests."""

    @staticmethod
    def before_audit(request, response):
        return request, response


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    import tina4_python.core.router as router_mod
    import tina4_python.orm.model as orm_model
    from tina4_python.core.router import get, noauth, middleware
    from tina4_python.database import Database
    from tina4_python.mcp import McpServer
    from tina4_python.mcp.tools import register_dev_tools
    from tina4_python.orm import bind_database

    old_cwd = os.getcwd()
    old_database = orm_model._database
    old_databases = dict(orm_model._databases)
    old_routes = list(router_mod._routes)
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.setenv("TINA4_MCP", "true")
    monkeypatch.delenv("TINA4_DATABASE_URL", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "src" / "routes").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "routes" / "__init__.py").write_text("")
    os.chdir(tmp_path)

    db = Database(f"sqlite:///{tmp_path / 'm271.db'}")
    bind_database(db)
    db.execute("CREATE TABLE empty_widgets (id INTEGER PRIMARY KEY, label TEXT NOT NULL, qty INTEGER)")
    db.commit()

    @noauth()
    @middleware(AuditMiddleware)
    @get("/m271/guarded")
    async def _guarded(request, response):
        return response({"ok": True})

    @get("/m271/plain")
    async def _plain(request, response):
        return response({"ok": True})

    server = McpServer("/__dev/mcp", name="m271")
    register_dev_tools(server)
    request_id = [0]

    def call(tool, arguments=None):
        request_id[0] += 1
        raw = server.handle_message({
            "jsonrpc": "2.0", "id": request_id[0], "method": "tools/call",
            "params": {"name": tool, "arguments": arguments if arguments is not None else {}},
        })
        message = json.loads(raw)
        assert "error" not in message, f"{tool} escaped as a JSON-RPC error: {message}"
        return json.loads(message["result"]["content"][0]["text"])

    call.server_tools = lambda: server._handle_tools_list({})["tools"]
    yield call

    os.chdir(old_cwd)
    orm_model._database = old_database
    orm_model._databases.clear()
    orm_model._databases.update(old_databases)
    router_mod._routes[:] = old_routes
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            del sys.modules[module_name]


# ── P1 ──────────────────────────────────────────────────────────

def test_database_columns_reports_columns_of_an_empty_table(mcp):
    columns = mcp("database_columns", {"table": "empty_widgets"})
    by_name = {column["name"]: column for column in columns}
    assert list(by_name) == ["id", "label", "qty"]
    assert by_name["label"]["type"] == "TEXT" and by_name["label"]["nullable"] is False
    assert by_name["id"]["primary_key"] is True


def test_database_columns_missing_table_is_a_clear_error_not_empty(mcp):
    result = mcp("database_columns", {"table": "no_such_table"})
    assert isinstance(result, dict) and "no_such_table" in result["error"]


# ── P2 ──────────────────────────────────────────────────────────

def test_missing_required_argument_is_actionable(mcp):
    assert mcp("api_method", {"class": "Database"}) == {
        "error": "missing required argument 'name' (api_method takes class, name)"}
    assert mcp("database_columns", {}) == {
        "error": "missing required argument 'table' (database_columns takes table)"}


def test_unknown_argument_is_rejected_with_same_shape(mcp):
    assert mcp("api_method", {"class": "Database", "name": "get_columns", "method": "x"}) == {
        "error": "unknown argument 'method' (api_method takes class, name)"}
    assert mcp("route_list", {"bogus": 1}) == {
        "error": "unknown argument 'bogus' (route_list takes no arguments)"}


def test_every_tool_with_required_args_rejects_an_empty_call_actionably(mcp):
    listing = mcp.server_tools()
    with_required = [tool for tool in listing if tool["inputSchema"].get("required")]
    assert len(with_required) > 10
    for tool in with_required:
        first = tool["inputSchema"]["required"][0]
        result = mcp(tool["name"], {})
        assert result["error"].startswith(f"missing required argument '{first}' ({tool['name']} takes "), tool["name"]


def test_api_method_populates_params_and_return(mcp):
    spec = mcp("api_method", {"class": "Database", "name": "get_columns"})
    assert spec["params"] == [{"name": "table", "type": "str", "required": True, "default": None}]
    assert spec["return"] == "list[dict]"


def test_api_method_unknown_method_still_errors(mcp):
    assert "method not found" in mcp("api_method", {"class": "Database", "name": "nope"})["error"]


# ── P3 ──────────────────────────────────────────────────────────

def test_route_list_reports_middleware_names(mcp):
    routes = {route["path"]: route for route in mcp("route_list")}
    guarded, plain = routes["/m271/guarded"], routes["/m271/plain"]
    assert guarded["middleware"] == ["AuditMiddleware"]
    assert guarded["auth_required"] is False and guarded["method"] == "GET"
    assert plain["middleware"] == []


# ── P4 ──────────────────────────────────────────────────────────

def test_route_file_added_at_runtime_shows_in_route_list(mcp, tmp_path):
    from tina4_python.core import server as server_module
    server_module._auto_discover("src")
    assert "/m271/late" not in [route["path"] for route in mcp("route_list")]
    (tmp_path / "src" / "routes" / "late.py").write_text(textwrap.dedent('''
        from tina4_python.core.router import get

        @get("/m271/late")
        async def late(request, response):
            return response({"ok": True})
    '''))
    server_module._auto_discover("src")  # what POST /__dev/api/reload runs
    assert "/m271/late" in [route["path"] for route in mcp("route_list")]
