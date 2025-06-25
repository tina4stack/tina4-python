import os
import pytest
import logging
from unittest import mock
from tina4_python import Debug
from tina4_python import Constant


@pytest.fixture(scope="function")
def log_dir():
    path = os.path.join(".", "logs")
    os.makedirs(path, exist_ok=True)
    yield path
    for f in os.listdir(path):
        os.remove(os.path.join(path, f))


# DEBUG-001
def test_info_log_creates_entry(log_dir):
    Debug.info("Test info message")
    assert os.path.exists(os.path.join(log_dir, "debug.log"))


# DEBUG-002
def test_error_log(log_dir):
    Debug.error("Test error message")
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "ERROR" in contents


# DEBUG-003
def test_debug_log(log_dir):
    Debug.debug("Debugging things")
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "DEBUG" in contents


# DEBUG-004
def test_warning_log(log_dir):
    Debug.warning("Something to warn")
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "WARNING" in contents


# DEBUG-005
def test_multiple_arguments(log_dir):
    Debug.info("Multiple", "args", 123)
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "Multiple args 123" in contents


# DEBUG-006
@mock.patch.dict(os.environ, {"TINA4_DEBUG_LEVEL": Constant.TINA4_LOG_INFO})
def test_custom_log_file():
    import time
    from logging import getLogger

    log_name = "custom.log"
    file_path = os.path.join(".", "logs", log_name)

    if os.path.exists(file_path):
        os.remove(file_path)

    logger = getLogger('TINA4')
    logger.handlers.clear()

    Debug.info("Custom file test", file_name=log_name)

    time.sleep(0.2)

    assert os.path.exists(file_path)

# DEBUG-007
@mock.patch.dict(os.environ, {"TINA4_DEBUG_LEVEL": Constant.TINA4_LOG_DEBUG})
def test_debug_level_environment_filter(log_dir):
    Debug.debug("Filtered debug")
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        assert "Filtered debug" in log_file.read()


# DEBUG-009
def test_empty_log_message(log_dir):
    Debug.info()
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert contents.strip()  # Should contain at least timestamp


# DEBUG-010
def test_invalid_level_fallback(log_dir):
    Debug("Test message", "INVALID_LEVEL")
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "Test message" in contents


# DEBUG-011
def test_non_string_args(log_dir):
    Debug.info({"key": "value"}, ["list", 2])
    with open(os.path.join(log_dir, "debug.log")) as log_file:
        contents = log_file.read()
        assert "key" in contents and "list" in contents


# DEBUG-012
@mock.patch("tina4_python.Debug.RotatingFileHandler")
def test_invalid_log_path(mock_handler):
    mock_handler.side_effect = OSError("Path error")
    with pytest.raises(OSError):
        Debug.info("Path test", file_name="/invalid/path.log")
