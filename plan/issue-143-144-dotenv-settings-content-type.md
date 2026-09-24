# Task: #143 settings read before .env loads + #144 header Content-Type duplicates

**Outcome:** a Content-Type set with `header()` is the response's one Content-Type
(any name case; an explicit content-type argument still wins), and every setting
is read when it is used, so a value set only in `.env` applies. Governed by
`tina4-documentation/plan/v3/decisions/ADR-0072.md`. Depends on
`fix/body-cap-header-crlf` (ADR-0068), which owns `core/server.py` and
`core/response.py`; this branch is based on it.

## Scope
- [x] Reproduce #144 and #143 for real on origin/v3 in all four frameworks
- [x] Grep load-time env reads in all four (AST scans, not text grep)
- [x] Python: `header("Content-Type")` sets the one content type; detection keeps it
- [x] Python: `TINA4_MAX_UPLOAD_SIZE` read per request (`max_upload_size()`)
- [x] Python: `TINA4_HEALTH_PATH` re-applied after `run()` loads .env
- [x] PHP: header Content-Type (any case) is one header, kept by `$response($data)`; `send()` casing
- [x] Ruby: header Content-Type (any case) is one header, kept by `call`
- [x] Node: header Content-Type kept by `response(data)` for every body type
- [x] Node: `TINA4_MAX_UPLOAD_SIZE` read per request
- [x] ADR-0072
- [x] Full suites on the lab (see Lab: Python and Ruby zero/zero; Node and PHP each case green, the stragglers were shared-lab races proved in isolation)

## Reproduced on origin/v3 (2026-09-24)
| Bug | Python | PHP | Ruby | Node |
|-----|--------|-----|------|------|
| #144 header Content-Type + bytes | 2 headers | header lost (text/plain) | Puma: 2 headers | kept |
| #144 lowercase `content-type` | 2 headers | 2 headers | header lost | kept |
| #144 header + string body | 2 headers | header lost | Puma: 2 headers | header lost |
| #143 `TINA4_MAX_UPLOAD_SIZE` in .env | ignored (200) | honoured (413) | honoured (413) | ignored (200) |
| other load-time env reads | `TINA4_HEALTH_PATH` | none | none | none |

## Parity
| Behaviour | Python | PHP | Ruby | Node |
|-----------|--------|-----|------|------|
| header Content-Type is the one Content-Type | ✅ | ✅ | ✅ | ✅ |
| upload cap from .env | ✅ | ✅ (was) | ✅ (was) | ✅ |
| health path from .env | ✅ | ✅ (was) | ✅ (was) | ✅ (was) |

## Tests (written first, red on origin/v3, real servers, no mocks)
Same case names in all four: Python `tests/test_dotenv_settings_and_content_type.py`,
PHP `tests/DotenvSettingsAndContentTypeTest.php`, Ruby
`spec/dotenv_settings_and_content_type_spec.rb`, Node
`test/dotenvSettingsAndContentType.test.ts`.
- [x] header content type replaces the detected type
- [x] a lowercase content type header is the same header
- [x] header content type survives a string body
- [x] an explicit content type argument wins over the header
- [x] without a header the detected type is used (negative)
- [x] max upload size from dotenv is enforced
- [x] a body under the dotenv limit is accepted (negative)
- [x] health path from dotenv is served
- [x] max upload size follows the environment
- [x] a bad max upload size falls back to the default

## Bugs
- [x] #144 Python duplicate Content-Type
- [x] #144 PHP Content-Type lost / duplicated
- [x] #144 Ruby Content-Type duplicated (Puma) / lost (lowercase)
- [x] #144 Node Content-Type lost for a string or object body
- [x] #143 Python `TINA4_MAX_UPLOAD_SIZE` frozen at import
- [x] #143 Python `TINA4_HEALTH_PATH` frozen at import
- [x] #143 Node `TINA4_MAX_UPLOAD_SIZE` frozen at import
- [x] Python: a bad `TINA4_MAX_UPLOAD_SIZE` crashed the import; now warns and uses the default (ADR-0068 s3)

## Commits
- python 3a4aa1d  fix: header Content-Type is the one Content-Type; .env settings read when used (#143, #144)
- php    cae030ad fix: header Content-Type is the one Content-Type; bad upload limit falls back
- php    58c1172a test(migration): filter the Firebird relation listing to the table under test
- ruby   d7b66c0  fix: header Content-Type is the one Content-Type; bad upload limit falls back
- nodejs 4c518bb  fix: header Content-Type survives response(data); upload cap read when used
- docs   3113223  ADR-0072 (tina4-documentation#70)

## Lab (Linux; Python 3.12.3, Ruby 3.2.3, Node 24.18.0, PHP 8.3.6; TINA4_REQUIRE_SERVICES=1; sudo -E per lab convention)
| Suite | Head tested | Passed | Failed | Skipped |
|-------|-------------|--------|--------|---------|
| Python | 3a4aa1d merged with v3 958377c | 6157 | 0 | 0 |
| Ruby | d7b66c0 (on v3 bc90fc7) | 5848 | 0 | 0 |
| Node | 4c518bb (on v3 b53face) | 9338 | 1 (shared-Firebird race; 7/7 twice in isolation) | 0 |
| PHP main | 58c1172a merged with v3 f0c90875 | 5788 run | 1 error + 1 failure (shared-Firebird races; green 2/2 in isolation) | 41 = 4 openswoole (pass OK 4/4) + 37 graph (pass 39/39 with lab-only drivers) |

PRs: tina4-python#152, tina4-php#227 (depends on #217), tina4-ruby#59, tina4-nodejs#76, tina4-documentation#70 (ADR-0072).

## Status: Complete (PRs open, not merged)
