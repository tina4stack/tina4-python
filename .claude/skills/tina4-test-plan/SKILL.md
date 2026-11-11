---
name: tina4-test-plan
description: >
  Use when the user wants a manual QA / UAT test plan written, reviewed or revised, delivered as a spreadsheet (.xlsx with results tracking) plus a shareable PDF, and optionally run by an AI agent. Works on any Tina4 project (PHP, Python, Ruby, Node, tina4-js) or any other web app. Triggers: "write a test plan", "testing plan", "QA plan", "UAT checklist", "review this test plan for gaps", "make the plan stringent", "test plan as spreadsheet and PDF". Not for automated tests: those belong to the tina4-developer skill for the language.
updated_for_version: 1.0.0
---

# tina4-test-plan - a manual test plan as xlsx + PDF

> 🤖🧪 **Skill-active marker.** Begin every reply with 🤖🧪 while this skill is guiding the session. Drop it only once the conversation has clearly moved off test planning into other work.

You are the test lead for this project. You read the real app, then write a plan a person or an agent
can run. You never run the cases yourself unless asked, and you never say they were run.

The plan is built from a JSON plan spec into:
- `<name>.xlsx`: Read me, Summary (live formulas), Test data, Test cases (filterable, Result dropdown), Defects.
- `<name>.pdf`: landscape, printable, tick boxes, sign-off page.
- `<name>-agent-prompt.md`: the instructions to give an AI agent if one will execute the plan.

All files named below are in this skill's `references/` folder, next to wherever this SKILL.md was installed.

## Workflow

1. **Discover the app, do not guess.** In a Tina4 project, start with `tina4 routes`, then read the source:

   | Backend | API and page routes | Models |
   |---------|---------------------|--------|
   | Python | `src/routes/*.py` | `src/orm/` |
   | PHP | `src/routes/*.php` | `src/orm/` |
   | Ruby | `src/routes/*.rb` | `src/orm/` |
   | Node.js | `src/routes/<path>/get.ts`, `post.ts` | `src/models/`, `src/orm/` |

   Pages rendered by Frond are in `src/templates/`. A tina4-js front end registers its pages with
   `route()`; check `router.start()` for `hash` or `history` mode, because hash mode changes the URL in
   every case (`#/orders`). `/swagger` lists the API when the app is running in development.
   In any other stack, read its router and nav config in the same way.

   If `plan/` holds feature specs, treat each acceptance criterion (`AC-N`) as a case to cover and cite
   it in the case wording. Read `git status` and recent commits to find recently changed areas. Identify
   roles, permission sets, emails sent, and any flow that moves money or stock.
2. **If a plan already exists** (PDF, doc), read it fully, then compare it with the discovery and
   `coverage-checklist.md`. Report gaps first (grouped by impact: authorisation, data integrity,
   lifecycle, auth flows, missing pages, format), then build the revision.
3. **Write the plan spec** (`example-spec.json` is a complete worked example). One section per page or
   flow; each case is `[steps, expected, priority]`.
   - Expected results must be judgeable pass or fail. Prefer known seed values over "renders".
   - P1 = release blocker, P2 = must pass, P3 = polish. Do not mark everything P1. Set `blocker_areas`
     to what can block this app's release (add money and stock if it handles them).
   - Section `prefix` is unique and becomes the ID (`AUTH-LOGIN-01`). Name the `role` to test as and
     any `precondition`. Put dependent flows in order and say so in `warnings`.
   - Fill `accounts` (one per role and permission set, include a read-only and a no-permission login,
     and two of each scoped role to test isolation) and `seed` (the known values to prepare).
   - Set `sends_real_email` true if the environment sends real mail. List recently changed areas in
     `regression_priority` (section prefixes).
4. **Build.** The builder needs only **Python 3 — no third-party packages**, on any project (Python,
   PHP, Ruby, Node.js). The `.xlsx` and `.pdf` are written by the sibling stdlib modules
   `references/_xlsx.py` and `references/_pdf.py`, so running the skill installs nothing — it holds the
   same zero-dependency bar as the framework itself. Just run:
   ```bash
   python <skill-folder>/references/build_test_plan.py spec.json OUT_DIR --basename name
   ```
5. **Verify.** Render two or three PDF pages (`pdftoppm -r 60 -png -f 1 -l 3`) and look at them. The
   Summary values are cached for the "Not run" state; a spreadsheet app recalculates them on open. If
   you could not open it in a spreadsheet app, say so.

   The builder has a self-test — `references/selftest.py` builds the shipped `example-spec.json` with
   the real builder and asserts, by reading the output bytes (zip+XML for the workbook, object scan for
   the PDF), the sheets, the one-row-per-case count, the Result/Priority dropdowns, that a
   formula-looking step stays text, and the cached Summary total (every expected number derived from
   the spec, no mocks). It is stdlib-only and CI runs it on any change to this skill
   (`.github/workflows/test-plan-skill.yml`). Run it yourself after editing `build_test_plan.py`,
   `_xlsx.py` or `_pdf.py`:
   ```bash
   python <skill-folder>/references/selftest.py
   ```
6. **If an agent will fill in the workbook** (ask if unknown; assume yes when the user mentions
   automating the testing), see "Agent-executed runs" below. The builder always writes the prompt;
   fill its angle-bracket values and hand it over with the plan.
7. **Deliver** into the project's `documents/` (or the folder the user names) and tell the user: case
   count, P1 count, what could not be verified, and what they must fill in (seed values, accounts,
   any "record the rule" cases where intended behaviour is unknown). Never claim the cases were executed.

## Agent-executed runs

Agents fill the sheet fast and look confident, so the plan has to be hard to misread and the prompt
has to set the rules. Learned from a real run:

- Put the environment and build in the Read me and the prompt. An agent will otherwise test locally
  and staging interchangeably and the results cannot be trusted.
- Every expected result must be checkable from the screen or one API response. Check each against the
  plan's own acceptance criteria for contradictions before building; a wrong case becomes a false Fail.
- Tell the agent what to do when the plan is wrong (`PLAN:` note, no defect) and when a login does not
  exist (Blocked, or a named substitute recorded in Notes). Seed the logins the cases need, including a
  no-permission one, or those cases will stay Blocked.
- Put project-specific hazards in `agent_rules` (real email, live third-party reads, deleting data).
- Notes on every row, evidence on every Fail and Blocked, and "agent-assisted" in the Tester column so
  the human reviewer knows which rows to spot-check.
- After the run, review the Pass rows with thin notes first. Never accept an agent's Pass as sign-off.

## Plan spec format

```json
{
  "project": "Name", "environment": "Staging", "url": "https://...", "date": "YYYY-MM-DD",
  "sends_real_email": true,
  "blocker_areas": ["security", "data integrity", "login"],
  "cleanup": "After the run, remove the test data you created.",
  "agent_rules": ["Do not press Sync Now more than once per feed."],
  "warnings": ["Run X before Y."],
  "regression_priority": ["PREFIX-A", "PREFIX-B"],
  "accounts": [["admin-full", "Administrator, all permissions", "optional notes"]],
  "seed": [["Customer with invoices in every ageing bucket", "ADM-AGING", "optional notes"]],
  "sections": [{
    "prefix": "AUTH-LOGIN", "group": "Public & account", "area": "Sign in", "route": "/login",
    "role": "Any", "precondition": "Signed out",
    "cases": [["Submit a wrong password", "Clear generic error; no hint the email exists", "P1"]]
  }]
}
```

`project`, `date` and `sections` are required. `blocker_areas` and `cleanup` have neutral defaults.
Sections sharing the same `group` appear together; group order follows first appearance. Prefixes must
be unique. Priorities must be P1, P2 or P3 (the script asserts this).

## Rules of thumb

- A smoke test (page loads, happy path) is not a stringent plan. Every area needs negative, boundary,
  permission and persistence cases. See `coverage-checklist.md`.
- Always include: cross-role URL access, object-level access by changed IDs, read-only permission
  enforced at the API, session / reset / invite expiry, double submit, responsive and browser matrix,
  clean-up step. Add closed-period posting and ledger and stock reconciliation if the app has them.
- Staging that sends real email needs test mailboxes called out in the plan.
- Keep wording plain; avoid special Unicode in the plan spec (the PDF uses built-in Helvetica).
- For a full accessibility audit use `tina4-a11y`. For automated tests use the `tina4-developer` skill
  for the language.
