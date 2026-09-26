# Task: Integrate release 3.13.139 (tina4-python)

## Outcome
One green, conflict-resolved integration branch feature/release3.13.139 off
origin/v3 (== tag 3.13.138). 8 fix branches merged keeping BOTH intents. No
merge to v3, no version bump, no tag (main session does that).

## Scope
- [x] git fetch origin; confirmed live PR/branch list (7 PRs + fix/auth-hardening)
- [x] Cut feature/release3.13.139 from origin/v3
- [x] (a) fix/supply-chain-python-release-env (clean)
- [x] (b) fix/ssrf-guard (clean)
- [x] (c) fix/session-first-use-race (clean)
- [x] (d) fix/db-async-concurrency (conflicts resolved)
- [x] (e) fix/dev-surface-hardening (conflicts resolved)
- [x] (f) fix/queue-orm-bugs (clean)
- [x] (g) fix/medium-security (conflicts resolved)
- [x] (h) fix/auth-hardening (clean)
- [x] Signed-off + both trailers on all my commits
- [ ] Full pytest on lab under mutex (require services + OIDC)
- [ ] Push feature/release3.13.139

## Integration fixes / conflict resolutions (both intents kept)
- db-async: pool.py ADR-0074 (blocking exclusive checkout + async) supersedes v3
  interim inline pool (6c07321a) but keeps exclusive-lease intent. Re-applied
  v3-only semantic fixes db-async predated: column_key write filter (658b8d10),
  execute() returns rows via result._returns_rows (30b61019), fetch/fetch_one
  cache flush+bypass for a write that returns rows (#133, eebb0a7e). Ported the
  #133 is_write guard into every engine's reworked fetch() so a write that
  returns rows is never paginated/COUNT-probed (a probe repeats the write); kept
  _commit_fetched_write on fetch/fetch_one (postgres/mssql/firebird/odbc). Dropped
  stale auto-merge leftover 'if total is None: total = len(rows)'. odbc: kept
  try/finally rollback + guarded _end_transaction.
- dev-surface (ADR-0078): superseded by v3 ADR-0082 (stronger: dedicated MCP
  token, app API key no longer unlocks dev surface). Took v3 everywhere.
- medium-security (F5/F6): already on v3 as supersets; took v3 (stricter host
  assertions, extra regressions).

## Fixes #145
ADR-0074 pool (exclusive checkout + transaction-to-connection affinity via a
contextvars borrow) closes #145 (round-robin handed a tx's pinned connection to
other threads). Named red-first regression added: real Postgres, pool=4 -
tests/test_issue145_pool_transaction_isolation.py. Belongs in the PR description.

## Tests
- [ ] Full suite: 0 failed AND 0 skipped on lab (graph/OIDC/firebird run)

## Bugs
- (none outstanding from integration; short-secret auth A2 test fallout to watch
  during lab run)

## Commits (HEAD after trailer normalisation)
- a7683ef0063add1788f239cda1fef0dc3e8f2566  Merge fix/auth-hardening (HEAD)
- 8 merge commits + #145 regression test; see git log origin/v3..HEAD

## Status: In Progress (lab verification pending)
