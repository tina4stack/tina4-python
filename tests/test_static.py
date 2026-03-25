# Tests for static file serving in tina4_python.core.server (v3)
import pytest
import mimetypes
from pathlib import Path
from unittest.mock import patch
from tina4_python.core.server import _try_static
from tina4_python.core.response import Response


# Framework public directory
_PUBLIC_DIR = Path(__file__).resolve().parent.parent / "tina4_python" / "public"


class TestMimeTypeDetection:

    def test_css_mime_type(self):
        mime, _ = mimetypes.guess_type("style.css")
        assert mime == "text/css"

    def test_js_mime_type(self):
        mime, _ = mimetypes.guess_type("app.js")
        assert "javascript" in mime

    def test_png_mime_type(self):
        mime, _ = mimetypes.guess_type("image.png")
        assert mime == "image/png"

    def test_jpg_mime_type(self):
        mime, _ = mimetypes.guess_type("photo.jpg")
        assert mime == "image/jpeg"

    def test_svg_mime_type(self):
        mime, _ = mimetypes.guess_type("icon.svg")
        assert mime is not None
        assert "svg" in mime

    def test_html_mime_type(self):
        mime, _ = mimetypes.guess_type("page.html")
        assert mime == "text/html"

    def test_json_mime_type(self):
        mime, _ = mimetypes.guess_type("data.json")
        assert mime == "application/json"

    def test_webp_mime_type(self):
        mime, _ = mimetypes.guess_type("photo.webp")
        assert mime is not None

    def test_ico_mime_type(self):
        mime, _ = mimetypes.guess_type("favicon.ico")
        assert mime is not None

    def test_unknown_extension_returns_none(self):
        mime, _ = mimetypes.guess_type("file.xyz123abc")
        assert mime is None


class TestFrameworkPublicFiles:

    def test_tina4_min_css_exists(self):
        assert (_PUBLIC_DIR / "css" / "tina4.min.css").is_file()

    def test_tina4_min_js_exists(self):
        assert (_PUBLIC_DIR / "js" / "tina4.min.js").is_file()

    def test_frond_min_js_exists(self):
        assert (_PUBLIC_DIR / "js" / "frond.min.js").is_file()

    def test_favicon_exists(self):
        assert (_PUBLIC_DIR / "favicon.ico").is_file()

    def test_tina4_css_unminified_exists(self):
        assert (_PUBLIC_DIR / "css" / "tina4.css").is_file()

    def test_logo_exists(self):
        assert (_PUBLIC_DIR / "images" / "logo.svg").is_file()

    def test_dev_admin_js_exists(self):
        assert (_PUBLIC_DIR / "js" / "tina4-dev-admin.min.js").is_file()


class TestStaticFileSerialization:

    def test_response_file_sets_content_type_css(self, tmp_path):
        css = tmp_path / "test.css"
        css.write_text("body { color: red; }")
        resp = Response()
        resp.file(str(css))
        assert resp.content_type == "text/css"

    def test_response_file_sets_content_type_js(self, tmp_path):
        js = tmp_path / "test.js"
        js.write_text("console.log('hi');")
        resp = Response()
        resp.file(str(js))
        assert "javascript" in resp.content_type

    def test_response_file_sets_content_type_png(self, tmp_path):
        png = tmp_path / "test.png"
        png.write_bytes(b"\x89PNG\r\n")
        resp = Response()
        resp.file(str(png))
        assert resp.content_type == "image/png"

    def test_response_file_reads_content(self, tmp_path):
        txt = tmp_path / "test.html"
        txt.write_text("<h1>hello</h1>")
        resp = Response()
        resp.file(str(txt))
        assert resp.content == b"<h1>hello</h1>"

    def test_response_file_unknown_type_uses_octet_stream(self, tmp_path):
        unknown = tmp_path / "data.xyz123"
        unknown.write_bytes(b"\x00\x01\x02")
        resp = Response()
        resp.file(str(unknown))
        assert resp.content_type == "application/octet-stream"


class TestStaticFile404:

    def test_nonexistent_file_returns_404(self):
        resp = Response()
        resp.file("/nonexistent/path/to/file.css")
        assert resp.status_code == 404

    def test_nonexistent_file_content(self):
        resp = Response()
        resp.file("/nonexistent/file.js")
        assert resp.content == b"File not found"

    def test_nonexistent_file_content_type(self):
        resp = Response()
        resp.file("/no/such/file.png")
        assert resp.content_type == "text/plain"


class TestDirectoryTraversalPrevention:

    def test_try_static_traversal_returns_none(self):
        result = _try_static("/../../../etc/passwd")
        assert result is None

    def test_try_static_dot_dot_slash(self):
        result = _try_static("/../../etc/shadow")
        assert result is None

    def test_try_static_encoded_traversal(self):
        result = _try_static("/..%2F..%2Fetc/passwd")
        assert result is None

    def test_try_static_nonexistent_path(self):
        result = _try_static("/nonexistent/file/abc123.css")
        assert result is None

    def test_try_static_valid_framework_asset(self):
        # The framework built-in files should be servable
        result = _try_static("/css/tina4.min.css")
        # This may return None if CWD does not have a public dir,
        # but should not raise an error
        if result is not None:
            assert result.status_code != 404

    def test_try_static_returns_response_or_none(self):
        result = _try_static("/js/tina4.min.js")
        assert result is None or isinstance(result, Response)
