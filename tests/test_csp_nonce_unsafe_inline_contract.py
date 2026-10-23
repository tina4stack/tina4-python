# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CSP nonce respects a user's 'unsafe-inline' (ADR-0100, refines ADR-0088).

A browser ignores 'unsafe-inline' in any directive that also lists a nonce
(CSP Level 2+). Since 3.13.143 the framework appended its per-response nonce to
script-src/style-src unconditionally - including an app's own TINA4_CSP - so an
app that deliberately allowed inline through 'unsafe-inline' had it silently
blocked (tina4-php#330). The rule now: a directive (present, or derived from
default-src) that already carries 'unsafe-inline' gets NO nonce; the app's
explicit choice wins. The strict default policy is unchanged and still nonced.

The answer key is tina4-documentation/plan/v3/fixtures/securityheaders_contract.json,
invariant csp-nonce-respects-unsafe-inline. The same cases run in all four
frameworks on the real inject function - no mocks, a pure string transform.
"""
from tina4_python.core.csp import inject_nonce_into_csp

NONCE = "abc123"
TOKEN = "'nonce-abc123'"


def _directive(csp: str, name: str) -> str:
    for part in csp.split(";"):
        part = part.strip()
        if part.split(" ", 1)[0].lower() == name:
            return part
    return ""


def test_explicit_unsafe_inline_script_src_keeps_unsafe_inline_and_gets_no_nonce():
    out = inject_nonce_into_csp(
        "default-src 'self'; script-src 'self' 'unsafe-inline'", NONCE
    )
    assert "'unsafe-inline'" in _directive(out, "script-src")
    assert TOKEN not in _directive(out, "script-src")


def test_explicit_unsafe_inline_style_src_keeps_unsafe_inline_and_gets_no_nonce():
    out = inject_nonce_into_csp(
        "default-src 'self'; style-src 'self' 'unsafe-inline'", NONCE
    )
    assert "'unsafe-inline'" in _directive(out, "style-src")
    assert TOKEN not in _directive(out, "style-src")


def test_unsafe_inline_default_src_does_not_spawn_a_nonced_directive():
    out = inject_nonce_into_csp("default-src 'self' 'unsafe-inline'", NONCE)
    # No derived script-src/style-src is added - they fall back to default-src,
    # so the app's inline keeps working; the nonce is nowhere.
    assert TOKEN not in out
    assert _directive(out, "script-src") == ""
    assert _directive(out, "style-src") == ""


def test_mixed_unsafe_inline_script_but_strict_style_nonces_only_style():
    out = inject_nonce_into_csp(
        "default-src 'self'; script-src 'self' 'unsafe-inline'", NONCE
    )
    # script-src opted into inline -> untouched; style-src derived from the
    # strict default -> gets the nonce so framework inline styles still run.
    assert TOKEN not in _directive(out, "script-src")
    assert TOKEN in _directive(out, "style-src")


def test_strict_default_policy_still_gets_the_nonce():
    out = inject_nonce_into_csp("default-src 'self'", NONCE)
    assert TOKEN in _directive(out, "script-src")
    assert TOKEN in _directive(out, "style-src")


def test_explicit_non_unsafe_inline_directive_still_gets_the_nonce():
    out = inject_nonce_into_csp(
        "default-src 'self'; script-src 'self' https://cdn.example", NONCE
    )
    assert TOKEN in _directive(out, "script-src")
