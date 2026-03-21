# Tests for tina4_python.debug.Log (v3)
import json
import pytest
from pathlib import Path
from tina4_python.debug import Log, set_request_id, get_request_id, _LogWriter


@pytest.fixture(autouse=True)
def reset_log(tmp_path):
    """Reset Log state between tests."""
    Log._initialized = False
    Log._writer = None
    Log._error_writer = None
    Log._level = "info"
    Log._is_production = False
    set_request_id(None)
    yield
    Log._initialized = False
    Log._writer = None
    Log._error_writer = None


class TestLogInit:

    def test_init_sets_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug")
        assert Log._level == "debug"

    def test_init_sets_production(self, tmp_path):
        Log.init(log_dir=str(tmp_path), production=True)
        assert Log._is_production is True

    def test_init_creates_writer(self, tmp_path):
        Log.init(log_dir=str(tmp_path))
        assert Log._writer is not None

    def test_init_creates_error_writer(self, tmp_path):
        Log.init(log_dir=str(tmp_path))
        assert Log._error_writer is not None

    def test_init_marks_initialized(self, tmp_path):
        Log.init(log_dir=str(tmp_path))
        assert Log._initialized is True

    def test_init_level_is_case_insensitive(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="WARNING")
        assert Log._level == "warning"


class TestLogLevels:

    def test_should_log_info_at_info_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="info")
        assert Log._should_log("info") is True

    def test_should_not_log_debug_at_info_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="info")
        assert Log._should_log("debug") is False

    def test_should_log_error_at_info_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="info")
        assert Log._should_log("error") is True

    def test_should_log_warning_at_warning_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="warning")
        assert Log._should_log("warning") is True

    def test_should_not_log_info_at_error_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="error")
        assert Log._should_log("info") is False

    def test_debug_level_logs_everything(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug")
        for level in ("debug", "info", "warning", "error"):
            assert Log._should_log(level) is True


class TestLogFormat:

    def test_dev_format_contains_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=False)
        line = Log._format("info", "test message")
        assert "INFO" in line

    def test_dev_format_contains_message(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=False)
        line = Log._format("info", "hello world")
        assert "hello world" in line

    def test_dev_format_contains_timestamp(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=False)
        line = Log._format("info", "test")
        # ISO 8601 timestamp should contain T
        assert "T" in line

    def test_dev_format_contains_kwargs(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=False)
        line = Log._format("info", "test", user="alice")
        assert "alice" in line

    def test_production_format_is_json(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=True)
        line = Log._format("info", "test message")
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"

    def test_production_format_includes_context(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=True)
        line = Log._format("error", "fail", code=500)
        data = json.loads(line)
        assert data["context"]["code"] == 500

    def test_format_with_request_id(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=True)
        set_request_id("req-123")
        line = Log._format("info", "test")
        data = json.loads(line)
        assert data["request_id"] == "req-123"


class TestLogOutput:

    def test_info_writes_to_file(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=True)
        Log.info("file write test")
        log_file = tmp_path / "tina4.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "file write test" in content

    def test_error_writes_to_error_log(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="debug", production=True)
        Log.error("error write test")
        error_file = tmp_path / "error.log"
        assert error_file.exists()
        content = error_file.read_text()
        assert "error write test" in content

    def test_debug_not_logged_at_info_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="info", production=True)
        Log.debug("should not appear")
        log_file = tmp_path / "tina4.log"
        if log_file.exists():
            assert "should not appear" not in log_file.read_text()

    def test_warning_logged_at_info_level(self, tmp_path):
        Log.init(log_dir=str(tmp_path), level="info", production=True)
        Log.warning("warn test")
        content = (tmp_path / "tina4.log").read_text()
        assert "warn test" in content


class TestRequestId:

    def test_set_and_get_request_id(self):
        set_request_id("abc-123")
        assert get_request_id() == "abc-123"

    def test_default_request_id_is_none(self):
        set_request_id(None)
        assert get_request_id() is None


class TestLogWriter:

    def test_writer_creates_directory(self, tmp_path):
        log_dir = tmp_path / "logs" / "nested"
        writer = _LogWriter(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_writer_writes_line(self, tmp_path):
        writer = _LogWriter(log_dir=str(tmp_path))
        writer.write("test line")
        content = (tmp_path / "tina4.log").read_text()
        assert "test line" in content

    def test_writer_appends(self, tmp_path):
        writer = _LogWriter(log_dir=str(tmp_path))
        writer.write("line 1")
        writer.write("line 2")
        content = (tmp_path / "tina4.log").read_text()
        assert "line 1" in content
        assert "line 2" in content

    def test_writer_custom_filename(self, tmp_path):
        writer = _LogWriter(log_dir=str(tmp_path), filename="custom.log")
        writer.write("custom test")
        assert (tmp_path / "custom.log").exists()
