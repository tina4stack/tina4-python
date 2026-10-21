# Validation and handoff

> Reference for the `tina4-a11y` skill: Phase 20 (validation and handoff), the DESIGN.md accessibility section, the plan structure, the relationship to other tina4 skills, and the avoid-list. Moved out of `SKILL.md` unchanged.

## Phase 20 — Validation and handoff

### 20.1 Manual keyboard walkthrough

Do a keyboard-only walkthrough of one full user journey per key page. If you can complete the primary action (buy, sign up, contact) using only Tab/Shift-Tab/Enter/Escape/arrow keys, that page passes the keyboard gate. If you can't, name the block.

### 20.2 Screen reader walkthrough

Do a screen reader walkthrough with:
- **NVDA** (Windows, free) — most common testing target
- **VoiceOver** (Mac, built-in) — `Cmd+F5` to toggle
- **Orca** (Linux, built-in)

Test at least: page load announcement (title + landmarks), main navigation, one form submission, one modal open/close.

### 20.3 Re-run automated tools

After fixes:
- axe DevTools — target zero critical/serious issues
- Lighthouse a11y score — target 95+
- Pa11y — clean run in CI

### 20.4 Handoff report

Generate a complete audit summary in this format. Every cell contains a real value — never "see above" or "completed".

```
## Accessibility Audit Report — [Project Name]  [date]  WCAG 2.1 Level AA

### Page structure and landmarks
<html lang>:              ✅ en-ZA on all templates
Skip link:                ✅ implemented on base template
Landmarks:                ✅ header/nav/main/footer on all pages
Unique page titles:       ✅ per-page dynamic
aria-current on nav:      ✅

### Keyboard navigation
Tab order:                ✅ logical, top-left → bottom-right
No tabindex > 0:          ✅
Custom components:        ✅ Enter/Space/arrow/Escape wired
Modal focus trap:         ✅ native <dialog> used

### Focus indicators
outline: none replaced:   ✅ 5 sites patched with box-shadow focus ring
:focus-visible pattern:   ✅

### Images and media
img alt text:             ✅ 12 corrected
SVG icons:                ✅ 8 marked aria-hidden
Video captions:           ✅ / N/A

### Forms
Labels on every input:    ✅
Required indicators:      ✅ visible + sr-only "required"
Error messages linked:    ✅ aria-describedby + aria-invalid
Autocomplete tokens:      ✅

### ARIA states
Accordion:                ✅ aria-expanded toggles
Modal:                    ✅ aria-modal + aria-labelledby
Tabs:                     ✅ role=tablist / tab / tabpanel
Toast:                    ✅ role=status + aria-live=polite

### Colour contrast (WCAG 1.4.3)
Body on bg:               ✅ 13.2:1
Body on surface:          ✅ 10.4:1
Placeholder:              ✅ 4.6:1 (fixed from 2.8:1)
Ghost button:             ✅ 4.7:1 (fixed from 2.4:1)
Semantic colours:         ✅ all pairs ≥ 4.5:1

### Interactive semantics
Label in Name (2.5.3):    ✅ visible text contained in every accessible name
Hover/focus content (1.4.13): ✅ dismissable + hoverable + persistent

### Zoom and reflow
320px width:              ✅ single column, no h-scroll
400% zoom:                ✅ reflows without clipping
Orientation (1.3.4):      ✅ no portrait/landscape lock

### Text spacing (WCAG 1.4.12)
User-override safe:       ✅ min-height used, no clipping

### Reduced motion
@media prefers-reduced:   ✅ tokens redefined to 0ms
JS animations gated:      ✅

### Touch targets
44×44 minimum:            ✅ / ⚠️ [N] icon buttons padded

### Automated tools
axe DevTools:             ✅ 0 critical, 0 serious
Lighthouse a11y:          ✅ 98 / 100
Pa11y:                    ✅ clean

### Manual walkthroughs
Keyboard only:            ✅ full purchase flow completed
Screen reader (NVDA):     ✅ page load + form + modal announced correctly

### Files changed
[List every file that was created or modified]
- src/templates/main.html — lang, skip link, landmarks, aria-current
- src/templates/checkout.html — form labels, aria-describedby errors
- public/css/app.css — focus-visible pattern, prefers-reduced-motion tokens
- public/js/modal.js — replaced manual trap with <dialog>.showModal()
- DESIGN.md — WCAG section appended
```

---

## DESIGN.md accessibility section

Append the following to `design/DESIGN.md` once the audit is complete:

```markdown
## Accessibility (WCAG 2.1 AA)

### Contrast ratios verified
- [pair]: [ratio]  ✅
(repeat for every audited pair)

### Focus ring
Token: --focus-ring
Value: [computed value]
Contrast against adjacent: [ratio] ✅

### Touch target minimum
[24×24 WCAG only / 44×44 mobile best-practice]

### Reduced motion
Duration tokens redefined to 0ms under prefers-reduced-motion.

### Automated tool baseline
axe: 0 critical, 0 serious   Lighthouse: 98/100   Pa11y: clean

### Screen reader coverage
NVDA / VoiceOver walkthroughs completed on [pages listed]

### Key decisions
- [date]: [decision] — [reason]
```

---

## Plan structure

Create `plan/a11y/PLAN.md` in the project:

```markdown
# Accessibility Plan — [Project Name]

**Outcome:** WCAG 2.1 Level AA compliance — page structure, keyboard navigation, focus
indicators, ARIA states, colour contrast, forms, zoom/reflow, reduced motion, touch targets.
Every finding fixed and verified via manual walkthrough + automated tools.

## Scope
- [ ] Phase 1: Discovery audit — current state documented, automated tools run
- [ ] Phase 2: Page structure and landmarks (CRITICAL)
- [ ] Phase 3: Keyboard navigation (CRITICAL)
- [ ] Phase 4: Focus indicators (CRITICAL)
- [ ] Phase 5: Images and non-text content (CRITICAL)
- [ ] Phase 6: Forms (CRITICAL)
- [ ] Phase 7: ARIA states and properties (HIGH)
- [ ] Phase 8: Colour contrast (HIGH)
- [ ] Phase 9: Interactive element semantics — incl. Label in Name (2.5.3) + Content on hover/focus (1.4.13) (HIGH)
- [ ] Phase 10: Live regions and dynamic content (MEDIUM)
- [ ] Phase 11: Tables (MEDIUM)
- [ ] Phase 12: Reduced motion (MEDIUM)
- [ ] Phase 13: Touch target sizes (MEDIUM)
- [ ] Phase 14: Heading hierarchy (MEDIUM)
- [ ] Phase 15: Zoom and reflow — incl. Orientation (1.3.4) (HIGH)
- [ ] Phase 16: Text spacing (HIGH)
- [ ] Phase 17: Time and motion limits (MEDIUM)
- [ ] Phase 18: Enhanced screen reader support (OPTIONAL)
- [ ] Phase 19: High contrast mode (OPTIONAL)
- [ ] Phase 20: Validation and handoff — walkthroughs + report

## Bugs
(none yet)

## Commits
(none yet)

## Status: Not Started
```

---

## Relationship to other tina4 skills

| Skill | Relationship |
|-------|-------------|
| **tina4-design** | Runs first. tina4-a11y reads DESIGN.md as its source of truth — focus ring token, contrast ratios, touch target minimum, motion personality. Never duplicate intake. |
| **tina4-developer-*** | Implements the template and stylesheet changes. tina4-a11y tells the developer what to add and where; the developer skill handles framework-specific wiring. |
| **tina4-seo** | Runs alongside for complete coverage. Overlap: alt text, semantic HTML, page titles, `<html lang>`. If both are running, do those items once in whichever runs first. tina4-a11y owns keyboard navigation, ARIA, focus, contrast, forms, zoom/reflow. |

## Avoid these defaults

- Do not add `aria-*` attributes as a substitute for semantic HTML — a `<button>` beats `<div role="button">`
- Do not add `tabindex="0"` to make a `<div>` focusable — use a `<button>` instead
- Do not use `title` attributes as tooltips or labels — they are inaccessible
- Do not use `outline: none` without a replacement focus indicator
- Do not rely on colour alone to convey meaning
- Do not implement custom modal focus traps when `<dialog>.showModal()` will do
- Do not run only the automated tools and call the audit done — they catch ~30–40% of issues
- Do not mark an item complete without a manual verification (keyboard walkthrough or screen reader test)
