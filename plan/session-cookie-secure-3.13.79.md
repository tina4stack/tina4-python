# Task: 3.13.79 — session-cookie Secure parity + CI runner + migration fix

## Goal
Ship one cross-framework release that makes the session `Secure` flag correct and consistent
across all four frameworks, closes the CI gap that let the #174 security test go unrun, and
publishes the already-merged migration #176 fix.

## Context
justin-k-bruce filed a cluster on 2026-07-17 after 3.13.78:
- **python#95 / ruby#31**: `server.py` / `rack_app.rb` hand-roll the session Set-Cookie and
  NEVER call the cookie builder (`Session.cookie_header`), so `TINA4_SESSION_SECURE` is a
  silent no-op. Ruby also hardcodes `SameSite=Lax`, ignoring `TINA4_SESSION_SAMESITE`.
- **nodejs#34**: `buildSessionCookie()` sets Secure only from explicit `TINA4_SESSION_SECURE`;
  ignores `x-forwarded-proto`, so HTTPS-behind-a-proxy ships without Secure.
- **php#179**: parity umbrella. PHP already fixed in 3.13.78 (Request::isSecureScheme + both
  Router cookie sites) — it is the proven reference.
- **php#178**: `phpunit.xml` hand-lists test files; 89 of 186 classes never run in CI,
  including SessionCookieAttributesTest (the #174 regression). Same class of hole as the file
  I registered by hand in 3.13.78.

My 3.13.78 claim that Python/Ruby/Node were "never affected" was WRONG — I checked the cookie
builder method, not whether it is called on the emit path. Correction posted on php#179.
The 3.13.78 release notes for Python/Ruby/Node still carry the false "verified" claim and must
be corrected in this release.

## The unified contract (proven in tina4-php 3.13.78)
Session cookie `Secure` is set when ANY of:
1. `TINA4_SESSION_SECURE` truthy (true/1/yes/on), OR
2. SameSite is `None` (browsers reject None without Secure), OR
3. request scheme is https, detected PROXY-AWARE via `x-forwarded-proto` (first hop of a
   comma list is the client-facing one), else the native scheme.
Plus: the response emit path MUST route through the single cookie builder (fix the bypass),
and honour `TINA4_SESSION_SAMESITE` (default `Lax`). Plain HTTP with no proxy header and no
TLS => NOT Secure (a Secure cookie on plain http is undeliverable).

## Scope
- [ ] Python (MASTER): route emit through cookie builder + proxy-aware Secure (python#95)
- [ ] Ruby: same bypass + hardcoded-SameSite fix (ruby#31)
- [ ] Ruby: TINA4_SESSION_BACKEND wiring (backend selection was unreachable) — worker done, uncommitted
- [ ] Ruby: Redis/Mongo session handlers read env (were hardcoded localhost) — parity gap
- [ ] Ruby: background no-overlap spec (test parity; Python/Node/PHP have it) — worker done, uncommitted
- [ ] Node: proxy-aware Secure in buildSessionCookie (nodejs#34)
- [ ] PHP: switch phpunit.xml to directory discovery + guard test (php#178)
- [ ] PHP: confirm #179 PHP portion already complete from 3.13.78 (no code change expected)
- [ ] PHP: publish the already-merged migration #176 fix (on v3, 2 commits ahead of tag 3.13.78)
- [ ] Correct the 3.13.78 release notes for Python/Ruby/Node (false "verified" claim)
- [ ] Version bump all 4 to 3.13.79
- [ ] Release notes (4 docs + 4 book 36-releases.md), ASCII-only, zero em dashes
- [ ] docs:build GREEN before docs push
- [ ] INDEPENDENT re-verify each full suite at HEAD (never trust worker green)
- [ ] tag 3.13.79 all 4 → CI publishes; verify registries
- [ ] comment (not close) python#95, ruby#31, nodejs#34, php#178, php#179

## Parity
| Item | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| Session Secure proxy-aware + honours TINA4_SESSION_SECURE | building | ✅ 3.13.78 | building | building |
| Honours TINA4_SESSION_SAMESITE on session cookie | ✅ | ✅ | building (was hardcoded) | ✅ |
| TINA4_SESSION_BACKEND selects handler | ✅ | ✅ | building | ✅ |
| Redis/Mongo session handler reads env | ✅ | n/a | building | ✅ |
| background no-overlap spec | ✅ | ✅ 3.13.78 | building | ✅ |
| CI runs ALL test files (no hand-list) | ✅ discover | building (#178) | ✅ discover | ✅ discover |

## Tests (real, no mocks, positive + negative, must BITE against reverted code)
- [ ] Secure present with X-Forwarded-Proto: https (real served request, real Set-Cookie) — all 4
- [ ] Secure absent on plain http AND on X-Forwarded-Proto: http (guard over-reach) — all 4
- [ ] Secure present with TINA4_SESSION_SECURE=true — all 4
- [ ] Ruby: TINA4_SESSION_SAMESITE honoured (not hardcoded Lax)
- [ ] Ruby: TINA4_SESSION_BACKEND=redis selects RedisHandler; Redis/Mongo read env
- [ ] Ruby: background no-overlap (PEAK==1)
- [ ] PHP: guard test — every tests/*Test.php is collected by phpunit.xml

## Bugs
- [ ] python#95 — server.py bypasses cookie_header (Secure no-op)
- [ ] ruby#31 — rack_app.rb bypasses cookie_header (Secure no-op) + hardcoded SameSite
- [ ] nodejs#34 — buildSessionCookie ignores x-forwarded-proto
- [ ] php#178 — 89/186 test classes never run in CI
- [ ] php#179 — parity umbrella (PHP already done 3.13.78; other 3 land here)
- [ ] php#176 — already merged on v3, needs publishing (passed=0 pending fix)

## Discovered mid-batch — FIX IN THIS RELEASE (not out of scope, per Andre 2026-07-17)
- [ ] TINA4_SESSION_NAME read/write inconsistency, ALL 4: the cookie builder now
      honours TINA4_SESSION_NAME (write side) but the incoming-cookie READ still
      uses the hardcoded `tina4_session=` literal (Python `_init_session`
      server.py:1130; check PHP Router, Ruby rack_app/session, Node server). An
      operator who sets TINA4_SESSION_NAME writes a renamed cookie the framework
      then cannot read back. Surfaced by the Python worker. Fix + wire test all 4.
- [ ] PHP: 4 PHPUnit "risky" tests (DocsTest, FeedbackTest,
      McpDevToolsConformanceTest) — "removed error handlers other than its own".
      They pass (non-fatal) but are now collected by the #178 discovery fix. Clean
      up the global error-handler manipulation so they are not risky.

## Risks / Open questions
- Switching phpunit.xml to directory discovery runs ~89 previously-invisible files under
  CI's TINA4_REQUIRE_SERVICES=1; newly-collected service tests could fail. Verify each.
- Ruby Redis/Mongo live round-trips skip locally (no service); CI must confirm.

## Commits (landed on v3, each independently re-verified by main session)
- python  07e1980  #95 proxy-aware Secure + emit bypass (suite 3510/0)
- node    4ea69eb  #34 proxy-aware Secure (wire 10/10, build+typecheck green)
- php     f2b1e564 #178 phpunit directory discovery + guard; #179 verified done (config 3811/0)
- ruby    9448ac8  #31 cookie Secure/SameSite + backend wiring + Redis/Mongo env + overlap spec (rspec 3925/0)
- php     a74ae6bf #176 migration passed=0 pending (merged earlier, unreleased)

## Cross-framework Secure contract — VERIFIED IDENTICAL in source (all 4)
env TINA4_SESSION_SECURE OR SameSite==None OR proxy-aware https. Python
is_secure_scheme / PHP isSecureScheme / Ruby secure_scheme? / Node isSecureScheme.
(Ruby worker's "Python has 1 / PHP has 2" drift claim was a stale-tree misread.)

## STILL TO DO IN THIS BATCH (no worker collision now — all 4 done)
- [ ] TINA4_SESSION_NAME read/write parity, all 4 (discovered item above)
- [ ] PHP 4 risky tests cleanup (discovered item above)
- [ ] version bump all 4 -> 3.13.79 + release notes (4 docs + 4 book) + correct the
      false "verified" 3.13.78 notes for py/ruby/node
- [ ] docs:build green; final independent cross-framework gate; tag 3.13.79 (owner's call)
- [ ] comment (not close) python#95, ruby#31, nodejs#34, php#178, php#179

## Status: 3.13.79 SHIPPED (2026-07-19) - all 4 registries verified (PyPI/RubyGems/npm/Packagist).
## Session Secure + TINA4_SESSION_NAME + Ruby backend + PHP #178/risky/setAccessible + migration #176
## all landed, bumped, release-noted (docs+book, with the 3.13.78 false-claim correction), docs:build
## green, full suites re-verified at bumped HEAD, tagged bare 3.13.79, issue comments posted
## (python#95/ruby#31/nodejs#34/php#178/php#179, comment-not-close).
##
## DISCOVERED at final CI gate (fixed on PHP v3, NOT yet published): Tina4/Test.php (the \Tina4\Test
## xUnit base documented since 3.13.0) was never committed - .gitignore `test.php` matched it
## case-insensitively. #178 dir-discovery finally collected tests/ParityTestClassTest.php -> CI fatal
## "Class Tina4\Test not found". Fixed on v3 (12ad1f9b, `!Tina4/Test.php` + committed file); PHP CI
## now GREEN. Cross-checked PHP-only (Python/Ruby/Node test base classes are committed).
## OPEN OWNER DECISION: cut PHP 3.13.80 to publish Test.php (Packagist 3.13.79 lacks it), or ride the
## next release. Fix is safe on v3.
