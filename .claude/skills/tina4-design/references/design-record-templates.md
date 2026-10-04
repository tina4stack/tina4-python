# Design Record Templates and Guards

> Reference for the `tina4-design` skill: the plan structure, the `DESIGN.md` template, "Avoid these defaults" and the handoff note to tina4-developer. Moved out of `SKILL.md` unchanged.

## Plan structure

Create `plan/design/PLAN.md` in the project. If `plan/` doesn't exist, create it.

```markdown
# Design Plan — [Project Name]

**Outcome:** A complete visual identity and UI system recorded in design/DESIGN.md and shipped as design/brand-guidelines.html and design/ui-guide.html.

## Scope
- [ ] Phase 1: Intake complete — logo, name, about us, industry, project outline gathered
- [ ] Phase 2: Market research complete — sector landscape, colour direction, typography choice recorded in DESIGN.md
- [ ] Phase 3: Design tokens decided — palette, form tokens, semantic colours, fluid type scale, spacing, radius, shadows, animation, z-index locked in DESIGN.md
- [ ] Phase 4: brand-guidelines.html built and saved to design/
- [ ] Phase 5: ui-guide.html built and saved to design/
- [ ] Phase 6: DESIGN.md finalised; both files verified open correctly in browser
- [ ] Phase 7: website.html built and saved to design/ (optional — skip if not requested)

## Bugs
(none yet)

## Commits
(none yet)

## Status: Not Started
```

---

## DESIGN.md template

Create this file at `design/DESIGN.md` when Phase 3 begins (create the `design/` folder if it does not exist). Fill it as you work through each phase. This is the living record — if anything changes, update it here first.

```markdown
# DESIGN.md — [Project Name]

## Project
[One sentence: what the company does and who it serves]

## Logo
- File: [filename, or "none — text logotype placeholder"]
- Colours extracted: [hex values parsed from the logo file]
- Mark type: [icon + wordmark / wordmark only / icon only]
- Geometry: [geometric / organic / illustrative / typographic]
- Weight: [bold / medium / light / outline]
- Iconographic motif: [describe the icon element if present]
- Square-safe icon mark: [yes — icon element separable from wordmark / no — wordmark only, designer to supply]

## Favicon Brief
- Icon mark: [describe the element used as the favicon — icon glyph, monogram, initial, symbol; or "none — designer to supply square-safe mark"]
- Light background: [hex]  ·  Icon colour on light: [hex]
- Dark background: [hex]   ·  Icon colour on dark: [hex]
- Format preference: SVG with @media (prefers-color-scheme: dark) embedded; PNG + Apple touch icon fallback
- App name: [short brand name for PWA / home-screen label]
- RFG package: pending — run tina4-seo to generate

## Market Research

### Sector overview
[2–3 sentences: what industry, what sub-sector, who the client serves]

### Competitor landscape
| Brand | Palette category | Typeface category | Visual register |
|-------|-----------------|-------------------|----------------|
| | | | |
| | | | |
| | | | |
| | | | |

### Industry visual conventions
[What the sector expects — what following the convention buys, what breaking it costs]

### Design thesis
[The one-sentence direction: "The [sector] leans [X]. This client should sit [Y] relative to that because [Z]."]

### Motion personality
[One sentence: what the UI motion feels like and what it avoids. E.g. "Motion is functional — transitions confirm state changes only. No decorative animation."]

### Colour direction
[Why this palette — grounded in the sector research, not in preference]

### Typography direction
[Why these specific faces — grounded in the sector research]

### Icon system
- Library: [name + URL]
- Stroke weight in use: [1.5px / 2px]
- Size tokens: --icon-xs 14px · --icon-sm 16px · --icon-md 20px · --icon-lg 24px · --icon-xl 32px
- Rationale: [one sentence — why this library fits the brand personality]

## Design Tokens

### Colour — light theme
| Token | Hex | Role |
|-------|-----|------|
| --accent | | Primary action, highlights, logo accent echo |
| --accent-hover | | Darkened accent for hover states |
| --accent-active | | Further darkened for pressed states |
| --accent-tint | | Subtle accent background (~10% opacity) |
| --dark | | Primary text and dark surfaces |
| --bg | | Page background |
| --surface | | Cards, panels, inputs |
| --surface-2 | | Secondary surfaces, table rows, sidebars |
| --border | | Dividers, input borders |
| --text-2 | | Body copy, labels |
| --text-3 | | Captions, placeholders, metadata |

### Colour — dark theme
| Token | Hex | Notes |
|-------|-----|-------|
| --bg | | |
| --surface | | |
| --surface-2 | | |
| --border | | |
| --text-2 | | |
| --text-3 | | |

### Semantic colours
| Role | Token | Light hex | Dark hex |
|------|-------|-----------|---------|
| Success | --success | | |
| Warning | --warning | | |
| Error | --error | | |
| Info | --info | | |

### Typography
| Role | Token | Family | Weight(s) | clamp() value | Notes |
|------|-------|--------|-----------|---------------|-------|
| Display | --text-display | | | | |
| H1 | --text-h1 | | | | |
| H2 | --text-h2 | | | | |
| H3 | --text-h3 | | | | |
| Overline | --text-overline | | | | Uppercase, +0.1em tracking |
| Body Large | --text-body-lg | | | | |
| Body | --text-body | | | | |
| Caption | --text-caption | | | | |
| Code / Mono | --text-code | | | | |

Viewport anchors: min 320px · max 1280px

### Form tokens (aliases — map each to a palette token)
| Token | Alias of |
|-------|---------|
| --label-color | --text-2 |
| --label-color-focused | --accent |
| --label-color-error | --error |
| --label-color-disabled | --text-3 |
| --input-bg | --surface |
| --input-bg-disabled | --surface-2 |
| --input-border | --border |
| --input-border-hover | --border-strong |
| --input-border-focused | --accent |
| --input-border-error | --error |
| --placeholder-color | --text-3 |
| --helper-color | --text-3 |
| --helper-color-error | --error |

### Interaction tokens
| Token | Value |
|-------|-------|
| --focus-ring | |
| --focus-ring-offset | 2px |
| --disabled-opacity | 0.45 |
| --hover-tint | |

### Animation tokens
| Token | Value |
|-------|-------|
| --duration-fast | 100ms |
| --duration-base | 200ms |
| --duration-slow | 350ms |
| --ease-out | cubic-bezier(0.2, 0, 0, 1) |
| --ease-in-out | cubic-bezier(0.4, 0, 0.2, 1) |

### Z-index scale
base: 1 · dropdown: 100 · sticky: 200 · topbar: 300 · drawer: 400 · modal-backdrop: 500 · modal: 600 · toast: 700 · tooltip: 800

### Spacing scale
4 · 8 · 12 · 16 · 24 · 32 · 40 · 48 · 64 · 80 · 96 px

### Layout width tokens
--max-prose: 65ch · --max-content: 720px · --max-wide: 1200px

### Border radius
sm: [px] · md: [px] · lg: [px] · full: 999px

### Shadows (hue-tinted — not pure black)
sm: [value]
md: [value]
lg: [value]

### Contrast pairs (verified)
| Text token | Background token | Ratio | Pass? |
|-----------|-----------------|-------|-------|
| --text-1 | --bg | | |
| --text-2 | --bg | | |
| --text-1 | --surface | | |
| --accent (on light text) | --accent | | |

## Next Steps
- SEO/AISO implementation: run tina4-seo (reads this file as its source of truth)
- WCAG 2.1 AA audit: use website-accessibility-prompt in plan/
- Developer implementation: read design/ui-guide.html and design/brand-guidelines.html as the spec

## Rationale log
[One entry per significant design decision — what, why, date]
- [date]: [decision] — [reason grounded in research]
```

---

## Avoid these defaults

Before finalising the design plan in Phase 3, check each element against this list. If any appears without a specific client reason recorded in `DESIGN.md`, revise it.

| Pattern to avoid | The problem |
|-----------------|-------------|
| Warm cream (`#F4F1EA`) background + serif display + terracotta accent | The default AI "artisan brand" — indistinguishable from thousands of other outputs |
| Near-black background + single neon accent (acid green, electric blue, hot pink) | The default AI "tech brand" — reads as generated, not considered |
| Inter or Space Grotesk as the heading face by default | Overused to the point of invisibility; fine if the sector genuinely calls for it, but name the reason |
| Purple-to-blue gradient hero on white | The default AI "SaaS brand" |
| Emoji as section markers (📌 🔑 ✨ as decorative bullets) | Reads as generated; use typographic hierarchy instead |
| Everything centre-aligned | Centred layout reads as a lack of structural decision |
| `border-radius: 12px` on every element | Rounds everything equally regardless of component personality |
| Pure `rgba(0,0,0,…)` shadows on a warm-toned brand | Shadows should be hue-tinted to match the palette |
| Lorem ipsum or "Sample Text" in any deliverable | Real content or nothing; lorem is a placeholder for something that was never finished |

Following these patterns with a genuine reason is always acceptable — the point is that the reason must be named.

---

## Handoff note to tina4-developer

When this skill's work is complete, `design/DESIGN.md` contains the complete token system. Any Tina4 developer skill picking up the implementation should:

1. Read `design/DESIGN.md` — the palette, typefaces, and spacing are already decided
2. Load the Google Fonts declared there in any templates
3. Apply the CSS custom properties as a `:root` block in the project's global stylesheet or in Frond's base template
4. Use `design/brand-guidelines.html` and `design/ui-guide.html` as the living reference — not as files to edit, but as files to match in the actual application UI

The UI guide's components are the specification. The application's components should implement the same states, the same token references, and the same interaction behaviour.
