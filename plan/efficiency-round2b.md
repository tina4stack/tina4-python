# Task: Efficiency round 2b — carbonah E002 (N+1) + E003 (unbounded)

## Outcome
Every carbonah E002/E003 finding in `tina4_python` is investigated. Genuine N+1 /
unbounded hot-path queries are fixed (batch/eager, bound/paginate) with a result +
query-count characterization test. Reviewed false positives and intentional patterns
are annotated `# carbonah:ignore <CODE>` with a one-line reason, so the reported count
drops honestly with zero behaviour change. Branch `refactor/efficiency-round2b` off
`origin/v3`, one PR to `v3`, NOT merged.

## Investigation (carbonah 0.3.3 — before: E002 9, E003 1)

| # | File:line | Rule | Verdict | Reason |
|---|-----------|------|---------|--------|
| 1 | database/adapter.py:770 | E002 | FALSE POS | `execute_many` chunk loop — the ANTI-N+1: one round-trip per collapsed multi-row VALUES chunk (200 rows → 1 statement on SQLite), not per row |
| 2 | database/adapter.py:783 | E002 | INTENTIONAL | row-at-a-time fallback for statements `build_batch_inserts` cannot collapse safely (RETURNING / upsert / Firebird / ragged) |
| 3 | dev_admin/__init__.py:1029 | E002 | FALSE POS | admin SQL console runs the developer's own multi-statement batch (split on `;`); each is distinct arbitrary SQL, not a data-driven N+1 |
| 4 | migration/runner.py:275 | E002 | INTENTIONAL | one-time v2→v3 backfill; per-row UPDATE+commit isolates failures (a failed row aborts the whole PostgreSQL txn) and keeps log-and-continue. Cold path, runs once |
| 5 | migration/runner.py:829 | E002 | INTENTIONAL | sequential DDL statements from a migration file — ordered, distinct, cannot be JOINed |
| 6 | migration/runner.py:898 | E002 | INTENTIONAL | rollback DDL statements — same as apply |
| 7 | migration/runner.py:906 | E002 | INTENTIONAL | one DELETE per rolled-back migration, each inside its own per-migration transaction (down + delete atomic together) |
| 8 | orm/model.py:1363 | E002 | INTENTIONAL | one spatial-index DDL per PointField at CREATE TABLE — DDL, not a data N+1 |
| 9 | session/__init__.py:229 | E002 | FALSE POS | race-safe CREATE TABLE; the `while` is a bounded retry on a concurrent-create collision, executes once on success |
| 10 | dev_admin/__init__.py:1108 | E003 | FALSE POS | single-row lookup by primary key via `fetch_one` (`WHERE id = ?` → at most one row); a LIMIT is redundant |

Genuine, safely-fixable findings: **0**. All 9 E002 + 1 E003 are heuristic false
positives (DDL-in-loop, the batch primitive itself, a retry loop, an arbitrary-statement
executor, a PK lookup) or behaviour-locked cold-path writes. Fixing any would regress
behaviour (esp. #4 PostgreSQL failure isolation) for no real hot-path win — refused.

## Scope
- [ ] Characterization tests (real SQLite, no mocks): result + query-count
- [ ] Annotate all 10 with `# carbonah:ignore <CODE>` + reason
- [ ] carbonah lint: E002 9→0, E003 1→0, other rules unchanged
- [ ] carbonah measure: no regression
- [ ] tina4 metrics: unaffected
- [ ] affected subsystem suites green (SQLite local)

## Tests (written first, real — no mocks, positive + negative)
- [ ] execute_many collapsible: build_batch_inserts returns 1 stmt for 200 rows (query-count), all 200 land, affected_rows/data correct (result)
- [ ] execute_many fallback: RETURNING not collapsed (returns []), rows still land via the fallback loop
- [ ] migration apply + rollback on real SQLite: end state correct

## Bugs
- (none — comment-only change; no runtime behaviour touched)

## Commits
- (log here)

## Status: In Progress
