# Task: Child Python processes must import the checkout under test

**Outcome:** every Python child a test spawns (server, CLI, `-c` probe, nested
pytest) imports `tina4_python` from the repository the test lives in, and aborts
loudly if it ever loads another checkout. No production code changes.

## Bug (ghost-test class)

`tests/test_response_binary_body.py` spawned its server with
`env={**os.environ, ...}` and `cwd=tmp_path`, and never set `PYTHONPATH`. The
venv's editable install is a `.pth` line pointing at ONE checkout. When pytest
runs from a git worktree (or any other checkout), the child's `sys.path` has the
script's directory first and then the `.pth` entry, so it imports the OTHER
checkout. The test then passes or fails on code that is not under test.
Observed 2026-09-24 on macOS: `/bin/send: content type 'text/html; charset=utf-8'`
from the worktree, while the worktree's own code was correct.

The same hole exists wherever a child starts with a working directory that is
not the repo root (a script's own directory, or `-c` / `-m` with `cwd=tmp`), or
where a test overrides `PYTHONPATH` with a generated project path only.

## Scope
- [x] Survey every child-process spawn in `tests/` (44 files)
- [x] conftest: pin `PYTHONPATH=<repo>:<guard>` in `os.environ` for every child
- [x] conftest: pin the pytest process itself (console-script `pytest` run from a worktree)
- [x] Guard: `tests/_child_guard/sitecustomize.py` aborts a child that imports tina4_python from outside the repo
- [x] `test_response_binary_body.py` -> `boot_child_server`
- [x] Call sites that REPLACE `PYTHONPATH` -> `child_pythonpath(...)` helper
- [x] Red-to-green proof from a worktree whose venv points at a decoy checkout (lab)
- [x] Mutation-prove the guard and the pin
- [x] Full suite on the lab, 0 failed / 0 skipped under TINA4_REQUIRE_SERVICES=1
- [x] Report PHP / Ruby / Node harness risk

## Parity (harness risk: "child loads a different checkout")
| Framework | Mechanism | Risk | Status |
|-----------|-----------|------|--------|
| Python | editable `.pth` | real, reproduced | fixing here |
| Ruby   | `-I lib` / `$LOAD_PATH.unshift(lib)`, CLI uses `require_relative`, Gemfile `path:` | low: every child pins lib by absolute path; only one spec verifies it (`load_guard`) | report only |
| PHP    | `__DIR__`-relative `vendor/autoload.php`, relative composer baseDir | low: pinned per checkout; `bin/tina4php` prefers `$cwd/vendor/autoload.php`, and a symlinked `vendor/` would redirect | report only |
| Node   | `@tina4/core` via `<repo>/node_modules` workspace symlinks | medium: a worktree nested in another checkout with no own `node_modules` resolves the OUTER checkout (proved with a toy tree) | report only |

## Tests (written first, real - no mocks, positive + negative)
- [x] `test_child_import_guard.py`: a child spawned the normal way imports tina4_python from REPO_ROOT (positive)
- [x] same file: a child whose path resolves tina4_python to a DECOY checkout is aborted by the guard with a clear message (negative)
- [x] same file: the pytest process itself imported tina4_python from REPO_ROOT

## Bugs
- [x] test_response_binary_body child imports the venv's checkout, not the one under test

- [x] the `pytest` console script (not `python -m pytest`) imported the other checkout IN-PROCESS from a worktree

## Mutation proof (macOS, Python 3.13, test_child_import_guard.py)
| Mutant | Killed by |
|--------|-----------|
| M1 drop the os.environ PYTHONPATH pin | both pin cases red |
| M2 guard finder not installed | guard case red |
| M3 guard accepts any origin | guard case red |
| M4 guard returns the wrong spec instead of aborting | guard case red |
| M5 no sys.path pin for the pytest process (console script) | parent case red |

## Lab evidence (Linux, Python 3.13.13, TINA4_REQUIRE_SERVICES=1, /home/andre/py-childpath)
Venv editable target = a decoy checkout; suite run from a DIFFERENT checkout.
| Run | Result |
|-----|--------|
| binary-body test, v3 base, decoy drops bytes in send() | FAIL `/bin/send: content type 'text/html; charset=utf-8'` |
| binary-body test, this branch | pass |
| full suite, v3 base, canary target exits 97 on import | 41 failed, 12 errors, 6041 passed; 92 canary hits, 16 files |
| full suite, this branch, same canary venv | 6098 passed, 0 failed, 0 skipped, 0 canary hits |
| full suite, this branch, own venv (private MySQL/MSSQL db) | 6098 passed, 0 failed, 0 skipped |

A first own-venv run had 8 mysql/mssql provider-contract failures ("table doesn't exist"):
two other agents' full suites were dropping the same fixed-name tables in `tina4_test`
at the same time. Isolated re-runs passed; the re-run on private databases was green.

Ghost files found by the canary at base (children imported the venv target):
autocrud_contract, background_contract, cli_commands_manifest, cli_generate(_coemits),
cli_test_exit_code, compression_etag_contract, generate_envelope_v1_1, generate_resolution,
inline_testing_contract, mcp_migration_create_envelope, migrate_create_envelope_parity,
migration_contract, response_binary_body, testing (plus 2 unrelated: firebird deadlock
from a concurrent suite, logger fork warning).

## Commits
- 96bdf32  test: pin every child process to the checkout under test, and guard it

## Status: Complete (PR #153, not merged)
