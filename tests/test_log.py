# Tests for tina4_python.debug.Log (3.14 contract, black-box against the
# public surface only). Rewritten 2026-08-13 alongside the shared
# logger_contract.json conformance runner (tests/test_logger_fixture_contract.py):
# the old version imported private internals (`_LogWriter`, `Log._format`,
# `Log._should_log`, `Log._writer`, a `production=` kwarg) that no longer
# exist post-contract. Real files, real env vars, no doubles.
import json

import pytest

from tina4_python.debug import Log, set_request_id, get_request_id, clear_request_id


@pytest.fixture(autouse=True)
def reset_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in (
        "TINA4_LOG_LEVEL", "TINA4_LOG_FILE_LEVEL", "TINA4_LOG_FORMAT",
        "TINA4_LOG_OUTPUT", "TINA4_LOG_DIR", "TINA4_LOG_FILE",
        "TINA4_LOG_ROTATE_SIZE", "TINA4_LOG_ROTATE_KEEP", "TINA4_LOG_STRICT",
        "TINA4_LOG_FUNC", "TINA4_DEBUG",
    ):
        monkeypatch.delenv(name, raising=False)
    Log.reset()
    yield
    Log.reset()


class TestLogLevels:

    def test_should_log_info_at_info_level(self):
        Log.configure(level="info", output="both")
        assert Log.is_enabled("info") is True

    def test_should_not_log_debug_at_info_level(self):
        Log.configure(level="info", output="both", file_level="info")
        assert Log.is_enabled("debug") is False

    def test_should_log_error_at_info_level(self):
        Log.configure(level="info", output="both")
        assert Log.is_enabled("error") is True

    def test_should_log_warning_at_warning_level(self):
        Log.configure(level="warning", output="both")
        assert Log.is_enabled("warning") is True

    def test_should_not_log_info_at_error_level(self):
        Log.configure(level="error", output="both")
        assert Log.is_enabled("info") is False

    def test_debug_level_logs_everything(self):
        Log.configure(level="debug", output="both")
        for level in ("debug", "info", "warning", "error"):
            assert Log.is_enabled(level) is True


class TestLogIsEnabled:

    def test_is_enabled_matches_threshold_at_info(self):
        Log.configure(level="info", output="both")
        assert Log.is_enabled("debug") is False
        assert Log.is_enabled("info") is True
        assert Log.is_enabled("warning") is True
        assert Log.is_enabled("error") is True

    def test_is_enabled_at_error_level(self):
        Log.configure(level="error", output="both")
        assert Log.is_enabled("info") is False
        assert Log.is_enabled("warning") is False
        assert Log.is_enabled("error") is True

    def test_is_enabled_is_case_insensitive(self):
        Log.configure(level="info", output="both")
        assert Log.is_enabled("INFO") is True
        assert Log.is_enabled("Debug") is False

    def test_is_enabled_critical_is_top_level(self):
        Log.configure(level="info", output="both")
        assert Log.is_enabled("critical") is True
        Log.configure(level="error", output="both")
        assert Log.is_enabled("critical") is True

    def test_is_enabled_is_sink_aware(self):
        # Console gated by `level`, file independently by `file_level`
        # (2026-08-10 owner override of Decision 8).
        Log.configure(level="error", file_level="debug", output="both")
        assert Log.is_enabled("info") is False           # console: below error
        assert Log.is_enabled("info", sink="file") is True  # file: at/above debug

    def test_is_enabled_unknown_level_raises_argument_error(self):
        from tina4_python.debug import LogArgumentError
        Log.configure(output="both")
        with pytest.raises(LogArgumentError):
            Log.is_enabled("verbose")


class TestLogFormat:

    def test_json_format_is_json(self, tmp_path):
        Log.configure(format="json", output="file", log_dir=str(tmp_path))
        Log.info("test message")
        line = (tmp_path / "tina4.log").read_text().splitlines()[0]
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"

    def test_json_format_includes_context(self, tmp_path):
        Log.configure(format="json", output="file", log_dir=str(tmp_path))
        Log.error("fail", context={"code": 500})
        line = (tmp_path / "tina4.log").read_text().splitlines()[0]
        data = json.loads(line)
        assert data["context"]["code"] == 500

    def test_format_with_request_id(self, tmp_path):
        Log.configure(format="json", output="file", log_dir=str(tmp_path))
        set_request_id("req-123")
        try:
            Log.info("test")
        finally:
            clear_request_id()
        line = (tmp_path / "tina4.log").read_text().splitlines()[0]
        data = json.loads(line)
        assert data["request_id"] == "req-123"

    def test_text_format_contains_level_and_message(self, tmp_path):
        Log.configure(format="text", output="file", log_dir=str(tmp_path))
        Log.info("hello world")
        content = (tmp_path / "tina4.log").read_text()
        assert "INFO" in content
        assert "hello world" in content

    def test_debug_derived_format_is_json_without_debug(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.info("prod line")
        line = (tmp_path / "tina4.log").read_text().splitlines()[0]
        json.loads(line)  # must parse as JSON

    def test_debug_derived_format_is_text_with_debug(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_DEBUG", "true")
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.info("dev line")
        line = (tmp_path / "tina4.log").read_text().splitlines()[0]
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


class TestLogOutput:

    def test_info_writes_to_file(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.info("file write test")
        content = (tmp_path / "tina4.log").read_text()
        assert "file write test" in content

    def test_error_writes_to_error_log(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.error("error write test")
        content = (tmp_path / "error.log").read_text()
        assert "error write test" in content

    def test_warning_also_writes_to_error_log(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.warning("warn into errors")
        assert "warn into errors" in (tmp_path / "error.log").read_text()

    def test_critical_always_logs_at_critical_severity(self, tmp_path):
        Log.configure(level="error", output="file", log_dir=str(tmp_path))
        Log.critical("meltdown")
        content = (tmp_path / "tina4.log").read_text()
        assert "meltdown" in content
        assert "CRITICAL" in content

    def test_critical_writes_to_error_log(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.critical("page the oncall")
        assert "page the oncall" in (tmp_path / "error.log").read_text()

    def test_info_and_debug_do_not_write_to_error_log(self, tmp_path):
        Log.configure(level="debug", output="file", log_dir=str(tmp_path))
        Log.debug("debug noise")
        Log.info("info noise")
        error_file = tmp_path / "error.log"
        if error_file.exists():
            content = error_file.read_text()
            assert "debug noise" not in content
            assert "info noise" not in content

    def test_debug_always_logged_to_file_when_file_level_all(self, tmp_path):
        # File records every level under the default file_level=ALL,
        # independent of the console `level` (Decision 8 override).
        Log.configure(level="info", output="file", log_dir=str(tmp_path))
        Log.debug("should still appear in file")
        assert "should still appear in file" in (tmp_path / "tina4.log").read_text()


class TestStdoutInProduction:
    """v3.13.14 — logs MUST reach stdout in production so `docker logs`
    and k8s (which read PID 1 stdout) see them."""

    def test_production_logs_go_to_stdout(self, capsys):
        Log.configure(level="info", output="stdout")
        Log.info("hello from prod")
        assert "hello from prod" in capsys.readouterr().out

    def test_json_stdout_has_no_ansi(self, capsys):
        Log.configure(level="info", output="stdout", format="json")
        Log.error("boom", context={"code": 500})
        out = capsys.readouterr().out.strip().splitlines()[-1]
        data = json.loads(out)
        assert data["message"] == "boom"
        assert data["level"] == "ERROR"
        assert "\x1b[" not in out

    def test_production_respects_level_on_stdout(self, capsys):
        Log.configure(level="info", output="stdout")
        Log.debug("debug noise")
        assert "debug noise" not in capsys.readouterr().out

    def test_stdout_disabled_when_output_is_file(self, tmp_path, capsys):
        Log.configure(output="file", log_dir=str(tmp_path))
        Log.info("file only")
        assert "file only" not in capsys.readouterr().out
        assert "file only" in (tmp_path / "tina4.log").read_text()


class TestRequestId:

    def test_set_and_get_request_id(self):
        set_request_id("abc-123")
        assert get_request_id() == "abc-123"
        clear_request_id()

    def test_default_request_id_is_none(self):
        clear_request_id()
        assert get_request_id() is None

    def test_clear_request_id(self):
        set_request_id("abc-123")
        clear_request_id()
        assert get_request_id() is None


# Caller-name injection — feature #41 across all four Tina4 frameworks.
class TestFunctionNameInLog:
    """When TINA4_LOG_FUNC=true, log lines include the calling function name.
    Default behaviour is unchanged when the setting is absent or false. Only
    the literal tokens "true"/"false" are valid (Decision 19: native
    booleans, not private truth-token parsing) -- narrower than the old
    Env.bool truthy set, and pinned by test_logger_fixture_contract.py."""

    def test_caller_name_not_injected_by_default(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path), format="json")

        def super_trooper():
            Log.info("hello")

        super_trooper()
        line = json.loads((tmp_path / "tina4.log").read_text().splitlines()[0])
        assert "function" not in line
        assert line["message"] == "hello"

    def test_caller_name_injected_when_enabled(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path), format="json", caller=True)

        def super_trooper():
            Log.info("hello")

        super_trooper()
        line = json.loads((tmp_path / "tina4.log").read_text().splitlines()[0])
        assert line["function"] == "super_trooper"

    def test_caller_name_env_true_enables_injection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_LOG_FUNC", "true")
        Log.configure(output="file", log_dir=str(tmp_path), format="json")

        def super_trooper():
            Log.info("hi")

        super_trooper()
        line = json.loads((tmp_path / "tina4.log").read_text().splitlines()[0])
        assert line["function"] == "super_trooper"

    def test_caller_name_env_false_disables_injection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TINA4_LOG_FUNC", "false")
        Log.configure(output="file", log_dir=str(tmp_path), format="json")

        def super_trooper():
            Log.info("hi")

        super_trooper()
        line = json.loads((tmp_path / "tina4.log").read_text().splitlines()[0])
        assert "function" not in line

    def test_caller_name_rejects_non_boolean_token(self, monkeypatch):
        from tina4_python.debug import LogConfigurationError
        monkeypatch.setenv("TINA4_LOG_FUNC", "1")
        with pytest.raises(LogConfigurationError):
            Log.configure(output="stdout")

    def test_caller_name_filters_lambda(self, tmp_path):
        Log.configure(output="file", log_dir=str(tmp_path), format="json", caller=True)
        produce = lambda: Log.info("from lambda")  # noqa: E731
        produce()
        line = json.loads((tmp_path / "tina4.log").read_text().splitlines()[0])
        assert line.get("function") != "<lambda>"
        assert line["message"] == "from lambda"
