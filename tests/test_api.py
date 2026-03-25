# Tests for tina4_python.api (v3)
import pytest
import base64
import json
from unittest.mock import patch, MagicMock
from tina4_python.api import Api


class TestApiInstantiation:

    def test_default_instance(self):
        api = Api()
        assert api.base_url == ""
        assert api.auth_header == ""
        assert api.timeout == 30

    def test_base_url_strips_trailing_slash(self):
        api = Api("https://api.example.com/")
        assert api.base_url == "https://api.example.com"

    def test_custom_timeout(self):
        api = Api("https://api.example.com", timeout=60)
        assert api.timeout == 60

    def test_auth_header_passed_in(self):
        api = Api("https://api.example.com", auth_header="Bearer abc123")
        assert api.auth_header == "Bearer abc123"

    def test_ignore_ssl_creates_context(self):
        api = Api("https://self-signed.local", ignore_ssl=True)
        assert api._ssl_context is not None
        assert api._ssl_context.check_hostname is False

    def test_ignore_ssl_false_no_context(self):
        api = Api("https://api.example.com", ignore_ssl=False)
        assert api._ssl_context is None


class TestAuthMethods:

    def test_set_basic_auth(self):
        api = Api()
        api.set_basic_auth("user", "pass")
        expected = "Basic " + base64.b64encode(b"user:pass").decode()
        assert api.auth_header == expected

    def test_set_bearer_token(self):
        api = Api()
        api.set_bearer_token("mytoken")
        assert api.auth_header == "Bearer mytoken"

    def test_set_bearer_overwrites_basic(self):
        api = Api()
        api.set_basic_auth("user", "pass")
        api.set_bearer_token("tok")
        assert api.auth_header == "Bearer tok"

    def test_add_headers(self):
        api = Api()
        api.add_headers({"X-Custom": "value1"})
        assert api._headers["X-Custom"] == "value1"

    def test_add_headers_merges(self):
        api = Api()
        api.add_headers({"X-One": "1"})
        api.add_headers({"X-Two": "2"})
        assert api._headers["X-One"] == "1"
        assert api._headers["X-Two"] == "2"

    def test_add_headers_overwrites_existing(self):
        api = Api()
        api.add_headers({"X-Key": "old"})
        api.add_headers({"X-Key": "new"})
        assert api._headers["X-Key"] == "new"


class TestUrlBuilding:

    def test_url_with_path(self):
        api = Api("https://api.example.com")
        assert api._url("/users") == "https://api.example.com/users"

    def test_url_strips_leading_slash(self):
        api = Api("https://api.example.com")
        assert api._url("users") == "https://api.example.com/users"

    def test_url_empty_path_returns_base(self):
        api = Api("https://api.example.com")
        assert api._url("") == "https://api.example.com"

    def test_url_absolute_url_passthrough(self):
        api = Api("https://api.example.com")
        result = api._url("https://other.com/path")
        assert result == "https://other.com/path"

    def test_url_http_passthrough(self):
        api = Api("https://api.example.com")
        result = api._url("http://other.com/data")
        assert result == "http://other.com/data"


class TestMethodSignatures:

    def test_get_method_exists(self):
        api = Api()
        assert callable(api.get)

    def test_post_method_exists(self):
        api = Api()
        assert callable(api.post)

    def test_put_method_exists(self):
        api = Api()
        assert callable(api.put)

    def test_patch_method_exists(self):
        api = Api()
        assert callable(api.patch)

    def test_delete_method_exists(self):
        api = Api()
        assert callable(api.delete)

    def test_send_method_exists(self):
        api = Api()
        assert callable(api.send)


class TestRequestConstruction:

    @patch("tina4_python.api.urlopen")
    def test_get_builds_correct_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        api.set_bearer_token("tok123")
        api.get("/users")

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.example.com/users"
        assert req.get_method() == "GET"
        assert req.get_header("Authorization") == "Bearer tok123"

    @patch("tina4_python.api.urlopen")
    def test_post_sends_json_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.read.return_value = b'{"id": 1}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        api.post("/users", body={"name": "Alice"})

        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.data == json.dumps({"name": "Alice"}).encode("utf-8")
        assert req.get_header("Content-type") == "application/json"

    @patch("tina4_python.api.urlopen")
    def test_get_with_params_appends_query_string(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'[]'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        api.get("/search", params={"q": "test", "page": "1"})

        req = mock_urlopen.call_args[0][0]
        assert "q=test" in req.full_url
        assert "page=1" in req.full_url

    @patch("tina4_python.api.urlopen")
    def test_delete_method(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.read.return_value = b''
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        result = api.delete("/users/1")

        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "DELETE"

    @patch("tina4_python.api.urlopen")
    def test_custom_headers_sent(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        api.add_headers({"X-Tenant": "acme"})
        api.get("/data")

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("X-tenant") == "acme"

    @patch("tina4_python.api.urlopen")
    def test_response_format(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"users": []}'
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        result = api.get("/users")

        assert result["http_code"] == 200
        assert result["body"] == {"users": []}
        assert result["error"] is None
        assert "headers" in result

    @patch("tina4_python.api.urlopen")
    def test_send_generic_method(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{}'
        mock_resp.headers = {}
        mock_urlopen.return_value = mock_resp

        api = Api("https://api.example.com")
        api.send("OPTIONS", "/resource")

        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "OPTIONS"


class TestErrorHandling:

    @patch("tina4_python.api.urlopen")
    def test_url_error_returns_error_dict(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        api = Api("https://unreachable.example.com")
        result = api.get("/data")

        assert result["http_code"] is None
        assert result["error"] == "Connection refused"
        assert result["body"] is None

    @patch("tina4_python.api.urlopen")
    def test_generic_exception_returns_error_dict(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Something broke")

        api = Api("https://api.example.com")
        result = api.get("/data")

        assert result["http_code"] is None
        assert "Something broke" in result["error"]
