# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Web Push crypto through the OS OpenSSL, called by ctypes. Zero packages.

This is the server path. A Linux host already carries ``libcrypto.so`` (OpenSSL),
so a Tina4 app sends Web Push with nothing installed - the same "use the platform
crypto" model PHP, Ruby and Node get from their stdlib. The five primitives call
straight into OpenSSL's EVP/EC surface; HKDF and the record framing stay in the
stdlib layer above.

Loadability is the catch, so it is handled honestly rather than assumed:

- Linux / most Unix: ``find_library('crypto')`` resolves the system OpenSSL.
- macOS: the SYSTEM libcrypto is LibreSSL and ABORTS the process when ctypes
  loads it ("loading libcrypto in an unsafe way"), so this NEVER calls
  find_library on Darwin - it looks only for a real Homebrew OpenSSL. A stock Mac
  has none, so ``load()`` raises and the caller falls back to ``cryptography``.
- Windows: there is no system OpenSSL to find, so ``load()`` raises and the
  caller falls back to ``cryptography``. Tina4 is not hosted on Windows; it is a
  dev platform, and the fallback covers it.

``load()`` runs a known-answer self-test (a NIST AES-128-GCM vector and the P-256
generator). If the resolved library is ABI-incompatible - an old OpenSSL, a
LibreSSL, a BoringSSL that does not match these call signatures - the self-test
fails and ``load()`` raises ``BackendUnavailable`` rather than let the backend
emit wrong bytes. A wrong answer never ships; it degrades to the package.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import sys

from ._base import BackendUnavailable

NID_P256 = 415              # NID_X9_62_prime256v1
POINT_UNCOMPRESSED = 4
EVP_CTRL_GCM_GET_TAG = 0x10
_c = ctypes.c_void_p
_i = ctypes.c_int
_sz = ctypes.c_size_t


def _resolve() -> ctypes.CDLL:
    """Load a libcrypto that is safe to load on this platform, or raise."""
    override = os.environ.get("TINA4_LIBCRYPTO")
    if override:
        return ctypes.CDLL(override)
    if sys.platform == "darwin":
        # The system libcrypto is LibreSSL and aborts a ctypes load. Only a real
        # Homebrew OpenSSL is safe; a stock Mac has none, so raise and fall back.
        for path in ("/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib",
                     "/usr/local/opt/openssl@3/lib/libcrypto.dylib"):
            if os.path.exists(path):
                return ctypes.CDLL(path)
        raise BackendUnavailable("no Homebrew OpenSSL on this Mac (system LibreSSL aborts a ctypes load)")
    name = ctypes.util.find_library("crypto") or ctypes.util.find_library("libcrypto")
    if not name:
        raise BackendUnavailable("no system libcrypto found (find_library('crypto') returned nothing)")
    return ctypes.CDLL(name)


def _bind(lib: ctypes.CDLL) -> None:
    """Declare restype/argtypes so ctypes never truncates a 64-bit pointer."""
    def sig(name, restype, argtypes):
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes
    sig("EC_KEY_new_by_curve_name", _c, [_i])
    sig("EC_KEY_free", None, [_c])
    sig("EC_KEY_generate_key", _i, [_c])
    sig("EC_KEY_get0_group", _c, [_c])
    sig("EC_KEY_get0_private_key", _c, [_c])
    sig("EC_KEY_set_private_key", _i, [_c, _c])
    sig("EC_KEY_set_public_key", _i, [_c, _c])
    sig("BN_bin2bn", _c, [_c, _i, _c])
    sig("BN_bn2binpad", _i, [_c, _c, _i])
    sig("BN_free", None, [_c])
    sig("BN_CTX_new", _c, [])
    sig("BN_CTX_free", None, [_c])
    sig("EC_POINT_new", _c, [_c])
    sig("EC_POINT_free", None, [_c])
    sig("EC_POINT_mul", _i, [_c, _c, _c, _c, _c, _c])
    sig("EC_POINT_point2oct", _sz, [_c, _c, _i, _c, _sz, _c])
    sig("EC_POINT_oct2point", _i, [_c, _c, _c, _sz, _c])
    sig("EC_KEY_get0_public_key", _c, [_c])
    sig("ECDH_compute_key", _i, [_c, _sz, _c, _c, _c])
    sig("EVP_CIPHER_CTX_new", _c, [])
    sig("EVP_CIPHER_CTX_free", None, [_c])
    sig("EVP_aes_128_gcm", _c, [])
    sig("EVP_EncryptInit_ex", _i, [_c, _c, _c, _c, _c])
    sig("EVP_EncryptUpdate", _i, [_c, _c, _c, _c, _i])
    sig("EVP_EncryptFinal_ex", _i, [_c, _c, _c])
    sig("EVP_CIPHER_CTX_ctrl", _i, [_c, _i, _i, _c])
    sig("ECDSA_do_sign", _c, [_c, _i, _c])
    sig("ECDSA_SIG_get0", None, [_c, ctypes.POINTER(_c), ctypes.POINTER(_c)])
    sig("ECDSA_SIG_free", None, [_c])


class LibcryptoBackend:
    """RFC 8291 / RFC 8292 primitives over the OS OpenSSL via ctypes."""

    name = "libcrypto"

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib

    # -- EC key material -----------------------------------------------------
    def _new_key(self):
        key = self._lib.EC_KEY_new_by_curve_name(NID_P256)
        if not key:
            raise BackendUnavailable("EC_KEY_new_by_curve_name failed")
        return key

    def _point_bytes(self, group, point, ctx) -> bytes:
        buf = ctypes.create_string_buffer(65)
        n = self._lib.EC_POINT_point2oct(group, point, POINT_UNCOMPRESSED, buf, 65, ctx)
        if n != 65:
            raise ValueError("EC point did not encode to 65 bytes")
        return buf.raw[:65]

    def generate_keypair(self):
        lib = self._lib
        key = self._new_key()
        ctx = lib.BN_CTX_new()
        try:
            if lib.EC_KEY_generate_key(key) != 1:
                raise BackendUnavailable("EC_KEY_generate_key failed")
            group = lib.EC_KEY_get0_group(key)
            priv_bn = lib.EC_KEY_get0_private_key(key)
            raw = ctypes.create_string_buffer(32)
            if lib.BN_bn2binpad(priv_bn, raw, 32) != 32:
                raise BackendUnavailable("BN_bn2binpad failed")
            pub = self._point_bytes(group, lib.EC_KEY_get0_public_key(key), ctx)
            return raw.raw[:32], pub
        finally:
            lib.BN_CTX_free(ctx)
            lib.EC_KEY_free(key)

    def public_from_private(self, raw_private: bytes) -> bytes:
        lib = self._lib
        key = self._new_key()
        bn = lib.BN_bin2bn(raw_private, len(raw_private), None)
        ctx = lib.BN_CTX_new()
        point = None
        try:
            if not bn or lib.EC_KEY_set_private_key(key, bn) != 1:
                raise ValueError("invalid P-256 private scalar")
            group = lib.EC_KEY_get0_group(key)
            point = lib.EC_POINT_new(group)
            if lib.EC_POINT_mul(group, point, bn, None, None, ctx) != 1:
                raise ValueError("invalid P-256 private scalar")
            return self._point_bytes(group, point, ctx)
        finally:
            if point:
                lib.EC_POINT_free(point)
            lib.BN_CTX_free(ctx)
            lib.BN_free(bn)
            lib.EC_KEY_free(key)

    def encrypt_ecdh(self, peer_public: bytes):
        lib = self._lib
        key = self._new_key()
        ctx = lib.BN_CTX_new()
        peer_point = None
        try:
            if lib.EC_KEY_generate_key(key) != 1:
                raise BackendUnavailable("EC_KEY_generate_key failed")
            group = lib.EC_KEY_get0_group(key)
            server_pub = self._point_bytes(group, lib.EC_KEY_get0_public_key(key), ctx)
            peer_point = lib.EC_POINT_new(group)
            if lib.EC_POINT_oct2point(group, peer_point, peer_public, len(peer_public), ctx) != 1:
                raise ValueError("subscriber public key is not a valid P-256 point")
            shared = ctypes.create_string_buffer(32)
            if lib.ECDH_compute_key(shared, 32, peer_point, key, None) != 32:
                raise ValueError("ECDH did not yield a 32-byte secret")
            return server_pub, shared.raw[:32]
        finally:
            if peer_point:
                lib.EC_POINT_free(peer_point)
            lib.BN_CTX_free(ctx)
            lib.EC_KEY_free(key)

    def aes128gcm_encrypt(self, key: bytes, iv: bytes, plaintext: bytes) -> bytes:
        lib = self._lib
        ctx = lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise BackendUnavailable("EVP_CIPHER_CTX_new failed")
        try:
            if lib.EVP_EncryptInit_ex(ctx, lib.EVP_aes_128_gcm(), None, key, iv) != 1:
                raise BackendUnavailable("EVP_EncryptInit_ex failed")
            out = ctypes.create_string_buffer(len(plaintext) + 16)
            outl = _i(0)
            if lib.EVP_EncryptUpdate(ctx, out, ctypes.byref(outl), plaintext, len(plaintext)) != 1:
                raise BackendUnavailable("EVP_EncryptUpdate failed")
            body = out.raw[:outl.value]
            fin = _i(0)
            if lib.EVP_EncryptFinal_ex(ctx, out, ctypes.byref(fin)) != 1:
                raise BackendUnavailable("EVP_EncryptFinal_ex failed")
            body += out.raw[:fin.value]
            tag = ctypes.create_string_buffer(16)
            if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tag) != 1:
                raise BackendUnavailable("GCM tag fetch failed")
            return body + tag.raw[:16]
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)

    def sign_es256(self, raw_private: bytes, message: bytes) -> bytes:
        lib = self._lib
        digest = hashlib.sha256(message).digest()
        key = self._new_key()
        bn = lib.BN_bin2bn(raw_private, len(raw_private), None)
        sig = None
        try:
            if not bn or lib.EC_KEY_set_private_key(key, bn) != 1:
                raise ValueError("invalid P-256 private scalar")
            sig = lib.ECDSA_do_sign(digest, len(digest), key)
            if not sig:
                raise ValueError("ECDSA_do_sign failed")
            r, s = _c(), _c()
            lib.ECDSA_SIG_get0(sig, ctypes.byref(r), ctypes.byref(s))
            rb, sb = ctypes.create_string_buffer(32), ctypes.create_string_buffer(32)
            if lib.BN_bn2binpad(r, rb, 32) != 32 or lib.BN_bn2binpad(s, sb, 32) != 32:
                raise ValueError("ECDSA signature did not encode to 64 bytes")
            return rb.raw[:32] + sb.raw[:32]
        finally:
            if sig:
                lib.ECDSA_SIG_free(sig)
            lib.BN_free(bn)
            lib.EC_KEY_free(key)


# NIST AES-128-GCM known-answer: all-zero key/IV, empty plaintext -> this tag.
_KAT_GCM_TAG = bytes.fromhex("58e2fccefa7e3061367f1d57a4e7455a")
# P-256 generator G (public point for scalar == 1).
_KAT_GENERATOR = bytes.fromhex(
    "04"
    "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
    "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5")


def _self_test(backend: LibcryptoBackend) -> None:
    """Prove this libcrypto matches the call signatures before trusting it."""
    if backend.aes128gcm_encrypt(b"\x00" * 16, b"\x00" * 12, b"") != _KAT_GCM_TAG:
        raise BackendUnavailable("AES-128-GCM known-answer test failed (ABI mismatch)")
    if backend.public_from_private((1).to_bytes(32, "big")) != _KAT_GENERATOR:
        raise BackendUnavailable("P-256 known-answer test failed (ABI mismatch)")


def load() -> LibcryptoBackend:
    """Return a verified libcrypto backend, or raise BackendUnavailable."""
    try:
        lib = _resolve()
        _bind(lib)
    except BackendUnavailable:
        raise
    except (OSError, AttributeError) as exc:
        raise BackendUnavailable(f"libcrypto not usable via ctypes: {exc}") from exc
    backend = LibcryptoBackend(lib)
    _self_test(backend)
    return backend
