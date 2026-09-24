# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Web Push crypto backend conformance: libcrypto vs cryptography.

No mocks. ``cryptography`` here is a genuine independent implementation standing
in for the browser (the receiver that decrypts and the verifier that checks the
VAPID signature), which is exactly what the wire contract must interoperate with.
The libcrypto backend is proven correct by decrypting its real output and by
byte-comparing its deterministic primitives against the package.

On a Linux host (the deploy target) and on this Mac both backends are present, so
every check runs. A host that genuinely lacks one backend skips only the
comparison it cannot make, never an assertion it could have run.
"""
import os
import sys

import pytest

from tina4_python import push
from tina4_python.push import _base, _cryptography, _libcrypto


def _load_or_skip(module):
    try:
        return module.load()
    except _base.BackendUnavailable as exc:
        pytest.skip(f"[needs:runtime=libcrypto] {module.__name__} unavailable here: {exc}")


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    """Never let a forced backend leak into another test."""
    push._reset_backend()
    yield
    os.environ.pop("TINA4_PUSH_BACKEND", None)
    push._reset_backend()


# ---- backend selection -----------------------------------------------------
def test_libcrypto_is_available_and_preferred_on_the_server():
    if sys.platform == "win32":
        with pytest.raises(_base.BackendUnavailable):
            _libcrypto.load()
        return
    backend = _libcrypto.load()          # raises if the KAT self-test fails
    assert backend.name == "libcrypto"
    push._reset_backend()
    assert push._select_backend().name == "libcrypto"   # auto prefers it


def test_forcing_an_unknown_backend_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TINA4_PUSH_BACKEND", "openssl")
    push._reset_backend()
    with pytest.raises(push.PushError, match="auto, libcrypto or cryptography"):
        push._select_backend()


# ---- deterministic primitives are byte-identical ---------------------------
def test_aes128gcm_is_byte_identical_across_backends():
    pytest.importorskip("cryptography")
    lib = _load_or_skip(_libcrypto)
    pyc = _cryptography.load()
    for key, iv, pt in (
        (b"\x00" * 16, b"\x00" * 12, b""),
        (b"\x11" * 16, b"\x22" * 12, b"hello web push"),
        (bytes(range(16)), bytes(range(12)), b"x" * 4000),   # multi-block
    ):
        assert lib.aes128gcm_encrypt(key, iv, pt) == pyc.aes128gcm_encrypt(key, iv, pt)


def test_public_from_private_is_byte_identical_including_zero_top_byte():
    pytest.importorskip("cryptography")
    lib = _load_or_skip(_libcrypto)
    pyc = _cryptography.load()
    scalars = [
        (1).to_bytes(32, "big"),
        (2).to_bytes(32, "big"),
        b"\x00" + b"\x11" * 31,        # zero top byte: the left-pad case
        bytes.fromhex("3a2f1e0d9c8b7a695847362514c9f58f89813e9f8e872f7f4f2b3a1d6e0a5c4b"),
    ]
    for scalar in scalars:
        lib_pub = lib.public_from_private(scalar)
        assert lib_pub == pyc.public_from_private(scalar)
        assert len(lib_pub) == 65 and lib_pub[0] == 4


# ---- full RFC 8291 payload decrypts back to the plaintext ------------------
def _receiver_keypair():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return priv, pub


def _decrypt_as_browser(priv, auth_secret, body):
    """RFC 8291 receiver: reverse the aes128gcm record with the subscriber key."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = body[:16]
    idlen = body[20]
    server_pub = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    receiver_pub = priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    server_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_pub)
    shared = priv.exchange(ec.ECDH(), server_key)
    key_info = b"WebPush: info\0" + receiver_pub + server_pub
    ikm = push._hkdf(push._hmac(auth_secret, shared), key_info, 32)
    prk = push._hmac(salt, ikm)
    cek = push._hkdf(prk, b"Content-Encoding: aes128gcm\0", 16)
    nonce = push._hkdf(prk, b"Content-Encoding: nonce\0", 12)
    plaintext = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plaintext.rstrip(b"\x02")


@pytest.mark.parametrize("backend_name", ["libcrypto", "cryptography"])
def test_encrypt_decrypt_roundtrip_for_each_backend(backend_name, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("TINA4_PUSH_BACKEND", backend_name)
    push._reset_backend()
    try:
        assert push._select_backend().name == backend_name
    except push.PushError as exc:
        # Only the libcrypto backend is a platform exclusion (no reachable safe
        # OpenSSL on a stock macOS/Windows); cryptography is in the test extra.
        tag = "[needs:runtime=libcrypto] " if backend_name == "libcrypto" else ""
        pytest.skip(f"{tag}{backend_name} unavailable here: {exc}")

    priv, pub = _receiver_keypair()
    auth_secret = bytes([7]) * 16
    subscription = {"endpoint": "http://127.0.0.1/push",
                    "keys": {"p256dh": push._b64(pub), "auth": push._b64(auth_secret)}}
    message = b'{"title":"Tina4","body":"zero-dep web push"}'
    body = push._encrypt(message, subscription)
    assert _decrypt_as_browser(priv, auth_secret, body) == message


# ---- ES256 VAPID signature verifies, and a tampered one is rejected --------
def test_es256_signature_verifies_and_tamper_is_rejected():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature

    lib = _load_or_skip(_libcrypto)
    keys = push.generate_vapid_keys()
    raw_private = push._unb64(keys["privateKey"], "priv")
    public_point = push._unb64(keys["publicKey"], "pub")
    message = b"eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJodHRwczovL2ZjbSJ9"

    signature = lib.sign_es256(raw_private, message)
    assert len(signature) == 64
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_point)
    verifier.verify(encode_dss_signature(r, s), message, ec.ECDSA(hashes.SHA256()))  # raises on failure

    tampered = bytearray(signature)
    tampered[0] ^= 0x01
    tr = int.from_bytes(bytes(tampered[:32]), "big")
    ts = int.from_bytes(bytes(tampered[32:]), "big")
    with pytest.raises(InvalidSignature):
        verifier.verify(encode_dss_signature(tr, ts), message, ec.ECDSA(hashes.SHA256()))


# ---- negative: an off-curve subscriber key is rejected ---------------------
@pytest.mark.parametrize("backend_name", ["libcrypto", "cryptography"])
def test_off_curve_p256dh_is_rejected(backend_name, monkeypatch):
    monkeypatch.setenv("TINA4_PUSH_BACKEND", backend_name)
    push._reset_backend()
    try:
        push._select_backend()
    except push.PushError as exc:
        # Only the libcrypto backend is a platform exclusion (no reachable safe
        # OpenSSL on a stock macOS/Windows); cryptography is in the test extra.
        tag = "[needs:runtime=libcrypto] " if backend_name == "libcrypto" else ""
        pytest.skip(f"{tag}{backend_name} unavailable here: {exc}")

    off_curve = bytes([4]) + b"\x01" * 64          # 0x04 prefix, not on P-256
    subscription = {"endpoint": "http://127.0.0.1/push",
                    "keys": {"p256dh": push._b64(off_curve), "auth": push._b64(bytes([7]) * 16)}}
    with pytest.raises(push.PushError, match="p256dh"):
        push._encrypt(b"payload", subscription)
