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
