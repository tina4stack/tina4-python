# Task: ORM footguns + zero-dep batteries — docs & framework fixes

**Branch:** `v3` (active release line). **Reference:** Python; port to PHP/Ruby/Node after.

## Goal
Close the two undocumented surfaces that drive the ~2.4× agent-build token tax: ORM/write-path
**footguns** (things that silently bite) and the zero-dependency **batteries** (built-ins the agent
doesn't know exist, so it `pip install`s what's already there). Fix the two places the skill is
actively **wrong**.

## Context
Benchmark: a Tina4 app is ≈20 LOC / ~1 dep, but ~2.4× the tokens to build — the unfamiliar-framework
tax. That tax is almost entirely (a) footgun discover→fail→reread loops and (b) the agent reaching
for external libs it doesn't know Tina4 ships. Audit (verified against source) found 10 footguns
incl. 2 skill bugs; `pyproject.toml` `dependencies = []` yet the skill has **0** coverage of
"don't add a dep — it's built in."

## Scope
### A. Skill docs — `tina4-developer-python/references/data-and-orm.md` (then parity)
- [ ] Add an **ORM lifecycle / Footguns** section: no auto table-create + silent `save()→False`;
      `save()`/`create()` never raise (check return + `get_error()`); constructor **raises** on
      explicit `None`/non-dict (the 500-vs-4xx trap); `delete()`/`restore()` raise (asymmetry);
      field constraints validate on the **read** path; `bind_database`/`TINA4_DATABASE_URL`
      precondition (ORM + QueryBuilder); `db.execute()` raises (not `False`); auto-migrate is
      fail-soft + server-only; ordering ties need `created_at DESC, id DESC`.
- [ ] Fix BUG: soft_delete example must declare `is_deleted` (`data-and-orm.md:160`).
- [ ] Fix BUG: migrations path `src/migrations/` → `migrations/` (`data-and-orm.md:351`).
- [ ] Extend the Footguns section with the **framework-gotcha tier** (verify each vs source first;
      port from `tina4_python/CLAUDE.md §11`): **N1** `noauth` from `swagger` = docs-only, route left
      OPEN (security) — frame `@noauth()` as a **last resort**: an unexpected 401 → "the caller needs a
      token", NOT "open the route"; never blanket `@noauth()` to silence 401s; **N2** decorator order
      (`@get/@post` innermost, meta above — wrong order crashes); **N3** Postgres autocommit off → raw
      writes need explicit commit; **N4** Frond (`|raw`/`|safe`, `elif`, `~` concat, `|e` no-args,
      live same-origin/poll/ws); **N5** `DatabaseResult.records` + dict access `row["col"]`; **N6**
      `background(fn, interval)` not `threading.Thread`; **N7** route type-name set (typo raises).
      Resolve the `uv run python app.py` vs `tina4 serve` drift in §11.7.
- [ ] Add a **When to reach for `tina4_context`** subsection (the grounding ladder: skill first →
      context for uncovered / current-API / surprise → write it yourself + verify via `api_method`).
- [ ] Add a **Batteries included — zero deps** section (need → built-in; don't pip-install).
- [ ] Port language-agnostic parts to php/ruby/nodejs dev skills — **verify each lang's behaviour first**.

### B. Framework — `tina4-python` (reference), then parity
- [ ] `save()`: on a driver "no such table" / "no such column: is_deleted", append a targeted hint
      to `last_error` (call `create_table()` / run a migration; declare `is_deleted`).
- [ ] OPEN QUESTION (own issue, not this PR): failure-contract asymmetry — constructor raises /
      `save()`→False / `delete()`→raise / `db.execute()`→raise. Decide the intended contract; making
      them consistent is a bigger, possibly breaking change. Document now, converge later.

## Parity
| Item | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| Footguns doc | ❌ BUILD | ❌ Missing | ❌ Missing | ❌ Missing |
| Batteries doc | ❌ BUILD | ❌ Missing | ❌ Missing | ❌ Missing |
| soft_delete example fix | ❌ BUILD | ⚠️ verify | ⚠️ verify | ⚠️ verify |
| migrations path fix | ❌ BUILD | ⚠️ verify | ⚠️ verify | ⚠️ verify |
| save() no-such-table hint | ✅ done* | ❌ Missing | ❌ Missing | ❌ Missing |

## Tests (real, positive + negative — no mocks)
- [ ] `save()` into a missing table → returns `False` AND `last_error` carries the create_table/migrate hint (real SQLite).
- [ ] soft_delete model WITH declared `is_deleted` → `all()`/`delete()`/`restore()` work; WITHOUT → the documented failure (negative case).
- [ ] Constructor: `Model({"required": None})` raises; `Model()` + set + `save()` → `False` (proves the asymmetry the doc warns about).
- [ ] Each footgun's documented "safe" idiom actually runs (boot-gate over the doc snippets).

## Bugs
- [ ] soft_delete example omits `is_deleted` (`data-and-orm.md`) — HIGH (skill drift; I own the skill, fix direct).
- [ ] migrations path wrong in skill (`src/migrations/`) — LOW-MED (skill drift).
- [x] Framework: `save()` appends a `create_table()`/migrate + `is_deleted` hint on the driver error
      (Python) — `tests/test_orm_save_hints.py` 6 tests + 102-test ORM sweep green, **independently
      re-run** at HEAD. Contract intact (returns `self|False`, never raises). *TODO before commit:
      tighten the table-branch match to require `"table"` in the message so a Postgres/MySQL
      column-not-found doesn't get a spurious table hint (SQLite unaffected).
- [ ] Not committed yet — bundle into `feature/release` with the docs (workstream A) once A lands.

## Commits
- (log here — hash + one-line description per landed change)

## Status: Approved (2026-07-09) — in progress, Python-first (2 workers: docs + framework)
