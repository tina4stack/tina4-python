# Task: Database concurrency - async API, exclusive connection lending, no double execution

**Outcome:** an `async def` route that talks to the database never blocks the event
loop, on every engine; no two concurrent requests ever share a connection or a
transaction; a paginated `fetch()` runs its statement once when the page proves the
total. Recorded as ADR-0074 (tina4-documentation, branch `adr/0074-db-concurrency`).

User report: "psycopg2 is blocking routes" (reproduced on origin/v3, real PostgreSQL).

## Scope
- [ ] Baseline: measure before-latency per engine on the built-in server and uvicorn
- [ ] Tests first, confirmed RED on origin/v3 (real engines, no mocks)
- [ ] Bounded `ConnectionPool`: exclusive checkout/checkin, timeout, `DatabasePoolExhausted` naming TINA4_DB_POOL
- [ ] Every sync `Database` operation runs on an exclusively leased connection
- [ ] Transaction affinity via ContextVar (thread-local for sync code, task-local for async)
- [ ] SQLite: `BEGIN IMMEDIATE`, write lock never held across a busy wait, `:memory:` pool = 1
- [ ] Async API: `*_async` on `Database` + `run_async()`; ORM `*_async`; `transaction_async()`
- [ ] Debug warning: sync DB call on an event-loop thread, once per route
- [ ] `fetch()` COUNT probe only when the page cannot prove the total (all engines)
- [ ] Docs: README, CLAUDE.md, .claude/skills references, tina4-documentation python chapters
- [ ] CLI scaffold templates (tina4 repo) if they emit `async def` DB routes
- [ ] Parity measurement: Node / PHP / Ruby, same scenarios per engine (lab)
- [ ] Benchmark before/after (hot path: fetch / fetch_one / execute)

## Parity
| Concern                              | Python | PHP | Ruby | Node |
|--------------------------------------|--------|-----|------|------|
| no-DB request blocked by slow query  | ❌ BUILD | ?  | ?    | ?    |
| second DB request blocked            | ❌ BUILD | ?  | ?    | ?    |
| concurrent requests share a txn      | ❌ BUILD | ?  | ?    | ?    |
| async API                            | ❌ BUILD | n/a | n/a | native |

## Tests (written first, real - no mocks, positive + negative)
- [ ] slow query + concurrent no-DB request < 0.5s (async API in async route; sync API in def route) - every engine
- [ ] concurrent DB request does not wait for the slow one - every engine
- [ ] rollback isolation between concurrent requests - every engine
- [ ] pool exhaustion raises the clear error naming TINA4_DB_POOL
- [ ] async API == sync API on the write-path + pagination contract fixtures - every engine
- [ ] fetch() executes the statement once when the page proves the total; COUNT still runs for a full page
- [ ] debug warning fires once per route for a sync call on the loop; never for def routes / async API

## Bugs
- [ ] async route + sync DB call blocks the whole event loop (/ping waits 3.6s behind a 2s query)
- [ ] default pool=0 shares ONE connection between concurrent requests (serialises + shares a transaction)
- [ ] ConnectionPool is round-robin with a no-op checkin: lends one adapter to many threads
- [ ] fetch() runs the statement twice (COUNT probe + page)
- [ ] thread-local transaction pin leaks across requests on a reused worker thread

## Commits
- (hash  description)

## Status: In Progress
