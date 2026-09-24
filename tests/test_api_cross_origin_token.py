# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Medium security finding F5 — the configured Authorization token must never be
sent to a host other than the client's configured base origin.

A path that is itself an absolute off-origin URL (e.g. get("http://evil/x"))
previously reused the base client's Authorization header, leaking a bearer token
to an attacker-chosen host. The cross-origin strip already existed for REDIRECT
following; this pins it for the initial request target too. Only same-origin
requests carry the token. Case names match the sibling regressions in
tina4-nodejs/test/apiCrossOriginToken.test.ts,
tina4-php/tests/ApiCrossOriginTokenTest.php and
tina4-ruby/spec/api_cross_origin_token_spec.rb.

Two real threaded http.server instances on 127.0.0.1; a real Api client. No mocks.
"""
import http.server
import threading
import pytest

from tina4_python.api import Api


class _RecordingServer:
    """Records the Authorization header of the last request it received."""

    def __init__(self):
        self.last_auth = None
        self.last_headers = {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.last_auth = self.headers.get("Authorization")
                outer.last_headers = {k.lower(): v for k, v in self.headers.items()}
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Set-Cookie", "session=synthetic-cookie; Path=/")
                self.end_headers()
                self.wfile.write(payload)

            do_POST = do_GET

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


class TestApiCrossOriginToken:
    def test_absolute_off_origin_path_does_not_leak_the_token(self):
        with _RecordingServer() as base, _RecordingServer() as evil:
            api = Api(base.base_url, auth_header="Bearer s3cret-token")
            api.get(f"{evil.base_url}/steal")
            assert evil.last_auth is None, (
                f"bearer token leaked to another host: {evil.last_auth}"
            )

    def test_same_origin_request_still_carries_the_token(self):
        with _RecordingServer() as base:
            api = Api(base.base_url, auth_header="Bearer s3cret-token")
            api.get("/me")
            assert base.last_auth == "Bearer s3cret-token", (
                f"same-origin token missing/wrong: {base.last_auth}"
            )


@pytest.mark.parametrize("mode", ["get", "post", "upload", "download", "stream"])
@pytest.mark.parametrize("off_origin", [False, True])
def test_final_target_credentials_on_every_http_path(mode, off_origin, tmp_path):
    with _RecordingServer() as base, _RecordingServer() as other:
        api = Api(base.base_url, headers={"aUtHoRiZaTiOn": "Bearer configured", "cOoKiE": "manual=value"}, cookies=True)
        api.get("/seed")
        target = other if off_origin else base
        path = target.base_url + "/probe"
        if mode == "get": result = api.get(path)
        elif mode == "post": result = api.post(path, {"hello": "world"})
        elif mode == "upload":
            source = tmp_path / "upload.txt"; source.write_text("upload")
            result = api.upload(path, file_path=str(source))
        elif mode == "download": result = api.download(path, dest_path=str(tmp_path / "download.txt"))
        else:
            assert b''.join(api.stream_bytes(path, extra_headers={"Authorization": "Bearer stream", "Cookie": "stream=value"}))
            result = {"http_code": 200}
        assert result["http_code"] == 200
        assert bool(target.last_headers.get("authorization")) is (not off_origin)
        assert bool(target.last_headers.get("cookie")) is (not off_origin)
