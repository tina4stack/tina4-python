# Phase 6 - Handoff

> Reference for the `tina4-design` skill: Phase 6 (tina4-css mapping note and Design Summary template). Moved out of `SKILL.md` unchanged.

## Phase 6 — Handoff

When both deliverables are built:

1. Finalise `DESIGN.md` — fill any sections left as placeholders, complete the rationale log
2. Update `plan/design/PLAN.md` — tick all phases `[x]`, add commit or save entries under Commits, set `## Status: Complete`
3. Verify both files open correctly in a browser — confirm the theme toggle works, all components are interactive, the logo loads
4. **Favicon brief check** — confirm `DESIGN.md` has a complete `## Favicon Brief` section:
   - Icon mark described (or "none — designer to supply" noted)
   - Light and dark background + icon colours recorded
   - App name recorded
   - Square-safe mark availability noted
   - RFG package status: `pending` (tina4-seo generates the actual package — this skill's responsibility ends at the brief)
5. **Design-level SEO and accessibility readiness check.** These are design decisions — the items below confirm the design system is ready for a developer to implement correctly. The code-level audits are handled by tina4-seo and the accessibility prompt after implementation.

   **Accessibility (design decisions):**
   - [ ] `--focus-ring` token defined and used on every interactive component in ui-guide
   - [ ] Touch target minimum (44×44px) documented in the Spacing & Grid section of ui-guide
   - [ ] All contrast pairs verified and recorded in DESIGN.md with computed ratios
   - [ ] Colour is never the only indicator — every badge, alert, and status chip has a text label or icon alongside the colour
   - [ ] ARIA state patterns shown on all custom components in ui-guide (accordion, modal, tabs, toggle, progress)
   - [ ] `prefers-reduced-motion` block included in the animation token CSS

   **SEO-ready design:**
   - [ ] og:image: at least one page in ui-guide or website.html demonstrates a social share card at 1200×630px using real brand assets — this is the og:image template the developer generates from
   - [ ] `theme-color` values noted in DESIGN.md Favicon Brief (`--accent` light, `--bg` dark variant)
   - [ ] Page title format defined in DESIGN.md (recommended: `[Page name] — [Brand name]`)
   - [ ] Favicon brief complete (icon mark, colours, app name, RFG status)

   **Handoff pointers (record in DESIGN.md under `## Next Steps`):**
   - SEO/AISO implementation → run **tina4-seo** (reads this DESIGN.md as its source of truth)
   - WCAG 2.1 AA accessibility audit → use the **website-accessibility-prompt** in `plan/`

6. Report to the user with a ✅/❌ dashboard per deliverable

### tina4-css mapping note

All Tina4 backend apps (PHP, Python, Ruby, Node) ship with `tina4.min.css` — a Bootstrap-compatible CSS framework with class-based components. The ui-guide.html uses a CSS custom property token system; the developer implements those patterns using tina4-css classes in the actual app.

Include this mapping table in the closing report so the developer or AI developer agent knows exactly how to translate the design system into the framework:

| Design component | tina4-css classes | Notes |
|-----------------|-------------------|-------|
| Primary button | `btn btn-primary` | Colour override via theme |
| Secondary button | `btn btn-secondary` | |
| Destructive button | `btn btn-danger` | Use `--error` token for hover |
| Ghost button | `btn btn-outline-*` | |
| Form input | `form-control` inside `form-group` | |
| Form label | `form-label` | |
| Card | `card` > `card-header` / `card-body` / `card-footer` | |
| Alert / Banner | `alert alert-success/danger/warning/info` | Add `alert-dismissible` for close button |
| Badge | `badge badge-primary/danger/…` + `badge-pill` for rounded | |
| Table | `table table-striped table-hover` | Wrap in `overflow-x: auto` |
| Modal | `modal` > `modal-dialog` > `modal-content/header/body/footer` | Uses `data-t4-toggle="modal"` |
| Navbar | `navbar` > `navbar-brand` / `navbar-nav` / `nav-item` / `nav-link` | |
| Grid column | `col-12 col-md-6 col-lg-4` inside `row` inside `container` | |
| Shadow sm/md/lg | `.shadow-sm` / `.shadow` / `.shadow-lg` | |
| Responsive hide | `.d-none .d-md-block` | |

**Components not in tina4-css** (implement from ui-guide.html reference):
Drawer, Accordion, Stepper, Notification banner, Date picker, File upload, Quantity input, Toast (custom), Skeleton loaders, Empty states, Avatar, Progress bar, Tabs.

**Theme override approach:** to apply brand colours to tina4-css components, add a `theme.css` after `tina4.min.css` that redefines button backgrounds, border colours, and focus rings using the brand's `--accent` value. This keeps tina4-css intact and layers the brand on top. Do not modify `tina4.min.css` directly.

**Closing summary format — be specific, never vague.**

The closing report must contain real values, not descriptions. "A modern, clean palette" is not a deliverable summary. This is:

```
## Design Summary — [Project Name]

**Mode:** existing-brand / provisional (logo pending)

**Palette**
--accent:    #FAB033  Amber — derived from logo icon fill
--dark:      #292627  Charcoal — derived from logo wordmark
--bg:        #F4EFE6  Warm linen — warm neutral, not default grey
--success:   #2A7C4F  Forest green
--warning:   #8C5200  Burnt umber (amber brand → warning shifted to avoid clash)
--error:     #B03A2A  Brick red
--info:      #2A5C8F  Steel blue

**Contrast pairs verified**
--text-1 on --bg:       14.2:1  ✓
--text-2 on --bg:        8.1:1  ✓
--text-1 on --surface:  13.6:1  ✓
--accent text on --bg:   2.9:1  ✗ → --accent-accessible: #B07800 (4.6:1 ✓) flagged

**Typography**
Display: Oswald 700 — clamp(2.75rem, 2rem + 4vw, 5rem)
Body:    Source Sans 3 400/600 — clamp(0.9rem, 0.85rem + 0.25vw, 1rem)
Mono:    IBM Plex Mono 400

**Icon system**
Library: Tabler Icons (2px stroke)
Rationale: industrial/technical brand, heavier stroke weight matches Oswald's weight

**Favicon brief**
Icon mark: amber triangle (icon element from logo lockup) · Square-safe mark: yes
Light: bg #F4EFE6, icon #292627 · Dark: bg #292627, icon #FAB033
Format: SVG with dark-mode media query · App name: Elkanah Hardware
RFG package: pending — run tina4-seo

**Files**
brand-guidelines.html — [x] theme toggle works, [x] logo loads, [x] print stylesheet present
ui-guide.html         — [x] theme toggle works, [x] sidebar drawer works on mobile,
                           [x] all interactive components respond, [x] logo loads
website.html          — [x] all pages reachable, [x] theme toggle works, [x] logo loads,
                           [x] mobile nav works (if built)

**Provisional status** (if Path B)
Logo brief written to DESIGN.md — awaiting designer handoff
```

Call out any contrast fixes made to brand colours explicitly. Call out any logo variants that are missing. Never close with "everything looks great" — close with numbers.
