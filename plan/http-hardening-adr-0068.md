# Task: Built-in server body cap before read + response header CR/LF/NUL refusal (ADR-0068)

**Outcome:** the asyncio built-in server never buffers more than the upload cap and
answers malformed framing cleanly; response headers, redirects and cookies refuse
CR/LF/NUL at the call site; the socket writer and the ASGI path refuse them again.
Governed by `tina4-documentation/plan/v3/decisions/ADR-0068.md`, gated by
`tina4-documentation/plan/v3/fixtures/http_hardening_contract.json`.

## Scope
- [x] Read PHP `Server::enforceRequestLimits` / `sendHttpError`, the ASGI cap path, Node's native `setHeader` wording
- [x] ADR-0068 + fixture pushed (`adr/0068-header-crlf-body-cap`)
- [x] Regression suite `tests/test_http_hardening_contract.py`, red on the previous code (45 of 47 at first commit)
- [x] Built-in server: bounded head read (431), framing validation (400), declared cap (413), chunked decode + running cap (413), idle timeout (408), clean close
- [x] One transport-rejection shape shared by the built-in server and the ASGI 413
- [x] Response: header / one-shot headers / redirect / content type / download name / cookie refuse at call site
- [x] Built-in writer refuses an unsafe header (500); ASGI path does too (uvicorn used to drop the connection)
- [x] HTTP/1.1 keep-alive + HEAD Content-Length (found by the Ruby worker's wire probe)
- [x] Browser-open gate (ADR-0070), separate commits, runner for `browser_open_contract.json`
- [x] Mutation-prove every case
- [x] Full suite on the lab, zero failed, zero skipped (TINA4_REQUIRE_SERVICES=1)
- [x] RSS before / after measured
- [x] Fixture invariants flipped to proven, CONTRACT-MAP synced from the auditor

## Parity
| Part | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| call-site refusal | ✅ | ✅ tina4-php#217 | ✅ tina4-ruby#50 | ✅ tina4-nodejs#69 |
| writer refusal | ✅ | ✅ #217 | ✅ #50 | ✅ #69 (native + fixture body) |
| limits before read | ✅ | ✅ #217 | ✅ #50 | ⚠️ in progress |
| rejection shape | ✅ | ✅ #217 | ✅ #50 | ⚠️ in progress |

## Tests (written first, real — no mocks, positive + negative)
- [x] header/redirect/cookie refusal + normal values + multiple Set-Cookie (real Response, real server)
- [x] writer refusal (real built-in server) and ASGI refusal (real uvicorn)
- [x] declared over cap -> 413 before read, RSS flat (real server, real socket, OS RSS)
- [x] chunked over cap -> 413; chunked under cap decoded
- [x] invalid CL / CL+TE / bare LF -> 400; oversized head -> 431; stalled -> 408; server keeps serving
- [x] rejection shape: JSON body + security headers + Connection: close (built-in only)
- [x] keep-alive (sequential + pipelined), Connection: close / HTTP/1.0, HEAD length (built-in + uvicorn)
- [x] browser gate: booted server with a real BROWSER script; 85-row fixture runner

## Bugs
- [x] BODY-READ-BEFORE-CAP: `readexactly(content_length)` before the cap check — 916131d
- [x] CL-VALUEERROR: non-numeric Content-Length raised uncaught ValueError, socket leaked — 916131d
- [x] HEAD-LIMITOVERRUN: oversized head raised uncaught LimitOverrunError, socket leaked — 916131d
- [x] CHUNKED-DROPPED: chunked body silently read as empty — 916131d
- [x] BODY-TIMEOUT-UNCAUGHT: stalled body raised uncaught TimeoutError — 916131d
- [x] HDR-CRLF: header()/redirect()/cookie() accepted CR/LF/NUL; writer wrote raw — 916131d
- [x] COOKIE-UNVALIDATED: cookie name/value/attributes unvalidated — 916131d
- [x] ASGI-413-CONNECTION-CLOSE: shared shape sent Connection: close through uvicorn, client lost the 413 — 5ab2a23
- [x] BROWSER-OPENS-IN-TESTS: browser opened with debug off, under CI, ignored "on" — c815f09, 68c7f51, d11270c
- [x] SHUTDOWN-PROBE-RACE: graceful-shutdown test treated a kernel handshake reset as a failure (base v3 too) — 61efd0e
- [x] NO-KEEPALIVE / HEAD-LENGTH-ZERO — fbcc85b
- [x] DUPLICATE-CL-ACCEPTED: an agreeing second Content-Length was accepted (maintainer ruling: refuse) — 38673da
- [x] ASGI-UNSAFE-HEADER-DROPS: uvicorn dropped the connection on an unsafe header — 6f8293b

## Commits
- 916131d  Enforce the upload cap before reading the body; refuse CR/LF/NUL in response headers (ADR-0068)
- 5ab2a23  Leave the connection to uvicorn on the ASGI 413
- c815f09  Open a browser only in debug, and never under CI or TINA4_NO_BROWSER=on
- 61efd0e  Graceful-shutdown probe: a handshake reset by the closing listener is not a failure
- fbcc85b  Built-in server: keep HTTP/1.1 connections open and answer HEAD with the GET length (also carries the CI-list code described in 68c7f51)
- 68c7f51  Browser gate: ADR-0070's eight CI variables, and a runner for its fixture
- 6f8293b  ASGI path: answer an unsafe response header with the ADR-0068 500, not a dropped connection
- d11270c  Browser gate: ADR-0070 final CI rule - blank, false, 0, no and off mean not CI
- 38673da  Built-in server: refuse a second Content-Length even when it agrees (ADR-0068)

Lab (Linux, Python 3.13.13, TINA4_REQUIRE_SERVICES=1, OIDC required, graph engines on, own Firebird db) at 38673da: 6240 passed, 0 failed, 0 skipped.

## Status: Complete (PR open, not merged)
