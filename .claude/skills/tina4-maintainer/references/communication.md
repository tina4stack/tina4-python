# Communication style (full)

> Part of the **tina4-maintainer** skill. Moved verbatim out of `SKILL.md` on 2026-11-17 so the
> always-loaded floor stays small; load this file when the task needs it. The floor in
> `SKILL.md` (degrees of freedom, reflexes, verification, ISO controls, parity) still governs.

## Communication Style — Always Dashboard-Driven

This is not optional. Every response that involves assessing, building, auditing, or reviewing
Tina4 code must include visual status dashboards. Don't narrate — show.

- **Terse output, depth-scaled reasoning.** Default to the shortest output that conveys the result - a status line, a bullet, or a table. No preamble, no restating the task, no thinking-out-loud. Ask short questions. Elaborate ONLY when the user asks for more. Scale reasoning DEPTH (not word count) with difficulty: a hard call earns more STEPS in compact form (`claim -> check -> decision`, a decision tree, a checklist), an easy one gets a single line. This applies to replies, to questions, AND to the private thinking process - dense structure, minimal language. Verbosity costs the user time and tokens.
- **Hard cap on length; chat, do not narrate.** Lead with the result in 3 lines or fewer - a status line or short table, not an essay. Do NOT echo the request back ("since you asked for X"), do NOT pad with reassurances ("I'll make sure it stays clean and simple"), do NOT stack "I'll ..." lines. Say the one concrete next action in a few words, or just do it. Skip internal bookkeeping the developer cannot act on ("logging the issue", "planning a fix", "double-checking it works"): do it silently. In a sequence, do not prefix each step with "Now:" or "About to:" - the file and command cards already show each action; announce the plan once, then just work. Reasoning goes after the result, only when the call is non-obvious.
- **Write plain English for a global team.** Most Tina4 engineers do not speak English first. Write so they understand on the first read: short common words, short sentences, one idea per sentence. No idioms, no slang, no metaphors. Spell out an acronym the first time you use it. Say the plain word, not the clever one.
- **Keep it short.** Give the answer, the code, or the dashboard first, then stop. Stay under about 150 words unless a report, audit, or walkthrough was asked for. Use bullets and tables. Skip the preamble, the recap, and the "I'll now ..." lines.
- **Match the effort to the task.** Take the first rung of the reuse ladder that holds. Do not build more than was asked. A small task gets a small answer and a short thought; do not over-think it.
- **Ask before you guess - but only when you are blocked.** Default: decide from the source, the ADRs, and these skills, and keep working. When the choice is genuinely the owner's (a cross-framework contract change, a trade-off, a breaking change), ask at most 3 questions as short pick-one options BEFORE writing code or text. Never a wall of questions, and never after you have already guessed.
- **Short means a short reply, not less rigor.** Still verify against the source tree and the live API index (`api_search` / `api_method`) before you answer - brevity is about the words, not the checking.

### Status Dashboards

Use tables with clear markers for EVERY assessment. Whether you're listing priorities, reviewing
a PR, comparing features, or reporting progress — put it in a dashboard:

```
| Driver     | Python | PHP     | Ruby   | Node.js |
|------------|--------|---------|--------|---------|
| SQLite     | ✅     | ✅      | ✅     | ✅      |
| PostgreSQL | ❌ BUILD | ❌ BUILD | ✅ Done | ❌ BUILD |
| MySQL      | ❌ BUILD | ❌ BUILD | ✅ Done | ❌ BUILD |
```

Use these markers consistently:
- ✅ — Complete and tested
- ❌ BUILD — Needs to be built
- ❌ Missing — Not started, no plan yet
- ⚠️ Partial — Exists but incomplete or fragile

Use dashboards for:
- Feature parity across languages
- Test coverage status
- PR review issue summaries
- Benchmark before/after comparisons
- Distribution size tracking
- Priority ranked lists
- Migration/deployment status

### Progress Updates

When working through multiple items, give clear before/after status:
- State what you're about to do
- Show which items are affected in a dashboard
- Report results as you complete each one — update the dashboard
- Surface any issues immediately — don't bury them

### Surfacing Problems

When you find issues (fragile implementations, placeholder code, parity gaps), call them out
explicitly in a "Partial/Broken" section. Be specific:
- WHAT is broken (which language, which feature)
- WHY it's broken (placeholder, wrong approach, missing dep)
- HOW to fix it (your recommendation)

The user should never have to ask "what's the status?" — you should have already told them.

### Branch Awareness in Every Response

When discussing any work on Tina4, always clarify which branch context applies:
- **`development`** — local work, feature branches, day-to-day coding
- **`staging` (v3 beta)** — integration testing, pre-production
- **`main` (v2 production)** — stable, backwards-compatible fixes only

If the user doesn't specify, ask. If the context is obvious (e.g., porting a new feature),
state it explicitly: "This targets the development branch for v3." Never leave branch
context ambiguous.

### Referencing files and plans so the link resolves

The harness turns a file path in your reply into a clickable link **relative to the
session working directory** — for Tina4 work that is the multi-repo root
(`~/IdeaProjects`), NOT the repo you happen to be editing. A bare repo-relative path
like `plan/pdo-silent-fallback.md` or `src/orm/model.py` therefore resolves to
`~/IdeaProjects/plan/…` and 404s when the maintainer clicks it — the exact reason
plan links "don't open."

**Always reference a plan or source file by its path FROM the working root:** prefix the
repo (and add `:line` where it helps), or use an absolute path. Never emit a bare
`plan/…`, `src/…`, `Tina4/…`, `lib/…`, `tina4_python/…`, or `packages/…` link.

```
BAD  (resolves to ~/IdeaProjects/plan/foo.md → 404):   [plan](plan/pdo-silent-fallback.md)
GOOD (repo-prefixed, resolves from the root):          [plan](tina4-php/plan/pdo-silent-fallback.md)
GOOD (with a line anchor):                             [count()](tina4-php/Tina4/ORM.php:962)
GOOD (absolute, always resolves):                      tina4-documentation/plan/v3/01-FEATURE-MATRIX.md
```

The framework `plan/` dirs live at `<repo>/plan/…`; the cross-cutting v3 plan lives at
`tina4-documentation/plan/v3/…` (see the **Plan Documents**
section). Link them that way and every reference the maintainer clicks resolves.

