# Tests for tina4_python health endpoint (v3)
import json
import shutil
import pytest
from pathlib import Path
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.core.server import _health_handler


@pytest.fixture
def broken_dir(tmp_path, monkeypatch):
    """Provide a temp broken dir and patch Path references."""
    broken = tmp_path / "data" / ".broken"
    broken.mkdir(parents=True)
    # Monkey-patch the working directory so _health_handler finds data/.broken
    monkeypatch.chdir(tmp_path)
    return broken


class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_healthy_status_ok(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_healthy_status_code_200(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_version(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert "version" in body

    @pytest.mark.asyncio
    async def test_response_has_framework(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["framework"] == "tina4-python"

    @pytest.mark.asyncio
    async def test_response_has_uptime(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert "uptime" in body
        assert isinstance(body["uptime"], float)


    @pytest.mark.asyncio
    async def test_broken_file_does_not_set_error_status(self, broken_dir):
        """Liveness reports the PROCESS, not the app's error history.

        This asserted ``status == "error"`` until feature 8. A recorded route
        error is not a reason to restart the container, so it no longer moves
        the status. See tests/test_health_liveness.py and ADR-0016.
        """
        error_data = {"error": "Something broke", "timestamp": "2025-01-01T00:00:00Z"}
        (broken_dir / "test.broken").write_text(json.dumps(error_data))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_broken_file_returns_200(self, broken_dir):
        """Was 503. One unhandled route error used to flip liveness to 503 for
        the life of the process AND across restarts (nothing cleared the
        sentinel), which is a CrashLoopBackOff from a single bad request."""
        (broken_dir / "crash.broken").write_text(json.dumps({"error": "crash"}))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        assert result.status_code == 200



    @pytest.mark.asyncio
    async def test_malformed_broken_file_handled(self, broken_dir):
        """An unreadable sentinel cannot break the probe.

        This used to parse the file to build `latest_error`. The body no
        longer reads .broken at all, so a corrupt sentinel is structurally
        incapable of affecting the response - which is the stronger guarantee.
        """
        (broken_dir / "bad.broken").write_text("not json")
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        assert result.status_code == 200
        body = json.loads(result.content)
        assert body["status"] == "ok"
        assert set(body) == {"status", "version", "uptime", "framework"}

    @pytest.mark.asyncio
    async def test_no_broken_dir_returns_ok(self, tmp_path, monkeypatch):
        """When data/.broken doesn't exist at all, health should be ok."""
        monkeypatch.chdir(tmp_path)
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["status"] == "ok"
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_response_content_type_is_json(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        assert "json" in result.content_type
