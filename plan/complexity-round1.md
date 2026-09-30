# Task: Cyclomatic complexity round 1 — six functions below CC 40

## Outcome
Every production function currently at CC >= 40 drops below 40, behaviour-preserving,
on branch `refactor/complexity-round1` off `origin/v3`. One PR to `v3`, not merged.

## Scope (before -> after CC via radon; all off tina4-metrics top-15)
- [x] ORM.create_table (56 -> 12) — orm/model.py
- [x] app (53 -> 7) — core/server.py
- [x] ORM.save (49 -> 9) — orm/model.py
- [x] Ai._translate_message (45 -> 3) — ai/client.py
- [x] _resolve (44 -> 6) — frond/engine.py
- [x] _split_statements (40 -> 1) — migration/runner.py (parity state scanner)

## Parity
| Function | Python |
|----------|--------|
| create_table | ✅ |
| app | ✅ |
| save | ✅ |
| _translate_message | ✅ |
| _resolve | ✅ |
| _split_statements | ✅ |

## Tests (characterization first, real — no mocks; SQLite local + PG/MySQL/MSSQL/Mongo on lab)
- [x] characterization module pins current behaviour of all six (45 tests, green pre-refactor)
- [~] full suite green locally (SQLite) — running clean (earlier failures were a corrupt local pytest-asyncio, not the refactor)
- [~] full suite green on lab (postgres, mysql, mssql, mongo) — running

## Perf gate (hot paths: _resolve, save, app)
- carbonah lint: 62 findings vs v3 baseline 63 (one E005 removed in ai/client.py, none added)
- carbonah measure: grade APlus on both; branch SCI min 0.0088 <= baseline min 0.0108 (SCI ~ duration; energy not directly measured)
- micro A/B: render throughput at parity (within ~1.5%, inside noise); save I/O-bound, branch median >= baseline

## Bugs
- (none — behaviour-preserving refactor)

## Commits
- 7dc7565 test: characterization net for complexity-round1 refactor
- 97e6175 refactor: decompose _split_statements into an explicit state scanner
- 6db4cdf refactor: split _resolve into literal + index + member resolvers
- d32b6ed refactor: split Ai._translate_message into per-shape translators
- c9cbfc5 refactor: decompose ORM.create_table into type-map + column helpers
- 4d787d3 refactor: decompose ORM.save into collect/decide/write/hint helpers
- 28e3c06 refactor: split ASGI app() into lifespan/body/stream/buffered helpers

## Status: In Progress
