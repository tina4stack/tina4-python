# Task: `doctor` / `setup` / `deploy` reachable from every framework CLI (delegation)

## Goal
`tina4python doctor`, `tina4php doctor`, `tina4ruby doctor`, `tina4nodejs doctor`
(and `setup`, `deploy`) must all work and behave identically, without cloning the
Rust client's implementation into four languages.

## Context — the gap
The docs list the CLI's commands as `serve / migrate / generate / test / doctor /
setup / deploy`, but `doctor`, `setup` and `deploy` are dispatched by NONE of the
four framework CLIs. They live only in the Rust client
(`tina4/src/{doctor,setup,deploy}.rs`). Measured before this change:

| CLI          | `doctor` dispatched | exit code | message                          |
|--------------|---------------------|-----------|----------------------------------|
| tina4python  | no                  | **0**     | "Unknown command: doctor" + help |
| tina4php     | no                  | **0**     | "Unknown command: doctor" + help |
| tina4ruby    | no                  | 1         | "Unknown command: doctor" + help |
| tina4nodejs  | no                  | 1         | "Unknown command: doctor" + help |

Two separate defects:
1. the three client-owned commands are unreachable from the framework CLIs;
2. Python (master) and PHP exit **0** on an unknown command, so `tina4 <typo>` in
   a Python or PHP project reports success. Ruby and Node were already correct.

## Design decision: allow-listed DELEGATION to the `tina4` client (not native ports)

Chosen: each framework CLI recognises a closed `DELEGATED` set — exactly
`doctor`, `setup`, `deploy` — resolves the `tina4` client on PATH, execs it with
the same argv, and propagates its exit code.

Why delegation and not four native implementations:
- `doctor` probes **all four** runtimes + package managers + ports + global
  AI-skills currency. A PHP copy that checks whether Ruby is installed is ~550
  lines of duplicated system probing per language for zero new capability.
- `setup` is a **bootstrap** command: it installs language runtimes via
  Chocolatey/Homebrew and needs UAC/Administrator elevation. If you can run
  `tina4php setup`, PHP and tina4-php are already installed — the command's
  purpose is gone. Cloning it would also replicate a privilege-elevation path
  into four more codebases.
- `deploy` writes static, language-aware boilerplate (Dockerfile, .dockerignore,
  systemd unit, nginx block, cPanel .htaccess) baked into the client binary. Four
  copies of the same templates is guaranteed drift.
- "Same across frameworks" is *stronger* under delegation: all four reach ONE
  implementation, so they cannot diverge. Four ports would.

Why **allow-listed** and not blind-forward-everything:
- The Rust client forwards ITS unknown commands to the framework CLI
  (`Commands::External`). If the framework forwarded its unknowns back, an
  unknown command would ping-pong between the two processes forever.
- Not hypothetical: `tina4-nodejs/packages/cli/package.json` declares a `"tina4"`
  bin alias pointing at the *Node* CLI. It is workspace-only (the PUBLISHED
  package is the root `tina4-nodejs`, whose only bin is `tina4nodejs`), but
  inside the monorepo `node_modules/.bin/tina4` really does shadow the Rust
  client — measured, see Findings.
- A closed allow-list of commands the client dispatches **natively** cannot loop
  by construction, and keeps "Unknown command" honest for real typos.

Belt-and-braces re-entry guard: the framework sets `TINA4_CLI_DELEGATED=<command>`
in the child environment. If a delegation request arrives with that variable
already naming the same command, the framework refuses to spawn and prints an
actionable error. Internal process marker only (same class as the client's
existing `TINA4_SETUP_ELEVATED`), not user configuration — deliberately NOT added
to the CLI's `known_vars()`.

## Contract (identical in all four)
| situation                                | behaviour                                                        | exit |
|------------------------------------------|------------------------------------------------------------------|------|
| delegated command, `tina4` on PATH       | exec `tina4 <cmd> <args...>`, stream its output                  | the client's exit code |
| delegated command, `tina4` NOT on PATH   | "`<cmd>` is provided by the tina4 client" + install one-liner    | 127  |
| delegated command, re-entry guard tripped| "refusing to delegate `<cmd>` again" + how to fix                | 127  |
| genuinely unknown command                | "Unknown command: `<cmd>`" + help                                | 1    |

`--help` gains a "Delegated to the tina4 client" section listing the three with
their client summaries. `commands --json` lists them too, each flagged
`"delegated": true`, so the manifest is a truthful description of the surface the
CLI accepts. The Rust client needs NO change: `print_help` already filters
manifest names that clash with its native subcommands, and serde ignores the extra
field.

## Scope
- [x] Python (master): `DELEGATED` registry, `_delegate_to_client`, dispatch,
      exit-1 on unknown, help section, manifest `delegated` flag
- [x] PHP mirror
- [x] Ruby mirror
- [x] Node mirror

## Tests (real — no mocks, real subprocesses)
Each framework, invoking its CLI as a real subprocess:
- [x] delegated command reaches the client: a REAL executable named `tina4`
      placed on a temp PATH is exec'd with the exact argv, and its exit code is
      propagated (positive)
- [x] `tina4` absent from PATH -> actionable message naming the command + the
      install line, exit 127 (negative)
- [x] genuinely unknown command -> "Unknown command" + exit 1 (negative)
- [x] re-entry guard: `TINA4_CLI_DELEGATED=doctor` in the env -> refuses, exit
      127, spawns nothing (negative)
- [x] manifest lock-ins updated: names == COMMANDS + DELEGATED, delegated
      entries flagged, native entries not

## Bugs found and fixed on the way
- [x] Python (master) exited **0** on an unknown command; PHP mirrored it. Both
      now exit 1. Ruby and Node were already correct — the master was wrong, so
      the master was fixed rather than the correct behaviour mirrored away.

## Findings surfaced, deliberately NOT fixed here (owner's call)
1. **Node workspace `tina4` bin alias shadows the client inside this monorepo.**
   `packages/cli/package.json` declares `"bin": {"tina4nodejs": ..., "tina4": ...}`,
   so `node_modules/.bin/tina4` points at the Node CLI's own `dist/bin.js`. Run
   from the monorepo, `tina4nodejs doctor` therefore resolves `tina4` to itself
   instead of the Rust client. Run from any other directory it resolves the real
   client and works (verified: `deploy bogus` -> exit 2 from the Rust client).
   Users are unaffected — the PUBLISHED package is the root `tina4-nodejs` and
   its only bin is `tina4nodejs`. Removing the workspace alias is a packaging
   change, so it is left for a direction call.
2. **`packages/cli/dist/bin.js` no-ops when invoked through a symlink.** Its
   entrypoint guard compares `import.meta.url` (realpath) with
   `pathToFileURL(process.argv[1])` (the symlink path); they never match through
   a symlink or a symlinked ancestor such as macOS `/tmp`, so `main()` never runs
   and it exits 0 silently. Pre-existing and NOT on the shipped path — the
   published binstub is the shell script `packages/cli/bin/tina4nodejs`, which
   resolves symlinks itself before exec'ing `npx tsx .../src/bin.ts`. Worth a
   separate one-line hardening (`realpathSync(process.argv[1])`).
3. **Stale local RubyGems binstub `tina4`** (from before commit `cb491a7`
   "Standardise CLI binary to tina4ruby"). The current gemspec declares only
   `tina4ruby`; the leftover binstub is a local-machine artifact.

## Status: DONE in all four — see each repo's commit.
