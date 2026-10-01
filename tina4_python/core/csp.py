# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Per-response Content-Security-Policy nonce.

The framework serves a strict default CSP (``default-src 'self'``). A browser
refuses every inline ``<style>`` and ``<script>`` under that policy unless the
element carries a nonce that the ``Content-Security-Policy`` header also names.
So the framework mints one cryptographically-random nonce per response, stamps
it on every inline ``<style>``/``<script>`` it emits, and injects the matching
``'nonce-<X>'`` into the ``style-src`` and ``script-src`` directives of the CSP
header. The same value reaches user templates through the Frond global
``csp_nonce()``.

The nonce lives in a :class:`contextvars.ContextVar`, so each request gets its
own value and concurrent requests never see each other's. ``server.handle()``
sets a fresh nonce at the start of every request and clears it in ``finally``,
exactly as it does the request id. Whoever touches the nonce first in a request
- the body emitter rendering inline content, or the security middleware building
the header - gets the same value, because :func:`current_csp_nonce` generates
one on first access and caches it in the contextvar for the rest of the request.
"""
import base64
import contextvars
import os
import secrets

# None until a request (or the first emitter/header call) sets one.
_current_nonce: contextvars.ContextVar = contextvars.ContextVar(
    "tina4_csp_nonce", default=None
)


def generate_nonce() -> str:
    """Return a fresh cryptographically-random nonce (128 bits, URL-safe)."""
    return base64.b64encode(secrets.token_bytes(16)).decode("ascii")


def set_current_nonce(value: str) -> None:
    """Set the nonce for the current request context."""
    _current_nonce.set(value)


def clear_current_nonce() -> None:
    """Clear the nonce at the end of a request (mirrors clear_request_id())."""
    _current_nonce.set(None)


def current_csp_nonce() -> str:
    """Return the current request's nonce, minting one on first access.

    Generate-on-first-access makes the value independent of ordering: whether
    the inline body or the CSP header is built first, both read the same nonce.
    """
    value = _current_nonce.get()
    if not value:
        value = generate_nonce()
        _current_nonce.set(value)
    return value


def csp_nonce() -> str:
    """Frond global: the current response's CSP nonce.

    Use it on any inline element a template emits::

        <style nonce="{{ csp_nonce() }}"> ... </style>
        <script nonce="{{ csp_nonce() }}"> ... </script>
    """
    return current_csp_nonce()


def inject_nonce_into_csp(csp: str, nonce: str) -> str:
    """Return ``csp`` with ``'nonce-<nonce>'`` present in style-src AND script-src.

    For the default ``default-src 'self'`` this yields
    ``default-src 'self'; style-src 'self' 'nonce-X'; script-src 'self' 'nonce-X'``.
    When a directive is absent it is derived from ``default-src`` (falling back to
    ``'self'``) so the framework's own nonce'd content always works; when present
    the nonce is appended (idempotently). Every other directive is kept, in order.
    """
    token = f"'nonce-{nonce}'"
    directives: list[list[str]] = []
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(None, 1)
        name = bits[0].lower()
        value = bits[1].strip() if len(bits) > 1 else ""
        directives.append([name, value])

    default_value = next(
        (value for name, value in directives if name == "default-src"), "'self'"
    )

    for directive in ("style-src", "script-src"):
        existing = next((d for d in directives if d[0] == directive), None)
        if existing is not None:
            if token not in existing[1].split():
                existing[1] = (existing[1] + " " + token).strip()
        else:
            base = default_value if default_value else "'self'"
            directives.append([directive, (base + " " + token).strip()])

    return "; ".join(
        f"{name} {value}".strip() if value else name for name, value in directives
    )


def resolve_csp_header(nonce: str) -> str:
    """Build the CSP header value for ``nonce`` from the environment.

    Honours ``TINA4_CSP`` (default ``default-src 'self'``) and always injects the
    nonce into style-src and script-src. ``TINA4_CSP=""`` is treated as the
    default policy (the empty-string / unset behaviour is unchanged elsewhere).
    """
    csp = os.environ.get("TINA4_CSP") or "default-src 'self'"
    return inject_nonce_into_csp(csp, nonce)
