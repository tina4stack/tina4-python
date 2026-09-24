# Task: A binary body with an explicit content type is sent as bytes (all four)

**Outcome:** `response(bytes, status, contentType)` and `send(bytes, status, contentType)` deliver the
exact bytes in every framework. Found 2026-09-24 in tina4-simple-agent: Node wrote `String(buffer)`,
so a PNG served with `image/png` arrived as 512 bytes of UTF-8 text and did not decode.

## Scope
- [x] Node: explicit-content-type branch writes a Buffer as bytes; any Uint8Array is a binary body
- [x] Python: `send(bytes, ...)` no longer drops the body; `bytearray` / `memoryview` are bytes, not `str()`
- [x] PHP: checked - strings are bytes, no bug; lock-in test added
- [x] Ruby: checked - binary bodies are fine (also a UTF-8-tagged binary string); lock-in spec added
- [x] Ruby: `call(hash, status, content_type)` sent `Hash#inspect`, not JSON - fixed (found by the new spec)

## Parity
| Case (explicit content type)        | Python | PHP | Ruby | Node |
|-------------------------------------|--------|-----|------|------|
| `response(bytes)` arrives identical | ✅     | ✅  | ✅   | ✅ fixed |
| `send(bytes)` arrives identical     | ✅ fixed | ✅ | ✅  | ✅ fixed |
| other byte types (Uint8Array / bytearray / memoryview) | ✅ fixed | n/a | n/a | ✅ fixed |
| dict / array with a type is JSON    | ✅     | ✅  | ✅ fixed | ✅ |

## Tests (written first, real server, no mocks, positive + negative)
- [x] Node `test/responseBinaryBody.test.ts` - real `startServer()`, route files on disk
- [x] Python `tests/test_response_binary_body.py` - real `run()` in a child process
- [x] PHP `tests/ResponseBinaryBodyTest.php` + `tests/fixtures/response_binary_body_server.php` - real `App::run()`
- [x] Ruby `spec/response_binary_body_spec.rb` - real `Tina4::WebServer`
- Each sends all 256 byte values 0x00-0xFF and compares the raw bytes received. Controls: text with a
  type stays UTF-8 text, an object with a type stays JSON, a byte body with no type is octet-stream.
- Mutation proof (each test seen red, then green):
  - Node: red before the fix (512 bytes, and 2341 bytes for Uint8Array); red again with only the Uint8Array part removed.
  - Python: red before the fix (`send` returned the default HTML); red with only the bytearray part removed (749 bytes of `bytearray(b'...')`).
  - PHP: red with the body re-encoded ISO-8859-1 -> UTF-8.
  - Ruby: red (3 examples) with the body re-encoded ISO-8859-1 -> UTF-8; the JSON example was red before its fix.

## Bugs
- [x] Node: `response(buffer, status, type)` corrupts binary (String(buffer))
- [x] Node: `response(uint8array, ...)` sent JSON of the indices
- [x] Python: `send(bytes, status, type)` silently dropped the body
- [x] Python: `bytearray` / `memoryview` sent as `str()` text
- [x] Ruby: `call(hash, status, type)` sent `Hash#inspect`, not JSON

## Commits
- (filled in when landed)

## Status: In Progress
