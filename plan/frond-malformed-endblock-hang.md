# Task: Frond hangs forever on a malformed `{% endblock %}` (tina4-python#271)

## Scope
- [x] Reproduce the hang in Python at HEAD (unit + render level)
- [x] Fix `Frond._extract_blocks` so a malformed block advances `pos`
- [x] Real no-mock regression test (malformed child renders; well-formed unchanged)
- [x] Mutation-prove the test (remove the advance -> hang test times out)
- [x] Parity sweep: check PHP / Ruby / Node for the same defect

## Bug

`Frond._extract_blocks` (`tina4_python/frond/engine.py`) pairs each `{% block %}`
with its matching `{% endblock %}` using a depth counter. When the inner scan finds
no closing tag it did `break  # malformed`. Python's `while ... else` runs the
`else` (which advanced `pos = content_start`) ONLY on a normal loop exit, never on
a `break` — so `pos` never moved, and the outer `while pos < len(source)` re-found
the same `{% block %}` forever. A child template whose last `{% endblock %}` lost
its `}` therefore made the render spin forever (no return, no raise). Reported
against 3.13.156.

Fix: set `pos = content_start` before the `break`, exactly as the `else` branch
already does for the scan-ran-off-the-end case, so both malformed cases advance
identically and the outer loop always makes progress.

## Parity (Python is the reference)

| Framework | Affected? | Why |
|-----------|-----------|-----|
| Python  | YES — fixed | `while...else` skips `else` on `break`, so `pos` never advanced |
| Ruby    | no | `extract_blocks` sets `pos = content_start unless matched` AFTER the loop |
| Node    | no | `extractBlocks` runs `if (depth > 0) pos = contentStart;` AFTER the loop |
| PHP     | no | the compiler's `parse()` loop is bounded by the finite token array; a malformed `{% endblock %` is not tokenised as an endblock tag |

Only Python carried the defect. The other three advance (or are token-bounded) by a
differing-but-correct structure. Each was confirmed by reproducing the exact
malformed template; all three returned. An equivalent regression test lands in all
four to lock the contract so a future refactor cannot reintroduce the hang in one.

## Tests (written real — no mocks, positive + negative)
- [x] Python `tests/test_frond_malformed_endblock_hang.py` (render + unit; `@pytest.mark.timeout(10)`), mutation-proven
- [x] Ruby `spec/frond_malformed_endblock_hang_spec.rb` (Timeout-bounded render)
- [x] Node `test/frondMalformedEndblockHang.test.ts` (render)
- [x] PHP `tests/FrondMalformedEndblockHangTest.php` (render)

## Commits
- (python) fix `_extract_blocks` advance + regression test — closes #271
- (ruby / node / php) parity regression guard

## Status: Done pending CI
