# Task: Align Frond function/closure globals to Node (ADR-0085)

Outcome: a bare zero-argument callable global registered via add_global/addGlobal
is invoked and its return value is used for both `{{ g }}` output and `{% if g %}`
conditions, matching Node. `g()` still works and calls once. Scope is globals only.

## Scope
- [x] Read the Node reference (engine.ts resolvePathPart auto-calls a function member)
- [x] Node: add guard test only (behaviour already correct); mutation-proved
- [x] Python: wrap zero-param callable globals; auto-call at end of _resolve
- [x] PHP: wrap zero-param Closure globals; auto-call at end of resolveVariable
- [x] Ruby: wrap zero-arity Proc/Method globals; auto-call at end of resolve
- [x] Shared fixture frond_globals_contract.json + runner test in all four
- [x] ADR-0085 + DECISIONS.md + CONTRACT-MAP.md

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| bare zero-arg global auto-calls | ✅ | ✅ | ✅ | ✅ (reference) |

## Tests (written first, real — no mocks, positive + negative)
- [x] zero arg global closure returning false is falsy in if
- [x] zero arg global closure returning true is truthy in if
- [x] zero arg global closure prints its return value
- [x] explicit call syntax still works
- [x] non callable global is unchanged
- [x] global returning a callable is not double called
- [x] unregistered function call is falsy

## Bugs
- [x] tina4-documentation#90 — `{% if admin_only %}` always truthy in Python/PHP/Ruby

## Commits
- (see git log; signed-off, Tina4 + Claude co-authors)

## Status: In Progress
