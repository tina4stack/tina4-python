"""Regression contract for the read-only ``tina4 routes`` command."""

import os
import json
from pathlib import Path
import subprocess
import sys


def test_routes_discovers_source_without_executing_app_entrypoint(tmp_path):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "cli_routes_contract.json").read_text()
    )
    invariants = {item["id"]: item for item in fixture["invariants"]}
    route_path = invariants["canonical-route-is-listed"]["route_path"]
    marker_name = invariants["application-entrypoint-is-not-executed"]["marker_name"]
    routes = tmp_path / "src" / "routes"
    routes.mkdir(parents=True)
    (routes / "probe.py").write_text(
        "from tina4_python.core.router import get\n"
        f"@get({route_path!r})\n"
        "async def probe(request, response):\n"
        "    return response({'ok': True})\n",
        encoding="utf-8",
    )
    marker = tmp_path / marker_name
    (tmp_path / "app.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('unsafe')\n"
        "raise RuntimeError('routes executed app.py')\n",
        encoding="utf-8",
    )

    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from tina4_python.cli import main; "
            "sys.argv=['tina4python', 'routes']; main()",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert route_path in result.stdout
    assert not marker.exists(), "app.py was executed by the routes command"
