# Task: native `Context` subsystem — code/doc grounding inside Tina4

**Branch:** `v3`. **Reference:** Python; port to PHP/Ruby/Node.
**Status: APPROVED — build MVP in tina4-python first (2026-07-09), then parity. Build after the
unified harness pod lands (see aatos `aatos-code/deploy/harness-pod/plan.md`).**

**Locked decisions (2026-07-09):** MVP = tina4-python only first · on-disk portable index (Q3 →
`.tina4/context.db` gitignored, not `:memory:`) · dense rerank OFF by default (Q4 zero-dep line held
via `veclite`) · keep `code_search` distinct from `api_*` (Q6 → structural vs semantic).

## Goal
Ship a first-class Tina4 subsystem that indexes an app's own codebase + docs and answers
semantic/keyword queries over it — so a Tina4 app can **ground its own AI assistant on its own
code, offline, ~zero-dep** — with the index kept fresh **automatically on file change**, and
exposed to agents via the dev MCP.

## Context / validation (already done — spike proof)
neemee's retrieval core is **~994 LOC of pure stdlib** (pipeline+memory+encoders+spans; `PIL`/
`pystray` are tray-UI only). Spike (`scratchpad/neemee_spike.py`): `Neemee()` default backend =
`sqlite_fts` (stdlib `sqlite3` FTS, no embedder) **indexed `tina4_python/` → 1000 chunks in 0.57s**
and retrieved the right subsystem on 4/4 queries (`orm/model.py`, `queue/__init__.py`,
`auth/__init__.py`, `frond/FROND.md`) at **7–11 ms**. Passes the reuse ladder: it **complements**
the existing `api_*` reflection index (structured/exact) with semantic/FTS retrieval (fuzzy).

## Scope
- [x] **`tina4_python/context/`** — ported the neemee core (chunkers + `sqlite_fts` backend) as a
      zero-dep `Context` class. API landed per the MVP task brief (not the earlier sketch): `Context(path)`,
      `index_path(file, label=None)`, `index_root(root)`, `search(query, k=5) → [{path, score, snippet}]`.
      Files: `tina4_python/context/__init__.py` (Context), `tina4_python/context/chunker.py` (fold/terms/
      chunk_code/chunk_text). FTS5 schema `chunks(cid, path, raw UNINDEXED, body)`; `bm25()` ranking.
- [x] **Incremental reindex on file-change — WIRED to the dev WebSocket-reload trigger.** `POST
      /__dev/api/reload` (`dev_admin._api_reload`, the same handler that broadcasts the instant reload
      over the `/__dev_reload` WebSocket) now calls `Context.reindex_file(changed_file)` after
      `_auto_discover`, so a saved file is reindexed (UPSERT) and searchable immediately — no rebuild.
      `Context` + `code_search` share ONE process-wide index (`context.default_context` /
      `existing_context`) so the hook keeps the same index `code_search` reads. `reindex_file` resolves
      the project-root-relative path the trigger reports against the index root (may be `src/`),
      handles deletes (drop rows), and skips outside-root / skip-dir / ineligible files. Guarded so a
      context failure never breaks the reload. Real end-to-end test drives `_api_reload` → search.
- [x] **Dev-MCP `code_search` tool** — registered as a sibling of `api_search` in
      `tina4_python/mcp/tools.py` (handler + entry in the `tools` list). Docstring + list description
      state the split: `api_*` = exact structural lookup, `code_search` = fuzzy/semantic over source+docs.
- [ ] **Skills** — document `code_search` + fold it into the grounding ladder: rung 1 skill →
      rung 2 `api_*` (structural) / `code_search` (semantic, in-repo) → `tina4_context` (external corpus).
- [ ] **Optional dense rerank** — `TINA4_CONTEXT_RERANK=dense` + an embed endpoint for the accuracy
      uplift (router got ~82%→95% with it). Now **numpy-free** (stdlib `veclite` — dot/normalize/
      argsort in pure Python): it adds **no** language dependency, only needs an embed endpoint at
      runtime. OFF by default (opt-in) — but zero-dep holds even with it on.
- [ ] Port to PHP (PDO SQLite FTS5) / Ruby (sqlite3 FTS5) / Node (better-sqlite3 FTS5) — parity.

## Parity
| Item | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| `Context` core (stdlib FTS) | ✅ | ❌ | ❌ | ❌ |
| reindex-on-change (WS-reload trigger) | ✅ | ❌ | ❌ | ❌ |
| dev-MCP `code_search` | ✅ | ❌ | ❌ | ❌ |
| optional dense rerank | ❌ BUILD | ❌ | ❌ | ❌ |

## Design decisions / open questions (need the maintainer's call)
1. **The `1000` in the spike is suspiciously round** — likely a default chunk cap in the backend. Confirm; make configurable; must scale to a large repo.
   → RESOLVED for the native `Context`: there is **no** chunk cap; `index_root` indexes every eligible
   file. The spike's 1000 was a harness default, not a `Context` limit.
2. **Chunking** — reuse neemee's split (code by def/class boundary; docs by sentence — the fixed `_SENT` rule). Ship the fix, not the mangling.
   → DONE in `chunker.py`: `chunk_code` (def/class boundaries, `# file:` header for path-token search)
   + `chunk_text` (`_SENT` boundary, no bare-`.` shredding). Config/YAML/Dockerfiles go through the
   line-window code chunker (sentence chunking shreds them).
3. **Index location** — a SQLite file under `data/` (gitignored), rebuilt on boot, upserted on change. Or `:memory:` in dev for zero disk?
   → RESOLVED per the locked decision: on-disk portable index at `.tina4/context.db` (added `/.tina4/`
   to `.gitignore`); `Context(path)` takes any path, so `:memory:` remains available for tests/ephemeral.
4. **Zero-dep line** — FTS core ships stdlib on Python/PHP/Ruby; Node already carries `better-sqlite3` (its one accepted dep). Dense rerank is the only thing that adds a dep, and it's opt-in. Hold that line.
5. **Scope vs budget** — ~1000 LOC/lang against the ~5000 target. Does a code-context engine earn a 20% budget bump, or stay an optional module (not in the default dist)?
6. **Overlap with `api_*`** — keep them distinct (structural vs semantic), or unify behind one `search`?

## Tests (real, no mocks — positive + negative, per backend)
`tests/test_context.py` — 9 tests, REAL temp SQLite files + REAL temp source trees, no mocks.
Run: `.venv/bin/python -m pytest tests/test_context.py -v` → **9 passed**.
- [x] index a temp code tree → `search(q)` returns the defining source file ABOVE a test that merely
      mentions the symbol (source-over-tests + definition-first reorder over `bm25()`).
- [x] reindex-on-change: modify a file → new content retrievable AND old chunks for that file gone,
      with no row duplication (UPSERT = delete-by-path + insert). Plus: re-index unchanged file ≠ append.
- [x] FTS5 guard: real `Context.fts5_available()` is True here; a Context that finds FTS5 absent
      degrades to safe no-ops (index → 0, search → []) instead of crashing.
- [x] result shape `{path, score, snippet}` + score descending; docs indexed as prose; vendor/build
      dirs skipped; empty/stopword query → []. `code_search` MCP tool registered + finds a known symbol
      in a real temp project.
- [ ] parity output shape across PHP/Ruby/Node backends — deferred to the parity task.

## Bugs
- (none found in this MVP)

## Commits
- (pending — see git log for the `context: ...` commit on branch v3)
