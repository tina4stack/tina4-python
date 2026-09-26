# Task: Medium security findings (Sept 2026 audit) — fix/medium-security

Outcome: fix the Sept-2026 Medium findings genuinely present on current v3,
red-first + mutation-proved with real services on the lab, at parity across
Python/PHP/Ruby/Node, PR against v3.

## Scope (Python)
- [x] F5 Api host confusion / token leak — fixed (same-origin auth/cookie gate in _build_request)
- [x] F6 X-Forwarded-Host trusted without a trusted-proxy check — fixed (gate on is_trusted_proxy in from_scope)
- [ ] F3 trailing-slash redirect protocol-relative open redirect
- [ ] F2 GraphQL fan-out (node/alias/complexity limit) — needs ADR
- [ ] Lab: full suite green at HEAD, TINA4_REQUIRE_SERVICES=1, 0 failed / 0 skipped
- [ ] PR against v3

## Tests (red-first, real — no mocks)
- [x] tests/test_forwarded_host_trust.py (RED→GREEN + positive twin)
- [x] tests/test_api_cross_origin_token.py (RED→GREEN + positive twin)

## Commits
- (pending push)

## Status: In Progress
