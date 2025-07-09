import pytest
from tina4_python import Messages as Message

def test_msg_debug():
    assert Message.MSG_DEBUG.format(message="Test") == "Debug: Test"

def test_msg_warning():
    assert Message.MSG_WARNING.format(message="Alert") == "Warning: Alert"

def test_msg_error():
    assert Message.MSG_ERROR.format(message="Failure") == "Error: Failure"

def test_msg_info():
    assert Message.MSG_INFO.format(message="Note") == "Info: Note"

def test_msg_router_matching():
    assert Message.MSG_ROUTER_MATCHING.format(matching="/api/test") == "Matching: /api/test"

def test_msg_server_started():
    assert Message.MSG_SERVER_STARTED.format(host_name="localhost", port=7145) == "Server started http://localhost:7145"

def test_msg_static_file():
    assert Message.MSG_ROUTER_STATIC_FILE.format(static_file="style.css") == "Attempting to serve static file: style.css"

# Negative tests

def test_msg_missing_parameter():
    with pytest.raises(KeyError):
        _ = Message.MSG_DEBUG.format()  # Missing 'message'

def test_msg_non_string_parameter():
    result = Message.MSG_INFO.format(message=12345)
    assert result == "Info: 12345"
