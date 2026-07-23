# Task: SCSS `!default` — strip the flag AND implement its semantics (all 4)

## Goal
`$x: value !default;` must (a) never leak `!default` into the compiled CSS, and
(b) assign only when `$x` is not already set — the behaviour that makes a
variable themeable.

## Context
All four compilers stored the raw declaration value including the flag, so
`$g: 1.5rem !default;` compiled to `padding: 1.5rem !default;` — invalid CSS
that browsers drop. Because the flag rode inside the *stored variable value*, it
was then substituted into function arguments too, producing
`rgba(#000 !default, 0.075)`. Both halves were broken: assignments always
overwrote, so a user override placed before an importing partial was silently
discarded.

## Dart Sass 1.101.6 reference (measured, not assumed)
| Input | Dart Sass |
| --- | --- |
| `$g: 1.5rem !default;` then `padding: $g` | `1.5rem` (flag consumed) |
| `$p: red;` then `$p: blue !default;` | `red` (override wins) |
| `$c: null;` then `$c: teal !default;` | `teal` (null counts as unset) |
| `$a: 1rem !default;` then `$a: 2rem !default;` | `1rem` (first wins) |
| `$a: 1rem !default;` then `$a: 2rem;` | `2rem` (plain overwrites) |
| `$p: hotpink;` + `@import` partial with `$p: navy !default;` | `hotpink` |
| `$a: 5px !default !global;` | `5px` |
| `rgba(#000 !default, 0.1)` | **syntax error** — not valid SCSS |
| `content: "x !default y";` | preserved verbatim |
| `$a: 1rem !DEFAULT;` | **error** — flag names are case-SENSITIVE |

## Decisions
1. **Strip flags only in a variable-declaration value.** A literal `!default`
   anywhere else (a quoted string, a property value, a function argument) is left
   verbatim, matching Dart Sass. A global strip would corrupt
   `content: "x !default y"` and would silently manufacture valid-looking CSS
   from input Sass calls a syntax error.
2. **`!default` inside a function argument needs no handling.** It never appears
   in valid SCSS (Dart Sass rejects it) and it appears **zero** times in
   `tina4-css`'s source — verified by grep. The 41 `rgba(#000 !default, 0.1)`
   occurrences are entirely the compilers' own corruption, downstream of the leak.
   Fixing the declaration-site strip removes all 41 with no special case.
3. **No new error surface.** These compilers have no exception path at all
   (unresolved imports/mixins emit `/* NOT FOUND */` comments). Raising on a
   stray `!default` would be a new behaviour class in four languages for a
   construct that does not occur. Leaving it verbatim keeps invalid input visibly
   invalid.
4. **`!global` is consumed too** — same reason, same place.
5. **Case-sensitive match** (no `IGNORECASE`), because Sass flag names are.

## Scope
- [x] Measure Dart Sass reference behaviour
- [x] Prove the negative tests fail against the current compilers
- [x] Python master: `_strip_variable_flags` + `!default` guard in `_extract_variables`
- [x] PHP mirror
- [x] Ruby mirror (+ `/m` on the declaration regex — see Bugs)
- [x] Node mirror
- [x] Lock-in tests in all four (positive + negative)
- [x] End-to-end: compile `tina4-css/src/scss/tina4.scss`, leak count -> 0
- [x] Cross-check all four agree on the same input
- [x] Full suite green per framework at final HEAD

## Baseline (before fix) — `ScssCompiler().compileFile("tina4-css/src/scss/tina4.scss")`
| Compiler | `!default` tokens | lines (`grep -c`) | broken `rgba(#hex !default` | output bytes |
| --- | --- | --- | --- | --- |
| Python | 432 | **317** | 41 | 39531 |
| PHP | 438 | 321 | 41 | 39580 |
| Ruby | 209 | 203 | 37 | 26413 |
| Node | 438 | 321 | 41 | 39580 |

The owner's reported "317 leaked / 41 broken rgba" reproduces exactly as the
Python **line** count.

## After the fix — same command, same file
| Compiler | `!default` tokens | lines | broken `rgba` | output bytes |
| --- | --- | --- | --- | --- |
| Python | **0** | **0** | **0** | 35436 |
| PHP | **0** | **0** | **0** | 35431 |
| Ruby | **0** | **0** | **0** | 25167 |
| Node | **0** | **0** | **0** | 35431 |

Python's changed output was diffed against the before-output with the literal
` !default` text removed: the only remaining differences are **downstream
repairs** — 42 lines that were invalid CSS before are now valid
(`rgba(#000, 0.1)` -> `rgba(0, 0, 0, 0.1)` now that the hex-to-rgb conversion can
match; `min-height: 1.5 * 1rem` -> `1.50rem` now that the math fold can match).
Nothing else moved: the count of pre-existing `@each`-variable leftovers (905)
and map-literal leak lines (211) is byte-identical before and after.

## Cross-check — all four on 12 identical inputs
Every case agrees across Python / PHP / Ruby / Node, and every answer matches
the measured Dart Sass result: `padding: 1.5rem`, `color: red`, `color: blue`,
`color: teal`, `margin: 1rem`, `margin: 2rem`, `top: 5px`,
`content: "x !default y"`, `rgba(#000 !default, 0.1)` (verbatim),
`rgba(0, 0, 0, 0.075)`, `top: 3px !important`, `z-index: 1`.

## Tests (real compiles, no mocks — a compiler is a pure string function)
- [x] `!default` declaration produces zero `!default` tokens in output
- [x] already-set variable is NOT overwritten by a later `!default`
- [x] unset variable IS assigned by `!default`
- [x] `null` counts as unset
- [x] first `!default` wins over a second `!default`
- [x] a plain declaration after a `!default` DOES overwrite
- [x] override survives across a real `@import` of a real partial (real files on disk)
- [x] `!global` consumed
- [x] `!default` inside a quoted string is preserved (negative — guards the strip's scope)
- [x] preset variables (`set_variable`) beat a source `!default`
- [x] end-to-end: real `tina4-css` source compiles with zero `!default`

## Bugs
- [x] `!default` leaked into compiled CSS (all 4)
- [x] `!default` semantics unimplemented — user override silently discarded (all 4)
- [x] `rgba(#hex !default, a)` corruption (all 4) — downstream of the above
- [x] Ruby only: the declaration regex `(.+?);` lacked `/m`, so a **multi-line**
      `$var:` declaration was never extracted and the raw SCSS (map literal and
      all) was dumped verbatim into the CSS. Fixed to match the master's
      `[^;]+` span semantics; required for Ruby to reach zero.

## Not in scope (pre-existing, reported not fixed)
- Ruby's `basic_compile` emits materially less CSS than the master (26KB vs
  39KB) — single-level `flatten_nesting`, no mixin/placeholder extraction.
- Python emits 39531 bytes vs PHP/Node's 39580 (Python extracts `%placeholder`
  selectors, PHP/Node do not).
- Assignments remain "last declaration wins for the whole document" (the
  substitution map is applied after the whole file is scanned). `!default` is
  resolved in source order, which is what this fix needs; full per-statement
  ordering is a much larger change.

## Full-suite totals at final HEAD (macOS 15 / darwin 25.5.0, arm64)
Python 3.13.5 | PHP 8.5.7 | Ruby 4.0.2 | Node 24.9.0 | reference Dart Sass 1.101.6

| Framework | Owner's baseline | Final HEAD | Delta |
| --- | --- | --- | --- |
| Python | 3562 passed / 104 skipped | **3576 passed / 104 skipped** | +14 |
| PHP | 3867 tests / 9995 assertions / 0 failures | **3881 tests / 10025 assertions / 0 failures** | +14 / +30 |
| Ruby | 3988 examples / 0 failures / 61 pending | **4002 examples / 0 failures / 61 pending** | +14 |
| Node | 5575 passed / 170 files | **5589 passed / 0 failed / 170 files** | +14 |
| Node `npm run typecheck` | green | **green** | - |

Every delta is exactly the 14 new tests; nothing regressed. PHP reports 8 PHPUnit
deprecations and 100 skips — pre-existing (the changed `ScssV3Test.php` run alone
is a clean `OK (57 tests, 108 assertions)`), and failures are 0 either way.

## Status: Complete
