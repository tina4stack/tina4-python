# Task: Self-describing CLI — `commands` subcommand (Phase 1, Python master)

## Goal
Give the Tina4 Python CLI a `commands` subcommand that emits its own command
surface — human-readable (`tina4python commands`) and machine-readable
(`tina4python commands --json`) — so the Rust `tina4` client can DISCOVER what
this framework supports instead of hardcoding it.

## Context
Today three copies of the same knowledge live in `tina4_python/cli/__init__.py`
and drift independently:
1. the `commands = {name: handler}` dispatch dict inside `main()` (~L202)
2. the hand-written help block in `_help()` (~L276)
3. the `generators = {name: fn}` dict inside `_generate()` (~L817)

The epic's whole point is: ONE registry, no drift.

## Scope
- [x] Ground with `tina4_context("cli internals", "python")` + read live source
- [x] Lift the generator dispatch dict to a module-level `GENERATORS` registry
      (name -> {handler, usage, summary}); `_generate` dispatches from it
- [x] Add a module-level `COMMANDS` registry (name -> {handler, summary, usage?,
      args?, subcommands?}) as the single source of truth
- [x] `main()` dispatches from `COMMANDS`
- [x] `_help()` is generated from `COMMANDS` + `GENERATORS` (no hand-written list)
- [x] `_commands_manifest()` builds the JSON manifest from `COMMANDS`
- [x] `_commands()` handler: prints human list, or `--json` manifest. CHEAP +
      side-effect-free (no bootstrap / DB / migrations / app imports)
- [x] Real test `tests/test_cli_commands_manifest.py` (no mocks): in-process
      content assertions + real subprocess `commands --json` in a temp dir with
      NO `TINA4_DATABASE_URL` and no `migrations/` (app/DB-free proof)

## Manifest shape (exact keys)
```
{ "framework": "python", "version": "<tina4_python.__version__>",
  "commands": [ {"name","summary", "args"?, "subcommands"?}, ... ] }
```
Truthful to the real command set: init, serve, start, migrate, migrate:create,
migrate:rollback, migrate:status, env-migrate, seed, routes, test, build, ai,
generate, console, metrics, help, commands. `generate.subcommands` derived from
`GENERATORS`. No invented commands (no top-level `queue` yet).

## Tests (real — no mocks)
- [x] in-process: framework=="python", version non-empty, commands non-empty,
      every entry has name+summary, generate has subcommands incl model+crud,
      known commands all present
- [x] subprocess `commands --json` exits 0 with valid JSON in a clean temp dir
      with no DB url and no migrations/ (proves no bootstrap); creates no *.db

## Decision: FULL single-registry refactor (not the minimal fallback)
Dispatch, help, and the manifest all read from `COMMANDS` (+ `GENERATORS` for
the generate subcommands). No residual fourth list.

## Status: DONE (Python master) — verified green: new test 11/11, full suite
3365 passed / 125 skipped / 0 failed on macOS, Python 3.13 (SQLite). Parity
mirror to PHP/Ruby/Node is a later phase of the epic.
