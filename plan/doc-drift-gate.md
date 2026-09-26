# Task: Fix doc/skill drift + add a doc-drift CI gate

Outcome: the packaged CLAUDE.md and the authoritative skills stop documenting APIs that
do not exist, and a real CI gate (per framework repo for CLAUDE.md, in the skills upstream
for skill references) turns RED on any such drift. Follow-up doc/skill fixes only — the
3.13.139 release is published; touch no versions or tags. Target branch: v3 (via PR).

## Scope
- [ ] #1 CLAUDE.md `CRUD.to_crud(...)` -> `AutoCrud` / `auto_crud = True` (tina4-python)
- [ ] #1 parity: php/ruby/nodejs packaged CLAUDE.md — checked, none carry the wrong API (note)
- [ ] #2 skill data-and-orm.md: `where()` "plain list" -> `ModelCollection` + `.to_paginate()`
- [ ] #3 skill auth-and-services.md: websocket `chat(connection)` -> `chat(connection, event, data)`
- [ ] #4 skill auth-and-services.md: login `@post` above `@noauth()` -> `@noauth()` above `@post`
- [ ] #5 skill rtc.md: `import { mount } from 'tina4js'` -> real export (`html` fragment + `${()=>}`)
- [ ] Sync .claude -> .cursor/.agents skill mirror copies
- [ ] Python doc-drift gate (CLAUDE.md + skills references), wired into CI
- [ ] Port gate to php/ruby/nodejs packaged CLAUDE.md (framework test conventions)

## Verified evidence (against real code at origin/v3)
- CRUD: `tina4_python/crud/__init__.py:83` class AutoCrud (register/discover); `tina4_python/orm/model.py:206,231` auto_crud; no `class CRUD`, no `to_crud`.
- where(): `tina4_python/orm/model.py:1055-1056` returns `ModelCollection`; `orm/collection.py:34` `class ModelCollection(list)`, `:59` `to_paginate()`, `get_total_records()`. No `to_dict`/`to_array` on it.
- websocket: `core/router.py:221` and `:836` `async def handler(connection, event, data)`, event in {open,message,close}.
- decorator order: `core/router.py:862` docstring — documented order is `@noauth()` ABOVE `@get/@post`.
- tina4-js exports: `tina4-js/src/index.ts` — no `mount`; `html` returns DocumentFragment (`src/core/html.ts:60`), reactive `${()=>expr}` holes (`:148`, docs line 16).

## Parity
| Item | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| CLAUDE.md wrong CRUD API | ❌ FIX | ✅ n/a (AutoCrud) | ✅ n/a (none) | ✅ n/a (autoCrud.ts) |
| skill fixes #2-#5 | ❌ FIX | — | — | — |
| doc-drift gate | ❌ BUILD | ❌ BUILD | ❌ BUILD | ❌ BUILD |

## Tests (real, RED before / GREEN after)
- [ ] gate flags `CRUD.to_crud` unresolved in CLAUDE.md; green once fixed
- [ ] gate flags `mount` not a tina4js export in rtc.md; green once fixed
- [ ] gate asserts `where()` return annotation == ModelCollection (doc must not say plain list)
- [ ] gate asserts websocket handler signature (connection, event, data)
- [ ] gate flags meta-decorator (@noauth/@secured) below @get/@post in a fence

## Bugs
- (log here)

## Commits
- (hash  description)

## Status: In Progress
