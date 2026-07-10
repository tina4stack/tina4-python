# Real, no-mock tests for the tina4_python.api transfer features (v3):
#   - multipart upload()  (from disk AND in-memory bytes)
#   - streaming download()
#   - the injectable transport seam
#   - the opt-in cookie jar
#   - the cross-origin Authorization/Cookie strip on redirects (regression)
#
# Every test drives a REAL threaded http.server bound to 127.0.0.1:0 and makes
# REAL socket round-trips. Nothing is mocked, monkeypatched, or faked: the
# server records exactly what it received off the wire so the assertions are on
# real bytes, not on "was a method called". This mirrors tests/test_api.py.
#
# The transport-seam test deliberately injects a REAL alternate transport (one
# that itself performs a genuine urllib round-trip to the local server) — never
# a canned/fake transport, so the framework suite stays free of mocks per the
# no-mock rule. The canned-fake pattern is for APPLICATION code, not here.
import json
import os
import threading
import http.server
import urllib.request

import pytest

from tina4_python.api import Api


# ──────────────────────────────────────────────────────────────────────────
# Local recording server (same shape as tests/test_api.py). Records method,
# path, headers and the raw body of every request; serves scripted responses.
# ──────────────────────────────────────────────────────────────────────────
class _RecordingServer:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.requests = []
        records = self.requests
        routes_ref = self.routes

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _record_and_reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                records.append({
                    "method": self.command,
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                key = (self.command, self.path.split("?", 1)[0])
                status, hdrs, payload = routes_ref.get(
                    key, (200, {"Content-Type": "application/json"}, b'{"ok": true}'))
                self.send_response(status)
                for hk, hv in (hdrs or {}).items():
                    self.send_header(hk, hv)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            do_GET = _record_and_reply
            do_POST = _record_and_reply
            do_PUT = _record_and_reply
            do_DELETE = _record_and_reply

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server():
    with _RecordingServer() as s:
        yield s


# ──────────────────────────────────────────────────────────────────────────
# A small, explicit multipart/form-data parser so the server can assert the
# EXACT bytes and fields it received. Deliberately hand-rolled (no cgi — gone
# in 3.13) and controllable rather than pulling anything in.
# ──────────────────────────────────────────────────────────────────────────
def _disposition_param(disposition: str, key: str):
    token = f'{key}="'
    start = disposition.find(token)
    if start == -1:
        return None
    start += len(token)
    end = disposition.find('"', start)
    return disposition[start:end]


def parse_multipart(content_type: str, body: bytes):
    boundary = content_type.split("boundary=", 1)[1].strip()
    marker = ("--" + boundary).encode("utf-8")
    fields, files = {}, {}
    for segment in body.split(marker):
        if segment in (b"", b"\r\n", b"--", b"--\r\n"):
            continue
        if segment.startswith(b"\r\n"):
            segment = segment[2:]
        if segment.endswith(b"\r\n"):
            segment = segment[:-2]
        header_blob, sep, content = segment.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, _, v = line.partition(b":")
                headers[k.strip().lower().decode()] = v.strip().decode()
        disposition = headers.get("content-disposition", "")
        name = _disposition_param(disposition, "name")
        filename = _disposition_param(disposition, "filename")
        if filename is not None:
            files[name] = {"filename": filename, "content": content,
                           "content_type": headers.get("content-type")}
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fields, files


# ──────────────────────────────────────────────────────────────────────────
# upload() — multipart/form-data, from disk and from in-memory bytes.
# ──────────────────────────────────────────────────────────────────────────
class TestUpload:

    def test_upload_file_from_disk_sends_exact_bytes_and_fields(self, server, tmp_path):
        payload = b"\x00\x01\x02hello-tina4\xffbinary-bytes"
        src = tmp_path / "report.bin"
        src.write_bytes(payload)
        server.routes[("POST", "/files")] = (
            201, {"Content-Type": "application/json"}, b'{"stored": true}')

        api = Api(server.base_url)
        result = api.upload("/files", file_path=str(src),
                            extra_fields={"user_id": "42", "kind": "report"})

        assert result["http_code"] == 201
        assert result["body"] == {"stored": True}
        assert result["error"] is None

        rec = server.requests[-1]
        assert rec["method"] == "POST"
        assert rec["content_type"].startswith("multipart/form-data; boundary=----Tina4Boundary")
        fields, files = parse_multipart(rec["content_type"], rec["body"])
        assert fields == {"user_id": "42", "kind": "report"}
        assert files["file"]["content"] == payload          # exact bytes on the wire
        assert files["file"]["filename"] == "report.bin"

    def test_upload_in_memory_bytes_variant(self, server):
        payload = b"in-memory-\x89PNG-ish-data"
        api = Api(server.base_url)
        result = api.upload("/files", file_bytes=payload, filename="avatar.png",
                            field_name="avatar", extra_fields={"scope": "profile"})

        assert result["http_code"] == 200
        rec = server.requests[-1]
        fields, files = parse_multipart(rec["content_type"], rec["body"])
        assert fields == {"scope": "profile"}
        assert files["avatar"]["content"] == payload
        assert files["avatar"]["filename"] == "avatar.png"
        # content-type guessed from the .png filename
        assert files["avatar"]["content_type"] == "image/png"

    def test_upload_guesses_octet_stream_for_unknown_extension(self, server):
        api = Api(server.base_url)
        api.upload("/files", file_bytes=b"data", filename="blob.unknownext")
        rec = server.requests[-1]
        _, files = parse_multipart(rec["content_type"], rec["body"])
        assert files["file"]["content_type"] == "application/octet-stream"

    def test_upload_per_call_header_is_sent(self, server):
        api = Api(server.base_url)
        api.upload("/files", file_bytes=b"x", filename="x.txt",
                   headers={"X-Upload-Token": "abc"})
        rec = server.requests[-1]
        assert rec["headers"]["x-upload-token"] == "abc"

    # ── negative cases ──────────────────────────────────────────────────
    def test_upload_missing_file_returns_clean_error(self, server, tmp_path):
        api = Api(server.base_url)
        result = api.upload("/files", file_path=str(tmp_path / "does-not-exist.bin"))
        assert result["http_code"] is None
        assert result["error"] is not None
        assert "not found" in result["error"]
        assert server.requests == []   # nothing was ever sent

    def test_upload_no_source_returns_clean_error(self, server):
        api = Api(server.base_url)
        result = api.upload("/files")
        assert result["http_code"] is None
        assert result["error"] is not None
        assert server.requests == []


# ──────────────────────────────────────────────────────────────────────────
# download() — chunked streaming to a destination file.
# ──────────────────────────────────────────────────────────────────────────
class TestDownload:

    def test_download_streams_large_body_to_file(self, server, tmp_path):
        # A few MB of real random bytes served over a real socket; the client
        # streams it to disk in 64 KB chunks and the file must match byte-for-byte.
        big = os.urandom(3 * 1024 * 1024 + 777)   # 3 MB + change (not chunk-aligned)
        server.routes[("GET", "/blob")] = (
            200, {"Content-Type": "application/octet-stream"}, big)
        dest = tmp_path / "downloaded.bin"

        api = Api(server.base_url)
        result = api.download("/blob", dest_path=str(dest))

        assert result["http_code"] == 200
        assert result["error"] is None
        assert result["path"] == str(dest)
        assert "body" not in result                 # body went to disk, not memory
        assert dest.read_bytes() == big             # exact bytes

    def test_download_with_params_appends_query_string(self, server, tmp_path):
        dest = tmp_path / "q.json"
        api = Api(server.base_url)
        api.download("/data", dest_path=str(dest), params={"format": "raw"})
        rec = server.requests[-1]
        assert rec["path"].startswith("/data?")
        assert "format=raw" in rec["path"]

    # ── negative cases ──────────────────────────────────────────────────
    def test_download_missing_dest_returns_error(self, server):
        api = Api(server.base_url)
        result = api.download("/blob")
        assert result["path"] is None
        assert result["error"] is not None
        assert result["http_code"] is None

    def test_download_http_error_writes_no_file(self, server, tmp_path):
        server.routes[("GET", "/missing")] = (
            404, {"Content-Type": "application/json"}, b'{"error": "nope"}')
        dest = tmp_path / "should-not-exist.bin"
        api = Api(server.base_url)
        result = api.download("/missing", dest_path=str(dest))
        assert result["http_code"] == 404
        assert result["path"] is None
        assert result["error"] is not None
        assert not dest.exists()               # no partial/garbage file on error

    def test_download_transport_failure_returns_error(self, tmp_path):
        # Real connection refused to a dead port — no mock.
        api = Api("http://127.0.0.1:1", timeout=2)
        result = api.download("/blob", dest_path=str(tmp_path / "x.bin"))
        assert result["http_code"] is None
        assert result["path"] is None
        assert result["error"] is not None


# ──────────────────────────────────────────────────────────────────────────
# Transport seam — REAL alternate transport (not a mock): the injected
# callable performs a genuine urllib round-trip to the real local server, so
# this proves the seam is honoured while still doing real socket I/O.
# ──────────────────────────────────────────────────────────────────────────
class TestTransportSeam:

    def test_injected_real_transport_replaces_default_path(self, server):
        server.routes[("GET", "/seam")] = (
            200, {"Content-Type": "application/json"}, b'{"via": "transport"}')
        calls = []

        def real_transport(method, url, headers, body, timeout):
            # A genuine network call through a DIFFERENT code path (bare urllib),
            # proving the seam replaces Api's own opener. No canned data.
            calls.append((method, url))
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return {"http_code": resp.status, "body": json.loads(raw),
                    "headers": dict(resp.headers), "error": None}

        api = Api(server.base_url, transport=real_transport)
        result = api.get("/seam")

        assert calls and calls[0][0] == "GET"            # the seam was used
        assert result["http_code"] == 200
        assert result["body"] == {"via": "transport"}    # its result flows out
        assert server.requests[-1]["path"] == "/seam"    # server really got hit

    def test_default_transport_is_none_real_network_used(self, server):
        # NEGATIVE/contract: with no transport, the real urllib path is used.
        api = Api(server.base_url)
        assert api._transport is None
        result = api.get("/anything")
        assert result["http_code"] == 200
        assert server.requests[-1]["path"] == "/anything"


# ──────────────────────────────────────────────────────────────────────────
# Cookie jar — opt-in (off by default), in-memory, per-client.
# ──────────────────────────────────────────────────────────────────────────
class TestCookieJar:

    def test_set_cookie_is_sent_on_next_request(self, server):
        server.routes[("GET", "/login")] = (
            200, {"Set-Cookie": "session=abc123; Path=/; HttpOnly"}, b"ok")

        api = Api(server.base_url, cookies=True)
        api.get("/login")           # response sets the cookie
        api.get("/dashboard")       # next request must carry it

        rec = server.requests[-1]
        assert rec["path"] == "/dashboard"
        assert rec["headers"].get("cookie") == "session=abc123"

    def test_cookies_accumulate_across_responses(self, server):
        server.routes[("GET", "/login")] = (
            200, {"Set-Cookie": "session=abc123; Path=/"}, b"ok")
        server.routes[("GET", "/prefs")] = (
            200, {"Set-Cookie": "theme=dark; Path=/"}, b"ok")

        api = Api(server.base_url, cookies=True)
        api.get("/login")
        api.get("/prefs")
        api.get("/account")

        cookie = server.requests[-1]["headers"].get("cookie")
        assert "session=abc123" in cookie
        assert "theme=dark" in cookie

    # ── negative: off by default ────────────────────────────────────────
    def test_cookie_jar_off_by_default_sends_no_cookie(self, server):
        server.routes[("GET", "/login")] = (
            200, {"Set-Cookie": "session=abc123; Path=/"}, b"ok")

        api = Api(server.base_url)   # cookies default False
        api.get("/login")
        api.get("/dashboard")

        rec = server.requests[-1]
        assert "cookie" not in rec["headers"]


# ──────────────────────────────────────────────────────────────────────────
# Redirect security regression — the cross-origin Authorization/Cookie strip
# must still hold after these additions. Real two-server redirect over sockets.
# ──────────────────────────────────────────────────────────────────────────
class TestRedirectSecurityRegression:

    def test_cross_origin_redirect_strips_authorization_and_cookie(self):
        seen = {}

        class Target(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                seen["cookie"] = self.headers.get("Cookie")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        target = http.server.HTTPServer(("127.0.0.1", 0), Target)
        tport = target.server_address[1]
        location = f"http://127.0.0.1:{tport}/steal"

        class Redir(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", location)
                self.end_headers()

        redir = http.server.HTTPServer(("127.0.0.1", 0), Redir)
        for srv in (target, redir):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            rport = redir.server_address[1]
            api = Api(f"http://127.0.0.1:{rport}", cookies=True)
            api.set_bearer_token("SECRET-TOKEN")
            api._cookies["session"] = "SECRET-SESSION"   # jar seeded
            result = api.get("/login")
            assert result["http_code"] == 200
            assert seen.get("auth") is None      # bearer NOT leaked cross-origin
            assert seen.get("cookie") is None    # cookie NOT leaked cross-origin
        finally:
            redir.shutdown()
            redir.server_close()
            target.shutdown()
            target.server_close()

    def test_same_origin_redirect_keeps_authorization(self):
        seen = {}

        class App(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/login":
                    self.send_response(302)
                    self.send_header("Location", "/dashboard")   # same origin
                    self.end_headers()
                else:
                    seen["auth"] = self.headers.get("Authorization")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")

        srv = http.server.HTTPServer(("127.0.0.1", 0), App)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            api = Api(f"http://127.0.0.1:{port}")
            api.set_bearer_token("SECRET-TOKEN")
            result = api.get("/login")
            assert result["http_code"] == 200
            assert seen.get("auth") == "Bearer SECRET-TOKEN"   # same-origin keeps it
        finally:
            srv.shutdown()
            srv.server_close()
