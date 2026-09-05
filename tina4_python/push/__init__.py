"""Provider-neutral Web Push delivery (RFC 8291 / RFC 8292).

The framework remains zero-dependency. Install the optional capability with
``pip install tina4-python[push]``; ``cryptography`` is imported only when a
push sender is constructed or used.
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


def _crypto() -> tuple[Any, ...]:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError as exc:
        raise PushError("Web Push requires the optional crypto capability; install tina4-python[push]") from exc
    return hashes, serialization, ec, Cipher, algorithms, modes, decode_dss_signature


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


def _public_bytes(public_key: Any, serialization: Any) -> bytes:
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys() -> dict[str, str]:
    _hashes, serialization, ec, *_ = _crypto()
    private = ec.generate_private_key(ec.SECP256R1())
    public = _public_bytes(private.public_key(), serialization)
    raw_private = private.private_numbers().private_value.to_bytes(32, "big")
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
    _hashes, serialization, ec, Cipher, algorithms, modes, _decode = _crypto()
    try:
        client_public_bytes = _unb64(subscription["keys"]["p256dh"], "subscription.keys.p256dh")
        auth_secret = _unb64(subscription["keys"]["auth"], "subscription.keys.auth")
    except (KeyError, TypeError) as exc:
        raise PushError("A Web Push subscription must include keys.p256dh and keys.auth") from exc
    if len(client_public_bytes) != 65 or client_public_bytes[0] != 4:
        raise PushError("subscription.keys.p256dh must be a 65-byte P-256 public key")
    if len(auth_secret) != 16:
        raise PushError("subscription.keys.auth must be a 16-byte authentication secret")

    client_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), client_public_bytes)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    server_public_bytes = _public_bytes(ephemeral.public_key(), serialization)
    shared = ephemeral.exchange(ec.ECDH(), client_public)
    key_info = b"WebPush: info\0" + client_public_bytes + server_public_bytes
    ikm = _hkdf(_hmac(auth_secret, shared), key_info, 32)
    salt = os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hkdf(prk, b"Content-Encoding: aes128gcm\0", 16)
    nonce = _hkdf(prk, b"Content-Encoding: nonce\0", 12)
    encryptor = Cipher(algorithms.AES(cek), modes.GCM(nonce)).encryptor()
    ciphertext = encryptor.update(payload + b"\x02") + encryptor.finalize() + encryptor.tag
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(server_public_bytes)]) + server_public_bytes + ciphertext


def _vapid_token(endpoint: str, subject: str, raw_private: bytes, raw_public: bytes) -> str:
    _hashes, serialization, ec, _Cipher, _algorithms, _modes, decode_dss_signature = _crypto()
    audience = urllib.parse.urlparse(endpoint)
    aud = f"{audience.scheme}://{audience.netloc}"
    header = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 60 * 60, "sub": subject}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    private = ec.derive_private_key(int.from_bytes(raw_private, "big"), ec.SECP256R1())
    der = private.sign(signing_input, ec.ECDSA(_hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return signing_input.decode("ascii") + "." + _b64(signature)


class Push:
    """Send encrypted payloads to browser PushManager subscriptions."""

    def __init__(self, subject: str | None = None, public_key: str | None = None,
                 private_key: str | None = None, ttl: int = 60,
                 urgency: str | None = None):
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

    def send(self, subscription: dict[str, Any], payload: Any) -> PushResult:
        endpoint = subscription.get("endpoint") if isinstance(subscription, dict) else None
        if not isinstance(endpoint, str) or not endpoint:
            raise PushError("A Web Push subscription with an endpoint is required")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise PushError("Push subscription endpoint must use HTTP or HTTPS")
        subject, public_key, private_key = self._configuration()
        raw_public = _unb64(public_key, "TINA4_VAPID_PUBLIC")
        raw_private = _unb64(private_key, "TINA4_VAPID_PRIVATE")
        if len(raw_public) != 65 or raw_public[0] != 4:
            raise PushError("TINA4_VAPID_PUBLIC must be a 65-byte P-256 public key")
        if len(raw_private) != 32:
            raise PushError("TINA4_VAPID_PRIVATE must be a 32-byte P-256 private key")
        _hashes, serialization, ec, *_ = _crypto()
        try:
            derived = ec.derive_private_key(int.from_bytes(raw_private, "big"), ec.SECP256R1())
            if _public_bytes(derived.public_key(), serialization) != raw_public:
                raise PushError("TINA4_VAPID_PUBLIC does not match TINA4_VAPID_PRIVATE")
        except ValueError as exc:
            raise PushError("TINA4_VAPID_PRIVATE is not a valid P-256 private key") from exc
        body = _encrypt(_payload_bytes(payload), subscription)
        headers = {
            "Authorization": f"vapid t={_vapid_token(endpoint, subject, raw_private, raw_public)}, k={public_key}",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(self.ttl),
        }
        if self.urgency:
            headers["Urgency"] = self.urgency
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = int(response.status)
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            text = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise PushError(f"Web Push request failed: {exc}") from exc
        return PushResult(status < 400, status, status in (404, 410), status == 408 or status == 429 or status >= 500, endpoint, text)


__all__ = ["Push", "PushError", "PushResult", "generate_vapid_keys"]
