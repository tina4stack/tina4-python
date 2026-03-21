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
        assert body["framework"] == "tina4py"

    @pytest.mark.asyncio
    async def test_response_has_uptime(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], int)

    @pytest.mark.asyncio
    async def test_response_has_errors_count(self, broken_dir):
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["errors"] == 0

    @pytest.mark.asyncio
    async def test_broken_file_sets_error_status(self, broken_dir):
        error_data = {"error": "Something broke", "timestamp": "2025-01-01T00:00:00Z"}
        (broken_dir / "test.broken").write_text(json.dumps(error_data))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["status"] == "error"

    @pytest.mark.asyncio
    async def test_broken_file_returns_503(self, broken_dir):
        (broken_dir / "crash.broken").write_text(json.dumps({"error": "crash"}))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_broken_file_includes_error_count(self, broken_dir):
        (broken_dir / "a.broken").write_text(json.dumps({"error": "a"}))
        (broken_dir / "b.broken").write_text(json.dumps({"error": "b"}))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["errors"] == 2

    @pytest.mark.asyncio
    async def test_broken_file_includes_latest_error(self, broken_dir):
        error_data = {"error": "test error", "trace": "line 42"}
        (broken_dir / "latest.broken").write_text(json.dumps(error_data))
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert "latest_error" in body

    @pytest.mark.asyncio
    async def test_malformed_broken_file_handled(self, broken_dir):
        (broken_dir / "bad.broken").write_text("not json")
        req = Request()
        resp = Response()
        result = await _health_handler(req, resp)
        body = json.loads(result.content)
        assert body["status"] == "error"
        assert "latest_error" in body
        assert "file" in body["latest_error"]

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
