# Task: Harden uploaded-file permissions (CodeQL py/overly-permissive-file) + CI workflow hardening

Outcome: `save_upload` creates files owner-only (0o600) in all four frameworks, with a
mutation-proof regression test each; tina4-python CI workflows carry least-privilege
`permissions:` blocks and SHA-pinned actions (ADR-0073). Branch: `skills/codeql-precheck`.

## Scope
- [x] Python: request.py save_upload 0o666 -> 0o600 (:864, :868) + test — mutation-proven
- [x] PHP: Request.php saveUpload chmod 0600 on create + test — mutation-proven
- [x] Ruby: request.rb save_upload 0o666 -> 0o600 (:227, :231) + test — mutation-proven
- [x] Node: request.ts saveUpload 0o666 -> 0o600 (:422, :428) + test — mutation-proven
- [x] CI hardening: add permissions: blocks + SHA-pin actions (tina4-python workflows)

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| upload mode 0o600 on create | ✅ | ✅ | ✅ | ✅ |
| regression test (mode & 0o077 == 0) | ✅ | ✅ | ✅ | ✅ |

## Tests (real, mutation-proof)
- [ ] write upload to temp dir -> stat mode & 0o077 == 0 (owner-only); revert to 0o666 -> FAILS
- [ ] existing plain file rewritten in place KEEPS its mode (mode only set on create)

## Bugs
- [ ] CodeQL #48/#49 py/overly-permissive-file — tina4_python/core/request.py:864,868

## Commits
- (pending commit) tina4-python  tina4_python/core/request.py 0o666->0o600 + test_file_upload_contract.py owner-only test
- (pending commit) tina4-php     Tina4/Request.php chmod 0600 on create + FileUploadContractTest.php owner-only test
- (pending commit) tina4-ruby    lib/tina4/request.rb 0o666->0o600 + file_upload_contract_spec.rb owner-only test
- (pending commit) tina4-nodejs  packages/core/src/request.ts 0o666->0o600 + fileUploadContract.test.ts owner-only test
- (pending commit) tina4-python  .github/workflows/{ci,test,docker-image}.yml permissions: contents:read; {ci,doc-drift}.yml setup-uv SHA-pinned v3.2.4

## Verification (this HEAD, macOS, umask 022)
- Python: 14/14 test_file_upload_contract.py green; mutation 0o600->0o666 turns owner-only RED
- Ruby:   14/14 file_upload_contract_spec.rb green; mutation RED
- Node:   owner-only + keeps-mode green; mutation RED (group/other bits=44)
- PHP:    13/13 FileUploadContractTest.php green; mutation (drop chmod) RED
- Workflows: all 4 parse, permissions=contents:read; test.yml top-level covers the firebird job (#38)
- Session tests (batch -k errors) proven environmental: test_session_anonymous_request.py 19/19 green in isolation

## Status: Code complete — not committed (awaiting go-ahead; workflow push needs the tina4stack full token)
```
Mode-on-create semantics: O_CREAT mode arg (Py/Ruby/Node) applies only when the file is
created; an existing plain file keeps its mode — matches the in-code comment. PHP fopen
has no mode arg, so chmod 0600 is applied only when the dest did not pre-exist.
umask note: 0o600 & ~umask = 0o600 (umask removes bits, never adds), so the test is
deterministic; 0o666 -> 0o644 under umask 022, leaving group/other read -> test catches it.
```
