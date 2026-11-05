# Task: Feature 142 — Raw TCP service (Python reference)

Outcome: a user-facing raw TCP *service* primitive — a Tina4 app exposes a
non-HTTP, long-lived binary TCP service (driving consumer: GPS/GPRS car-tracker
gateways, GT06/TK103/Concox/Teltonika) **in-process**, folded into the running
asyncio accept loop, at the contract pinned by ADR-0102 and
`tina4-documentation/plan/v3/fixtures/raw_tcp_service_contract.json`. Python is
the reference (ADR-0004); PHP/Ruby/Node follow in later PRs.

Branch: `feature/142-raw-tcp-service` off `origin/v3`. PR-only.

## Scope
- [ ] Read ADR-0102 + fixture + feature packet + server/websocket prior art  (done)
- [ ] `tina4_python/tcp/` module: `tcp_service()`, `tcp(name)`, `TcpService`, `TcpConnection`
- [ ] Fold the listener into `_serve()` (in-process) + production ASGI lifespan, drain on shutdown
- [ ] Real no-mock socket tests for all 10 invariants / 19 cases, each mutation-proved
- [ ] Full suite green at HEAD, 0 failed / 0 skipped
- [ ] Flip fixture invariants owed -> proven (python suite block) in a tina4-documentation PR

## Parity
| Invariant | Python | PHP | Ruby | Node |
|-----------|--------|-----|------|------|
| tcp-listen-accept-in-process | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-callbacks-raw-and-line | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-binary-roundtrip-ack | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-identify-registry-push | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-connection-object | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-max-connections-refusal | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-idle-reaper-default-off | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-graceful-shutdown-drain | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-backpressure | ❌ BUILD | ❌ | ❌ | ❌ |
| tcp-single-owner-bind | ❌ BUILD | ❌ | ❌ | ❌ |

## Tests (written first, real — no mocks, positive + negative; each mutation-proved)
Harness: `conftest.free_port` + `asyncio.start_server`/`open_connection` for the
pure cases; `conftest.boot_child_server(new_session=True)` for the two that need a
live HTTP server on the same process (in-process + SIGTERM drain).
- [ ] listen+accept in-process; on_connect fires while HTTP still serves  (child server)
- [ ] on_data raw (not newline-split); on_line splits; on_close once
- [ ] binary frame round-trips, ACK via conn.send
- [ ] identify + send_to reaches that socket; isolation; unknown-id no-op; broadcast; re-identify supersedes
- [ ] connection object: remote_addr raw peer; context persists per-conn; close() fires on_close + deregisters
- [ ] max_connections: (N+1)th refused, existing unaffected
- [ ] idle_timeout=0 keeps silent conn open; >0 reaps it; active conn not reaped
- [ ] graceful shutdown: SIGTERM drains live TCP conn, HTTP serves to deadline, exit 0  (child server)
- [ ] backpressure: stalled reader stays bounded, gets dropped, others keep serving
- [ ] single-owner bind: one owner binds under N workers; others do not bind, no error

## Bugs
- (none yet)

## Commits
- (hash  description — one line per landed change)

## Status: In Progress
