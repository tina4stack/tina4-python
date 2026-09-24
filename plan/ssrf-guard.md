# Task: F7 - outbound SSRF guard for the Api client and Web Push (ADR-0084)

Outcome: outbound HTTP (the `Api` client + every redirect it follows, and Web
Push delivery) refuses to connect to private/internal addresses by default, to
stop SSRF against internal services and cloud metadata. Off by default;
`TINA4_ALLOW_PRIVATE_REQUESTS` (truthy) or an explicit host/CIDR allow-list opts
out. Governed by ADR-0084; fixture `tina4-documentation/plan/v3/fixtures/ssrf_guard_contract.json`.

## Scope
- [x] `tina4_python/ssrf.py` - classifier + `guard_url` + no-follow redirect handler
- [x] `Api`: guard initial URL + each redirect hop + download + stream; `allow_hosts` kwarg
- [x] `Push`: guard endpoint, do not follow redirects; `allow_hosts` kwarg
- [x] conftest opt-out for existing local-listener suites (guard suite clears it)
- [x] contract runner `tests/test_ssrf_guard_contract.py` + fixture copy

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| SSRF guard | ✅ | (see repos) | (see repos) | (see repos) |

## Tests (real, no mocks, positive + negative)
- [x] classifier: loopback / metadata / private / cgnat / v4-mapped blocked; public allowed (fixture table)
- [x] non-http(s) scheme refused
- [x] Api blocks request to 127.0.0.1 by default (real loopback listener)
- [x] Api succeeds with TINA4_ALLOW_PRIVATE_REQUESTS=true and with allow_hosts
- [x] Api refuses a 302 hop to 169.254.169.254 (real listener)
- [x] Web Push to a private endpoint refused unless opted in
- [x] mutation-proved: neutering the classifier turns 6 cases red

## Bugs
- (none)

## Commits
- (logged on commit)

## Status: In Progress (local-verified on macOS, Python 3.13; full lab suite lab-pending - lab down this session)
