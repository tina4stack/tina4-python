"""Web Push crypto through the pyca ``cryptography`` package.

The dev fallback. When ctypes cannot reach a safe OS OpenSSL - a stock Mac, a
Windows workstation, a musl image without OpenSSL - this backend runs instead,
provided the optional package is installed (``pip install tina4-python[push]``).
It produces the same bytes as the libcrypto backend, so the wire output does not
change with the host.

``load()`` raises ``BackendUnavailable`` when the package is absent, so the
selector can report both misses in one clear error.
"""
from __future__ import annotations

from ._base import BackendUnavailable


class CryptographyBackend:
    """RFC 8291 / RFC 8292 primitives over the pyca cryptography package."""

    name = "cryptography"

    def __init__(self, module_bundle):
        (self._ec, self._AESGCM, self._Encoding, self._PublicFormat,
         self._hashes, self._decode_dss) = module_bundle

    def _public_bytes(self, public_key) -> bytes:
        return public_key.public_bytes(self._Encoding.X962, self._PublicFormat.UncompressedPoint)

    def generate_keypair(self):
        priv = self._ec.generate_private_key(self._ec.SECP256R1())
        pub = self._public_bytes(priv.public_key())
        raw = priv.private_numbers().private_value.to_bytes(32, "big")
        return raw, pub

    def public_from_private(self, raw_private: bytes) -> bytes:
        priv = self._ec.derive_private_key(int.from_bytes(raw_private, "big"), self._ec.SECP256R1())
        return self._public_bytes(priv.public_key())

    def encrypt_ecdh(self, peer_public: bytes):
        peer = self._ec.EllipticCurvePublicKey.from_encoded_point(self._ec.SECP256R1(), peer_public)
        ephemeral = self._ec.generate_private_key(self._ec.SECP256R1())
        server_pub = self._public_bytes(ephemeral.public_key())
        shared = ephemeral.exchange(self._ec.ECDH(), peer)
        return server_pub, shared

    def aes128gcm_encrypt(self, key: bytes, iv: bytes, plaintext: bytes) -> bytes:
        return self._AESGCM(key).encrypt(iv, plaintext, None)

    def sign_es256(self, raw_private: bytes, message: bytes) -> bytes:
        priv = self._ec.derive_private_key(int.from_bytes(raw_private, "big"), self._ec.SECP256R1())
        der = priv.sign(message, self._ec.ECDSA(self._hashes.SHA256()))
        r, s = self._decode_dss(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def load() -> CryptographyBackend:
    """Return the cryptography backend, or raise BackendUnavailable if absent."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ImportError as exc:
        raise BackendUnavailable("the cryptography package is not installed") from exc
    return CryptographyBackend((ec, AESGCM, Encoding, PublicFormat, hashes, decode_dss_signature))
