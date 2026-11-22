# Task: Make the Python suite pass on Windows

Outcome: `uv run python -m pytest tests/ -q -p no:cacheprovider` on Windows 11
fails only where this box runs no service, never because a test assumed POSIX.
Framework bugs the run exposes are FIXED here, with real regression tests, and
at parity in PHP, Ruby and Node where they share the bug. Branch
`fix/windows-test-portability`. Same class of work as tina4-nodejs#210.

Measured on Windows 11 Enterprise 10.0.26300, CPython 3.13.10, `uv sync --extra
test` (as CI), no local services. Baseline: pristine `origin/v3` @ bf16cdc4 in a
separate worktree, same venv recipe, same command:
**138 failed, 84 errors, 6242 passed, 974 skipped** (31 min).

## Scope
- [x] Baseline full run on pristine origin/v3
- [x] Replace the one `preexec_fn` spawn (tests/conftest.py) with a portable equivalent
- [x] Port every test that signals or kills a child to portable helpers
- [x] Classify every remaining failure: harness / framework / service missing
- [x] Fix framework bugs, each with a regression test proven red by mutation
- [x] Parity: check each framework bug in PHP, Ruby and Node (measured, not read)
- [x] Full Windows run; compare with the baseline per test (JUnit XML)
- [x] PR against v3 (DCO sign-off): tina4stack/tina4-python#332
- [ ] Linux CI green on the PR HEAD

## Parity
| # | Framework bug (Windows) | Python | PHP | Ruby | Node |
|---|---|---|---|---|---|
| 1 | Built-in server armed NO shutdown handler (`add_signal_handler` raises NotImplementedError, swallowed): Ctrl+C / Ctrl+Break / service stop killed it mid-request | fixed: SIGINT, SIGBREAK, SIGTERM via `signal.signal` | gap: pcntl only, nothing armed. PR in progress (`sapi_windows_set_ctrl_handler`, measured working on 8.4.8) | Ctrl+C trapped; Ctrl+Break cannot be trapped by Ruby 3.3 at all (measured: killed 0xC000013A even with `trap("INT")`). Runtime limit, no fix | gap: no SIGBREAK listener (measured: killed). PR in progress |
| 1b | `stop()` did `os.kill(own_pid, SIGTERM)` = TerminateProcess (exit 15, no drain) | fixed: `signal.raise_signal` on Windows | n/a (no self-signal) | n/a | n/a |
| 2 | Output encoded with the locale codepage (cp1252) on a pipe: every CLI status mark (U+2713) and any non-cp1252 Log line raised UnicodeEncodeError | fixed: `ensure_utf8_stdio()` | n/a: writes bytes | n/a: writes bytes | n/a: writes UTF-8 |
| 3 | A `tina4.cmd` client: cmd.exe re-parses the line, so `%PATH%` expanded, `^` dropped, `x\|y` ran `y` | fixed: `core/batch_spawn.py` (the #211 algorithm) | ok: all ten hostile args verbatim (PHP 8.4 `proc_open` escapes batch files) | same bug, measured. PR in progress | fixed in tina4-nodejs#211 |
| 4 | Dev-admin install spawned bare `npm`/`composer`/`bundle`/`gem`: never found on Windows (batch files) | fixed: PATHEXT lookup + escaped spawn | ok: `composer` via shell, name regex-validated | `command -v bundle` always fails under cmd.exe, falls back to Gemfile append (reported) | fixed in tina4-nodejs#211 |
| 5 | #277 migration file lock imported `fcntl`, so Windows ran UNLOCKED (7 of 8 workers applied the same data migration) | fixed: `msvcrt.locking` | ok: `flock` excludes across processes (measured) | ok: `File#flock` excludes across processes (measured) | ok (tina4-nodejs#210 run) |
| 6 | 31 JSON/text file sites used the locale codepage: `write_claude_config()` crashed on, or rewrote as mojibake, a non-ASCII value in the developer's `.claude/settings.json` | fixed: `encoding="utf-8"` everywhere (RFC 8259) | n/a: bytes | n/a: UTF-8 default external encoding | n/a: `utf8` reads |
| 7 | MCP `migration_create` envelope listed `existing` paths with `\` | fixed: `/` on every OS | - | - | - |

## Harness causes fixed (test side)
| Cause | Fix | Files |
|---|---|---|
| `preexec_fn` / `start_new_session` / `os.killpg` are POSIX-only | `spawn_kwargs()` (new process group on Windows), `send_graceful_shutdown()` (CTRL_BREAK_EVENT on Windows), `kill_process_tree()` (`taskkill /T`) in conftest | conftest, graceful_shutdown, raw_tcp_service_contract, cli_serve_debug_env, db_concurrency, serve_free_port_takeover_notice |
| A child's stdout on an undrained PIPE: Windows' default pipe holds ~4KB, so a module-scoped server wedged after ~15 requests of access log | `boot_child_server` always logs to a file | conftest (session_anonymous_request) |
| Nested pytest in a tmp project adopted a config file above %TEMP% (this box has a stray `%TEMP%\pyproject.toml`) and scanned %TEMP% while other processes churned it | `anchor_pytest_project()` gives each throwaway project its own `pytest.ini` | cli_generate, cli_generate_coemits, cli_help_flags, require_services_gate |
| Fake `tina4` client / `npm` were `#!/bin/sh` scripts | real `tina4.cmd` / `npm.cmd` programs on Windows | cli_delegated_commands, dev_admin_deps_install_spawn |
| RSS read with `ps` | `process_rss_mb()`: ps on POSIX, `K32GetProcessMemoryInfo` working set on Windows | request_body_cap, http_hardening_contract |
| Symlink creation needs Developer Mode/admin (WinError 1314) | probed once; `needs_symlinks` skips with `[needs:symlink-privilege]` only where the host cannot | dev_file_descriptor, dev_surface_contract, file_upload_contract, frond_tags, static |
| POSIX-only semantics with no Windows equivalent | tagged skip `[needs:os=posix]`: SIGINT to one child, SIGHUP, deleting a file a child holds open, `pty` | graceful_shutdown, logger_fixture_contract |
| uvicorn re-raises the captured signal: SIGBREAK's default action is exit(3) on Windows, -15 on POSIX | expected code per platform | graceful_shutdown |
| Windows refuses a connect to a closed loopback port only after ~2 s | longer drain / connect timeout / refusal bound | graceful_shutdown, database_connect_timeout |
| `write_text` writes CRLF; `NamedTemporaryFile` is held open exclusively; a clean env without SYSTEMROOT cannot start Winsock; OSError reprs a path (doubled backslashes); a 200KB param id exceeds the 32767-char env limit (PYTEST_CURRENT_TEST); 256MB thread stack is over CPython's Windows bound; `tmp/abs.lstrip("/")` is not a relative path on Windows; Windows dirs report mode 0o777 | byte writes, tmp_path, pass SYSTEMROOT, compare both forms, short ids, 64MB stack, `relative_to(anchor)`, POSIX-only mode check | response_file_traversal, database_result_subscript, docstore_substitutability, session_backend_failure, http_hardening_contract, overlay_contract, sqlite_abspath, sqlite_path_contract |
| Windows 11 ships `System32\libcrypto.dll`, which passes the push backend's known-answer test: "Windows never has libcrypto" is stale | absent: BackendUnavailable; present: same path as a server | push_backends |

## Tests (no mocks; each proven red by mutation)
| Test | Mutation that turns it red |
|---|---|
| graceful_shutdown (11 built-in-server cases) + raw_tcp drain | remove the Windows handlers: 10 red |
| `test_stop_runs_the_same_graceful_shutdown` (new) | old `os.kill` stop(): red (empty response) |
| `test_utf8_stdio.py` (new, red on Linux too via PYTHONIOENCODING=cp1252) | `ensure_utf8_stdio` a no-op: 2/2 red |
| `test_hostile_arguments_reach_the_client_verbatim_and_run_nothing` (new) | plain `subprocess.run`: red; PATHEXT lookup without escaping: red |
| `test_dev_admin_deps_install_spawn.py` (new) | plain `subprocess.run`: 2/2 red (not found); lookup without escaping: red (argv cut at `&`) |
| migration_concurrency_277 | no Windows lock: 5/5 runs red; with the lock 3/3 green |
| `test_mcp_claude_config_utf8.py` (new) | locale read: UnicodeDecodeError (0x9d) |
| `test_batch_spawn.py` (new, pure; runs on Linux) | expected strings are tina4-nodejs `escapeBatchArgument()` output for the same nine inputs, compared by running it |

## Verification (Windows 11, CPython 3.13.10, no local services)
| Run | Result |
|---|---|
| origin/v3 @ bf16cdc4 (pristine worktree) | 138 failed, 84 errors, 6242 passed, 974 skipped |
| branch @ 10f31ab7 | 7 failed, 0 errors, 6450 passed, 985 skipped |
| branch @ ac4a3864 | **0 failed, 0 errors, 6459 passed, 985 skipped** |

Per-test comparison, baseline vs ac4a3864 (JUnit XML): 0 pass→fail, 0 pass→skip, 0 pass→missing; 207 fail→pass; 12 fail→skip, every one a tagged Windows impossibility that still runs on Linux (7 `[needs:symlink-privilege]`, SIGINT x2, SIGHUP, pty); 2 renamed (short param ids) and 8 new tests, all passing.

Every remaining skip is a service this box does not run (PostgreSQL/PostGIS, MySQL, MSSQL, Firebird, ODBC, MongoDB, Redis, Valkey, Memcached, RabbitMQ, Kafka, MQTT, GreenMail SMTP/IMAP, MinIO, Neo4j, Memgraph, ArangoDB, Ultipa, OIDC) or a tagged platform exclusion (`[needs:os=posix]`, POSIX permission bits, port takeover's lsof path, `[needs:symlink-privilege]`).

## Bugs
- [x] (1) built-in server had no graceful shutdown on Windows
- [x] (1b) `stop()` killed the process on Windows
- [x] (2) cp1252 output crash in CLI and Log
- [x] (3) batch-file client argument injection (Python); Ruby PR pending
- [x] (4) dev-admin package managers not found on Windows
- [x] (5) migration lock absent on Windows
- [x] (6) locale-codepage JSON/text I/O
- [x] (7) `\` in the migration envelope
- [ ] PHP (1): tina4stack/tina4-php#374 (open)
- [ ] Node (1): tina4stack/tina4-nodejs#213 (open, CI green)
- [ ] Ruby (3): tina4stack/tina4-ruby#187 (open)
- Found by the Node work, not fixed here: tina4-nodejs binds `::1` before arming SIGTERM/SIGINT (a SIGTERM in that gap kills without a drain).
- Not fixed here (out of scope, recorded): a stray `%TEMP%\pyproject.toml` on this box (a copy of tina4-python 3.13.163's) that any tmp-dir pytest climbs to; `tests/test_static.py` imports `unittest.mock.patch` (unused, pre-existing); Ruby dev-admin `command -v` / `2>/dev/null` under cmd.exe.

## Commits
- b9fbd01c  test: portable child-server spawn and signalling on Windows; built-in server drains on Windows
- 10f31ab7  fix: Windows framework bugs found by the Windows test run; portable test harness
- ac4a3864  fix: UTF-8 for every JSON/text file the framework reads or writes; "/" paths in the migration envelope
- (next)    refactor batch_spawn under the metrics gate; pure escaping tests; this plan

## Status: In Progress
