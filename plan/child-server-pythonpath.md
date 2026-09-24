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
- [ ] conftest: pin `PYTHONPATH=<repo>:<guard>` in `os.environ` for every child
- [ ] conftest: pin the pytest process itself (console-script `pytest` run from a worktree)
- [ ] Guard: `tests/_child_guard/sitecustomize.py` aborts a child that imports tina4_python from outside the repo
- [ ] `test_response_binary_body.py` -> `boot_child_server`
- [ ] Call sites that REPLACE `PYTHONPATH` -> `child_pythonpath(...)` helper
- [ ] Red-to-green proof from a worktree whose venv points at a decoy checkout (lab)
- [ ] Mutation-prove the guard and the pin
- [ ] Full suite on the lab, 0 failed / 0 skipped under TINA4_REQUIRE_SERVICES=1
- [ ] Report PHP / Ruby / Node harness risk

## Parity (harness risk: "child loads a different checkout")
| Framework | Mechanism | Risk | Status |
|-----------|-----------|------|--------|
| Python | editable `.pth` | real, reproduced | fixing here |
| Ruby   | `-I`/`RUBYLIB`, `load_guard` | checked | see report |
| PHP    | composer autoload | checked | see report |
| Node   | relative imports / NODE_PATH | checked | see report |

## Tests (written first, real - no mocks, positive + negative)
- [ ] `test_child_import_guard.py`: a child spawned the normal way imports tina4_python from REPO_ROOT (positive)
- [ ] same file: a child whose path resolves tina4_python to a DECOY checkout is aborted by the guard with a clear message (negative)
- [ ] same file: the pytest process itself imported tina4_python from REPO_ROOT

## Bugs
- [ ] test_response_binary_body child imports the venv's checkout, not the one under test

## Commits
- (pending)

## Status: In Progress
