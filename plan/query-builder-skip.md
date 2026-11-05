# Task: QueryBuilder chainable skip() / offset() / take()

## Problem
An AI harness building on Tina4 reached for `QueryBuilder....skip(n)` and hit a wall:
the ORM query builder only exposes `limit(count, offset?)`, with the offset trapped as
`limit()`'s second positional arg. There is no chainable `skip()`, `offset()`, or
`take()`, even though the DocStore Mongo cursor HAS `.skip()` and QueryBuilder's own
`to_mongo()` already emits a `skip` key. Devs from Mongoose / Eloquent / Knex reach for
`.skip()` / `.offset()` and fail.

## Scope
- [x] Measure all four: QB has only `limit(count, offset?)`, no `skip`/`offset`/`take` (confirmed)
- [x] Python — add `offset()`, `skip()` (→offset), `take()` (→limit) + tests (6, mutation-proven)
- [x] PHP — same + tests (6)
- [x] Ruby — same + tests (6)
- [x] Node — same + tests (8) + regenerated committed `types/orm/src/queryBuilder.d.ts`

## Design (minimal, declarative)
Three thin fluent setters over existing internals (`_offset_val`, `_limit_val`):
- `offset(n)` — SQL-native name; exposes the already-stored offset as its own verb.
- `skip(n)` — alias of `offset`; the Mongo/Eloquent name; matches DocStore cursor + `to_mongo()`'s `skip` key.
- `take(n)` — alias of `limit`; the Eloquent name; pairs with `skip` (`.skip(20).take(10)`).
Both SQL `get()` and `to_mongo()` already read `_offset_val`/`_limit_val`, so no
further wiring is needed — the pagination flows to SQLite/Postgres/… AND to Mongo.

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| offset() | ✅ | ✅ | ✅ | ✅ |
| skip()   | ✅ | ✅ | ✅ | ✅ |
| take()   | ✅ | ✅ | ✅ | ✅ |

## Tests (written first, real — no mocks, positive + negative)
- [x] `.order_by(id).skip(2).limit(2)` returns the 3rd+4th rows (real SQLite)
- [x] `.offset(n)` behaves identically to skip (real SQLite)
- [x] `.take(n)` sets the limit (real SQLite)
- [x] `.skip(n)` over-skip past row count returns empty, not an error (negative, real SQLite)
- [x] `.skip(5)` → `to_mongo()` emits `{"skip": 5}` (Mongo path parity)
- [x] methods return the builder (chaining)

## Verification (self-run at HEAD, real SQLite, no mocks)
| Framework | Command | Result |
|-----------|---------|--------|
| Python | `pytest tests/test_query_builder.py` | 59 passed |
| PHP | `phpunit tests/QueryBuilderTest.php` | 63 tests, 113 assertions, OK |
| Ruby | `rspec spec/query_builder_spec.rb` | 66 examples, 0 failures |
| Node | `tsx test/queryBuilder.test.ts` | 66 passed, 0 failed (+ build:types regenerated d.ts) |

Python mutation proof: making `skip()` a no-op broke exactly the 3 skip-dependent
tests; restored → 6/6 pass.

## Docs
- [x] QueryBuilder `Methods:` list in all four CLAUDE.md now lists offset/skip/take
      (noting skip/take are the Mongo/Eloquent aliases) — docs match code.

## Bugs
- (none — additive feature)

## Commits
- (pending — one branch per repo off v3)

## Status: Implemented + verified locally; ready to branch/PR per repo
