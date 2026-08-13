"""Feature 130: dynamic framework version (single resolver + version User-Agent).

See plan/v3/features/130-dynamic-version.md and plan/v3/OWNER-DECISIONS.md
(Batch 5, VERSION-DEC-01/02/03). Shared fixture:
tina4-documentation/plan/v3/fixtures/version_contract.json.

Python is the reference resolver (_resolve_version(): pyproject.toml ->
importlib.metadata -> floor literal, locked to pyproject by
test_version_constant.py) and is UNCHANGED here. This suite adds the shared
DEC-02 cross-source drift shape (Python already had test_version_constant.py's
narrower version, this is the fixture-driven equivalent) and the DEC-03
outbound User-Agent.

A REAL bug was found and fixed while grounding this feature (not previously
catalogued, not something the "Python/Ruby are the reference" framing
predicted): tina4_python.mcp._get_default_server() constructed
McpServer("/__dev/mcp", name="Tina4 Dev Tools") with NO version= argument, so
the built-in dev MCP server's serverInfo.version was stuck on the
constructor's generic "1.0.0" default -- the exact same class of bug PHP was
audited for. Fixed by passing __version__ explicitly at that one call site
(mirrors the PHP/Node/Ruby fix). The resolver itself was not touched.

Case names (shared with PHP/Ruby/Node):
  - runtime_version_equals_the_package_manifest
  - every_reporting_surface_agrees
  - no_surface_reports_a_placeholder_version
  - the_outbound_http_client_sends_a_tina4_version_user_agent

NO MOCKS: a real child server process (python app.py) queried over real
sockets (health GET, dashboard GET, a real JSON-RPC POST to the MCP
endpoint), a real subprocess running the actual tina4python CLI entrypoint
for the manifest, and a real local TCP capture server the framework's own
Api client makes a real outbound request against.
"""
import http.client
import json
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import tina4_python
from tina4_python.api import Api
from conftest import boot_child_server, read_child_log

ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_VERSIONS = {"0.0.0", "1.0.0"}


def _write_app(project_dir, port):
    (project_dir / "app.py").write_text(
        "from tina4_python.core import run\nrun()\n"
    )


def _http_get(host: str, port: int, path: str, timeout: float = 10.0):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def _mcp_initialize_version(host: str, port: int, timeout: float = 10.0) -> str:
    """Real JSON-RPC 'initialize' POST to the mounted MCP endpoint; returns
    result.serverInfo.version."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "version-contract-test", "version": "1.0"},
        },
    })
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("POST", "/__dev/mcp", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        assert resp.status == 200, f"MCP initialize -> HTTP {resp.status}: {raw!r}"
        payload = json.loads(raw)
        return payload["result"]["serverInfo"]["version"]
    finally:
        conn.close()


# The real CLI entrypoint, driven exactly as the tina4 client would drive it
# (mirrors tests/test_cli_commands_manifest.py's _ENTRYPOINT_CODE).
_CLI_MANIFEST_CODE = (
    "import sys\n"
    "sys.argv = ['tina4python', 'commands', '--json']\n"
    "from tina4_python.cli import main\n"
    "main()\n"
)


def _cli_manifest_version() -> str:
    result = subprocess.run(
        [sys.executable, "-c", _CLI_MANIFEST_CODE],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"commands --json exited non-zero; stderr:\n{result.stderr}"
    manifest = json.loads(result.stdout)
    return manifest["version"]


def test_runtime_version_equals_the_package_manifest():
    """__version__ equals pyproject.toml's [project].version -- Python's
    resolver is unchanged by this feature; this is the fixture-driven
    equivalent of test_version_constant.py's narrower check."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pyproject_version = data["project"]["version"]
    assert tina4_python.__version__ == pyproject_version


@pytest.fixture(scope="module")
def booted_surfaces(tmp_path_factory):
    """Boot ONE real child server (debug mode) and gather every reporting
    surface's version once, shared by the two cases that need a live server.
    """
    tmp_path = tmp_path_factory.mktemp("version_contract_surfaces")
    log_dir = tmp_path / "logs"
    # No unset_env here: this test only needs TINA4_DEBUG for the dashboard +
    # MCP routes, not the dual AI port (feature 128) -- boot_child_server's
    # default TINA4_NO_AI_PORT=true keeps a single ordinary port.
    # TINA4_SUPPRESS overridden to "false": boot_child_server defaults it to
    # "true" (silences the startup banner) but this test needs the REAL
    # banner text to prove the version-every-surface-agrees case.
    proc, port = boot_child_server(
        tmp_path, _write_app,
        extra_env={"TINA4_DEBUG": "true", "TINA4_SUPPRESS": "false"},
        log_dir=log_dir,
    )
    try:
        assert proc.poll() is None, "server exited during startup"

        health_status, health_body = _http_get("127.0.0.1", port, "/health")
        assert health_status == 200, f"/health -> {health_status}"
        health_version = json.loads(health_body)["version"]

        dash_status, dash_body = _http_get("127.0.0.1", port, "/__dev/api/status")
        assert dash_status == 200, f"/__dev/api/status -> {dash_status}: {dash_body!r}"
        dashboard_version = json.loads(dash_body)["framework_version"]

        mcp_version = _mcp_initialize_version("127.0.0.1", port)

        cli_version = _cli_manifest_version()

        log = read_child_log(proc)
        expected_banner = f"Tina4 Python v{tina4_python.__version__}"

        yield {
            "resolved": tina4_python.__version__,
            "health": health_version,
            "dashboard": dashboard_version,
            "mcp": mcp_version,
            "cli": cli_version,
            "banner_log": log,
            "expected_banner": expected_banner,
        }
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_every_reporting_surface_agrees(booted_surfaces):
    """health + banner + dashboard + MCP serverInfo + CLI manifest ALL equal
    the runtime version -- no surface diverges."""
    s = booted_surfaces
    assert s["expected_banner"] in s["banner_log"], (
        f"boot banner missing {s['expected_banner']!r}; log: {s['banner_log']!r}"
    )
    assert s["health"] == s["resolved"], f"health {s['health']!r} != runtime {s['resolved']!r}"
    assert s["dashboard"] == s["resolved"], f"dashboard {s['dashboard']!r} != runtime {s['resolved']!r}"
    assert s["mcp"] == s["resolved"], f"MCP serverInfo {s['mcp']!r} != runtime {s['resolved']!r}"
    assert s["cli"] == s["resolved"], f"CLI manifest {s['cli']!r} != runtime {s['resolved']!r}"


def test_no_surface_reports_a_placeholder_version(booted_surfaces):
    """No live-queried surface ever returns the '0.0.0' or '1.0.0' sentinel --
    the negative control: a fix that made every surface agree by having them
    ALL report a wrong constant would still pass the case above, but not this
    one."""
    s = booted_surfaces
    for name in ("health", "dashboard", "mcp", "cli"):
        assert s[name] not in PLACEHOLDER_VERSIONS, f"{name} reported a placeholder version: {s[name]!r}"


def test_the_outbound_http_client_sends_a_tina4_version_user_agent():
    """A real outbound request via tina4_python.api.Api carries a default
    Tina4/<version> User-Agent; a caller-supplied one is preserved."""
    captured = {}

    class _CaptureHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            captured["user_agent"] = self.headers.get("User-Agent")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *args):
            pass  # keep test output quiet

    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        # Default: no caller-supplied User-Agent.
        api = Api(base_url)
        result = api.get("/probe")
        assert result["error"] is None, f"request failed: {result}"
        expected = f"Tina4/{tina4_python.__version__}"
        assert captured["user_agent"] == expected, (
            f"default User-Agent was {captured['user_agent']!r}, expected {expected!r}"
        )

        # Caller-supplied User-Agent must be preserved, not clobbered.
        captured.clear()
        api_custom = Api(base_url, headers={"User-Agent": "MyApp/9.9"})
        result2 = api_custom.get("/probe")
        assert result2["error"] is None, f"request failed: {result2}"
        assert captured["user_agent"] == "MyApp/9.9", (
            f"caller-supplied User-Agent was clobbered: {captured['user_agent']!r}"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
