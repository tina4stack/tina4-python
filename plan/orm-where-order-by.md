# Task: ORM `where()` gains `order_by` (parity with find/all/QueryBuilder)

## Goal
Add an optional `order_by` / `orderBy` argument to `Model.where()` in all four
frameworks so a filtered query can be ordered directly, matching what
`find()`, `all()`, and `QueryBuilder` already do.

## Context
`where()` is the only filtered finder that cannot order its result. Its
siblings all can. Because `where()` returns a plain `list`/array, you also
cannot chain `.order_by()` onto the result — so today, ordering a filtered set
forces a drop to `QueryBuilder` or hand-written `ORDER BY` in `select()` SQL.
`Model.where("active = ?", [1], order_by="name")` raises "unexpected argument".
Reported by the maintainer as "ORM -> where -> order_by, either functionality
or skills"; investigation shows it is **functionality** (a uniform omission in
all four), with minor doc drift on the side.

Verified against source (not CLAUDE.md, which has drifted):

| method        | Python           | PHP              | Ruby            | Node                    |
|---------------|------------------|------------------|-----------------|-------------------------|
| `find()`      | order_by ✅ :589 | orderBy ✅ :847  | ✅ :204         | orderBy ✅ :415/476     |
| `all()`       | order_by ✅ :692 | orderBy ✅ :903  | order_by ✅ :318| orderBy ✅ :552/569     |
| `QueryBuilder`| `.order_by()` ✅ | `.orderBy()` ✅  | `.order_by` ✅  | `.orderBy()` ✅         |
| **`where()`** | ❌ :745          | ❌ :1237         | ❌ :305         | ❌ :582                 |

Reuse ladder: rung 4 — the design is already proven in each framework's own
`all()`. Port that exact idiom into `where()`; write no new mechanism.

## Branch
Targets **`v3`** (staging) in all four repos. Additive, non-breaking. Natural
to ride the next framework release (3.13.65).

## Scope
- [ ] Read the Python `where()` / `all()` reference + existing where tests
- [ ] Python (master): add `order_by=None`, append `ORDER BY` to the SELECT (NOT the with_count COUNT query)
- [ ] Python: real-SQLite lock-in tests (positive + negative)
- [ ] PHP: mirror — `?string $orderBy = null`, append `ORDER BY`
- [ ] PHP: real-SQLite lock-in tests
- [ ] Ruby: mirror — `order_by: nil` kwarg, append `ORDER BY`
- [ ] Ruby: ALSO add `limit:` / `offset:` kwargs to `where()` (parity with the other 3; owner-approved fold-in 2026-07-10)
- [ ] Ruby: real-SQLite lock-in specs
- [ ] Node: mirror — `orderBy?: string` (6th positional, matching find/all), `ORDER BY` before LIMIT
- [ ] Node: real-SQLite lock-in tests + `npm run typecheck`
- [ ] Docs: `where()` stub in all 4 CLAUDE.md gains order_by; fix the `all()` order_by doc-drift; skill ORM refs show the ordered form
- [ ] Independent verification: re-run the FULL suite myself at HEAD in each repo

## Parity
| Feature                    | Python | PHP | Ruby | Node |
|----------------------------|--------|-----|------|------|
| `where(..., order_by=...)` | ❌     | ❌  | ❌   | ❌   |

## Tests (written first, real — no mocks, positive + negative)
- [ ] Python: insert rows out of order -> `where("1=1", order_by="name ASC")` returns sorted
- [ ] Python: `order_by="id DESC"` returns reverse order
- [ ] Python: negative — `where(...)` WITHOUT order_by is unchanged (insertion/natural order, no ORDER BY injected)
- [ ] Python: with_count path still returns `(rows, total)` and the COUNT query carries no ORDER BY
- [ ] PHP / Ruby / Node: the same three cases against real SQLite

## Bugs
- [ ] `where()` cannot order its results (all 4) — tick when a real ordered-result test passes per framework

## Commits
- (hash  description — one line per landed change, per framework)

## Risks / Open questions
1. **Node ergonomics.** `orderBy` lands as the 6th positional arg
   (`where(cond, params, limit, offset, include, orderBy)`), so you pass
   `20, 0, undefined` before it — ugly, but it is exactly how Node `find()` /
   `all()` already take `orderBy`. Keeping `where()` consistent with its own
   siblings beats inventing an options-object just for `where`. Moving all Node
   finders to an options object is a separate, bigger API decision.
2. **Security — raw `ORDER BY` interpolation.** `order_by` is concatenated into
   SQL (column expressions cannot be bound as params in any driver). This is
   the *existing* convention in `find()` / `all()` / `QueryBuilder` across all
   four, and `order_by` is developer-supplied, not user input. This fix keeps
   that convention rather than diverging in `where()` alone. A cross-cutting
   allowlist/validator for `order_by` across ALL finders is a possible future
   hardening item — out of scope here, flagged deliberately.
3. **Ruby `where()` also lacks `limit:` / `offset:`** (the other three have
   them). DECISION 2026-07-10 (owner): FOLD IN — add `limit:`/`offset:` to Ruby
   `where()` in the same pass so all four `where()` signatures reach full parity
   (order_by + limit + offset). Scope item added below.

## Status: Awaiting approval
