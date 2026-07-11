# Invoke-every-dev-tool conformance sweep for the built-in MCP dev tools.
"""
Lock-in test for the /__dev/mcp built-in dev tools (tina4_python.mcp.tools).

The gap this closes: the prior MCP tool tests only checked that tools were
REGISTERED and that a hand-picked read-only subset executed. Four tools
(swagger_spec, migration_status, migration_run, seed_table) shipped broken —
they raised or silently returned {"error": ...} the moment they were actually
invoked — because no test invoked EVERY tool end to end.

This test builds the real McpServer, calls the real register_dev_tools, then
iterates the registry (never a hardcoded list) and invokes every registered
tool BOTH ways an MCP client can reach it:

  1. the direct handler call (identical to _handle_tools_call's handler(**args))
  2. the JSON-RPC tools/call wire path via server.handle_message(...)

against a REAL throwaway temp project: a temp SQLite DB, a real route, a real
ORM model + table + row, a pending migration file, and plan/log fixtures. No
mocks — every tool touches the real dependency.

Assertions:
  * NO tool raises an unhandled exception on either path. A graceful
    {"error": ...} dict is acceptable ONLY for genuinely env/arg-gated tools
    (e.g. plan_flesh with the AI backend unreachable, docs_section with an
    unknown heading, code_search when FTS5 is absent).
  * The four fixed tools MUST return real success payloads (never an error
    dict): swagger_spec a spec with paths, migration_status the pending/completed
    dict, migration_run an applied-count, seed_table a real inserted row count.

Pre-fix, this FAILS: swagger_spec / migration_status / migration_run raise
(TypeError / ImportError / AttributeError) and seed_table returns {"error": ...}.
"""
import json
import os

import pytest

from tina4_python.orm import ORM, IntegerField, StringField


# Module-scope ORM model — a real, distinctly-named subclass the tools can
# describe, seed, and query. Table is created against the temp DB in the fixture.
class ConformanceWidget(ORM):
    table_name = "conformance_widget"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    qty = IntegerField()


# Tools that are legitimately allowed to return a graceful {"error": ...} /
# {"ok": False} dict in this fully-provisioned temp project — they depend on
# something outside the harness (a live AI backend, a heading that may not
# exist in the framework's own bundled docs, or an optional SQLite build).
# Every OTHER tool must return a non-error payload. None of them may RAISE.
_GRACEFUL_ERROR_ALLOWED = {"plan_flesh", "docs_section", "code_search"}

# The four tools this change fixes — they MUST return real success payloads.
_FIXED_TOOLS = ("swagger_spec", "migration_status", "migration_run", "seed_table")


def _is_error_payload(value):
    return isinstance(value, dict) and ("error" in value or value.get("ok") is False)


@pytest.fixture
def dev_tools_env(tmp_path, monkeypatch):
    """Build a real McpServer with the real dev tools registered against a
    throwaway temp project. Yields (server, args_for) and restores all mutated
    global/process state on teardown."""
    from tina4_python.database import Database
    from tina4_python.orm import bind_database
    import tina4_python.orm.model as orm_model
    import tina4_python.core.router as router_mod
    from tina4_python.core.router import get, post, noauth
    from tina4_python.dev_admin import plan as plan_mod
    from tina4_python.mcp import McpServer
    from tina4_python.mcp.tools import register_dev_tools

    # --- snapshot mutable global state so we leave the suite as we found it
    old_cwd = os.getcwd()
    old_database = orm_model._database
    old_databases = dict(orm_model._databases)
    old_routes = list(router_mod._routes)

    # dev mode on; pin the AI backend to a closed local port so plan_flesh
    # reaches its code path but can NEVER contact a real LLM (graceful error).
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.setenv("TINA4_MCP", "true")
    monkeypatch.setenv("TINA4_SECRET", "conformance-secret-key")
    monkeypatch.setenv("TINA4_AI_URL", "http://127.0.0.1:9/closed-on-purpose")
    monkeypatch.delenv("TINA4_DATABASE_URL", raising=False)

    # --- lay out a real project tree
    proj = tmp_path
    for sub in ("src/routes", "src/orm", "src/templates", "src/public",
                "migrations", "logs", "data/sessions", "plan"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    (proj / "src" / "__init__.py").write_text("")
    (proj / "README.md").write_text("# Conformance Project\n\nThrowaway app.\n")
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "conformance-app"\nversion = "0.0.1"\n'
        'requires-python = ">=3.12"\ndependencies = ["tina4-python"]\n'
    )
    (proj / "logs" / "debug.log").write_text(
        "INFO boot line 1\nINFO boot line 2\nERROR sample failure\n"
    )
    # A real pending migration for migration_status / migration_run.
    (proj / "migrations" / "000001_create_gadget.sql").write_text(
        "CREATE TABLE IF NOT EXISTS gadget "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT);\n"
    )
    (proj / "src" / "templates" / "hello.twig").write_text("<p>Hi {{ name }}</p>\n")

    # A real git repo so git_status returns real branch/status data (no mock).
    import subprocess

    def _git(*a):
        subprocess.run(["git", *a], cwd=str(proj), capture_output=True, text=True)

    _git("init", "-q")
    _git("config", "user.email", "conformance@example.com")
    _git("config", "user.name", "Conformance")
    _git("add", "-A")
    _git("commit", "-qm", "initial conformance commit")
    (proj / "README.md").write_text("# Conformance Project (edited)\n")  # a modified file
    (proj / "untracked.txt").write_text("x\n")                          # an untracked file

    os.chdir(proj)

    # --- real DB + model + a seeded row
    db = Database(f"sqlite:///{proj / 'conformance.db'}")
    bind_database(db)
    ConformanceWidget().create_table()
    db.execute("INSERT INTO conformance_widget (name, qty) VALUES (?, ?)", ["alpha", 3])
    db.commit()

    # --- real routes (public GET for route_test; a public POST too)
    @get("/conformance/hello")
    async def _hello(request, response):
        return response({"hello": "world"})

    @noauth()
    @post("/conformance/echo")
    async def _echo(request, response):
        return response({"ok": True})

    # --- a stable, never-archived plan fixture for plan_read / plan_flesh
    plan_mod.create("Fixture Plan", goal="stable target",
                    steps=["step one", "step two"], make_current=False)

    # --- build the REAL server + register the REAL tools (cwd is the temp proj)
    server = McpServer("/__dev/mcp", name="Tina4 Dev Tools")
    register_dev_tools(server)

    # --- per-tool safe arguments. Callables receive the shared run-state so
    # plan_switch_to / plan_archive target the plan created earlier in the sweep.
    args_for = {
        "database_query":     {"sql": "SELECT 1 AS one"},
        "database_execute":   {"sql": "CREATE TABLE IF NOT EXISTS _probe (id INTEGER)"},
        "database_tables":    {},
        "database_columns":   {"table": "conformance_widget"},
        "route_list":         {},
        "route_test":         {"method": "GET", "path": "/conformance/hello"},
        "swagger_spec":       {},
        "template_render":    {"template": "Hello {{ name }}", "data": '{"name": "Ada"}'},
        "file_read":          {"path": "README.md"},
        "file_write":         {"path": "scratch_probe.txt", "content": "hello world\n"},
        "file_patch":         {"path": "scratch_probe.txt", "old_string": "hello", "new_string": "bye"},
        "file_list":          {"path": "."},
        "asset_upload":       {"filename": "probe.txt", "content": "asset body"},
        "migration_status":   {},
        "migration_create":   {"description": "add probe column"},
        "migration_run":      {},
        "queue_status":       {"topic": "default"},
        "session_list":       {},
        "cache_stats":        {},
        "orm_describe":       {},
        "log_tail":           {"lines": 5},
        "error_log":          {"limit": 5},
        "env_list":           {},
        "seed_table":         {"table": "conformance_widget", "count": 2},
        "system_info":        {},
        "docs_list":          {},
        "docs_search":        {"query": "route"},
        "docs_section":       {"file": "README.md", "heading": "Conformance"},
        "git_status":         {},
        "deps_list":          {},
        "project_overview":   {},
        "index_rebuild":      {},
        "index_search":       {"query": "widget"},
        "index_file":         {"path": "README.md"},
        "index_overview":     {},
        "plan_current":       {},
        "plan_list":          {},
        "plan_create":        {"title": "sweepplan", "goal": "probe", "steps": ["do a thing"]},
        "plan_switch_to":     (lambda s: {"name": s.get("plan_name", "sweepplan.md")}),
        "plan_complete_step": {"index": 0},
        "plan_add_step":      {"text": "extra sweep step"},
        "plan_note":          {"text": "sweep breadcrumb"},
        "plan_archive":       (lambda s: {"name": s.get("plan_name", "sweepplan.md")}),
        "plan_read":          {"name": "fixture-plan.md"},
        "plan_flesh":         {"name": "fixture-plan.md", "prompt": "probe"},
        "api_search":         {"query": "ORM", "k": 3},
        "api_class":          {"name": "ORM"},
        "api_method":         {"class_": "Database", "name": "fetch"},
        "code_search":        {"query": "route", "k": 3},
    }

    try:
        yield server, args_for
    finally:
        os.chdir(old_cwd)
        orm_model._database = old_database
        orm_model._databases.clear()
        orm_model._databases.update(old_databases)
        router_mod._routes[:] = old_routes
        try:
            db.close()
        except Exception:
            pass


def _sweep(server, args_for):
    """Invoke every registered tool via both the direct handler and the
    JSON-RPC tools/call path, in registration order. Returns
    (results, failures) where results maps tool name -> the direct return
    value and failures is a list of human-readable failure strings."""
    state = {}
    results = {}
    failures = []

    for name in list(server._tools.keys()):
        spec = args_for.get(name)
        assert spec is not None, (
            f"No conformance arguments defined for registered tool {name!r} — "
            "a new dev tool was added; add its safe args to this test."
        )
        kwargs = spec(state) if callable(spec) else dict(spec)
        handler = server._tools[name]["handler"]

        # 1) DIRECT invocation (identical to McpServer._handle_tools_call).
        try:
            value = handler(**kwargs)
            results[name] = value
            if name == "plan_create" and isinstance(value, dict) and value.get("name"):
                state["plan_name"] = value["name"]
        except Exception as exc:  # noqa: BLE001 — we want ANY unhandled raise
            results[name] = None
            failures.append(f"{name}: direct call RAISED {type(exc).__name__}: {exc}")
            continue

        # 2) JSON-RPC round-trip through the real dispatcher. A raised handler
        #    surfaces here as a protocol-level {"error": ...}.
        raw = server.handle_message(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": kwargs},
        }))
        obj = json.loads(raw) if raw else {}
        if "error" in obj:
            failures.append(f"{name}: JSON-RPC tools/call errored: {obj['error']}")
        elif "result" not in obj:
            failures.append(f"{name}: JSON-RPC tools/call returned no result: {obj}")

    return results, failures


class TestMcpDevToolConformance:
    """Invoke EVERY registered dev tool (direct + JSON-RPC) against a real
    temp project and assert none raises and the fixed tools really work."""

    def test_no_tool_raises_on_either_path(self, dev_tools_env):
        server, args_for = dev_tools_env
        assert len(server._tools) >= 40, "dev tools failed to register"
        _, failures = _sweep(server, args_for)
        assert not failures, "MCP dev tools failed conformance sweep:\n  " + "\n  ".join(failures)

    def test_only_allowed_tools_return_error_dicts(self, dev_tools_env):
        # Every tool that isn't genuinely env/arg-gated must return a real
        # (non-error) payload — this is what catches seed_table's silent
        # {"error": ...} regression, which does NOT raise.
        server, args_for = dev_tools_env
        results, _ = _sweep(server, args_for)
        offenders = [
            name for name, value in results.items()
            if _is_error_payload(value) and name not in _GRACEFUL_ERROR_ALLOWED
        ]
        assert not offenders, (
            "tools returned an error dict without being env/arg-gated: "
            + ", ".join(f"{n} -> {results[n]}" for n in offenders)
        )

    def test_every_registered_tool_has_conformance_args(self, dev_tools_env):
        server, args_for = dev_tools_env
        missing = [n for n in server._tools if n not in args_for]
        assert not missing, f"registered tools with no conformance args: {missing}"

    # ── The four fixed tools: real success payloads, not error dicts ──

    def test_swagger_spec_returns_real_spec(self, dev_tools_env):
        server, _ = dev_tools_env
        spec = server._tools["swagger_spec"]["handler"]()
        assert isinstance(spec, dict) and "error" not in spec, spec
        assert spec.get("openapi") == "3.0.3", spec
        assert isinstance(spec.get("paths"), dict) and spec["paths"], spec
        # And through the wire path.
        obj = json.loads(server.handle_message(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "swagger_spec", "arguments": {}},
        })))
        assert "result" in obj, obj
        wire_spec = json.loads(obj["result"]["content"][0]["text"])
        assert wire_spec.get("openapi") == "3.0.3" and wire_spec.get("paths")

    def test_migration_status_returns_pending_completed(self, dev_tools_env):
        server, _ = dev_tools_env
        status = server._tools["migration_status"]["handler"]()
        assert isinstance(status, dict) and "error" not in status, status
        assert "completed" in status and "pending" in status, status
        pending_names = {m.get("migration_name") for m in status["pending"]}
        assert "000001_create_gadget" in pending_names, status

    def test_migration_run_applies_pending(self, dev_tools_env):
        server, _ = dev_tools_env
        result = server._tools["migration_run"]["handler"]()
        assert isinstance(result, dict) and "error" not in result, result
        assert isinstance(result.get("applied"), list), result
        assert result.get("count", 0) >= 1, result
        assert "000001_create_gadget.sql" in result["applied"], result
        # The migration really ran — the gadget table now exists.
        from tina4_python.orm.model import ORM as _ORM
        assert "gadget" in _ORM._get_db().get_tables()

    def test_seed_table_inserts_real_rows(self, dev_tools_env):
        server, _ = dev_tools_env
        before = server._tools["database_query"]["handler"](
            sql="SELECT COUNT(*) AS c FROM conformance_widget")["records"][0]["c"]
        result = server._tools["seed_table"]["handler"](table="conformance_widget", count=2)
        assert isinstance(result, dict) and "error" not in result, result
        assert result.get("inserted") == 2, result
        after = server._tools["database_query"]["handler"](
            sql="SELECT COUNT(*) AS c FROM conformance_widget")["records"][0]["c"]
        assert after == before + 2, (before, after, result)
