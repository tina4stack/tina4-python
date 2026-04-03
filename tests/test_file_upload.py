# File Upload Tests — uses the actual framework logo.svg
import pytest
from pathlib import Path
from tina4_python.core.request import Request

LOGO_PATH = Path(__file__).parent.parent / "tina4_python" / "public" / "images" / "logo.svg"


def _build_multipart(boundary, fields=None, files=None):
    parts = []
    for name, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    for name, fi in (files or {}).items():
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{fi["filename"]}"\r\n'
            f'Content-Type: {fi["type"]}\r\n\r\n'
        )
        parts.append(header.encode() + fi["content"] + b"\r\n")
    parts.append(f"--{boundary}--\r\n")
    body = b""
    for p in parts:
        body += p.encode() if isinstance(p, str) else p
    return body


def _make_request(body, content_type):
    scope = {
        "method": "POST", "path": "/api/upload", "query_string": b"",
        "headers": [(b"content-type", content_type.encode()), (b"content-length", str(len(body)).encode())],
    }
    return Request.from_scope(scope, body)


class TestSingleFileUpload:
    def test_file_in_request_files(self):
        logo = LOGO_PATH.read_bytes()
        boundary = "----TB123"
        body = _build_multipart(boundary, files={"avatar": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert "avatar" in req.files
        assert req.files["avatar"]["filename"] == "logo.svg"
        assert req.files["avatar"]["type"] == "image/svg+xml"
        assert req.files["avatar"]["size"] > 0

    def test_content_is_raw_bytes_not_base64(self):
        logo = LOGO_PATH.read_bytes()
        boundary = "----TB456"
        body = _build_multipart(boundary, files={"file": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        content = req.files["file"]["content"]
        assert isinstance(content, (bytes, bytearray)), f"Expected bytes, got {type(content)}"
        assert b"<svg" in content

    def test_svg_content_readable(self):
        logo = LOGO_PATH.read_bytes()
        boundary = "----TB789"
        body = _build_multipart(boundary, files={"img": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert b"<svg" in req.files["img"]["content"] or b"<?xml" in req.files["img"]["content"]


class TestFieldSeparation:
    def test_fields_in_body_files_in_files(self):
        logo = LOGO_PATH.read_bytes()
        boundary = "----SEP"
        body = _build_multipart(boundary, fields={"title": "My Logo"}, files={"logo": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert req.body["title"] == "My Logo"
        assert "logo" in req.files
        assert "logo" not in req.body

    def test_only_fields_no_files(self):
        boundary = "----NOFILE"
        body = _build_multipart(boundary, fields={"name": "Alice"})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert req.files == {}
        assert req.body["name"] == "Alice"


class TestMultipleFiles:
    def test_two_files(self):
        logo = LOGO_PATH.read_bytes()
        boundary = "----MULTI"
        body = _build_multipart(boundary, files={
            "avatar": {"filename": "avatar.svg", "type": "image/svg+xml", "content": logo},
            "banner": {"filename": "banner.svg", "type": "image/svg+xml", "content": logo},
        })
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert req.files["avatar"]["filename"] == "avatar.svg"
        assert req.files["banner"]["filename"] == "banner.svg"


class TestMaxUploadSize:
    def test_oversized_rejected(self, monkeypatch):
        import tina4_python.core.request as req_mod
        monkeypatch.setattr(req_mod, "TINA4_MAX_UPLOAD_SIZE", 10)
        logo = LOGO_PATH.read_bytes()
        boundary = "----SIZE"
        body = _build_multipart(boundary, files={"file": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        with pytest.raises(Exception):
            _make_request(body, f"multipart/form-data; boundary={boundary}")

    def test_undersized_accepted(self, monkeypatch):
        monkeypatch.setenv("TINA4_MAX_UPLOAD_SIZE", "10485760")
        logo = LOGO_PATH.read_bytes()
        boundary = "----OK"
        body = _build_multipart(boundary, files={"file": {"filename": "logo.svg", "type": "image/svg+xml", "content": logo}})
        req = _make_request(body, f"multipart/form-data; boundary={boundary}")
        assert "file" in req.files
