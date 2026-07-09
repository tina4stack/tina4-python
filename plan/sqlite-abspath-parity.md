# Task: SQLite absolute-path footgun — cross-backend parity

## Goal
A naive `Database("sqlite:" + abs_path)` (one leading slash, e.g. `sqlite:/tmp/x.db`) must open the
**absolute** file, not a path relative to cwd. All four backends identical; documented
`sqlite:///relative` / `sqlite:////absolute` forms preserved.

## Grounding — CORRECTED premise (verified empirically 2026-07-09; the task's premise was wrong)
Root cause: python/php strip/collapse the one-slash form's leading `/` before the abs-check, so a
naive absolute path silently became cwd-relative. nodejs threw. Only ruby was right.

| Backend | `sqlite:/abs` before | Mechanism | Action |
|---------|----------------------|-----------|--------|
| python  | ❌ silently relative (`cwd/tmp/x.db`) | `urlparse` collapses `sqlite:/x`≡`sqlite:///x` | **FIXED** — raw-string strip |
| php     | ❌ silently relative (`getDsn=tmp/abs/x.db`) | `sqlite:///`-only branch → generic `parse_url` drops the slash | **FIXED** — raw-string strip in `DatabaseUrl` |
| nodejs  | ❌ throws "unsupported scheme" | `sqlite:/x` matched no branch → generic reject | **FIXED** — added `sqlite:` branch in `parseDatabaseUrl` |
| ruby    | ✅ absolute (`/tmp/x.db`) | sequential `sub(sqlite:///)`→`sub(sqlite://)`→`sub(sqlite:)` | no code change — regression test only |

Fix pattern (all): strip the scheme on the RAW url string in order `sqlite:///` → `sqlite://` →
`sqlite:`, then let the adapter's absolute-detection (`/…` or `C:/…`) decide — mirroring ruby.

## Scope
- [x] python `connection.py` `_connection_path()` — raw-string strip (fix the 1-slash footgun)
- [x] php `DatabaseUrl.php` — broaden `sqlite:///` branch to all `sqlite:` forms (raw-string strip)
- [x] nodejs `database.ts` `parseDatabaseUrl()` — add `sqlite:` branch (keep leading slash)
- [x] ruby — confirmed already correct (no code change)

## Parity dashboard (probe-verified; committed tests below)
| Case | python | php | ruby | nodejs |
|------|--------|-----|------|--------|
| `sqlite:/abs` → absolute file | ✅ (fixed) | ✅ (fixed) | ✅ | ✅ (fixed) |
| `sqlite:////abs` → absolute (documented) | ✅ | ✅ | ✅ | ✅ |
| `sqlite:///rel` → relative-to-cwd (documented) | ✅ | ✅ | ✅ | ✅ |

## Tests (written FIRST / real — no mocks; run against the actual driver)
- [x] python `tests/test_sqlite_abspath.py` — naive-abs opens abs file + documented forms; 4 pass; 626 DB/ORM/migration tests green (no regression)
- [ ] php — worker writing PHPUnit test + running db suite
- [ ] nodejs — worker writing tsx test + running orm suite
- [ ] ruby — worker writing regression spec + running sqlite specs

## Bugs
- [x] python probe/pre-fix run polluted the repo (`tmp/`, `x.db`, `data/x.db`); cleaned. Also
  accidentally `rm`'d two tracked `tmp/*.db` files — **restored** via `git restore` (kept the diff focused).

## Commits
- (python) pending — connection.py fix + test
- (php/nodejs/ruby) pending — worker tests + fixes

## Status: In Progress — python fixed+tested; php/nodejs fixed (probe-verified), tests in flight; ruby confirmed correct
