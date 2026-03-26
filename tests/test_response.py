#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import json
import os
import pytest
from datetime import datetime, date
from tina4_python.Response import Response
from tina4_python import Constant


# --- Basic construction ---

def test_default_response():
    r = Response("Hello")
    assert r.content == "Hello"
    assert r.http_code == Constant.HTTP_OK
    assert r.content_type == Constant.TEXT_HTML


def test_custom_http_code():
    r = Response("Not Found", Constant.HTTP_NOT_FOUND)
    assert r.http_code == Constant.HTTP_NOT_FOUND


def test_custom_content_type():
    r = Response("data", Constant.HTTP_OK, Constant.APPLICATION_JSON)
    assert r.content_type == Constant.APPLICATION_JSON


def test_none_content():
    r = Response(None)
    assert r.content == ""


def test_none_http_code_defaults():
    r = Response("test", None)
    assert r.http_code == Constant.HTTP_OK


# --- Auto content type detection ---

def test_dict_auto_json():
    r = Response({"key": "value"})
    assert r.content_type == Constant.APPLICATION_JSON
    parsed = json.loads(r.content)
    assert parsed["key"] == "value"


def test_list_auto_json():
    r = Response([1, 2, 3])
    assert r.content_type == Constant.APPLICATION_JSON
    parsed = json.loads(r.content)
    assert parsed == [1, 2, 3]


def test_bool_true():
    r = Response(True)
    assert r.content == "True"


def test_bool_false():
    r = Response(False)
    assert r.content == "False"


# --- convert_special_types ---

def test_convert_dict_with_datetime():
    data = {"created": datetime(2025, 1, 1, 12, 0)}
    result = Response.convert_special_types(data)
    assert result["created"] == "2025-01-01T12:00:00"


def test_convert_dict_with_date():
    data = {"day": date(2025, 6, 15)}
    result = Response.convert_special_types(data)
    assert result["day"] == "2025-06-15"


def test_convert_nested():
    data = {"items": [{"dt": datetime(2025, 3, 1)}]}
    result = Response.convert_special_types(data)
    assert result["items"][0]["dt"] == "2025-03-01T00:00:00"


def test_convert_primitives():
    assert Response.convert_special_types("hello") == "hello"
    assert Response.convert_special_types(42) == 42
    assert Response.convert_special_types(None) is None


# --- Headers ---

def test_custom_headers():
    r = Response("test", headers_in={"X-Custom": "value"})
    assert r.headers["X-Custom"] == "value"


def test_add_header():
    Response.reset_context()
    Response.add_header("X-Test", "123")
    r = Response("test")
    assert r.headers.get("X-Test") == "123"


def test_add_header_merged():
    Response.reset_context()
    Response.add_header("X-A", "1")
    Response.add_header("X-B", "2")
    r = Response("test")
    assert r.headers.get("X-A") == "1"
    assert r.headers.get("X-B") == "2"


def test_headers_in_merges_with_pending():
    """headers_in should merge with pending headers, not replace them."""
    Response.reset_context()
    Response.add_header("X-Pending", "old")
    r = Response("test", headers_in={"X-Explicit": "new"})
    assert r.headers.get("X-Explicit") == "new"
    assert r.headers.get("X-Pending") == "old"


def test_add_header_survives_redirect():
    """Headers set via add_header() must survive Response.redirect()."""
    Response.reset_context()
    Response.add_header("Set-Cookie", "session=abc123; Path=/; HttpOnly")
    r = Response.redirect("/dashboard")
    assert r.headers.get("Location") == "/dashboard"
    assert r.headers.get("Set-Cookie") == "session=abc123; Path=/; HttpOnly"
    assert r.http_code == Constant.HTTP_REDIRECT


def test_multiple_add_headers_survive_redirect():
    """Multiple headers set via add_header() must all survive redirect."""
    Response.reset_context()
    Response.add_header("Set-Cookie", "token=xyz; Path=/")
    Response.add_header("X-Custom", "value")
    r = Response.redirect("/login")
    assert r.headers.get("Location") == "/login"
    assert r.headers.get("Set-Cookie") == "token=xyz; Path=/"
    assert r.headers.get("X-Custom") == "value"


def test_reset_context():
    Response.reset_context()
    Response.add_header("X-Before", "1")
    Response.reset_context()
    r = Response("test")
    assert "X-Before" not in r.headers


# --- redirect ---

def test_redirect():
    r = Response.redirect("/login")
    assert r.http_code == Constant.HTTP_REDIRECT
    assert r.headers["Location"] == "/login"
    assert r.content_type == Constant.TEXT_HTML


def test_redirect_custom_code():
    r = Response.redirect("/new-url", Constant.HTTP_REDIRECT_MOVED)
    assert r.http_code == Constant.HTTP_REDIRECT_MOVED
    assert r.headers["Location"] == "/new-url"


# --- file ---

def test_file_not_found():
    r = Response.file("nonexistent.txt", root_path="/tmp")
    assert r.http_code == Constant.HTTP_NOT_FOUND


def test_file_directory_traversal():
    r = Response.file("../../etc/passwd", root_path="/tmp/safe")
    assert r.http_code == Constant.HTTP_FORBIDDEN


def test_file_serves_content(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    r = Response.file("test.txt", root_path=str(tmp_path))
    assert r.http_code == Constant.HTTP_OK
    assert r.content == "hello world"
    assert r.content_type == Constant.TEXT_PLAIN


def test_file_binary(tmp_path):
    test_file = tmp_path / "image.png"
    test_file.write_bytes(b"\x89PNG\r\n")
    r = Response.file("image.png", root_path=str(tmp_path))
    assert r.http_code == Constant.HTTP_OK
    assert r.content == b"\x89PNG\r\n"
    assert r.content_type == "image/png"


def test_file_css(tmp_path):
    test_file = tmp_path / "style.css"
    test_file.write_text("body { margin: 0; }")
    r = Response.file("style.css", root_path=str(tmp_path))
    assert r.content_type == Constant.TEXT_CSS


def test_file_json(tmp_path):
    test_file = tmp_path / "data.json"
    test_file.write_text('{"key": "value"}')
    r = Response.file("data.json", root_path=str(tmp_path))
    assert r.content_type == Constant.APPLICATION_JSON


def test_file_unknown_extension(tmp_path):
    test_file = tmp_path / "data.xyz"
    test_file.write_bytes(b"\x00\x01")
    r = Response.file("data.xyz", root_path=str(tmp_path))
    assert r.content_type == "application/octet-stream"
