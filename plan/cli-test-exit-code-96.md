# Task: `tina4 test` must propagate the test runner's exit code (python#96) - all 4 CLIs

## Goal
`tina4 test` (and the PHP/Ruby/Node equivalents) must exit NON-ZERO when any test fails,
so `tina4 test || exit 1` CI gates actually catch a red suite. Reported: python#96.

## Contract (identical observable behavior, all 4)
- Tests fail (any failure/error) -> the command exits with a NON-ZERO code.
- Tests pass -> exit 0.
- Propagate the underlying runner's real exit code where practical.

## Findings (verified in source 2026-07-21)
- Python: `_test` (cli/__init__.py:766) does `subprocess.run([...pytest...])` and DISCARDS
  returncode; main() never sys.exit()s for it. BROKEN. Fix: capture + `sys.exit(result.returncode)`.
- PHP: `case 'test'` (bin/tina4php:1123) does `passthru(...)` without the &$result_code arg and
  just `break`s. BROKEN. Fix: `passthru($cmd, $code); ... exit($code);`.
- Ruby: `cmd_test` (lib/tina4/cli.rb:565) runs `Tina4::Testing.run_all` then
  `exit(1) if results[:failed] > 0 || results[:errors] > 0`. OK already - needs a lock-in test.
- Node: `runTests` (packages/cli/src/commands/test.ts) uses `execSync(..., stdio:inherit)` in
  try/catch -> `process.exit(1)`. OK for the specific-file branch; CONFIRM the auto-discover
  branch propagates too. Needs a lock-in test (fix only if the discover branch swallows it).

## Scope
- [ ] Python (master): fix `_test` to exit with pytest's return code + real lock-in test
- [ ] PHP: capture passthru result code + exit($code) + real lock-in test
- [ ] Ruby: confirm exit-on-failure + add real lock-in test (parity)
- [ ] Node: confirm both branches propagate; fix discover branch if needed + real lock-in test

## Tests (REAL, no mocks, positive + negative, must BITE)
Each framework: a test that SPAWNS the real `tina4 test` (or the command entry) in a temp
project containing (a) one deliberately-FAILING test -> assert the child exit code != 0, and
(b) one PASSING test -> assert exit code == 0. No doubles - a real child process, real runner.
The negative case must fail against the un-fixed command (returns 0 on failure today).

## Bugs
- [ ] python#96 - `tina4 test` exits 0 on failing pytest (+ PHP parity)

## Commits
- (log per framework)

## Commits (all on v3, pushed, CI validating)
- python  82b8cd26  _test -> sys.exit(returncode) + real spawn test (suite 3514/0)
- php     9f3af673  passthru captures $testExit + exit($testExit) + smoke-branch test
- php     003c91e7  drop PHPUnit-removed --verbose (--colors=always) + phpunit-branch test (suite 3819/0/0)
- php     a5e6014e  docs: CLAUDE.md test command --colors=always (docs match code)
- ruby    540cfc7a  lock-in spec only (code already exit(1)s on failure; suite 3933/0)
- node    0f3401b   lock-in test only (code already propagates both branches; 5412 pass / 18 Docker-down baseline)

## Cross-framework result: code bug was Python + PHP ONLY. Ruby + Node already correct (verified + locked).
## Each fix's negative test proven to BITE against pre-fix code. All 4 re-verified by main session (diff + own run).

## Status: SHIPPED in 3.13.81 (2026-07-21) all 4 registries verified. Owner chose option (B) re-align
## all at 3.13.81. Bumps py 8b9b0fd / php 5dd9ed18 / ruby 0c9fec2 / node 37b777f; tags 3.13.81 bare;
## docs 53e5b0c + book 970da3c; commented (not closed) python#96. All fixes real-test-pinned + re-verified.
