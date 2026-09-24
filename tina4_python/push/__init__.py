# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Provider-neutral Web Push delivery (RFC 8291 / RFC 8292).

The framework stays zero-dependency on the server. The crypto runs through the OS
OpenSSL (``libcrypto``) by ctypes - the same "use the platform crypto" model the
PHP, Ruby and Node frameworks get from their stdlib - so a Linux host sends push
with nothing installed. Where ctypes cannot reach a safe OpenSSL (a stock Mac, a
Windows workstation), it falls back to the optional ``cryptography`` package
(``pip install tina4-python[push]``). Both backends emit identical bytes, so the
wire output is the same whichever runs. Set ``TINA4_PUSH_BACKEND`` to ``libcrypto``
or ``cryptography`` to pin one; ``auto`` (default) prefers libcrypto.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ._base import BackendUnavailable
from ..ssrf import guard_url, SsrfError, NoFollowRedirectHandler

RECORD_SIZE = 4096
MAX_PAYLOAD = RECORD_SIZE - 17


class PushError(RuntimeError):
    """Raised when Web Push is not configured, supported, or deliverable."""


@dataclass(frozen=True)
class PushResult:
    ok: bool
    status: int
    dead: bool
    retryable: bool
    endpoint: str
    response: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str, name: str) -> bytes:
    if not isinstance(value, str) or not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value):
        raise PushError(f"{name} must be a non-empty base64url string")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


_BACKEND = None


def _select_backend():
    """Pick the crypto backend: OS libcrypto first, cryptography as fallback.

    ``TINA4_PUSH_BACKEND`` forces ``auto`` (default), ``libcrypto`` or
    ``cryptography``. The choice is cached for the process; ``_reset_backend``
    drops the cache so a later call re-selects after the environment changes.
    """
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    choice = os.getenv("TINA4_PUSH_BACKEND", "auto").strip().lower() or "auto"
    order = {"auto": ("libcrypto", "cryptography"),
             "libcrypto": ("libcrypto",),
             "cryptography": ("cryptography",)}.get(choice)
    if order is None:
        raise PushError("TINA4_PUSH_BACKEND must be auto, libcrypto or cryptography")
    reasons = []
    for name in order:
        if name == "libcrypto":
            from . import _libcrypto as backend_module
        else:
            from . import _cryptography as backend_module
        try:
            _BACKEND = backend_module.load()
            return _BACKEND
        except BackendUnavailable as exc:
            reasons.append(f"{name} ({exc})")
    raise PushError(
        "Web Push needs the OS OpenSSL (Linux/Unix) or the cryptography package "
        "(install tina4-python[push]); unavailable here: " + ", ".join(reasons))


def _reset_backend() -> None:
    """Drop the cached backend so the next call re-selects."""
    global _BACKEND
    _BACKEND = None


def _hmac(key: bytes, value: bytes) -> bytes:
    return hmac.new(key, value, hashlib.sha256).digest()


def _hkdf(prk: bytes, info: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    previous = b""
    counter = 1
    while len(b"".join(chunks)) < length:
        previous = _hmac(prk, previous + info + bytes([counter]))
        chunks.append(previous)
        counter += 1
        if counter > 255:
            raise PushError("HKDF output is too large")
    return b"".join(chunks)[:length]


def generate_vapid_keys() -> dict[str, str]:
    raw_private, public = _select_backend().generate_keypair()
    return {"publicKey": _b64(public), "privateKey": _b64(raw_private)}


def _payload_bytes(payload: Any) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    try:
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PushError(f"Push payload is not JSON serializable: {exc}") from exc


def _encrypt(payload: bytes, subscription: dict[str, Any]) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise PushError(f"Push payload is too large; maximum is {MAX_PAYLOAD} bytes")
    backend = _select_backend()
    try:
        client_public_bytes = _unb64(subscription["keys"]["p256dh"], "subscription.keys.p256dh")
        auth_secret = _unb64(subscription["keys"]["auth"], "subscription.keys.auth")
    except (KeyError, TypeError) as exc:
        raise PushError("A Web Push subscription must include keys.p256dh and keys.auth") from exc
    if len(client_public_bytes) != 65 or client_public_bytes[0] != 4:
        raise PushError("subscription.keys.p256dh must be a 65-byte P-256 public key")
    if len(auth_secret) != 16:
        raise PushError("subscription.keys.auth must be a 16-byte authentication secret")

    try:
        server_public_bytes, shared = backend.encrypt_ecdh(client_public_bytes)
    except ValueError as exc:
        raise PushError("subscription.keys.p256dh is not a valid P-256 public key") from exc
    key_info = b"WebPush: info\0" + client_public_bytes + server_public_bytes
    ikm = _hkdf(_hmac(auth_secret, shared), key_info, 32)
    salt = os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hkdf(prk, b"Content-Encoding: aes128gcm\0", 16)
    nonce = _hkdf(prk, b"Content-Encoding: nonce\0", 12)
    ciphertext = backend.aes128gcm_encrypt(cek, nonce, payload + b"\x02")
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(server_public_bytes)]) + server_public_bytes + ciphertext


def _vapid_token(endpoint: str, subject: str, raw_private: bytes, raw_public: bytes) -> str:
    audience = urllib.parse.urlparse(endpoint)
    aud = f"{audience.scheme}://{audience.netloc}"
    header = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 60 * 60, "sub": subject}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    signature = _select_backend().sign_es256(raw_private, signing_input)
    return signing_input.decode("ascii") + "." + _b64(signature)


class Push:
    """Send encrypted payloads to browser PushManager subscriptions."""

    def __init__(self, subject: str | None = None, public_key: str | None = None,
                 private_key: str | None = None, ttl: int = 60,
                 urgency: str | None = None,
                 allow_hosts: list[str] | None = None):
        # SSRF guard (ADR-0084): the push endpoint is refused when it resolves to
        # a private/internal address unless TINA4_ALLOW_PRIVATE_REQUESTS is truthy
        # or the host/CIDR is on this allow-list.
        self.allow_hosts = list(allow_hosts) if allow_hosts else []
        self.subject = (subject or os.getenv("TINA4_VAPID_SUBJECT", "")).strip()
        self.public_key = (public_key or os.getenv("TINA4_VAPID_PUBLIC", "")).strip()
        self.private_key = (private_key or os.getenv("TINA4_VAPID_PRIVATE", "")).strip()
        self.ttl = ttl
        self.urgency = urgency
        if os.getenv("TINA4_WEB_PUSH", "").strip().lower() in {"0", "false", "off", "no"}:
            raise PushError("Web Push is disabled by TINA4_WEB_PUSH")
        if any((self.subject, self.public_key, self.private_key)):
            self._configuration()

    @classmethod
    def from_env(cls, **kwargs: Any) -> "Push":
        return cls(**kwargs)

    @staticmethod
    def generate_keys() -> dict[str, str]:
        return generate_vapid_keys()

    def _configuration(self) -> tuple[str, str, str]:
        missing = [name for name, value in (
            ("TINA4_VAPID_SUBJECT", self.subject),
            ("TINA4_VAPID_PUBLIC", self.public_key),
            ("TINA4_VAPID_PRIVATE", self.private_key),
        ) if not value]
        if missing:
            raise PushError(f"Web Push is configured but missing: {', '.join(missing)}")
        return self.subject, self.public_key, self.private_key

    @staticmethod
    def _endpoint(subscription: dict[str, Any]) -> str:
        endpoint = subscription.get("endpoint") if isinstance(subscription, dict) else None
        if not isinstance(endpoint, str) or not endpoint:
            raise PushError("A Web Push subscription with an endpoint is required")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise PushError("Push subscription endpoint must use HTTP or HTTPS")
        return endpoint

    @staticmethod
    def _keys(public_key: str, private_key: str) -> tuple[bytes, bytes]:
        raw_public = _unb64(public_key, "TINA4_VAPID_PUBLIC")
        raw_private = _unb64(private_key, "TINA4_VAPID_PRIVATE")
        if len(raw_public) != 65 or raw_public[0] != 4:
            raise PushError("TINA4_VAPID_PUBLIC must be a 65-byte P-256 public key")
        if len(raw_private) != 32:
            raise PushError("TINA4_VAPID_PRIVATE must be a 32-byte P-256 private key")
        try:
            derived_public = _select_backend().public_from_private(raw_private)
        except ValueError as exc:
            raise PushError("TINA4_VAPID_PRIVATE is not a valid P-256 private key") from exc
        if derived_public != raw_public:
            raise PushError("TINA4_VAPID_PUBLIC does not match TINA4_VAPID_PRIVATE")
        return raw_public, raw_private

    def _deliver(self, endpoint: str, subject: str, public_key: str, raw_public: bytes, raw_private: bytes, body: bytes) -> PushResult:
        headers = {
            "Authorization": f"vapid t={_vapid_token(endpoint, subject, raw_private, raw_public)}, k={public_key}",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(self.ttl),
        }
        if self.urgency:
            headers["Urgency"] = self.urgency
        try:
            guard_url(endpoint, self.allow_hosts)
        except SsrfError as exc:
            raise PushError(str(exc)) from None
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        # A real push service answers the POST directly; a redirect from a push
        # endpoint is not followed to a private address (ADR-0084).
        opener = urllib.request.build_opener(NoFollowRedirectHandler())
        try:
            with opener.open(request, timeout=30) as response:
                status = int(response.status)
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            text = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise PushError(f"Web Push request failed: {exc}") from exc
        return PushResult(status < 400, status, status in (404, 410), status == 408 or status == 429 or status >= 500, endpoint, text)

    def send(self, subscription: dict[str, Any], payload: Any) -> PushResult:
        endpoint = self._endpoint(subscription)
        subject, public_key, private_key = self._configuration()
        raw_public, raw_private = self._keys(public_key, private_key)
        return self._deliver(endpoint, subject, public_key, raw_public, raw_private, _encrypt(_payload_bytes(payload), subscription))


__all__ = ["Push", "PushError", "PushResult", "generate_vapid_keys"]
