# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Zero-dependency S3 client (AWS Signature Version 4) over the standard library.

Covers exactly the operations the realtime ``S3Storage`` backend needs — PUT,
GET, DELETE, HEAD, and a presigned GET URL — so the ``s3`` extra no longer pulls
in boto3 (and transitively botocore + urllib3). It speaks path-style addressing
(``<endpoint>/<bucket>/<key>``), which S3-compatible servers (MinIO) require and
AWS accepts; with no endpoint it targets ``https://s3.<region>.amazonaws.com``.

SigV4 is HMAC-SHA256 canonical-request signing — the same primitive Tina4 already
owns for JWT. Nothing here is reinvented crypto: it is the published AWS algorithm
on ``hashlib``/``hmac``, proven against AWS's own test vectors in the suite.
"""
import datetime
import hashlib
import hmac
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "s3"
# S3 answers these when a request should simply be sent again (503 is also
# "SlowDown"). Every operation here is idempotent, so a retry is always safe.
_RETRY_STATUSES = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 0.5   # seconds; attempt n waits up to base * 2**n, jittered
_BACKOFF_CAP = 20.0
# AWS canonical URI/query encoding: unreserved set per RFC 3986 is kept literal.
# For the PATH we also keep "/" (segment separator); for QUERY values we do not.
_UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _uri_encode(value: str, *, is_path: bool) -> str:
    """Encode a string the way SigV4 canonicalisation requires.

    Every byte outside the RFC 3986 unreserved set becomes ``%XX`` (upper-case
    hex). ``/`` is preserved in a path (it separates key segments) and encoded
    everywhere else. This matches AWS's ``UriEncode`` reference exactly.
    """
    safe = _UNRESERVED + ("/" if is_path else "")
    return urllib.parse.quote(value, safe=safe)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str) -> bytes:
    k_date = _hmac(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, _SERVICE)
    return _hmac(k_service, "aws4_request")


class S3Error(Exception):
    """An S3 request returned a non-2xx status. ``status`` holds the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class S3Client:
    """Minimal path-style S3 client with SigV4 request + presigned-URL signing."""

    def __init__(self, *, endpoint: str = None, access_key: str = "",
                 secret_key: str = "", region: str = "us-east-1", timeout: int = 30,
                 session_token: str = ""):
        self.region = region or "us-east-1"
        if access_key or secret_key:
            self.access_key = access_key or ""
            self.secret_key = secret_key or ""
            self.session_token = session_token or ""
        else:
            # No explicit credentials: use the standard AWS environment, as a
            # whole. A session token only belongs with the key it was issued
            # for, so it is never mixed into explicit credentials.
            self.access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
            self.secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
            self.session_token = os.environ.get("AWS_SESSION_TOKEN", "")
        self.timeout = timeout
        base = (endpoint or f"https://s3.{self.region}.amazonaws.com").rstrip("/")
        self._base = base
        parsed = urllib.parse.urlsplit(base)
        self._scheme = parsed.scheme or "https"
        self._host = parsed.netloc  # host[:port] — the value of the Host header
        # An endpoint behind a path (https://host/s3) keeps it in front of every
        # request path, and in what is signed.
        self._prefix = parsed.path.rstrip("/")

    # -- public API (the subset S3Storage uses) --------------------------------

    def put_object(self, bucket: str, key: str, data: bytes,
                   content_type: str = "application/octet-stream") -> None:
        self._request("PUT", bucket, key, body=data,
                      extra_headers={"content-type": content_type})

    def get_object(self, bucket: str, key: str) -> bytes:
        status, body = self._request("GET", bucket, key)
        return body

    def delete_object(self, bucket: str, key: str) -> None:
        self._request("DELETE", bucket, key)

    def head_object(self, bucket: str, key: str) -> None:
        self._request("HEAD", bucket, key)

    def create_bucket(self, bucket: str) -> None:
        """Create the bucket (path-style ``PUT /<bucket>``).

        Idempotent for our purposes: an already-owned bucket answers 409, which
        we treat as success. Used by tests/provisioning, not the hot path.
        """
        try:
            self._request("PUT", bucket, "", bucket_only=True)
        except S3Error as exc:
            if exc.status != 409:
                raise

    def presigned_get_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        """A URL that fetches the object directly, signed via SigV4 query params."""
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        canonical_uri = self._canonical_uri(bucket, key)
        credential_scope = f"{datestamp}/{self.region}/{_SERVICE}/aws4_request"
        # The X-Amz-* query params are themselves part of the signature.
        query = {
            "X-Amz-Algorithm": _ALGORITHM,
            "X-Amz-Credential": f"{self.access_key}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires),
            "X-Amz-SignedHeaders": "host",
        }
        if self.session_token:
            query["X-Amz-Security-Token"] = self.session_token
        canonical_qs = self._canonical_query(query)
        canonical_headers = f"host:{self._host}\n"
        canonical_request = "\n".join([
            "GET", canonical_uri, canonical_qs, canonical_headers, "host",
            "UNSIGNED-PAYLOAD",
        ])
        signature = self._sign(canonical_request, amz_date, datestamp, credential_scope)
        canonical_qs += "&X-Amz-Signature=" + signature
        return f"{self._scheme}://{self._host}{canonical_uri}?{canonical_qs}"

    # -- signing + transport ----------------------------------------------------

    def _canonical_uri(self, bucket: str, key: str) -> str:
        return (self._prefix + "/" + _uri_encode(bucket, is_path=True)
                + "/" + _uri_encode(key, is_path=True))

    def _canonical_query(self, query: dict) -> str:
        # Sorted by key, each name and value URI-encoded (no "/" exemption).
        return "&".join(
            f"{_uri_encode(k, is_path=False)}={_uri_encode(v, is_path=False)}"
            for k, v in sorted(query.items())
        )

    def _sign(self, canonical_request: str, amz_date: str, datestamp: str,
              credential_scope: str) -> str:
        string_to_sign = "\n".join([
            _ALGORITHM, amz_date, credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ])
        key = _signing_key(self.secret_key, datestamp, self.region)
        return hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(self, method: str, bucket: str, key: str, body: bytes = b"",
                 extra_headers: dict = None, bucket_only: bool = False):
        # Each attempt is signed afresh (x-amz-date moves on). A retryable status
        # on the last attempt is raised like any other failure.
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._send(method, bucket, key, body, extra_headers, bucket_only)
            except S3Error as exc:
                if exc.status not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS - 1:
                    raise
            time.sleep(random.uniform(0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2 ** attempt)))

    def _send(self, method: str, bucket: str, key: str, body: bytes,
              extra_headers: dict, bucket_only: bool):
        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        canonical_uri = (self._prefix + "/" + _uri_encode(bucket, is_path=True)) if bucket_only \
            else self._canonical_uri(bucket, key)
        payload_hash = _sha256_hex(body or b"")

        signed = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self.session_token:
            signed["x-amz-security-token"] = self.session_token
        canonical_headers = "".join(f"{k}:{signed[k]}\n" for k in sorted(signed))
        signed_headers = ";".join(sorted(signed))
        canonical_request = "\n".join([
            method, canonical_uri, "", canonical_headers, signed_headers, payload_hash,
        ])
        credential_scope = f"{datestamp}/{self.region}/{_SERVICE}/aws4_request"
        signature = self._sign(canonical_request, amz_date, datestamp, credential_scope)
        authorization = (
            f"{_ALGORITHM} Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Authorization": authorization,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self.session_token:
            headers["x-amz-security-token"] = self.session_token
        if extra_headers:
            headers.update(extra_headers)

        url = f"{self._scheme}://{self._host}{canonical_uri}"
        request = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None,
                                         method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            raise S3Error(exc.code, f"{method} {canonical_uri}: {exc.code} {exc.reason}") from None
