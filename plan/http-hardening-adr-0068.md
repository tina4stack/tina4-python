# Task: Built-in server body cap before read + response header CR/LF/NUL refusal (ADR-0068)

**Outcome:** the asyncio built-in server never buffers more than the upload cap and
answers malformed framing cleanly; response headers, redirects and cookies refuse
CR/LF/NUL at the call site; the socket writer refuses them again. Governed by
`tina4-documentation/plan/v3/decisions/ADR-0068.md`, gated by
`tina4-documentation/plan/v3/fixtures/http_hardening_contract.json`.

## Scope
- [x] Read PHP `Server::enforceRequestLimits` / `sendHttpError`, the ASGI cap path, Node's native `setHeader` wording
- [x] ADR-0068 + owed fixture pushed (`adr/0068-header-crlf-body-cap`)
- [ ] Regression suite `tests/test_http_hardening_contract.py`, red on current code
- [ ] Built-in server: bounded head read (431), framing validation (400), declared cap (413), chunked decode + running cap (413), idle timeout (408), clean close
- [ ] One transport-rejection shape shared by the built-in server and the ASGI 413
- [ ] Response: header / one-shot headers / redirect / content type / download name / cookie refuse at call site
- [ ] Built-in writer refuses an unsafe header (500)
- [ ] Mutation-prove every case
- [ ] Full suite local + lab, zero failed, zero skipped (TINA4_REQUIRE_SERVICES=1)
- [ ] RSS before / after measured
- [ ] Flip fixture invariants to proven, CONTRACT-MAP synced from the auditor

## Parity
| Part | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| call-site refusal | ❌ BUILD | ⚠️ in progress (fix/refuse-header-crlf) | ❌ owed | ⚠️ headers native, cookie owed |
| writer refusal | ❌ BUILD | ❌ owed | server-provided | native |
| limits before read | ❌ BUILD | ⚠️ partial | ❌ measure | ❌ measure |
| rejection shape | ❌ BUILD | ❌ owed | ❌ owed | ❌ owed |

## Tests (written first, real — no mocks, positive + negative)
- [ ] header/redirect/cookie refusal + normal values + multiple Set-Cookie (real Response, real server)
- [ ] writer refusal (real server)
- [ ] declared over cap -> 413 before read, RSS flat (real server, real socket, OS RSS)
- [ ] chunked over cap -> 413; chunked under cap decoded
- [ ] invalid CL / CL+TE / bare LF -> 400; oversized head -> 431; stalled -> 408; server keeps serving
- [ ] rejection shape: JSON body + security headers + Connection: close

## Bugs
- [ ] BODY-READ-BEFORE-CAP: `readexactly(content_length)` before the cap check
- [ ] CL-VALUEERROR: non-numeric Content-Length raises uncaught ValueError, socket leaks
- [ ] HEAD-LIMITOVERRUN: oversized head raises uncaught LimitOverrunError, socket leaks
- [ ] CHUNKED-DROPPED: Transfer-Encoding: chunked body silently read as empty
- [ ] BODY-TIMEOUT-UNCAUGHT: stalled body raises uncaught TimeoutError
- [ ] HDR-CRLF: header()/redirect()/cookie() accept CR/LF/NUL; writer writes raw
- [ ] COOKIE-UNVALIDATED: cookie name/value/attributes unvalidated (`;` adds attributes)

## Commits
- (pending)

## Status: In Progress
