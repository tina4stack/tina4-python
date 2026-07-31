"""Feature 8: /health is a LIVENESS probe. Regression lock-in.

The bug this pins (measured 2026-07-31, tina4-python 3.13.94):

    GET /health                     -> 200
    GET /boom  (any route raising)  -> 500   and writes data/.broken/*.broken
    GET /health                     -> 503   <-- forever
    ...restart the process...
    GET /health                     -> 503   <-- STILL, nothing clears .broken

Under a Kubernetes ``livenessProbe`` that is a CrashLoopBackOff caused by ONE
bad request. Worse than a dependency outage, because a dependency recovers and
a ``.broken`` file does not. And a restart cannot fix the thing it is reacting
to: a route file that fails to import will fail to import again.

So ``/health`` answers the liveness question ONLY - "can this process serve at
all" - and the answer is carried by the fact that it responded. "Restart me" is
the wrong response to a broken route file, so a recorded route error no longer
touches the status code.

Nor does it appear in the body. Once errors stopped driving the status they were
pure diagnostics, and the wire contract is exactly four keys - status, version,
uptime, framework - identical in all four frameworks. ``.broken`` is still
written, and the dev dashboard and the MCP tools still read it; the probe just
stopped carrying it.

Readiness (dependency probes, 503 to withdraw traffic without a restart) is a
separate endpoint, specified in ADR-0014 and scheduled separately.

No mocks: a REAL child server over a REAL loopback socket, and the failure is
induced by a REAL route that really raises.
"""
import http.client
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import free_port

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_project(root: Path, port: int) -> None:
    (root / "src" / "routes").mkdir(parents=True, exist_ok=True)
    # An ordinary route that raises - the everyday unhandled 500.
    (root / "src" / "routes" / "boom.py").write_text(
        "from tina4_python.core.router import get\n"
        "\n"
        "@get('/boom')\n"
        "async def boom(request, response):\n"
        "    raise ValueError('transient downstream hiccup')\n"
    )
    (root / "app.py").write_text(
        "from tina4_python.core.server import start\n"
        "if __name__ == '__main__':\n"
        f"    start(host='127.0.0.1', port={port}, no_browser=True, no_reload=True)\n"
    )


def _boot(root: Path, port: int) -> subprocess.Popen:
    import os

    env = dict(os.environ)
    env.update({
        "TINA4_OVERRIDE_CLIENT": "true",
        "TINA4_DEBUG": "false",
        "PYTHONPATH": str(REPO_ROOT),
        "PORT": str(port),
    })
    env.pop("TINA4_HEALTH_PATH", None)
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc
        except OSError:
            if proc.poll() is not None:
                raise AssertionError(f"child server died:\n{proc.stdout.read()}")
            time.sleep(0.2)
    proc.terminate()
    raise AssertionError("child server never bound the port")


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    res = conn.getresponse()
    body = res.read().decode()
    conn.close()
    return res.status, body


@pytest.fixture
def live_server(tmp_path):
    port = free_port()
    _write_project(tmp_path, port)
    proc = _boot(tmp_path, port)
    try:
        yield tmp_path, port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


class TestHealthIsLiveness:
    """A route error must never make the process look dead."""

    def test_health_is_200_before_any_route_error(self, live_server):
        _, port = live_server
        status, _ = _get(port, "/health")
        assert status == 200

    def test_a_route_error_does_not_flip_health_to_503(self, live_server):
        """THE regression. One 500 used to poison /health for the process's life."""
        root, port = live_server

        assert _get(port, "/boom")[0] == 500, "the route under test must really raise"
        time.sleep(0.4)

        # The .broken sentinel really was written - we are not testing a no-op.
        broken = list((root / "data" / ".broken").glob("*.broken"))
        assert broken, "expected the route error to write a .broken sentinel"

        status, body = _get(port, "/health")
        assert status == 200, (
            "a route that raised is NOT a reason to restart the container: "
            f"/health returned {status} after one unhandled route error"
        )
        assert json.loads(body)["status"] == "ok"

    def test_a_route_error_leaves_the_health_body_unchanged(self, live_server):
        """Error diagnostics live on the dev dashboard, not on the probe.

        The body used to carry ``errors`` / ``latest_error``. Once they stopped
        driving the status code they were pure diagnostics, and the wire
        contract is four keys in all four frameworks. ``.broken`` is still
        written and the dashboard still reads it.
        """
        root, port = live_server
        before = json.loads(_get(port, "/health")[1])

        _get(port, "/boom")
        time.sleep(0.4)
        assert list((root / "data" / ".broken").glob("*.broken")), \
            "the sentinel must still be written for the dev dashboard"

        after = json.loads(_get(port, "/health")[1])
        assert set(after) == set(before)
        assert "errors" not in after
        assert "latest_error" not in after

    def test_stale_broken_files_are_cleared_at_boot(self, tmp_path):
        """A sentinel from a previous run describes a process that no longer
        exists. It must not be reported by, or outlive, this one."""
        broken_dir = tmp_path / "data" / ".broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "from_a_previous_run.broken").write_text(
            json.dumps({"error": "stale"})
        )

        port = free_port()
        _write_project(tmp_path, port)
        proc = _boot(tmp_path, port)
        try:
            status, body = _get(port, "/health")
            assert status == 200
            assert json.loads(body)["status"] == "ok"
            assert not list(broken_dir.glob("*.broken")), (
                "a .broken sentinel from a previous process survived boot"
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


class TestHealthWireContract:
    """The JSON shape an external consumer reads. Identical in all four."""

    def test_uptime_is_reported_as_seconds_under_the_uptime_key(self, live_server):
        _, port = live_server
        payload = json.loads(_get(port, "/health")[1])
        assert "uptime" in payload, "the key is `uptime` in all four frameworks"
        assert "uptime_seconds" not in payload
        assert isinstance(payload["uptime"], float)

    def test_the_framework_is_named_tina4_python(self, live_server):
        _, port = live_server
        payload = json.loads(_get(port, "/health")[1])
        assert payload["framework"] == "tina4-python"

    def test_the_body_is_exactly_the_four_contract_keys(self, live_server):
        """The whole point of the contract: one key set, four frameworks.

        php, ruby and node emit exactly {status, version, uptime, framework}.
        Any key added here is a key three other frameworks do not send.
        """
        _, port = live_server
        payload = json.loads(_get(port, "/health")[1])
        assert set(payload) == {"status", "version", "uptime", "framework"}
