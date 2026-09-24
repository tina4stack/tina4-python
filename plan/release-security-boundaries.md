# Release security boundaries

## Scope
- [x] Prevent initial off-origin credential forwarding across API paths.
- [x] Trust forwarded host/proto only from a declared raw-peer proxy.
- [x] Guard dev-admin access and resolved filesystem/identifier boundaries.
- [x] Preserve current health version and existing credential-file hardening.
- [x] Ruby-only narrow URL log redaction.

## Tests
- [x] Real HTTP/filesystem regressions red before fixes, green after.
- [ ] Coordinated full CI/lab before merge.

## Parity
Python/Ruby owned here; PHP/Node coordinated by sibling worker. ADR0082 records the approved clarification. Preserve accepted MCP transport API_KEY fallback; general dev endpoints require dedicated MCP token for remote access. Token cannot bypass Host or Origin. Health version unchanged.

## Bugs
Source confirmed missing initial-target guards, forwarded-host trust and dev-admin read/path gaps. No feature expansion.

## Commits
Signed release security commit follows.

## Focused evidence
38 focused security tests and 205 adjacent tests pass. Initial imported regressions failed against original source. Real local HTTP listeners, ASGI dispatch and filesystem witnesses; no mocks.

## Descriptor-bound development reads
Text/raw endpoints now validate regular-file type and read through the same descriptor, using available NOFOLLOW/NONBLOCK flags. Existing per-language size behavior is preserved. Final-component replacement by a symlink cannot make the read follow that link; FIFOs are refused without blocking. Previously resolved public symlinks within the project remain supported. Hostile concurrent ancestor-directory renames are not claimed atomic; the local project tree remains trusted. Python retains its existing 2 MiB text and 10 MiB raw limits; Ruby retains its existing uncapped read behavior.
