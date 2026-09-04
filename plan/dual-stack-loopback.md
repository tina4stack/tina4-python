# Task: Port tina4-php PR #206 dual-stack loopback to Python

Outcome: the built-in asyncio dev server ALSO listens on the sibling loopback
family (best-effort), so `localhost` reaches it on Windows (where `localhost`
resolves to ::1 first). Matches PHP `Server::loopbackBindHosts`. Branch:
`feature/release3.13.132`. Uvicorn/production path untouched.

## Scope
- [x] Read PHP PR #206 reference (Server.php + ServerDualStackLoopbackTest.php)
- [x] Find Python built-in bind path (asyncio.start_server, server.py:4012)
- [x] Add `loopback_bind_hosts(host)` mapping (Python: "::1" WITHOUT brackets)
- [x] Add `_bind_loopback_siblings(handler, host, port)` best-effort helper
- [x] Wire siblings after the UNCHANGED primary bind in `_serve()`
- [x] Close siblings alongside primary in the shutdown path
- [x] Tests: mapping unit (5 cases) + real dual-stack socket test (skip if no ::1)

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| dual-stack loopback | this task | PR #206 (open) | owed | owed |

## Tests (real sockets, no mocks, positive + negative)
- [x] loopback_bind_hosts: localhost/127.0.0.1/0.0.0.0/::1/:: + LAN negative
- [x] real: bind 127.0.0.1 primary + siblings -> client connects on 127.0.0.1 AND ::1

## Bugs
- (none)

## Verify (macOS Darwin 25.6, Python 3.13, ::1 available)
- new file: 5 passed
- mutation proof: disabling siblings turned the real dual-stack test RED (`assert []`)
- `-k "server or loopback or dual or bind or asgi"`: 121 passed, 22 skipped
  (all 22 skips pre-existing live-service gates: PostGIS/redis/valkey/memcached/
  MongoDB/PostgreSQL not on this Mac — none mine, none feature-related)
- server lifecycle (asgi/bind/dual_port/child_boot/graceful_shutdown): 42 passed
  — real server boots exercise the shutdown path that now closes siblings

## Commits
- (this commit) feat(server): dual-stack loopback siblings on the built-in dev server

## Status: Complete

