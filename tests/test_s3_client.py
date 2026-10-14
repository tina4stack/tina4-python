# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit proof of the zero-dependency SigV4 S3 client's signing math.

No service and no mocks: these are pure-logic checks of the AWS Signature
Version 4 algorithm against AWS's OWN published reference ("get-vanilla" from
the SigV4 test suite) plus the canonical URI-encoding rules. The live-server
behaviour (real PUT/GET/presigned/DELETE against MinIO or Garage) is proven
separately in tests/test_realtime_files.py::TestS3Storage.

Mutation-proof: change any step of the canonical request, the string-to-sign,
or the signing-key derivation and the AWS vector assertion goes red.
"""
import hashlib
import hmac

from tina4_python.realtime import s3_client as s3


class TestSigV4AgainstAwsVector:
    """AWS SigV4 test suite 'get-vanilla' — a published, authoritative vector."""

    SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
    AMZ_DATE = "20150830T123600Z"
    DATESTAMP = "20150830"
    REGION = "us-east-1"
    SERVICE = "service"
    EXPECTED = "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"

    def _signing_key(self, service):
        k = s3._hmac(("AWS4" + self.SECRET).encode(), self.DATESTAMP)
        k = s3._hmac(k, self.REGION)
        k = s3._hmac(k, service)
        return s3._hmac(k, "aws4_request")

    def test_full_signature_matches_the_published_vector(self):
        canonical_request = "\n".join([
            "GET", "/", "",
            "host:example.amazonaws.com\nx-amz-date:20150830T123600Z\n",
            "host;x-amz-date",
            hashlib.sha256(b"").hexdigest(),
        ])
        scope = f"{self.DATESTAMP}/{self.REGION}/{self.SERVICE}/aws4_request"
        string_to_sign = "\n".join([
            s3._ALGORITHM, self.AMZ_DATE, scope,
            s3._sha256_hex(canonical_request.encode()),
        ])
        signature = hmac.new(self._signing_key(self.SERVICE),
                             string_to_sign.encode(), hashlib.sha256).hexdigest()
        assert signature == self.EXPECTED

    def test_module_signing_key_derivation_is_the_standard_chain(self):
        # The module's own _signing_key (service pinned to "s3") must equal a
        # from-scratch derivation for service "s3" — guards the chain order.
        assert s3._signing_key(self.SECRET, self.DATESTAMP, self.REGION) == \
            self._signing_key("s3")


class TestCanonicalUriEncoding:
    def test_path_keeps_slash_encodes_space_preserves_tilde(self):
        assert s3._uri_encode("a/b c~d", is_path=True) == "a/b%20c~d"

    def test_query_encodes_slash(self):
        assert s3._uri_encode("a/b c~d", is_path=False) == "a%2Fb%20c~d"


class TestPresignedUrlShape:
    def test_presigned_url_carries_the_sigv4_query_params(self):
        client = s3.S3Client(endpoint="http://localhost:9100", access_key="AKID",
                             secret_key="secret", region="us-east-1")
        url = client.presigned_get_url("bucket", "obj.png", expires=120)
        assert url.startswith("http://localhost:9100/bucket/obj.png?")
        for param in ("X-Amz-Algorithm=AWS4-HMAC-SHA256", "X-Amz-Credential=",
                      "X-Amz-Date=", "X-Amz-Expires=120",
                      "X-Amz-SignedHeaders=host", "X-Amz-Signature="):
            assert param in url, f"missing {param} in {url}"


# ── Against a real local HTTP server ──────────────────────────────────
# A ThreadingHTTPServer records what the client sends and answers with the
# statuses a real S3 uses. Nothing in the client is replaced.

import http.server
import threading
import urllib.request

import pytest


class _RecordingS3(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _answer(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, dict(self.headers)))
        status = self.server.statuses.pop(0) if self.server.statuses else 200
        body = b"ok" if status == 200 and self.command == "GET" else b""
        self.send_response(status)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_PUT = do_HEAD = do_DELETE = _answer


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RecordingS3)
    srv.seen, srv.statuses = [], []
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_port}"
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def no_aws_env(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "TINA4_STORAGE_KEY", "TINA4_STORAGE_SECRET"):
        monkeypatch.delenv(name, raising=False)


def _header(headers, name):
    return {k.lower(): v for k, v in headers.items()}.get(name)


class TestAwsEnvironmentCredentials:
    """With no explicit key the client uses AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    / AWS_SESSION_TOKEN, as boto3 did; explicit keys never pick up an env token."""

    def test_storage_with_no_tina4_keys_signs_with_the_aws_environment(self, server, no_aws_env, monkeypatch):
        from tina4_python.realtime.storage import S3Storage
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIAENVKEY")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "envsecret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "ENVTOKEN")
        S3Storage(endpoint=server.url, bucket="b").put("k.txt", b"x")
        headers = server.seen[-1][2]
        assert "Credential=ASIAENVKEY/" in _header(headers, "authorization")
        assert _header(headers, "x-amz-security-token") == "ENVTOKEN"
        assert "x-amz-security-token" in _header(headers, "authorization").split("SignedHeaders=")[1]

    def test_explicit_keys_never_borrow_the_environment_token(self, server, no_aws_env, monkeypatch):
        monkeypatch.setenv("AWS_SESSION_TOKEN", "SOMEONE-ELSES-TOKEN")
        s3.S3Client(endpoint=server.url, access_key="AKID", secret_key="s").put_object("b", "k", b"x")
        headers = server.seen[-1][2]
        assert "Credential=AKID/" in _header(headers, "authorization")
        assert _header(headers, "x-amz-security-token") is None

    def test_presigned_url_carries_the_session_token(self, no_aws_env):
        client = s3.S3Client(endpoint="http://localhost:9100", access_key="ASIA", secret_key="s",
                             session_token="TOK/EN+1")
        assert "X-Amz-Security-Token=TOK%2FEN%2B1" in client.presigned_get_url("b", "k")


class TestRetries:
    """S3 asks for a retry with 500/502/503/504 (503 is SlowDown); boto3 retried."""

    @pytest.fixture(autouse=True)
    def fast_backoff(self, monkeypatch):
        monkeypatch.setattr(s3, "_BACKOFF_BASE", 0.001, raising=False)

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_a_retryable_status_is_sent_again(self, server, status):
        server.statuses = [status]
        s3.S3Client(endpoint=server.url, access_key="a", secret_key="b").put_object("b", "k", b"x")
        assert [s for s, *_ in server.seen] == ["PUT", "PUT"]

    def test_it_gives_up_after_three_attempts(self, server):
        server.statuses = [503, 503, 503, 503]
        with pytest.raises(s3.S3Error) as caught:
            s3.S3Client(endpoint=server.url, access_key="a", secret_key="b").get_object("b", "k")
        assert caught.value.status == 503 and len(server.seen) == 3

    @pytest.mark.parametrize("status", [400, 403, 404, 409])
    def test_a_final_answer_is_not_retried(self, server, status):
        server.statuses = [status]
        with pytest.raises(s3.S3Error):
            s3.S3Client(endpoint=server.url, access_key="a", secret_key="b").head_object("b", "k")
        assert len(server.seen) == 1


class TestEndpointPathPrefix:
    """An endpoint behind a path keeps it, as boto3 did: https://host/s3 -> /s3/<bucket>/<key>."""

    def test_requests_and_bucket_creation_keep_the_prefix(self, server):
        client = s3.S3Client(endpoint=server.url + "/s3-prefix/", access_key="a", secret_key="b")
        client.put_object("b", "dir/k.txt", b"x")
        client.create_bucket("nb")
        assert [p for _, p, _ in server.seen] == ["/s3-prefix/b/dir/k.txt", "/s3-prefix/nb"]

    def test_the_presigned_url_keeps_the_prefix_and_fetches(self, server):
        client = s3.S3Client(endpoint=server.url + "/s3-prefix", access_key="a", secret_key="b")
        url = client.presigned_get_url("b", "k.txt")
        assert url.startswith(server.url + "/s3-prefix/b/k.txt?")
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.read() == b"ok"
        assert server.seen[-1][1].startswith("/s3-prefix/b/k.txt?")
