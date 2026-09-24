# Task: Integrate release 3.13.139 (tina4-python)

## Outcome
One green, conflict-resolved integration branch `feature/release3.13.139` off origin/v3
(== tag 3.13.138). Merge 8 fix branches keeping BOTH intents. No merge to v3, no bump, no tag.

## Scope
- [x] git fetch origin; confirm live PR/branch list
- [x] Cut feature/release3.13.139 from origin/v3
- [ ] (a) merge fix/supply-chain-python-release-env
- [ ] (b) merge fix/ssrf-guard
- [ ] (c) merge fix/session-first-use-race
- [ ] (d) merge fix/db-async-concurrency
- [ ] (e) merge fix/dev-surface-hardening
- [ ] (f) merge fix/queue-orm-bugs
- [ ] (g) merge fix/medium-security
- [ ] (h) merge fix/auth-hardening
- [ ] Full pytest on lab under mutex (require services+oidc)
- [ ] Push feature/release3.13.139

## Tests
- [ ] Full suite: 0 failed AND 0 skipped on lab

## Bugs (integration fixes: red-because-v3-moved, conflict resolutions)
- (log here)

## Commits
- (merge commits + integration fixes)

## Status: In Progress
