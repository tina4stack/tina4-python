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
from urllib.parse import parse_qs, quote, urlsplit

from tina4_python.api import Api


class _RecordingServer:
    """Records the Authorization header of the last request it received."""

    def __init__(self):
        self.last_auth = None
        self.last_headers = {}
        self.last_path = None
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.last_auth = self.headers.get("Authorization")
                outer.last_headers = {k.lower(): v for k, v in self.headers.items()}
                outer.last_path = self.path
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path.startswith("/redirect?"):
                    query = parse_qs(urlsplit(self.path).query)
                    self.send_response(int(query.get("code", ["302"])[0]))
                    self.send_header("Location", query["to"][0])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
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


# A configured header can carry a credential under any name. It is bound to the
# base origin exactly like the token: never to an absolute target on another
# origin, never onto a cross-origin redirect hop.

def _redirect(to, code=302):
    return f"/redirect?code={code}&to={quote(to, safe='')}"


@pytest.mark.parametrize("how", ["ctor", "add_headers"])
def test_configured_header_stays_off_an_absolute_off_origin_target(how):
    with _RecordingServer() as base, _RecordingServer() as other:
        if how == "ctor":
            api = Api(base.base_url, headers={"X-Api-Key": "synthetic-key"})
        else:
            api = Api(base.base_url)
            api.add_headers({"X-Api-Key": "synthetic-key"})
        assert api.get(f"{other.base_url}/probe")["http_code"] == 200
        assert "x-api-key" not in other.last_headers, f"{how} key leaked to an absolute off-origin URL"
        api.get("/probe")
        assert base.last_headers.get("x-api-key") == "synthetic-key", f"{how} key lost on its own origin"


def test_configured_and_per_call_headers_stay_off_a_cross_origin_redirect(tmp_path):
    with _RecordingServer() as base, _RecordingServer() as other:
        api = Api(base.base_url, headers={"X-Api-Key": "synthetic-key", "Accept": "application/json"})
        assert api.get(_redirect(f"{other.base_url}/landed"))["http_code"] == 200
        assert "x-api-key" not in other.last_headers, "configured key followed a redirect to another origin"
        assert other.last_headers.get("accept") == "application/json", "content negotiation must still cross"

        # urllib follows a POST only on 301/302/303 (re-issued as a GET); a 307
        # POST is not followed in this port.
        source = tmp_path / "upload.txt"; source.write_text("upload")
        api.upload(_redirect(f"{other.base_url}/uploaded", 302), file_path=str(source),
                   headers={"X-Upload-Token": "synthetic-call"})
        assert other.last_path == "/uploaded", "the redirect hop never reached the other origin"
        assert "x-upload-token" not in other.last_headers, "per-call header followed a redirect to another origin"

        api.get(_redirect(f"{base.base_url}/landed"))
        assert base.last_headers.get("x-api-key") == "synthetic-key", "same-origin redirect lost the key"


def test_baseless_client_sends_configured_header_only_to_the_url_it_names():
    with _RecordingServer() as named, _RecordingServer() as other:
        api = Api(headers={"X-Api-Key": "synthetic-key"})
        api.get(f"{named.base_url}/probe")
        assert named.last_headers.get("x-api-key") == "synthetic-key"
        api.get(named.base_url + _redirect(f"{other.base_url}/landed"))
        assert "x-api-key" not in other.last_headers, "baseless key followed a redirect to another origin"
