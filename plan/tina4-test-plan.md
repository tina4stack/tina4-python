# Task: tina4-test-plan skill

## Outcome
A shared skill that writes a manual test plan (xlsx, PDF, agent prompt) for any Tina4 project or
other web app, built from the personal `qa-test-plan` skill. It ships through the normal skills bundle.

## Scope
- [x] Move the skill to `.claude/skills/tina4-test-plan/` with everything under `references/`, because
      the installers fetch only `SKILL.md` and `references/`
- [x] Discovery covers Python, PHP, Ruby, Node.js and tina4-js, using `tina4 routes`
- [x] Priorities and clean-up no longer assume money and stock (`blocker_areas`, `cleanup`)
- [x] Tina4 cases in the coverage checklist (auth defaults, CSRF, debug, `/health`, queue)
- [ ] tina4 repo: `scripts/skills-list.sh` entry (paired PR)
- [ ] Release: both installers, re-sign `install-skills.ps1`, regenerate `skills.sha256`

## Parity
| Discovery covered | Python | PHP | Ruby | Node |
|-------------------|--------|-----|------|------|
| routes + models   | ✅     | ✅  | ✅   | ✅   |

Skill only. No framework code changes, so there is nothing to port.

## Tests (real, no mocks: openpyxl, reportlab, formulas)
- [x] Example output matches the old builder apart from the planned text changes
- [x] Summary formulas recalculate with results filled in (`formulas` engine)
- [x] Neutral defaults with no `blocker_areas` or `cleanup`
- [x] Bad priority and duplicate prefix stop the build
- [x] A step that starts with `=` stays text (proven by mutation)
- [x] Builder runs from an install layout holding only the listed files
- [x] Frontmatter gate, no-symlink gate, encoding gate
- [ ] Open the workbook in Excel or LibreOffice (LibreOffice hangs in the sandbox used)

## Bugs
- [x] Agent prompt block ran twice in the builder
- [x] Text files opened with the system encoding, which breaks on Windows
- [x] A step that starts with `=` was stored as a formula
- [x] Skill named a `T4DD` plan folder; no Tina4 source or skill uses that name, so it now says `AC-N` specs

## Commits
- (this branch)  skills: add tina4-test-plan

## Status: In Progress
