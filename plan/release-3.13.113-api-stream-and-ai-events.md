# Release 3.13.113 — Api.stream primitives + Ai typed events + multimodal (ADR-0060)

**Outcome:** Ship Api.stream_bytes/stream_lines/stream_sse in Python; rewrite
Ai.chat streaming to yield typed AiEvent records; accept multimodal content
parts (text + image data:/https:); pass CONTRACT-MAP for feature 140 in
Python. All four backends will follow (Python is master).

## Scope
- [x] Read ADR-0060 + api_stream_contract.json + ai_client_contract.json
- [x] Read existing tina4_python/api/__init__.py and ai/client.py
- [x] Add SseEvent + ApiTimeoutError + stream_bytes/stream_lines/stream_sse to Api
- [x] Add AiEvent dataclass; export from tina4_python.ai
- [x] Rewrite Ai._stream / _stream_delta / _stream_data on top of Api.stream_sse
- [x] Update Ai._validate_messages to accept list-of-parts content
- [x] Update Ai._chat_body to translate multimodal parts per provider
- [x] Extend tests/test_ai_client_contract.py with the new cases
- [x] Add tests/test_api_stream_contract.py with the api_stream cases
- [x] Bump version to 3.13.113 (pyproject + __init__ literal + CLAUDE.md)
- [x] Prepend CHANGELOG.md entry for 3.13.113 citing ADR-0060
- [x] Full pytest suite green at HEAD; commit + push v3

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| Api.stream_bytes/lines/sse | ✅ | ❌ | ❌ | ❌ |
| Ai.chat typed events       | ✅ | ❌ | ❌ | ❌ |
| Ai multimodal content parts| ✅ | ❌ | ❌ | ❌ |

Ports run in parallel workers off this Python shape.

## Tests (real fixture server, no mocks; positive + negative)
### api_stream_contract (new file)
- [x] stream-bytes-yields-chunks-in-order (real chunked HTTP body)
- [x] stream-bytes-ends-on-eof
- [x] stream-bytes-raises-on-transport-drop (server closes mid-stream)
- [x] stream-lines-splits-on-lf
- [x] stream-lines-splits-on-crlf
- [x] stream-lines-yields-trailing-line-without-newline
- [x] stream-lines-multibyte-across-chunk-boundary
- [x] stream-sse-single-event
- [x] stream-sse-multi-line-data-concatenated
- [x] stream-sse-named-event (event: field)
- [x] stream-sse-comment-ignored (:hb line)
- [x] stream-sse-blank-line-boundary
- [x] stream-sse-done-sentinel-delivered
- [x] stream-sse-retry-field-captured
- [x] stream-connect-timeout-honoured
- [x] stream-total-timeout-honoured
- [x] stream-early-close-releases-socket
- [x] ai-chat-uses-api-stream-sse-under-the-hood

### ai_client_contract (extended)
- [x] ai-stream-text-deltas-order
- [x] ai-stream-tool-call-aggregated-openai
- [x] ai-stream-tool-call-aggregated-anthropic
- [x] ai-stream-done-fires-once
- [x] ai-stream-error-instead-of-done-on-midstream-failure
- [x] ai-stream-no-retry-after-first-event
- [x] ai-multimodal-text-part
- [x] ai-multimodal-image-data-uri
- [x] ai-multimodal-image-url
- [x] ai-multimodal-malformed-part-fails-config
- [x] ai-multimodal-openai-body-shape
- [x] ai-multimodal-anthropic-body-shape

## Bugs
- (log here as [ ], tick with commit hash when a real test proves them fixed)

## Commits
- (hash — description)

## Status: Complete (Python master, ports pending)

Verified on macOS Python 3.13.5: `.venv/bin/python -m pytest tests/`
→ `5138 passed, 644 skipped, 3 warnings in 383.73s`. Skips are the
usual local-services set (Firebird, MongoDB, RabbitMQ, Kafka, MSSQL,
MinIO); zero failures. Every new test in
`tests/test_api_stream_contract.py` (18) and every new/updated test
in `tests/test_ai_client_contract.py` (22 total, 12 new) is green.
