# Task: Queue + ORM correctness bugs (book review)

Outcome: fix the confirmed queue/ORM bugs at parity, each with a named red-first,
real-service, mutation-proved regression test. PRs to v3, not merged.

## Scope
- [ ] Bug 1 — Mongo `retry()`/`dead_letters()[i].id` mismatch (Python; parity check PHP/Ruby/Node)
- [ ] Bug 2 — `size("dead"/"failed"/"dead_letter")` counts DL store on Mongo + RabbitMQ (Kafka stays 0 per ADR-0022 dec 5)
- [ ] Bug 3 — Kafka dead-letter deterministic (flush/delivery-report)
- [ ] Bug 4 — `reject()` dead-letters NOW (ADR-0023), all four
- [ ] Bug 5 — PHP AutoCrud routes register at discovery, not first `new Model()`
- [ ] Bug 6 — Firebird auto_increment insert via generator (Python; parity)
- [ ] Bug 7 — AutoCrud precedence: trace all four; ADR only if they diverge
- [ ] Bug 8c — missing-table hint on MSSQL + Firebird
- [ ] Bug 8d — unknown `include=` raises
- [ ] Bug 8a — `tina4 console` import src (confirm repro first)
- [ ] Bug 8b — "No database bound" in plain scripts (confirm repro first)

## Parity
| Bug | Python | PHP | Ruby | Node |
|-----|--------|-----|------|------|
| 1 size/retry id | ❌ BUILD | ? | ? | ? |
| 2 size(dead) | ❌ BUILD | ? | ? | ? |
| 3 kafka DL | ❌ BUILD | ? | ? | ? |
| 4 reject now | ❌ BUILD | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| 5 autocrud disc | n/a | ❌ BUILD | ? | ? |
| 6 firebird ai | ❌ BUILD | ? | ? | ? |
| 8c table hint | ❌ BUILD | ? | ? | ? |
| 8d include raise| ❌ BUILD | ? | ? | ? |

## Tests (written first, real — no mocks, positive + negative)
- [ ] test_queue_mongo_retry_all_id (real Mongo)
- [ ] test_queue_size_dead_store (real Mongo + RabbitMQ + Kafka==0)
- [ ] test_queue_kafka_dead_letter_deterministic (real Kafka)
- [ ] test_queue_reject_dead_letters_now (real file backend + parity)
- [ ] test_orm_firebird_auto_increment (real Firebird)
- [ ] test_orm_missing_table_hint_mssql_firebird (real MSSQL + Firebird)
- [ ] test_orm_unknown_include_raises (SQLite pure)

## Bugs
- (log here)

## Commits
- (hash  description)

## Status: In Progress
