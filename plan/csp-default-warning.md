# Task: Warn (never fail) when the default CSP is in force

Issue: tina4-nodejs#61 — `SecurityHeadersMiddleware` serves `Content-Security-Policy:
default-src 'self'` unconditionally when `TINA4_CSP` is unset. It silently breaks
upgraded apps (runtime inline styles, cross-origin fonts/scripts/CDNs, data: URIs,
cross-origin WebSocket/XHR e.g. a LiveKit host). Failure surfaces only in the browser
at runtime — invisible to logs, health checks, and the rollout. Stack-wide (all four).

## Decision (maintainer, this session)
- KEEP `default-src 'self'` as the secure default. Do NOT weaken it, do NOT stop
  sending it. Removing a hardening default to accommodate cross-origin apps trades
  security for convenience; the app opts in by setting `TINA4_CSP`.
- The real defect is the SILENCE, not the strictness. Fix = a loud, **once-per-process**
  boot/first-request WARNING when the default is in force (TINA4_CSP unset), naming the
  header, what it blocks, the `TINA4_CSP` escape hatch, and how to silence the notice.
- **WARN, never FAIL** — a hard fail would block `tina4 serve` locally and a prod boot.
  Non-fatal: logging must never break a request (wrapped, like `_cors_warn_once`).
- Fires only when `TINA4_CSP` is ABSENT. Setting it to anything (incl. empty) is an
  explicit opt-in and stays silent.

## Scope
- [x] Python (reference): warn-once helper + call in `before_security`
- [x] PHP: parity
- [x] Ruby: parity
- [x] Node: parity

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| warn-once on default CSP | ✅ | ✅ | ✅ | ✅ |

## Tests (real logger capture, no mocks; positive + negative)
- [x] default in force (TINA4_CSP unset) -> warning emitted exactly ONCE across many calls
- [x] TINA4_CSP set -> NO warning
- [x] CSP header still `default-src 'self'` when unset (behaviour unchanged)

Verified locally (Windows), each targeted test green AND mutation-proven (neutralise
the once-guard -> the "exactly once" case goes RED):
- Python: `pytest tests/test_csp_default_warning.py` -> 2 passed
- PHP:    `phpunit tests/CspDefaultWarningTest.php` -> 2 tests, 4 assertions
- Ruby:   `rspec spec/csp_default_warning_spec.rb` -> 2 examples, 0 failures
- Node:   `tsx test/cspDefaultWarning.test.ts` -> 4 passed; `npm run typecheck` clean
Full suites run on CI/lab.

## Bugs
- (none — additive log line; behaviour unchanged, never fails a request)

## Commits
- (recorded on the v3 commits, all four repos)

## Status: Complete (pending CI green + release decision)
