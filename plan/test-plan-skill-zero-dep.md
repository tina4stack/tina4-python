# Task: tina4-test-plan skill — zero dependency + plan-aligned

The `tina4-test-plan` skill's builder (`.claude/skills/tina4-test-plan/references/build_test_plan.py`)
required **openpyxl** and **reportlab**. That contradicts two Tina4 rules: the framework's
zero-dependency promise, and this skill's own claim to teach the Tina4 way. An `.xlsx` is a zip of
OOXML parts and a PDF is a plain object format — both are buildable from the Python stdlib, exactly
how Tina4 builds its own HTTP server, JWT, base64 and XML parser.

**Outcome:** the skill builds the same `.xlsx` + `.pdf` + agent prompt with **standard library only**
(`zipfile`, `xml`, `zlib`, `struct` — all stdlib), so using the skill installs nothing. The self-test
and CI need no `pip install`. The skill also ties cases to `plan/` acceptance criteria (align with the
planning discipline), and this work is itself tracked here (plan-driven).

## Scope
- [x] `references/_xlsx.py` — minimal stdlib OOXML writer (cells, number/string/formula+cached value,
      fonts/fills/borders, column widths, freeze panes, auto-filter, list data-validation, conditional fill)
- [x] `references/_pdf.py` — minimal stdlib PDF writer (pages, Helvetica AFM text metrics, wrapped text,
      tables with wrapped cells + page breaks, filled/stroked rectangles, footer)
- [x] `references/build_test_plan.py` — rewired onto the two writers; no openpyxl/reportlab import
- [x] `references/selftest.py` — asserts the output via stdlib (zip+regex for xlsx, raw-byte scan
      for pdf); no openpyxl
- [x] `.github/workflows/test-plan-skill.yml` — dropped the `pip install`; runs pure python
- [x] `SKILL.md` — removed the openpyxl/reportlab + `uv --with` instructions; states stdlib-only; keeps the
      "cite plan/ AC-N" coverage rule (planning alignment)

## Tests (real, no mocks — build then assert the actual bytes)
- [x] selftest builds `example-spec.json` and asserts: 5 sheets, one row per case, Result/Priority
      dropdowns, 3 conditional fills, no Test-cases cell is a formula, Summary grand total carries a cached value
- [x] xlsx opens cleanly — `openpyxl` load with warnings-as-errors passes (dev-time check, not shipped)
- [x] pdf is a valid document (starts %PDF, ends %%EOF, >=3 pages, "Coverage at a glance"/"Sign-off" present)
- [x] mutation proof: dropping the cached-value write in `_xlsx.py` turns the selftest red; restore → green
- [x] formula-looking step (`=1+1`) proven stored as inline text, no `<f>`

## Bugs
- [x] my selftest referenced an undefined `c` in a comprehension (ruff F821) — fixed before commit
- [x] two dead locals in `_pdf.py` (ruff F841) — removed

## Commits
- 2dcd4566  test(skills): self-test gate (openpyxl-based — superseded by the stdlib rewrite)
- (this)    refactor(skills): zero-dependency builder (stdlib _xlsx.py/_pdf.py), stdlib self-test, plan

## Status: Complete
