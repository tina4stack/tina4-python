"""The Web Push crypto backend contract.

A backend supplies the five primitives RFC 8291 / RFC 8292 need that CPython's
stdlib cannot: P-256 keygen, ECDH, AES-128-GCM, the public point of a stored
scalar, and an ES256 signature. Everything else (HKDF, HMAC, the record framing,
the JWT assembly) is pure stdlib and lives in ``__init__``, written once and
shared by both backends.

Two backends implement this contract: ``_libcrypto`` (ctypes -> the OS OpenSSL,
zero packages, the server path) and ``_cryptography`` (the pyca package, the
Mac/Windows dev fallback). Both return the SAME bytes, so the wire output stays
identical to the PHP, Ruby and Node frameworks whichever one runs.

Each method raises ``ValueError`` on malformed key material. A backend that
cannot run on this host raises ``BackendUnavailable`` from its ``load()`` so the
selector can fall through to the next one.

Contract (all keys are raw bytes, points are 65-byte uncompressed ``0x04`` form):

    generate_keypair() -> (raw_private32, public65)
        A fresh random P-256 keypair.
    public_from_private(raw_private32) -> public65
        The public point for a stored scalar (used to validate a VAPID pair).
    encrypt_ecdh(peer_public65) -> (server_public65, shared32)
        Generate an ephemeral keypair, ECDH against the subscriber's key, and
        hand back both the ephemeral public point and the shared secret. The
        ephemeral private key never leaves the backend.
    aes128gcm_encrypt(key16, iv12, plaintext) -> ciphertext_with_tag
        AES-128-GCM; the 16-byte tag is appended to the ciphertext.
    sign_es256(raw_private32, message) -> signature64
        ECDSA P-256 / SHA-256 over ``message``, as raw r||s (each left-padded
        to 32 bytes).
"""
from __future__ import annotations


class BackendUnavailable(RuntimeError):
    """Raised by a backend's ``load()`` when it cannot run on this host."""
