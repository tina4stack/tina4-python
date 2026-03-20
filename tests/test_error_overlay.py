"""Tests for tina4_python.debug.error_overlay."""
import os
import pytest
from tina4_python.debug.error_overlay import (
    render_error_overlay,
    render_production_error,
    is_debug_mode,
)


class TestRenderErrorOverlay:
    """Tests for render_error_overlay()."""

    def _make_exception(self):
        """Create a real exception with a traceback."""
        try:
            raise ValueError("something broke")
        except ValueError as exc:
            return exc

    def test_returns_html_string(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_exception_type(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "ValueError" in html

    def test_contains_exception_message(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "something broke" in html

    def test_contains_file_path(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "test_error_overlay.py" in html

    def test_contains_source_code(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        # Should contain the raise statement from _make_exception
        assert "raise ValueError" in html

    def test_contains_error_line_marker(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        # The triangle marker for the error line
        assert "&#x25b6;" in html

    def test_with_dict_request(self):
        exc = self._make_exception()
        request = {"method": "GET", "url": "/api/users", "headers": {"host": "localhost"}}
        html = render_error_overlay(exc, request=request)
        assert "GET" in html
        assert "/api/users" in html
        assert "localhost" in html
        assert "Request Details" in html

    def test_without_request(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "Request Details" not in html

    def test_contains_environment_section(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "Environment" in html
        assert "Tina4 Python" in html
        assert "Python" in html

    def test_contains_debug_mode_footer(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "TINA4_DEBUG_LEVEL" in html

    def test_escapes_html_in_message(self):
        try:
            raise RuntimeError("<script>alert('xss')</script>")
        except RuntimeError as exc:
            html = render_error_overlay(exc)
            assert "<script>" not in html
            assert "&lt;script&gt;" in html

    def test_stack_trace_section_open(self):
        exc = self._make_exception()
        html = render_error_overlay(exc)
        assert "Stack Trace" in html
        assert "<details" in html
        assert "open" in html


class TestRenderProductionError:
    """Tests for render_production_error()."""

    def test_returns_html_string(self):
        html = render_production_error()
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_status_code(self):
        html = render_production_error(404, "Not Found")
        assert "404" in html
        assert "Not Found" in html

    def test_does_not_contain_stack_trace(self):
        html = render_production_error()
        assert "Stack Trace" not in html
        assert "traceback" not in html.lower()

    def test_default_500(self):
        html = render_production_error()
        assert "500" in html
        assert "Internal Server Error" in html


class TestIsDebugMode:
    """Tests for is_debug_mode()."""

    def test_all_is_debug(self):
        os.environ["TINA4_DEBUG_LEVEL"] = "ALL"
        assert is_debug_mode() is True

    def test_debug_is_debug(self):
        os.environ["TINA4_DEBUG_LEVEL"] = "DEBUG"
        assert is_debug_mode() is True

    def test_case_insensitive(self):
        os.environ["TINA4_DEBUG_LEVEL"] = "all"
        assert is_debug_mode() is True

    def test_warning_is_not_debug(self):
        os.environ["TINA4_DEBUG_LEVEL"] = "WARNING"
        assert is_debug_mode() is False

    def test_error_is_not_debug(self):
        os.environ["TINA4_DEBUG_LEVEL"] = "ERROR"
        assert is_debug_mode() is False

    def test_empty_is_not_debug(self):
        os.environ.pop("TINA4_DEBUG_LEVEL", None)
        assert is_debug_mode() is False
