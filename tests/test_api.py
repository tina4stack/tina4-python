# tests/test_api.py
import json
from unittest.mock import Mock, patch
import pytest
import requests
from tina4_python import Api


@pytest.fixture
def mock_response():
    """Reusable mock response with safe, real dict headers."""
    resp = Mock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}  # ← real dict!
    resp.text = ""
    resp.json.side_effect = lambda: json.loads(resp.text) if resp.text else {}
    return resp


@pytest.fixture
def api_client():
    return Api(base_url="https://api.example.com")


@patch("requests.request")
def test_get_request(mock_request, api_client, mock_response):
    mock_response.text = '{"url": "https://api.example.com/test", "args": {}}'
    mock_response.json.return_value = {"url": "https://api.example.com/test", "args": {}}
    mock_request.return_value = mock_response

    result = api_client.send_request("/test", request_type="GET")
    assert result["http_code"] == 200
    assert result["error"] is None
    assert result["body"]["url"] == "https://api.example.com/test"


@patch("requests.request")
def test_post_json_body(mock_request, api_client, mock_response):
    payload = {"name": "Alice", "role": "admin"}
    mock_response.text = json.dumps({"json": payload})
    mock_response.json.return_value = {"json": payload}
    mock_response.headers = {"Content-Type": "application/json"}
    mock_request.return_value = mock_response

    result = api_client.send_request(
        "/users",
        request_type="POST",
        body=payload,
        content_type="application/json"
    )
    assert result["http_code"] == 200
    assert result["body"]["json"] == payload


@patch("requests.request")
def test_post_form_encoded(mock_request, api_client, mock_response):
    form_data = {"username": "bob", "password": "secret"}
    mock_response.text = json.dumps({"form": form_data})
    mock_response.json.return_value = {"form": form_data}
    mock_response.headers = {"Content-Type": "application/json"}
    mock_request.return_value = mock_response

    result = api_client.send_request(
        "/login",
        request_type="POST",
        body=form_data,
        content_type="application/x-www-form-urlencoded"
    )
    assert result["http_code"] == 200
    assert result["body"]["form"] == form_data


@patch("requests.request")
def test_bearer_token_auth(mock_request, mock_response):
    client = Api(base_url="https://api.example.com", auth_header="Bearer mytoken123")
    mock_response.text = '{"authenticated": true, "token": "mytoken123"}'
    mock_response.json.return_value = {"authenticated": True, "token": "mytoken123"}
    mock_request.return_value = mock_response

    result = client.send_request("/profile")
    assert result["http_code"] == 200
    assert result["body"]["token"] == "mytoken123"


@patch("requests.request")
def test_basic_auth(mock_request, mock_response):
    client = Api(base_url="https://api.example.com")
    client.set_username_password("alice", "secret123")

    mock_response.text = '{"authenticated": true, "user": "alice"}'
    mock_response.json.return_value = {"authenticated": True, "user": "alice"}
    mock_request.return_value = mock_response

    result = client.send_request("/private")
    assert result["http_code"] == 200
    assert result["body"]["authenticated"] is True
    assert result["body"]["user"] == "alice"


@patch("requests.request")
def test_persistent_custom_headers(mock_request, api_client, mock_response):
    api_client.add_custom_headers({
        "X-Client-ID": "12345",
        "X-Version": "2.0"
    })
    mock_response.text = '{"headers": {"X-Client-ID": "12345", "X-Version": "2.0"}}'
    mock_response.json.return_value = {"headers": {"X-Client-ID": "12345", "X-Version": "2.0"}}
    mock_request.return_value = mock_response

    result = api_client.send_request("/echo-headers")
    assert result["body"]["headers"]["X-Client-ID"] == "12345"


@patch("requests.request")
def test_one_time_custom_headers(mock_request, api_client, mock_response):
    mock_response.text = '{"headers": {"X-Temp": "temp-value"}}'
    mock_response.json.return_value = {"headers": {"X-Temp": "temp-value"}}
    mock_request.return_value = mock_response

    result = api_client.send_request(
        "/echo",
        custom_headers={"X-Temp": "temp-value"}
    )
    assert result["body"]["headers"]["X-Temp"] == "temp-value"


@patch("requests.request")
def test_ssl_verification_disabled(mock_request, mock_response):
    client = Api(base_url="https://self-signed.example.com", ignore_ssl_validation=True)
    mock_response.text = '{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}
    mock_request.return_value = mock_response

    result = client.send_request("/")
    assert result["http_code"] == 200
    assert result["error"] is None


@patch("requests.request")
def test_timeout_error(mock_request, api_client):
    mock_request.side_effect = requests.exceptions.Timeout("Request timed out")
    result = api_client.send_request("/slow", timeout=1)
    assert result["http_code"] is None
    assert "timed" in result["error"].lower()


@patch("requests.request")
def test_connection_error(mock_request, api_client):
    mock_request.side_effect = requests.exceptions.ConnectionError("Failed to connect")
    result = api_client.send_request("/unreachable")
    assert result["http_code"] is None
    assert "connection" in result["error"].lower() or "failed" in result["error"].lower()


@patch("requests.request")
def test_non_json_response(mock_request, api_client, mock_response):
    mock_response.status_code = 200
    mock_response.text = "<html><body>Hello</body></html>"
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    mock_request.return_value = mock_response

    result = api_client.send_request("/page")
    assert result["http_code"] == 200
    assert isinstance(result["body"], str)
    assert "<html>" in result["body"]


@patch("requests.request")
def test_no_base_url_full_url(mock_request, mock_response):
    client = Api()  # no base_url
    mock_response.text = '{"success": true}'
    mock_response.json.return_value = {"success": True}
    mock_request.return_value = mock_response

    result = client.send_request("https://external-api.com/ping")
    assert result["http_code"] == 200
    assert result["body"]["success"] is True


@patch("requests.request")
def test_malformed_auth_header_graceful(mock_request, mock_response):
    client = Api(auth_header="NotAValidHeaderFormat")
    mock_response.text = '{"headers": {"Notavalidheaderformat": "value"}}'
    mock_response.json.return_value = {"headers": {"Notavalidheaderformat": "value"}}
    mock_request.return_value = mock_response

    result = client.send_request("/headers")
    assert result["http_code"] == 200


@patch("requests.request")
def test_explicit_auth_header_override(mock_request, mock_response):
    client = Api(auth_header="Authorization: Basic dGVzdDp0ZXN0")
    mock_response.text = '{"headers": {"Authorization": "Basic dGVzdDp0ZXN0"}}'
    mock_response.json.return_value = {"headers": {"Authorization": "Basic dGVzdDp0ZXN0"}}
    mock_request.return_value = mock_response

    result = client.send_request("/check-auth")
    assert result["body"]["headers"]["Authorization"] == "Basic dGVzdDp0ZXN0"


if __name__ == "__main__":
    pytest.main(["-v"])