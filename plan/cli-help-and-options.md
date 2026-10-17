# Task: CLI `--help` and option checking, all four frameworks

## Outcome
`--help` / `-h` on any framework CLI command prints that command's usage and
writes nothing. Unknown options are refused with a did-you-mean, value options
need a value, and `ai --all` works. Same behaviour and same wording in Python,
PHP, Ruby and Node, each with equivalent no-mock tests.

## Context
Found through `tina4 generate model --help`, which created a model called
`--help` (four files). The Rust `tina4` client forwards these commands verbatim,
so the fix belongs in the framework CLIs. A sweep in a scaffolded project
(Termux, tina4python 3.13.151) showed every one of the 31 forwarded commands
ignored `--help`. Several wrote files or changed the project:

| Command with `--help` | What it did |
|---|---|
| `generate model/route/page/crud/migration/...` | files named `--help` / `-h` |
| `generate base`, `generate auth` | ran fully |
| `migrate`, `migrate:rollback`, `migrate:status`, `seed`, `console` | created `app.db` |
| `lint` | installed ruff, rewrote `pyproject.toml` and `uv.lock` |
| `start`, `test`, `queue` | exit 1, no help |

Other broken switches found by the same audit:
- Misspelled or short options (`--feilds`, `--publc`, `-f`) were silently
  dropped: the model came out without its fields, exit 0.
- `--fields` with no value crashed with a traceback; `--every` with no value
  was ignored.
- `ai --all` was documented but the code checked for the bare word `all`.

## Design (Python is the reference)
- Each registry entry declares `flags`: `{name: takes_value}`. `test` is
  `None` (its arguments belong to pytest). Queue subcommands and the
  resolution-aware generators (`--json`, `--dry-run`) have their own maps.
- `main()`, before any handler runs:
  1. `--help` / `-h` anywhere after a command → that command's usage, exit 0.
  2. Unknown option → `Unknown option --feilds for "generate model". Did you mean --fields?`
     then `Run "tina4python generate model --help" for its options.`, exit 1.
  3. Value option with no value → `Option --fields for "generate model" needs a value: --fields <value>`, exit 1.
- `--name=value` is accepted as well as `--name value`.
- `generate` refuses a name starting with `-`.
- Delegated commands (`doctor`, `setup`, `deploy`) are untouched: the `tina4`
  client answers them.
- **Ruby exception:** `serve -h` already means `--host` there. `--help` is help
  everywhere; `-h` keeps meaning host for Ruby `serve` so scripts don't break.

## Parity
| Surface | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| `--help` / `-h` per command, no side effects | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| unknown option refused + did-you-mean | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| value option needs a value | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| `--name=value` | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| `ai --all` | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| generate name can't start with `-` | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| `generate crud --skip-model` (the `generate model` hint) | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |
| `help --help` prints the reference | ✅ | ❌ BUILD | ❌ BUILD | ❌ BUILD |

PHP, Ruby and Node track their own columns in their repos' copy of this plan.

## Tests (real, no mocks, positive + negative)
- [x] every command and generator, `--help` and `-h`: exit 0, usage printed,
      project tree hashed before/after and unchanged (70 cases)
- [x] `--help` after the name and options still wins
- [x] top-level `--help` / `-h`; `generate --help` lists every generator
- [x] misspelled options refused with the right suggestion, nothing written
- [x] short and foreign options refused
- [x] value option without a value refused, no traceback
- [x] `--fields price:float` and `--fields=price:float` both reach the model
- [x] `test -q -k one` still runs pytest
- [x] `ai --all` writes CLAUDE.md without the menu
- [x] every option in a usage string is an accepted option (drift guard)
- [x] `help`, `help --help`, `help -h` print the reference (Node's port found
      `help --help` said "Unknown option")
- [x] `generate crud Product --skip-model` after `generate model` keeps the
      model byte-identical (PHP's port found the hint pointed at a missing option)
- [x] all 78 original help cases fail on unfixed v3
- [x] tests/test_cli*.py: 250 passed, 1 skipped. One flaky failure in
      `test_cli_serve_debug_env.py` (1 in 7 runs, real server boot); 5/5 on v3
      and 6/7 with the fix
- [x] full suite (macOS, CPython 3.14, no service containers):
      branch 6184 passed / 2 failed / 938 skipped; unfixed v3 6091 / 3 / 938.
      No failure is new: Firebird connect-timeout and server libcrypto fail on
      both, and v3's third is the flaky serve-debug boot test.

## Commits
- fix(cli): --help prints usage; unknown options are refused (one commit on
  fix/cli-help-flags; see `git log`)

## Status: Python ready for PR vs v3; PHP, Ruby, Node PRs open alongside
