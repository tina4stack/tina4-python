# Task: Web Push zero-dep backend (ctypes -> libcrypto) with cryptography fallback

Python is the only framework that needed a package for Web Push (PHP=ext-openssl,
Ruby=stdlib openssl, Node=node:crypto are all zero-dep via platform crypto; CPython
stdlib ships no AES / no EC). This adds a Linux-first ctypes -> libcrypto backend so a
Linux SERVER sends push with zero packages, and falls back to `cryptography` on
Mac/Windows dev (and any host where libcrypto will not safely load).

Measured before building (fixed-key interop vs `cryptography`, no mocks):
byte-identical ECDH/CEK/nonce/AES-GCM/full RFC 8291 payload + ES256 cross-verify on
Darwin arm64 (OpenSSL 3.6.4) AND Linux x86_64 (OpenSSL 3.0.13). ctypes layer 97 LOC.

## Scope
- [x] `_base.py` - BackendUnavailable + the backend contract (5 leak-safe methods)
- [x] `_libcrypto.py` - ctypes -> libcrypto backend + safe loader + load-time KAT self-test
- [x] `_cryptography.py` - the existing pyca path behind the same contract
- [x] `__init__.py` - libcrypto-first selection, cryptography fallback, TINA4_PUSH_BACKEND override
- [x] pyproject - keep `push` extra (fallback + Mac/Windows dev); note libcrypto is the zero-dep server path

## Parity
This is Python-only. PHP/Ruby/Node already send push zero-dep via platform crypto and
are NOT touched. The wire output (RFC 8291 payload + ES256 JWT) stays byte-identical,
so the cross-framework contract is preserved by construction.

| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| Web Push zero-dep on server | libcrypto (new) | ext-openssl | stdlib openssl | node:crypto |

## Tests (real, no mocks - cryptography is a genuine interop peer, the browser's role)
- [x] libcrypto backend loads on this platform; `_backend()` prefers it
- [x] byte-identical primitives across both backends: aes128gcm + public_from_private (incl zero-top-byte scalar)
- [x] full encrypt -> decrypt round-trip, forced on EACH backend, decrypted independently by cryptography
- [x] ES256: libcrypto-signed verifies under cryptography; tampered sig rejected (negative)
- [x] off-curve p256dh rejected (negative)
- [x] existing tests/test_push.py stays green (now runs through libcrypto by default on Linux/Mac)

## Verification (real, no mocks)
- macOS arm64 (brew OpenSSL 3.6.4, cryptography 50.0.1): 14 passed, 0 skipped
- Linux lab x86_64 (SYSTEM libcrypto.so.3 OpenSSL 3.0.13, cryptography 41.0.7): 14 passed, 0 skipped
  - both backends exercised (byte-identity + [libcrypto]/[cryptography] round-trips all ran, not skipped)

## Bugs
- (none)

## Commits
- (v3) push: libcrypto-first Web Push backend + cryptography fallback + conformance tests

## Status: Done - verified on macOS and the Linux lab
