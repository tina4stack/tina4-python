# Task: Cyclomatic complexity round 1 — six functions below CC 40

## Outcome
Every production function currently at CC >= 40 drops below 40, behaviour-preserving,
on branch `refactor/complexity-round1` off `origin/v3`. One PR to `v3`, not merged.

## Scope
- [ ] ORM.create_table (56 -> <40) — orm/model.py
- [ ] app (53 -> <40) — core/server.py
- [ ] ORM.save (49 -> <40) — orm/model.py
- [ ] Ai._translate_message (45 -> <40) — ai/client.py
- [ ] _resolve (44 -> <40) — frond/engine.py
- [ ] _split_statements (40 -> <40) — migration/runner.py (parity state scanner)

## Parity
| Function | Python |
|----------|--------|
| create_table | ⬜ |
| app | ⬜ |
| save | ⬜ |
| _translate_message | ⬜ |
| _resolve | ⬜ |
| _split_statements | ⬜ |

## Tests (characterization first, real — no mocks; SQLite local + PG/MySQL/MSSQL/Firebird on lab)
- [ ] characterization module pins current behaviour of all six, mutation-proofed
- [ ] full suite green locally (SQLite)
- [ ] full suite green on lab (postgres, mysql, mssql, firebird, mongo)

## Bugs
- (none expected — behaviour-preserving refactor)

## Commits
- (log here)

## Status: In Progress
