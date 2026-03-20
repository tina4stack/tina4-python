# Tests for the Response callable pattern and HTTP constants.
import json
import pytest
from tina4_python.core.response import Response
from tina4_python.core.constants import (
    HTTP_OK, HTTP_CREATED, HTTP_NO_CONTENT, HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND, HTTP_UNAUTHORIZED, HTTP_SERVER_ERROR,
    APPLICATION_JSON, TEXT_HTML, TEXT_PLAIN,
)


class TestResponseCallable:
    """Test response(data, status, content_type) smart callable."""

    def test_dict_auto_json(self):
        r = Response()
        result = r({"key": "value"})
        assert result is r
        assert r.content_type == "application/json"
        assert r.status_code == 200
        assert json.loads(r.content) == {"key": "value"}

    def test_list_auto_json(self):
        r = Response()
        r([1, 2, 3])
        assert r.content_type == "application/json"
        assert json.loads(r.content) == [1, 2, 3]

    def test_dict_with_status(self):
        r = Response()
        r({"created": True}, HTTP_CREATED)
        assert r.status_code == 201
        assert r.content_type == "application/json"

    def test_html_auto_detect(self):
        r = Response()
        r("<h1>Hello</h1>")
        assert "text/html" in r.content_type
        assert r.content == b"<h1>Hello</h1>"

    def test_html_with_whitespace(self):
        r = Response()
        r("  <div>test</div>  ")
        assert "text/html" in r.content_type

    def test_plain_text(self):
        r = Response()
        r("hello world")
        assert "text/plain" in r.content_type

    def test_text_with_status(self):
        r = Response()
        r("Not found", HTTP_NOT_FOUND)
        assert r.status_code == 404
        assert "text/plain" in r.content_type

    def test_explicit_content_type(self):
        r = Response()
        r({"data": 1}, HTTP_OK, APPLICATION_JSON)
        assert r.content_type == APPLICATION_JSON
        assert r.status_code == 200

    def test_none_data(self):
        r = Response()
        r(None, HTTP_NO_CONTENT)
        assert r.status_code == 204
        assert r.content == b""

    def test_bytes_data(self):
        r = Response()
        r(b"\x89PNG")
        assert r.content_type == "application/octet-stream"
        assert r.content == b"\x89PNG"

    def test_number_to_string(self):
        r = Response()
        r(42)
        assert r.content == b"42"

    def test_chainable(self):
        r = Response()
        result = r({"ok": True}, HTTP_OK)
        assert result is r

    def test_empty_dict(self):
        r = Response()
        r({})
        assert r.content_type == "application/json"
        assert json.loads(r.content) == {}

    def test_nested_dict(self):
        data = {"users": [{"id": 1, "name": "Alice"}], "total": 1}
        r = Response()
        r(data)
        assert json.loads(r.content) == data


class TestResponseMethods:
    """Test explicit .json(), .html(), .text() methods still work."""

    def test_json_method(self):
        r = Response()
        result = r.json({"test": True})
        assert result is r
        assert r.content_type == "application/json"

    def test_html_method(self):
        r = Response()
        r.html("<p>Hello</p>")
        assert "text/html" in r.content_type

    def test_text_method(self):
        r = Response()
        r.text("hello")
        assert "text/plain" in r.content_type

    def test_redirect_method(self):
        r = Response()
        r.redirect("/login")
        assert r.status_code == 302
        assert ("location", "/login") in r._headers

    def test_status_chain(self):
        r = Response()
        r.status(201).json({"id": 1})
        assert r.status_code == 201

    def test_header_chain(self):
        r = Response()
        r.header("X-Custom", "value").json({"ok": True})
        assert ("X-Custom", "value") in r._headers

    def test_cookie(self):
        r = Response()
        r.cookie("session", "abc123")
        assert len(r._cookies) == 1
        assert "session=abc123" in r._cookies[0]


class TestHTTPConstants:
    """Verify all HTTP constants have correct values."""

    def test_success_codes(self):
        assert HTTP_OK == 200
        assert HTTP_CREATED == 201
        assert HTTP_NO_CONTENT == 204

    def test_client_error_codes(self):
        assert HTTP_BAD_REQUEST == 400
        assert HTTP_UNAUTHORIZED == 401
        assert HTTP_NOT_FOUND == 404

    def test_server_error_codes(self):
        assert HTTP_SERVER_ERROR == 500

    def test_content_types(self):
        assert APPLICATION_JSON == "application/json"
        assert "text/html" in TEXT_HTML
        assert "text/plain" in TEXT_PLAIN
