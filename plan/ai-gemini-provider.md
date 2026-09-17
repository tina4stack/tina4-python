# Task: Add a `gemini` provider to the Ai client (all 4 frameworks)

Gemini exposes an OpenAI-compatible API, so a `gemini` provider is a thin alias over the
existing OpenAI wire family: same body builder, response normaliser, tool translation and
streaming parser. Only the base URL, the endpoint-suffix append, the Bearer key and the
provider allow-list differ. No new dependency.

## Reference (Python master - DONE, 44/44 green on macOS)
tina4-python `tina4_python/ai/client.py` + `tests/test_ai_client_contract.py`. The six edits:
1. provider allow-list gains `gemini`.
2. `gemini` requires an API key (like openai/anthropic).
3. defaults: base `https://generativelanguage.googleapis.com/v1beta/openai`, model `gemini-2.5-flash`.
4. endpoint resolver appends `/chat/completions` (chat) or `/embeddings` (embed) onto the
   `/v1beta/openai` base, exactly as onto a bare host or `/v1`; a full URL passes through verbatim.
5. Bearer auth header for gemini (the OpenAI scheme), NOT the Anthropic `x-api-key`.
6. provider-list error message names gemini.
Everything that branches `if anthropic ... else openai` already covers gemini; embeddings work
(unlike anthropic which errors).

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| gemini provider (OpenAI-compat) | [x] | [ ] | [ ] | [ ] |

## Tests (real, no mocks - local HTTP server, positive + negative)
- default endpoint resolves to `.../v1beta/openai/chat/completions` and `.../embeddings`
- chat sends an OpenAI-shaped body with `Authorization: Bearer` (not `x-api-key`); normalised text/model
- embeddings supported (returns vectors)
- gemini requires a key (negative -> config error)
- streaming yields OpenAI-style text deltas + a terminal done event

## Files
- PHP: `tina4-php/Tina4/AI.php`
- Ruby: `tina4-ruby/lib/tina4/ai_client.rb`
- Node: `tina4-nodejs/packages/core/src/aiClient.ts`

## Commits
- (python) <pending> gemini provider + 5 contract tests
- (php/ruby/node) <pending>

## Status: In Progress - Python done, porting to PHP/Ruby/Node
