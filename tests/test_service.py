# Tests for tina4_python.service.ServiceRunner (v3)
import time
import threading
import pytest
from datetime import datetime
from tina4_python.service import (
    ServiceRunner, ServiceContext, parse_cron, cron_matches, _field_matches,
)


class TestParseCron:

    def test_valid_expression(self):
        result = parse_cron("*/5 * * * *")
        assert result["minute"] == "*/5"
        assert result["hour"] == "*"
        assert result["day"] == "*"
        assert result["month"] == "*"
        assert result["weekday"] == "*"

    def test_specific_values(self):
        result = parse_cron("30 8 1 6 3")
        assert result["minute"] == "30"
        assert result["hour"] == "8"
        assert result["day"] == "1"
        assert result["month"] == "6"
        assert result["weekday"] == "3"

    def test_invalid_expression_too_few_fields(self):
        result = parse_cron("* * *")
        assert result == {}

    def test_invalid_expression_too_many_fields(self):
        result = parse_cron("* * * * * *")
        assert result == {}

    def test_empty_string(self):
        result = parse_cron("")
        assert result == {}


class TestFieldMatches:

    def test_wildcard_matches_any(self):
        assert _field_matches("*", 0) is True
        assert _field_matches("*", 59) is True

    def test_exact_value(self):
        assert _field_matches("5", 5) is True
        assert _field_matches("5", 6) is False

    def test_step_on_wildcard(self):
        assert _field_matches("*/5", 0) is True
        assert _field_matches("*/5", 5) is True
        assert _field_matches("*/5", 10) is True
        assert _field_matches("*/5", 3) is False

    def test_range(self):
        assert _field_matches("1-5", 1) is True
        assert _field_matches("1-5", 3) is True
        assert _field_matches("1-5", 5) is True
        assert _field_matches("1-5", 0) is False
        assert _field_matches("1-5", 6) is False

    def test_range_with_step(self):
        assert _field_matches("1-10/2", 1) is True
        assert _field_matches("1-10/2", 3) is True
        assert _field_matches("1-10/2", 2) is False

    def test_list(self):
        assert _field_matches("1,3,5", 1) is True
        assert _field_matches("1,3,5", 3) is True
        assert _field_matches("1,3,5", 5) is True
        assert _field_matches("1,3,5", 2) is False


class TestCronMatches:

    def test_every_minute(self):
        now = datetime(2025, 6, 15, 10, 30)
        assert cron_matches("* * * * *", now) is True

    def test_specific_minute(self):
        now = datetime(2025, 6, 15, 10, 30)
        assert cron_matches("30 * * * *", now) is True
        assert cron_matches("15 * * * *", now) is False

    def test_specific_hour_and_minute(self):
        now = datetime(2025, 6, 15, 9, 0)
        assert cron_matches("0 9 * * *", now) is True
        assert cron_matches("0 10 * * *", now) is False

    def test_specific_day_of_month(self):
        now = datetime(2025, 6, 1, 0, 0)
        assert cron_matches("0 0 1 * *", now) is True
        assert cron_matches("0 0 15 * *", now) is False

    def test_specific_month(self):
        now = datetime(2025, 6, 15, 10, 0)
        assert cron_matches("0 10 * 6 *", now) is True
        assert cron_matches("0 10 * 7 *", now) is False

    def test_invalid_expression_returns_false(self):
        assert cron_matches("invalid", datetime.now()) is False
        assert cron_matches("* *", datetime.now()) is False


class TestServiceContext:

    def test_context_creation(self):
        stop = threading.Event()
        ctx = ServiceContext("test-svc", stop)
        assert ctx.name == "test-svc"
        assert ctx.running is True
        assert ctx.last_run == 0.0
        assert ctx.stop_event is stop

    def test_context_has_log(self):
        stop = threading.Event()
        ctx = ServiceContext("test-svc", stop)
        assert ctx.log is not None


class TestServiceRunnerRegistration:

    def test_register_service(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None)
        assert len(runner.services) == 1
        assert runner.services[0]["name"] == "test"

    def test_register_with_interval(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, interval=30)
        assert runner.services[0]["interval"] == 30

    def test_register_with_cron(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, cron="*/5 * * * *")
        assert runner.services[0]["cron"] == "*/5 * * * *"

    def test_register_daemon(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, daemon=True)
        assert runner.services[0]["daemon"] is True

    def test_register_max_retries(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, max_retries=5)
        assert runner.services[0]["max_retries"] == 5

    def test_register_multiple_services(self):
        runner = ServiceRunner()
        runner.register("svc-a", lambda ctx: None)
        runner.register("svc-b", lambda ctx: None)
        assert len(runner.services) == 2

    def test_initial_state(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None)
        svc = runner.services[0]
        assert svc["running"] is False
        assert svc["retries"] == 0
        assert svc["last_run"] is None
        assert svc["started_at"] is None


class TestServiceRunnerLifecycle:

    def test_start_sets_running(self):
        call_count = [0]
        def handler(ctx):
            call_count[0] += 1
        runner = ServiceRunner()
        runner.register("test", handler, interval=1)
        runner.start()
        time.sleep(0.2)
        runner.stop()
        assert call_count[0] >= 1

    def test_stop_marks_services_not_running(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, interval=1)
        runner.start()
        time.sleep(0.1)
        runner.stop()
        assert runner.services[0]["running"] is False

    def test_double_start_is_safe(self):
        runner = ServiceRunner()
        runner.register("test", lambda ctx: None, interval=60)
        runner.start()
        runner.start()  # Should not crash
        runner.stop()

    def test_daemon_handler_called(self):
        called = threading.Event()
        def daemon_handler(ctx):
            called.set()
        runner = ServiceRunner()
        runner.register("daemon-test", daemon_handler, daemon=True)
        runner.start()
        assert called.wait(timeout=2)
        runner.stop()


class TestServiceRunnerStatus:

    def test_status_returns_list(self):
        runner = ServiceRunner()
        runner.register("svc-a", lambda ctx: None)
        status = runner.status()
        assert isinstance(status, list)
        assert len(status) == 1

    def test_status_contains_name(self):
        runner = ServiceRunner()
        runner.register("my-service", lambda ctx: None)
        status = runner.status()
        assert status[0]["name"] == "my-service"

    def test_status_contains_all_fields(self):
        runner = ServiceRunner()
        runner.register("svc", lambda ctx: None, cron="* * * * *")
        status = runner.status()[0]
        for key in ("name", "running", "last_run", "retries", "started_at", "daemon", "cron", "interval"):
            assert key in status


class TestServiceRunnerDiscover:

    def test_discover_empty_dir(self, tmp_path):
        runner = ServiceRunner()
        result = runner.discover(str(tmp_path))
        assert result == []

    def test_discover_nonexistent_dir(self, tmp_path):
        runner = ServiceRunner()
        result = runner.discover(str(tmp_path / "nonexistent"))
        assert result == []

    def test_discover_valid_service(self, tmp_path):
        svc_file = tmp_path / "heartbeat.py"
        svc_file.write_text(
            'service = {"name": "heartbeat", "handler": lambda ctx: None, "interval": 10}\n'
        )
        runner = ServiceRunner()
        discovered = runner.discover(str(tmp_path))
        assert "heartbeat" in discovered
        assert len(runner.services) == 1

    def test_discover_skips_underscore_files(self, tmp_path):
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_helper.py").write_text(
            'service = {"name": "helper", "handler": lambda ctx: None}\n'
        )
        runner = ServiceRunner()
        discovered = runner.discover(str(tmp_path))
        assert discovered == []

    def test_discover_skips_missing_service_dict(self, tmp_path):
        (tmp_path / "bad.py").write_text("x = 1\n")
        runner = ServiceRunner()
        discovered = runner.discover(str(tmp_path))
        assert discovered == []
