# SQLite URL — always relative to project root (cwd)

**Branch:** `v3` (staging). Target release: **3.11.12**.

## Goal

Make `sqlite:///path` resolve relative to the project root (cwd) on both
Unix and Windows, matching the documented behaviour. Absolute paths use
four slashes (`sqlite:////abs/path`) or Windows drive letters
(`sqlite:///C:/Users/app.db`). Never auto-create directories outside the
project root.

## Context

Reported by the master maintainer running `tina4 migrate` in `~/bruceproject`:

```
OSError: [Errno 30] Read-only file system: '/data'
  at connection.py:213 os.makedirs(directory, exist_ok=True)
```

The project's `.env` contains `DATABASE_URL=sqlite:///data/app.db`. The
current Python implementation treats `.path = "/data/app.db"` as the final
filesystem path and tries to `os.makedirs("/data")` — which fails on macOS
(root is read-only) and would fail on Windows (root of drive) and in most
containers.

The Python CLAUDE.md is explicit:
```
db = Database("sqlite:///app.db")                          # SQLite (relative path)
db = Database("sqlite:////absolute/path/app.db")           # SQLite (absolute path)
```

## Parity dashboard

| Framework    | `sqlite:///data/app.db` parses as  | Matches docs? | Fix needed |
|--------------|------------------------------------|---------------|------------|
| tina4-python | absolute `/data/app.db`            | ❌ NO          | ✅ YES     |
| tina4-php    | relative `data/app.db`             | ✅ YES         | ⚪ no (already right; regression test) |
| tina4-nodejs | absolute `/data/app.db`            | ❌ NO          | ✅ YES     |
| tina4-ruby   | (audit)                            | —             | audit     |

## Fix (Python)

In `tina4_python/database/connection.py :: _connection_path`:

1. Use `urlparse(url).path` to get the raw path.
2. Handle `:memory:` passthrough.
3. Strip **exactly one** leading `/` — the URL netloc/path delimiter.
4. Windows drive-letter detection: if the stripped path matches
   `^[A-Za-z]:[/\\]`, treat as absolute.
5. Unix absolute detection: if the stripped path still starts with `/`
   (i.e. four-slash URL form), treat as absolute.
6. Otherwise, treat as relative → resolve against `os.getcwd()`, and
   only auto-create directories that are descendants of cwd.

Never `os.makedirs` on a path outside cwd — that's how `/data` ends up
being created at root.

## Checklist

- [x] Plan doc (this file)
- [ ] Fix `_connection_path` in tina4-python
- [ ] Add 8 tests in `tests/test_database_connection.py`:
  - [ ] `sqlite:///app.db` → `{cwd}/app.db`
  - [ ] `sqlite:///data/app.db` → `{cwd}/data/app.db` (the Bruce case)
  - [ ] `sqlite:////abs/app.db` → `/abs/app.db`
  - [ ] `sqlite:///C:/Users/app.db` (Windows) → `C:/Users/app.db`
  - [ ] `sqlite::memory:` → `:memory:`
  - [ ] Subdirs auto-created when under cwd
  - [ ] Subdirs NOT auto-created when outside cwd
  - [ ] Leading `/./data/` resolves cleanly
- [ ] Verify Bruce's project: `cd ~/bruceproject && tina4 migrate` succeeds
- [ ] Fix `parseDatabaseUrl` in tina4-nodejs to match
- [ ] Add Node test + regression test
- [ ] Audit tina4-ruby, fix if necessary
- [ ] Add PHP + Ruby regression tests (parity contract)
- [ ] Bump all four frameworks to 3.11.12
- [ ] Tag + push + update book

## Risks / Open questions

- **Breaking change**: Any Python user who relied on the current absolute
  interpretation of `sqlite:///X` will need to switch to `sqlite:////X`.
  Given v3 is still on the staging branch (`feedback_breaking_changes.md`
  allows this), it's acceptable. Loud release note required.
- **Node breaking change**: Same story. Parity wins.
- **`:memory:` edge case**: Both `sqlite::memory:` and
  `sqlite:///:memory:` must continue to work.
