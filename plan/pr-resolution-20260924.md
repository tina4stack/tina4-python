# Python pull request resolution — 2026-09-24

## Scope
- [x] Integrate every current open PR head through merge commits, preserving ancestry.
- [x] Resolve HTTP hardening, common bootstrap, runtime settings, child import guard, and MySQL readback conflicts.
- [x] Preserve already merged Frond escaping and measured skill timing changes.
- [ ] Merge combined PR #157 after required CI passes.
- [ ] Delete merged remote and local branches while preserving worktree files.

## Parity
Shared contracts preserved: ADR-0068 body/header limits, ADR-0070 browser gate, ADR-0072 runtime environment settings, statement semantics, security defaults, and ORM field-column mapping.

## Tests
- [x] Combined source tree: 119 real socket/bootstrap/settings/child-guard/binary-body tests passed (14.56s), local integration dc4ec29; same tree as 045cbd6.
- [x] HTTP hardening/browser/binary tests: 148 passed.
- [x] ORM column readback SQLite: 19 passed; other engines await CI/lab with drivers.
- [ ] Full required real-service CI suite on final combined PR head.
- [ ] Combined multi-framework lab run after all repositories merge.

## Bugs
- [x] Resolve overlapping bootstrap/settings changes while retaining complete startup and dynamic settings.
- [x] Retain buffered MySQL fetch_one with parameter-aware SQL translation.
- [x] Retain both browser suppression and child checkout pinning in conftest.
- [x] Integrate current canonical CI database URLs and service-skip tags.

## Commits
- 60b0563 — merged #155 Frond escaping.
- f967530 — merged #156 measured skill estimates.
- 09c429b — #150 HTTP hardening resolution and own-author signoff.
- e4756a7 — #151 statement semantics and common bootstrap integrated with #150.
- 6979566 — #152 runtime settings integrated with #151.
- df87c9f — #153 child import guard integrated with #152.
- 20797cb — #157 ORM mapping and buffered MySQL readback integrated with #153.
- 2c6dbea — #154 transport follow-ups integrated into final #157.
- 045cbd6 — #147 Mongo replica-set fixes integrated into final #157.

## Status: In progress
