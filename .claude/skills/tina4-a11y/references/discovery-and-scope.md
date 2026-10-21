# Discovery and scope

> Reference for the `tina4-a11y` skill: Phase 1 (discovery audit) and the scope checkpoint. Moved out of `SKILL.md` unchanged.

## Phase 1 — Discovery audit

Read the project files and report the current state before writing any fixes.

### 1.1 Read design/DESIGN.md

If present, extract:
- `--focus-ring` token definition
- Contrast ratios recorded per token pair
- Touch target minimum
- Motion personality and `prefers-reduced-motion` policy
- Whether ARIA state patterns are documented for custom components

### 1.2 Read existing templates and stylesheets

Find the base template layer:
- **PHP:** `src/templates/`
- **Python:** `src/templates/`
- **Ruby:** `lib/tina4/public/` or `src/templates/`
- **Node:** `src/templates/` or `views/`
- **Plain HTML:** the shared `<head>` include or index.html

And the stylesheets:
- Application CSS files
- Any theme override that layers over `tina4.min.css`

Read them. Extract:
- `<html lang="...">` — present? correct?
- Landmark elements (`<header>`, `<nav>`, `<main>`, `<footer>`) — present per template?
- `<title>` pattern (static or dynamic per page)
- `outline: none` usages without replacement focus rings
- Any inline `onclick` handlers on non-interactive elements

### 1.3 Run automated tools as a first pass

Automated tools catch ~30–40% of accessibility issues. They are a first sweep, not a substitute for the manual audit.

- **axe DevTools** — browser extension; the most reliable single tool. Run on every key page.
- **Lighthouse (Chrome DevTools)** — accessibility category runs axe under the hood plus additional heuristics. A score of 100 is NOT the same as compliant.
- **Pa11y** — CLI tool for CI integration.
- **WAVE** — visual overlay browser extension.

Report the tool findings; they seed the manual audit that follows.

### 1.4 Report and proceed

Report the audit results as a ✅/❌/⚠️ table before proceeding:

```
Accessibility Discovery Audit — [Project Name]

Page structure:
  <html lang>:              ✅ set to en-ZA on all templates
  Skip link:                ❌ missing
  Landmarks:                ⚠️ <main> missing on /contact
  Unique page titles:       ✅

Keyboard navigation:
  Tab order:                ⚠️ 3 clickable divs found, no keyboard access
  tabindex misuse:          ❌ tabindex="3" found on hero button
  Modal focus trap:         ⚠️ native <dialog> not used; manual trap absent

Focus indicators:
  outline: none replaced:   ❌ 5 uses of outline:none without box-shadow

Images and media:
  Missing alt text:         ⚠️ 12 images across 4 pages
  Decorative SVG marked:    ❌ 8 icon SVGs missing aria-hidden

Forms:
  Every input has label:    ⚠️ 4 inputs use placeholder as label
  Error messages linked:    ❌ aria-describedby not used

ARIA states:
  Accordion aria-expanded:  ❌ static true, does not toggle
  Modal aria-modal:         ✅
  Toast role="status":      ❌ missing

Colour contrast:
  Body text on bg:          ✅ 13.2:1
  Placeholder text:         ❌ 2.8:1 — below 3:1 minimum
  Ghost button on white:    ❌ 2.4:1 — below 4.5:1

Zoom and reflow:
  320px width:              ⚠️ horizontal scroll on /products
  400% zoom:                ✅

Reduced motion:
  prefers-reduced-motion:   ❌ no @media block found

Automated tool results:
  axe DevTools:             28 issues (9 critical, 12 serious, 7 moderate)
  Lighthouse a11y score:    76 / 100

Working through each item in priority order — CRITICAL first.
```

### 1.5 Scope checkpoint — wait for user signal

After the audit table, ask the user how to proceed and **wait for a response** before writing any fixes. Do not silently proceed to Phase 2.

**Preferred: use a structured-question tool** (`AskUserQuestion` in Claude Code, or the equivalent in the current agent harness) with these options:

- **Fix everything** — all phases including optional
- **AA-required** — everything WCAG 2.1 AA needs; skip OPTIONAL phases (enhanced SR support, forced-colors)
- **Critical only** — page structure, keyboard, focus, images, forms; nothing else
- **Let me scope** — user picks specifics via follow-up multi-select: skip checkout template, keep touch targets at 24×24, keep manual focus trap, only fix contrast, don't touch focus-ring styles

**Fallback if no structured tool is available:** send the same question as a numbered prose list.

Whichever path is used, also surface any decisions the skill cannot make alone — e.g. "brand accent #FAB033 fails contrast; darken to #E89A20, pair with a darker text token, or keep as-is with an exception note?" — using structured options where possible.

**Wait for the response.** Gather scope decision + any pending decisions in ONE round trip, then proceed to Phase 2. On a subsequent run of this skill, this checkpoint fires again — the user always gets to steer.
