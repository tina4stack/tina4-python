---
name: tina4-design
description: Use whenever a project needs a visual identity or design system — from scratch or from an existing logo. Triggers: "build me a brand", "create brand guidelines", "we need a UI guide", "design system", "I have a logo", "what should our brand look like", "design our app", "brand this project". Covers the full chain — client intake → market research → design system decisions → brand guidelines document → interactive UI component guide. Produces DESIGN.md (the living design record), brand-guidelines.html, and ui-guide.html, all saved to a top-level design/ folder. Project-agnostic: works for any industry, any Tina4 backend or frontend, or no Tina4 project at all.
updated_for_version: 1.0.0
---

# Tina4 Design — brand identity and UI system from brief to deliverable

> 🤖🎨 **Skill-active marker.** Begin every reply with the 🤖🎨 emoji while this skill is guiding the session. Drop it only once the conversation has clearly moved off design into implementation.

You are the design lead for this project. Your job is not to decorate. Your job is to make deliberate, research-backed choices that give the project a coherent and appropriate visual identity, and a UI system developers can build from immediately. Every choice is named, reasoned, and recorded before a single line of HTML is written.

## When you fire

Trigger when the user needs to establish a visual identity or a design system, at any stage of a project's life:

- A new project with no visual identity yet: "we need a brand", "build a design system", "what should our app look like"
- An existing logo that needs a system built around it: "I have a logo, build out the guidelines"
- A project with no UI conventions: "we need a component library", "design the UI", "give me a style guide"
- Explicit design-phase phrasing: "brand guidelines", "UI guide", "design tokens", "tone of voice"

Do NOT fire when:
- The user is asking about a framework feature or a bug — that belongs to `tina4-developer-<lang>` or `tina4-maintainer`
- A `DESIGN.md` exists and the request is a minor tweak — answer inline, no new deliverables
- The user asks about deploying or structuring a project — that belongs to `tina4-architect`

If uncertain: ask one question — "Is this a fresh brand or do you have existing visual assets I should work from?"

## Incremental build rule — read this before writing any file

**Never generate an entire HTML file in a single response.** Both `brand-guidelines.html` and `ui-guide.html` are large files. Attempting to output either in one response will exceed the output token limit and crash the session.

The correct method is to build each file section by section using the Write and Edit tools:

1. **Write the file skeleton first** — `<!doctype html>`, `<head>` with `<style>` (CSS tokens and reset only), `<body>` opening tag, and the layout shell (topbar, sidebar, main). Save it. The file now exists on disk.
2. **Append one section at a time** — use the Edit tool to insert each content section (e.g. "Foundation — Colours") into the file before the closing `</body>`. Save after each section. Never hold more than one section in a single response.
3. **Confirm each save before continuing** — after each Edit, confirm the file was written, then move to the next section.
4. **CSS goes in the skeleton** — write the complete token system and component CSS in the initial skeleton write, not spread across section edits. This way the CSS is complete from the start and each section edit is HTML only.

This means a complete UI guide takes 10–15 sequential edits, not one giant output. That is correct and expected. Do not try to shortcut it by combining sections.

**Section order for `ui-guide.html`:**
1. Skeleton (head + CSS + layout shell)
2. Foundation — Icon System
3. Foundation — Design Tokens
4. Foundation — Typography
5. Foundation — Spacing & Grid
6. Foundation — Responsive & Mobile
7. Components — Buttons
8. Components — Form Elements
9. Components — Cards
10. Components — Badges + Alerts + Tooltips
11. Components — Navigation + Skeleton Loaders
12. Components — Progress + Empty States + Toast
13. Components — Avatars + Data Table
14. Components — Modal + Drawer
15. Components — Dropdown Menu + Accordion
16. Components — Stepper + Notification Banner
17. Components — Date Picker + File Upload + Quantity Input
18. Utilities section + closing `</body></html>`

**Section order for `brand-guidelines.html`:**
1. Skeleton (head + CSS + layout shell)
2. Cover + sticky nav
3. Our Story
4. Logo
5. Colour
6. Typography
7. Tone of Voice
8. Applications
9. Footer + closing `</body></html>`

---

## The design workflow

Six phases in order. Each phase has a defined output. No phase is skipped — if inputs are missing, surface that clearly and offer a best-effort path forward.

| Phase | Name | Output |
|-------|------|--------|
| 1 | Intake & Discovery | Written brief — everything known about the client |
| 2 | Market Research | Research summary in `DESIGN.md` |
| 3 | Design System Decisions | Token decisions locked in `DESIGN.md` |
| 4 | Brand Guidelines | `brand-guidelines.html` in `design/` |
| 5 | UI Guide | `ui-guide.html` in `design/` |
| 6 | Handoff | `DESIGN.md` finalised; files verified open in browser |

---

## Output location — everything this skill produces lives in `design/`

Every deliverable this skill creates goes in a single top-level `design/` folder at the project root — never loose in the project root, never spread across the project. Create the folder in Phase 3 (when `DESIGN.md` is first written) if it does not already exist.

```
design/
├── DESIGN.md              # the living design record — source of truth
├── brand-guidelines.html  # Phase 4 (optional per scope)
├── ui-guide.html          # Phase 5 (optional per scope)
├── website.html           # Phase 7 (optional)
└── favicons/              # if a favicon package is generated later by tina4-seo
```

**`design/DESIGN.md` is the canonical path.** Downstream skills — tina4-seo and the tina4-developer-* skills — read `design/DESIGN.md` as their source of truth. If a logo file is supplied, keep it in `design/` too (or the project's asset folder) and reference it with a path relative to the deliverable, e.g. `<img src="logo.svg">` when the logo sits beside the HTML in `design/`.

The **plan** file is the one exception — it stays at `plan/design/PLAN.md`, following the universal Tina4 plan-folder convention. Plans live in `plan/`; deliverables live in `design/`.

---

## Working reflexes

These run in the background on every design task. Fire them at the right moment.

- **🤖 Engaged.** Begin every reply with 🤖 while this skill is active; drop it only when the conversation clearly leaves design.
- **🔍 Research before you decide.** A colour choice without a market reason is a preference, not a decision. Before locking in a palette or typeface, look at the industry — what the competition does, what the audience expects, and what would make this brand stand out without alarming anyone. Use web search.
- **🎯 Specificity over templates.** A generic warm-serif-on-cream brand is a non-decision. If any element of the design could belong to a completely different client in a completely different industry without modification, reconsider it. Every element should be traceable back to something specific about THIS client, their industry, and their audience.
- **📐 Name the decision.** Every colour, typeface, and layout choice is recorded in `DESIGN.md` with a one-line rationale grounded in the research. "We chose Oswald because the client is in industrial hardware and the face's geometric weight echoes that" is a decision. "We chose Oswald because it looks strong" is not.
- **🧭 Value check.** Before building a section of a deliverable: does this add something the user can act on? A brand guideline with no clear rules for when to use each colour is noise. A UI guide that shows components without their states is decoration. If a section earns nothing, cut it.
- **📣 Show the work.** Don't describe the design — ship it. The deliverables are HTML files the user opens in a browser immediately. Real content, real mockups. No lorem ipsum. Data in the UI guide uses real content from the client's domain.
- **🛑 Don't invent assets.** If the client has a logo, use it as `<img src="[filename]">` — never inline the SVG paths into the HTML. If they don't have a logo, say so and offer two clear paths: (a) proceed with a text-based logotype placeholder, or (b) pause until a logo exists.
- **💩 Avoid AI-generated design defaults.** Before finalising the design plan, check it against the avoid-list at the bottom of this skill. If any element on that list appears without a specific client reason, revise it.
- **🙊 Don't ask what you don't need to ask.** If the brief already implies the audience, tone, and industry, proceed — asking a clarifying question that restates the brief back is wasted time. Ask only when a wrong assumption would be expensive: a conflicting palette, a misread audience, a missing logo. One focused question beats a wall of them.

---

## Phase 1 — Intake & Discovery

Gather five inputs before any design decision is made. If any are missing, ask for all missing ones in a single message — never one question at a time.

### 1.1 Logo file

Ask the user to drop a logo file into the working directory. Accepted formats: SVG (preferred — extract colour values from path data), PNG, JPG.

---

**PATH A — Logo supplied (preferred)**

- Read it immediately.
- If SVG: parse the fill and stroke values to extract exact hex colours. Note the geometry (geometric/organic/illustrative), weight (bold/light/outline), and any iconographic motif separate from the wordmark.
- Record all extracted values in `DESIGN.md` under `## Logo`.
- The brand palette MUST be derived FROM the logo colours. Never invent an accent colour that clashes with a supplied logo — `--accent` must be a colour present in the logo.
- **Check the live site.** A logo file is often just one mark in isolation. If a company name or URL is known, do a quick web search or visit the site — it will frequently reveal secondary or accent colours in use, an established typeface, and tone of voice that the logo alone doesn't carry. This takes two minutes and prevents building a palette that conflicts with the company's existing presence. Skip this only if the user explicitly provides everything or asks you not to.
- Note whether the file provides a light-background version only, or both light and dark variants. If only one exists, say so explicitly in `DESIGN.md` — never invent a dark variant that was never supplied.
- **Check for a square-safe icon mark.** A wordmark-only logo (text with no separate icon element) cannot be used as a favicon at 32×32px — it becomes an illegible smear. Note in `DESIGN.md` whether a standalone icon element exists in the supplied file. If not, add it to the Logo Brief (see Path B step 2 for the brief format): "An icon-only variant is required for favicon, app icon, and social avatar use." The designer must provide this before tina4-seo can generate a complete favicon package.
- Proceed to Phase 2.

---

**PATH B — No logo yet (provisional mode)**

The designer has not yet produced a logo. Work continues, but everything is marked provisional. When the real logo arrives, Phase 1 and Phase 3 are re-run to reconcile.

**Step 1 — Get a colour brief from the designer or developer.**
Ask for one short brief before proceeding — even a sentence is enough:
> "Describe the intended feel of the brand in colour terms. Examples: 'dark and industrial with an amber accent', 'clean and minimal, navy and white', 'warm earth tones, terracotta and sand'. This guides the provisional palette until the real logo arrives."

Do not invent the palette from the company name or industry alone. The brief must come from a person.

**Step 2 — Build a provisional system.**
- Use the brief to choose a provisional `--accent` and palette. Mark every colour as provisional in `DESIGN.md`.
- For the logo position in both HTML files, render a CSS logotype — the company name set in the display typeface at the brand accent colour, inside a simple bounding box. No icon, no mark. Label it clearly with a small `[provisional]` tag beneath it in `--text-caption` size.
- Add a visible warning banner at the top of both `brand-guidelines.html` and `ui-guide.html`:

```html
<div class="provisional-banner">
  ⚠ Provisional design — logo pending. Colours may change when the final logo is supplied.
</div>
```

Style it as a full-width amber bar (amber being universally readable as "caution", regardless of brand palette) with dark text, `position: sticky; top: 0; z-index: var(--z-topbar) + 1`.

- Record in `DESIGN.md` under `## Logo`:
  ```
  Status: PROVISIONAL — awaiting final logo from designer
  Brief supplied: "[the brief, verbatim]"
  Provisional accent: [hex]
  ```

- **Write a logo brief.** Alongside the provisional system, write a short paragraph in `DESIGN.md` under `## Logo Brief` that tells the designer what the eventual mark must respect given the palette and type already chosen. This is the handoff back to the designer. Cover:
  - What backgrounds the mark must work on (light, dark, brand accent)
  - Whether an icon-only lockup is needed (for favicons, app icons, social avatars)
  - The minimum size the mark must remain legible at
  - Whether a horizontal and stacked variant are both required
  - Any colour constraints imposed by the provisional palette (e.g. "the mark must work in a single flat colour for embroidery / print")

  Example:
  ```
  ## Logo Brief
  The mark must work on three backgrounds: white/near-white (primary), charcoal (#2A2627),
  and the brand amber (#FAB033). An icon-only variant is required for favicon (16×16) and
  app icon (512×512) use. Minimum legible size: 120px wide for the full lockup,
  24px for the icon alone. A horizontal lockup is the primary form; a stacked version
  is optional but useful for square social contexts.
  ```

**Step 3 — Logo reconciliation (when the logo arrives).**
When a logo file is dropped into the project folder, re-run Phase 1 and Phase 3:
1. Extract the real colours from the logo file.
2. Compare `--accent` (provisional) against the logo's actual accent colour.
3. If they match or are compatible (same hue family, close value): update `--accent` to the exact logo hex, swap the CSS logotype for `<img src="[filename]">`, remove the provisional banner, and update `DESIGN.md`.
4. If they conflict (different hue, clashing value): flag every token that will change, list the affected components, and ask the developer to confirm before applying. Show a before/after colour diff in `DESIGN.md`.
5. Mark `DESIGN.md` status as `FINAL` once reconciled.

### 1.1b Brand reconnaissance (runs as soon as the company name is known)

The moment a company name is provided — whether with a logo or without — run a brand reconnaissance pass before asking any further questions. This often surfaces information that makes most of the intake questions unnecessary.

**Step 1 — Web search**

Search for:
- `"[company name]" brand guidelines`
- `"[company name]" brand manual`
- `"[company name]" style guide`
- `"[company name]" site:official-domain.com` (to find the actual site)

If a publicly available brand manual or guidelines PDF is found, read it. Many companies publish these openly. A brand manual from the company itself outranks everything else — it supersedes any decisions the skill would otherwise make about colour, typography, and tone.

**Step 2 — Visit the live site and read the source**

If a website is found, visit it and extract the following — in this order of precision. Visual guessing is the last resort, not the first.

**Fonts — read the source, do not guess visually:**

1. Fetch the page source (`view-source:` or via the browser tool's page text)
2. Scan `<head>` for Google Fonts `<link>` tags — the URL contains the exact family name:
   `fonts.googleapis.com/css2?family=Inter:wght@400;600` → font is **Inter**
3. Scan `<head>` for `@import` rules in `<style>` tags loading font services
4. Scan `<link rel="stylesheet">` hrefs — if a stylesheet is linked, fetch it and search for `font-family:` declarations in `:root`, `body`, `h1`, `h2`, `p`, and any CSS custom property definitions
5. Search the page source for `font-family` — note every distinct family name found; the one on `body` or `:root` is the body face, the one on headings is the display face
6. If a font is served from a custom CDN or self-hosted (no Google Fonts link), look for `@font-face` declarations in the CSS — the `font-family:` name inside is the family name
7. **Only if none of the above yields a font name** — visually estimate the face category (geometric sans / humanist sans / transitional serif / slab serif) and note it as "visually estimated, not confirmed" in `DESIGN.md`

**Never record a font as confirmed if it was only visually identified.** Visual identification of a typeface is unreliable and has caused incorrect font choices in previous tests. Source-confirmed fonts are recorded as facts; visual estimates are flagged as uncertain.

**Colours — read the CSS, do not only screenshot:**

1. In the page source, look for `:root { --color-*` or `:root { --accent` or similar CSS custom property blocks — these are the exact brand tokens
2. Look for `background-color` and `color` on `body`, `header`, `nav`, `.btn` — note the hex or rgb values
3. Check for a `<meta name="theme-color">` tag — this often encodes the primary brand colour
4. Visual observation of dominant colours supplements but does not replace source extraction

**Tone of voice:** read two or three pages of copy and note the register: formal/casual, technical/accessible, warm/corporate.

**Secondary brand elements:** note any secondary colours, patterns, or textures visible in the design that aren't present in the logo.

**Step 2b — Attempt to fetch the logo**

While visiting the site, attempt to locate and fetch the logo file:
1. Look in the `<header>` for an `<img>` tag or an inline `<svg>` used as the logo
2. If an `<img src="...svg">` is found: fetch the SVG file, read its path data, and extract exact hex colours — same process as reading a locally supplied logo file
3. If an inline `<svg>` is found in the page source: read the fill and stroke values directly from the markup
4. If only a PNG or WebP is found: note the dominant colours visually — less precise than SVG parsing but still useful for palette direction

**Important constraints on the fetched logo:**
- Use it for **colour extraction only** during Phase 1 reconnaissance — the extracted colours feed into `DESIGN.md` and Phase 3 token decisions
- **Do not hotlink to the fetched URL** in `brand-guidelines.html` or `ui-guide.html` — external URLs are fragile and may change or go offline
- **Do not save or embed the fetched logo as inline SVG** in any deliverable — the `<img>` rule applies here too
- After reconnaissance, tell the user what was found and ask them to drop the proper logo file into the project folder before the deliverables are built: "I found and read your logo from [URL] for colour extraction. Please drop the master logo file into the project folder so I can reference it as `<img src="[filename]">` in the deliverables."
- If no logo can be found on the site, note it in the reconnaissance report and follow the standard Path A / Path B flow

**Step 3 — Report and confirm**

Report what was found before proceeding:

```
Brand reconnaissance complete for [Company Name]:

Site found: [URL]
Brand manual found: [URL or "none found"]

Colours detected:    #FAB033 (dominant), #292627 (dark), #F4EFE6 (background) — source: CSS :root tokens
Typefaces detected:  Oswald 700 (headings) — source: Google Fonts <link> tag confirmed
                     Source Sans 3 400/600 (body) — source: font-family on body element confirmed
                     [or: "No font source found in markup — visually estimated as geometric sans, unconfirmed"]
Tone detected:       Direct, trade-focused, no-frills

This matches / conflicts with the supplied logo [describe match or conflict].

Proceeding with these findings unless you'd like to correct anything.
```

Do not silently use what was found — always surface it so the user can confirm or override. A website may be outdated, a rebrand may be in progress, or the user may have more accurate information than the public site shows.

**Step 4 — Feed into Phase 2**

Everything found during reconnaissance goes directly into `DESIGN.md` under `## Market Research` as a starting point. The competitor research in Phase 2.1 builds on this — the company's own site and any brand manual are the baseline; competitors are researched relative to it.

If a full brand manual was found: Phase 2 market research is still run for competitor context, but the design decisions in Phase 3 are anchored to the manual rather than derived from scratch. Note this explicitly in `DESIGN.md`.

### 1.2 Company name and tagline

Ask for both. The tagline, when present, reveals the brand register:
- "Quality Fasteners Since 1993" → craft, longevity, trade trust
- "Disrupting the Future of Work" → VC ambition, early adopter audience
- "Simple Banking for Everyone" → accessibility, anti-complexity, consumer mass market

Let the language set the tone-of-voice direction before you name it.

### 1.3 About us / company overview

A paragraph or two. Key things to extract:
- Industry and sub-sector (the narrower the better — "retail" is not enough; "independent hardware distribution in Southern Africa" is)
- Founding story — family business? corporate spin-off? funded startup? The founding story shapes the warmth of the brand
- Geographic reach — local, national, regional, global — affects the register and cultural references
- Values or beliefs the brand should express, especially if stated by the client
- Repeated phrases or language the company uses — these often become the tone-of-voice anchors

### 1.4 Industry and target audience

Extract from the about-us if explicit. If not, ask. Identify:
- Primary industry and sub-sector
- Primary audience — who buys, who uses, who decides (they are often different people)
- Audience sophistication — a 60-year-old hardware store owner and a 28-year-old SaaS procurement lead need very different visual languages
- Any secondary audiences (trade vs consumer, B2B vs B2C)

### 1.5 Deliverable scope

At the end of intake — after all other inputs are gathered — ask one question:

> "What deliverables do you need? Default is Full if you don't answer.
>
> 1. **Full** — DESIGN.md + brand-guidelines.html + ui-guide.html
> 2. **UI only** — DESIGN.md + ui-guide.html
> 3. **Brand guidelines only** — DESIGN.md + brand-guidelines.html"

Record the choice in `DESIGN.md` under `## Scope` and skip the phases that don't apply:

| Choice | Phases to run |
|--------|--------------|
| Full (default) | 1 → 2 → 3 → 4 → 5 → 6 |
| UI only | 1 → 2 → 3 → 5 → 6 (skip Phase 4) |
| Brand guidelines only | 1 → 2 → 3 → 4 → 6 (skip Phase 5) |

If the user doesn't answer or says "just go", proceed with **Full**.

Update the plan scope checklist to reflect the chosen deliverables so the plan is accurate from the start.

### 1.6 Project outline (optional)

If this design will be applied to a specific product or app:
- What the product does
- The screens and surfaces the UI guide must cover — a marketing site, a B2B portal, and a consumer checkout flow have different component needs
- Any existing technical constraints on the front end

---

## Phase 2 — Market Research

Do not skip this phase. A well-chosen serif for a law firm and the same serif for a children's toymaker are opposite decisions. The research is what makes one defensible and the other wrong.

### 2.1 Competitor and sector landscape

Use web search to find 4–6 direct competitors or analogous brands in the same industry. For each, note:
- Primary colour palette (dominant hue, secondary, neutral ground)
- Typeface category (geometric sans, humanist sans, slab serif, transitional serif, display/expressive)
- Overall visual register: minimal / bold / warm / technical / playful / premium / utilitarian
- Industry-wide visual conventions — patterns that repeat across most brands in the sector (these exist in almost every mature industry)

Summarise with a single sentence:

> **"The [industry] sector leans [X]. This client should sit [Y] relative to that because [Z]."**

That sentence goes into `DESIGN.md` as the design thesis.

### 2.2 Colour direction

Research how colour functions in this specific sector. Don't apply generic colour psychology — apply sector-specific logic:

| Sector | Colour conventions and their meanings |
|--------|--------------------------------------|
| Hardware / industrial | Amber and yellow read as high-visibility and safety; dark charcoal reads as durability and precision; orange reads as trade and DIY |
| Fintech / banking | Deep navy and charcoal read as stability; bright accent reads as innovation; green reads as growth |
| Healthcare / wellness | White and light blue read as clinical trust; green reads as wellness and nature; earth tones read as holistic |
| Food & beverage | Warm reds and oranges read as appetite and energy; black and gold read as premium; green reads as fresh and natural |
| Legal / professional services | Navy, dark grey, and gold read as authority; serif faces read as establishment |
| Education / EdTech | Blue and purple read as knowledge and creativity; high contrast reads as clarity |
| SaaS / tech | Blues and purples dominate; clean sans-serif is expected; the differentiator is in the accent and the warmth of the neutral |
| Retail | Depends heavily on price-point: discount uses bold primaries and high contrast; premium uses restraint and white space |

State the specific palette direction with a sentence grounded in the sector research, not in preference.

### 2.3 Typography research

Research typeface choices in the sector. Identify:
- What typeface categories the sector's strongest brands use
- What following the category convention costs vs. gains (safety vs. sameness)
- Whether the client's brand personality is better served by a structural/geometric face, a humanist face, a serif, or something expressive

Choose **exactly two typefaces** at this phase:
- **Display / heading**: carries the brand's personality; used at large scale for section headers, hero text, product names; can afford more character
- **Body / UI**: carries information at reading size (14–16px); must be legible at small sizes, on screen and in print; usually a humanist sans or a clear geometric sans

**Rules:**
- Both must be available on Google Fonts. Verify before recommending — load the URL `https://fonts.googleapis.com/css2?family=[Name]` to confirm.
- Declare real fallback stacks: `'Oswald', 'Arial Narrow', sans-serif` — never leave the fallback as just `sans-serif`.
- Never recommend Inter or Space Grotesk as the default "safe" choice. If the sector genuinely calls for them, name the reason.
- The display and body faces must pair deliberately — they should have a clear personality difference that serves a purpose (authority vs. legibility, character vs. clarity).

### 2.4 Motion personality

Research what motion should feel like for this brand. This is separate from timing tokens — those say *how fast*; motion personality says *what it feels like*. A one-sentence motion statement goes into `DESIGN.md` alongside the design thesis and governs every animation decision in the UI guide.

Map the brand's personality to a motion signature:

| Brand personality | Motion signature | Avoid |
|------------------|-----------------|-------|
| Industrial / technical / trade | Functional, precise — enter/exit only, no spring, no overshoot. Motion confirms an action; it doesn't entertain. | Bounce, delayed cascades, anything decorative |
| Professional / B2B services | Composed, efficient — short durations, clean ease-out. Fast enough to feel snappy, slow enough to feel considered. | Springy easing, playful micro-interactions |
| Consumer / lifestyle | Warm, inviting — gentle spring on entrances, slight overshoot on interactive feedback. Motion adds personality. | Robotic linear timing, jarring cuts |
| Premium / luxury | Deliberate, unhurried — longer durations, silky ease-in-out. Never rushed. Each transition is a small ceremony. | Fast snaps, bouncy easing, too many simultaneous animations |
| SaaS / productivity tool | Fast and invisible — motion gets out of the way. Transitions are below 150ms where possible. | Long reveals, staggered cascades, anything that slows the workflow |

State the motion personality as one sentence: *"[Brand] motion is [adjective] — [rule]. [What to avoid]."*
Example: *"Elkanah motion is functional — transitions confirm state changes and nothing more. Never decorative."*

### 2.5 Research summary

Write a compact summary covering all five points above. Store it in `DESIGN.md` under `## Market Research`. This is the "why" behind every Phase 3 decision. When someone asks "why did we choose these colours?" or "why does the UI move like this?" the answer is in this section.

---

## Phase 3 — Design System Decisions

Record every decision in `DESIGN.md` before writing a single line of HTML. The `DESIGN.md` is the source of truth for all deliverables. If a Phase 4 or Phase 5 file and `DESIGN.md` disagree, `DESIGN.md` wins and the file is corrected.

### 3.1 Colour palette

**Brand palette — always defined**

| Role | CSS token | Purpose |
|------|-----------|---------|
| Primary accent | `--accent` | CTAs, interactive highlights, key UI states, logo accent echo |
| Accent hover | `--accent-hover` | Darkened accent for hover states (~10% darker) |
| Accent active | `--accent-active` | Further darkened for pressed / active states (~20% darker) |
| Accent tint | `--accent-tint` | Subtle accent-coloured background; selected rows, highlights |
| Primary dark | `--dark` | Main text on light; dark surface backgrounds, headers |
| Page background | `--bg` | The colour the user sees most; sets the emotional ground |
| Surface | `--surface` | Cards, panels, modals, input backgrounds |
| Surface 2 | `--surface-2` | Slightly elevated or inset surfaces; table striping; sidebar |
| Border | `--border` | Dividers, default input borders |
| Border strong | `--border-strong` | Focused input borders, active separators |
| Primary text | `--text-1` | Headings and high-emphasis body text |
| Secondary text | `--text-2` | Body copy, field labels, secondary labels |
| Tertiary text | `--text-3` | Captions, placeholders, metadata, disabled labels |

**Form-specific tokens — derive from palette, never invent**

| Role | CSS token | Light | Dark |
|------|-----------|-------|------|
| Label default | `--label-color` | Same as `--text-2` | Same as `--text-2` (dark) |
| Label focused | `--label-color-focused` | Same as `--accent` | Same as `--accent` (dark) |
| Label error | `--label-color-error` | Same as `--error` | Same as `--error` (dark) |
| Label disabled | `--label-color-disabled` | Same as `--text-3` | Same as `--text-3` (dark) |
| Input background | `--input-bg` | Usually `--surface` | Usually `--surface` (dark) |
| Input background disabled | `--input-bg-disabled` | `--surface-2` with reduced opacity | Same pattern |
| Input border | `--input-border` | Same as `--border` | Same as `--border` (dark) |
| Input border hover | `--input-border-hover` | Same as `--border-strong` | Same as `--border-strong` (dark) |
| Input border focused | `--input-border-focused` | Same as `--accent` | Same as `--accent` (dark) |
| Input border error | `--input-border-error` | Same as `--error` | Same as `--error` (dark) |
| Placeholder text | `--placeholder-color` | Same as `--text-3` | Same as `--text-3` (dark) |
| Helper text | `--helper-color` | Same as `--text-3` | Same as `--text-3` (dark) |
| Helper text error | `--helper-color-error` | Same as `--error` | Same as `--error` (dark) |

**Interaction tokens — universal across all components**

| Role | CSS token | Value |
|------|-----------|-------|
| Focus ring | `--focus-ring` | `0 0 0 3px var(--accent-tint), 0 0 0 1px var(--accent)` — box-shadow, not outline |
| Focus ring offset | `--focus-ring-offset` | 2px gap between element edge and ring |
| Disabled opacity | `--disabled-opacity` | 0.45 — applied to any disabled element; never hide, always reduce |
| Hover tint | `--hover-tint` | `rgba` of `--accent` at 6–8% opacity — used for row hovers, menu items |

**Palette rules:**
- If a logo was supplied: `--accent` must be derived from a colour in the logo. Never invent an accent colour that doesn't appear in or harmonise with the logo.
- `--bg` must be a warm neutral if the brand is warm; a cool neutral if the brand is cold. Never default to `#F5F5F5` without a reason — that is the un-chosen neutral.
- Avoid pure `#000000` and pure `#FFFFFF` for body text and backgrounds — use near-black and near-white with a slight hue bias toward the accent.
- Define dark-theme equivalents for every token. The dark theme is not the light theme inverted — it is designed independently to hold the same contrast and hierarchy relationships on a dark ground.
- Form tokens are derived from the brand palette — they are aliases, not new colours. Record the mapping explicitly in `DESIGN.md`.

### 3.2 Semantic colours (separate from brand palette)

Never use the brand accent for error, warning, or success states.

| Role | Token | Tint token | Hover token | Active token | Light | Dark |
|------|-------|-----------|-------------|--------------|-------|------|
| Success | `--success` | `--success-tint` | `--success-hover` | `--success-active` | A green that reads as confirmed / go | Lighter, higher contrast on dark ground |
| Warning | `--warning` | `--warning-tint` | `--warning-hover` | `--warning-active` | An amber-dark or orange-brown that reads as caution | Lighter warning on dark |
| Error | `--error` | `--error-tint` | `--error-hover` | `--error-active` | A red-brick that reads as stop / problem | Lighter red on dark |
| Info | `--info` | `--info-tint` | `--info-hover` | `--info-active` | A mid-blue that reads as neutral information | Lighter blue on dark |

Tint tokens are the semantic colour at ~10% opacity — used for alert backgrounds, badge fills, and highlighted rows. Define them explicitly rather than using `rgba()` inline.

**Hover and active tokens are required.** `--error-hover` is typically `--error` darkened ~10%; `--error-active` darkened ~20%. Never hardcode a hex value in a `:hover` or `:active` rule — always use the token. A `btn-destructive:hover` with a hardcoded `#9C1F10` instead of `var(--error-hover)` is a bug.

**Contrast check:** before locking colours, compute the actual WCAG contrast ratio for every text/background pair using the formula below — never eyeball it. Thresholds: 4.5:1 for normal body text, 3:1 for large text (≥ 18pt regular or ≥ 14pt bold) and UI components/icons.

```js
function linearize(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
function relativeLuminance({ r, g, b }) {
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}
function contrastRatio(rgb1, rgb2) {
  const [L1, L2] = [relativeLuminance(rgb1), relativeLuminance(rgb2)];
  const [lighter, darker] = L1 >= L2 ? [L1, L2] : [L2, L1];
  return ((lighter + 0.05) / (darker + 0.05)).toFixed(1) + ':1';
}
// Example: contrastRatio({r:41,g:38,b:39}, {r:244,g:239,b:230}) → "13.2:1"
```

Pairs to verify at minimum:
- `--text-1` on `--bg`
- `--text-2` on `--bg`
- `--text-1` on `--surface`
- Accent-coloured text on `--bg` (if accent is used for links or labels)
- Each semantic colour on its own tint background

Record each pair with its computed ratio in `DESIGN.md`. Mark each ✓ (pass) or ✗ (fail).

**Never quietly substitute a failing brand colour.** If a brand colour fails contrast in the role it needs to play, do not silently swap it for something that works. Instead: propose a darkened or lightened variant that still reads as that brand colour, name it (e.g. `--accent-accessible`), and flag the fix explicitly in `DESIGN.md` and in the brand guidelines colour section. An unannounced substitution is how a brand colour quietly disappears from a product without anyone noticing.

**Warning on warning:** if the brand accent is amber or orange (common in hardware, construction, energy), the warning colour must not be the same hue. Shift it — amber brand accent → warning becomes a burnt sienna or deep ochre.

### 3.3 Typography tokens — fluid scale with `clamp()`

All type sizes are defined as fluid values using `clamp()`. This eliminates breakpoint-driven font-size changes — one token value scales continuously from the minimum viewport to the maximum. No `@media` query is needed for font size.

**Formula:** `clamp(minSize, minSize + (maxSize - minSize) * ((100vw - 320px) / (1280px - 320px)), maxSize)`

Simplified to the two-anchor shorthand used in all tokens below. Viewport anchors: 320px minimum, 1280px maximum. Adjust if the project's real range differs.

For each of the two chosen faces, record:
- Google Fonts family name exactly as it appears in the font URL
- Weights to load (load only the weights in use — never `wght@100..900`)
- Roles and justification (one sentence, grounded in Phase 2)

**Type scale — all sizes are `clamp()` values:**

| Role | Token | Face | clamp() value | Weight | Tracking | Line height |
|------|-------|------|---------------|--------|----------|-------------|
| Display | `--text-display` | Display | `clamp(2.75rem, 2rem + 4vw, 5rem)` | Bold | −0.03em | 1.0 |
| H1 | `--text-h1` | Display | `clamp(2rem, 1.5rem + 2.5vw, 3.5rem)` | Bold | −0.02em | 1.1 |
| H2 | `--text-h2` | Display | `clamp(1.4rem, 1.1rem + 1.5vw, 2.25rem)` | SemiBold | −0.01em | 1.2 |
| H3 | `--text-h3` | Display | `clamp(1.05rem, 0.9rem + 0.75vw, 1.5rem)` | Medium | default | 1.3 |
| Overline / Label | `--text-overline` | Display | `clamp(0.65rem, 0.6rem + 0.25vw, 0.75rem)` | Medium | +0.1em, uppercase | 1.4 |
| Body Large | `--text-body-lg` | Body | `clamp(1.05rem, 1rem + 0.25vw, 1.15rem)` | Regular | default | 1.65 |
| Body | `--text-body` | Body | `clamp(0.9rem, 0.85rem + 0.25vw, 1rem)` | Regular | default | 1.6 |
| Caption | `--text-caption` | Body | `clamp(0.72rem, 0.7rem + 0.1vw, 0.8rem)` | Regular | +0.01em | 1.5 |
| Code / SKU | `--text-code` | Monospace | `clamp(0.75rem, 0.72rem + 0.15vw, 0.85rem)` | Regular | default | 1.6 |

**Applying the tokens in CSS:**
```css
h1 { font-size: var(--text-h1); font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; }
p  { font-size: var(--text-body); line-height: 1.6; max-width: 65ch; }
```

`max-width: 65ch` on body text keeps line length readable at all viewport widths without a breakpoint.

For code/SKU: use a monospace face (Google Fonts: Source Code Pro, JetBrains Mono, Fira Code, IBM Plex Mono). Load it as a third face only if code or identifiers are prominent in the UI. Otherwise use the browser's default monospace fallback (`font-family: ui-monospace, monospace`).

### 3.4 Spacing

Base-4 grid. Every token is a multiple of 4px. Name them by step — the name is the thing referenced in CSS, never the pixel value.

`--space-1: 4px` · `--space-2: 8px` · `--space-3: 12px` · `--space-4: 16px` · `--space-5: 20px` · `--space-6: 24px` · `--space-8: 32px` · `--space-10: 40px` · `--space-12: 48px` · `--space-16: 64px` · `--space-20: 80px` · `--space-24: 96px`

**`--space-5` must be defined.** It is used by buttons, card bodies, alerts, toast, and tab navigation. The scale must not jump from `--space-4` (16px) directly to `--space-6` (24px) — the missing 20px step causes those components to render with zero padding.

**Layout width tokens:**
- `--max-prose: 65ch` — maximum width for body text columns
- `--max-content: 720px` — comfortable reading container
- `--max-wide: 1200px` — full-width layout container

### 3.5 Border radius

Four named values. Match the radius choice to the brand personality — industrial/technical brands use smaller radii; consumer/friendly brands use larger ones. Decide once; apply consistently. Do not mix radii arbitrarily across components.

| Token | Value range | Typical use |
|-------|------------|-------------|
| `--radius-sm` | 2–4px | Tags, table chips, tight inline elements |
| `--radius-md` | 4–8px | Inputs, buttons, default component radius |
| `--radius-lg` | 10–16px | Cards, panels, modals, popovers |
| `--radius-full` | 999px | Pills, badges, avatars, toggle tracks |

### 3.6 Shadows

Three levels. Shadows must be hue-tinted — use a dark version of the brand's ground colour as the shadow base, never pure `rgba(0,0,0,…)`. A warm-ground brand gets a warm shadow; a cool-ground brand gets a cool shadow.

| Token | Use |
|-------|-----|
| `--shadow-sm` | Subtle lift; hover states; inline chip elevation |
| `--shadow-md` | Cards, dropdown menus, sticky elements |
| `--shadow-lg` | Modals, overlays, popovers |

**Dark mode shadows:** on a very dark ground, the warm-tint shadow loses impact and may actually increase rather than decrease legibility (a warm shadow on a warm dark ground is nearly invisible). Switching to pure `rgba(0,0,0,…)` in dark mode is an acceptable and common departure from the warm-tint rule — it increases contrast and is what most design systems do. Document the dark-mode shadow value explicitly in the token block rather than leaving it undefined.

### 3.7 Animation tokens

Define timing and easing once. Every transition in every component references these tokens — never hardcoded `200ms ease`. Wrapped in a `prefers-reduced-motion` block that sets all durations to `0ms`, eliminating animation for users who need it without touching component code.

| Token | Value | Use |
|-------|-------|-----|
| `--duration-fast` | 100ms | Micro-interactions: button press, checkbox tick, badge appear |
| `--duration-base` | 200ms | Default transition: hover state, border-color change, opacity |
| `--duration-slow` | 350ms | Larger movements: drawer slide, modal fade, panel expand |
| `--ease-out` | `cubic-bezier(0.2, 0, 0, 1)` | Entering elements — fast start, settled end |
| `--ease-in-out` | `cubic-bezier(0.4, 0, 0.2, 1)` | Transitioning elements — smooth both ends |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Playful entries — slight overshoot |

**Motion personality statement** (from Phase 2.4) governs easing choice:
- Functional/technical brand → use only `--ease-out` and `--ease-in-out`; never `--ease-spring`
- Consumer/lifestyle brand → `--ease-spring` is appropriate for entrances and interactive feedback
- Premium brand → bias toward `--duration-slow`; never `--duration-fast` for primary transitions

```css
/* Apply in the CSS reset, before any component rules */
@media (prefers-reduced-motion: reduce) {
  :root {
    --duration-fast: 0ms;
    --duration-base: 0ms;
    --duration-slow: 0ms;
  }
}

/* Usage in a component — never hardcode */
.btn { transition: background var(--duration-fast) var(--ease-out),
                   box-shadow var(--duration-base) var(--ease-out); }
```

### 3.8 Z-index scale

Never use a magic number for `z-index`. Every positioned component references this scale. Higher is in front.

| Token | Value | Use |
|-------|-------|-----|
| `--z-base` | 1 | Default stacking context for elevated cards |
| `--z-dropdown` | 100 | Dropdown menus, custom selects, datepickers |
| `--z-sticky` | 200 | Sticky table headers, sticky toolbars |
| `--z-topbar` | 300 | Fixed navigation bar |
| `--z-drawer` | 400 | Slide-out sidebars and mobile nav drawers |
| `--z-modal-backdrop` | 500 | Modal overlay backdrop |
| `--z-modal` | 600 | Modal dialog itself |
| `--z-toast` | 700 | Toast / snackbar notifications |
| `--z-tooltip` | 800 | Tooltips — must always be on top |

### 3.9 Icon system

Decide the icon library once in Phase 3. Record it in `DESIGN.md`. Every icon in every deliverable must come from this one library — never mix libraries.

**Choose the library based on brand personality:**

| Library | Weight | Personality fit | Integration |
|---------|--------|----------------|-------------|
| [Lucide](https://lucide.dev) | 1.5px stroke, clean | Modern SaaS, productivity, clean B2B | CDN script + `<i data-lucide="name">` → `lucide.createIcons()` |
| [Heroicons](https://heroicons.com) | 1.5px or 2px stroke, minimal | Professional services, enterprise, restrained consumer | npm package or copy individual SVG files; no CDN script |
| [Phosphor](https://phosphoricons.com) | Multiple weights, versatile | Consumer, lifestyle, playful B2B — use a single weight throughout | CDN script + `<ph-icon name="...">` web components |
| [Tabler](https://tabler.io/icons) | 2px stroke, technical | Industrial, technical, developer tools | CDN CSS sprite or npm; SVG sprite via `<use>` |
| [Feather](https://feathericons.com) | 2px stroke, ultra-clean | Minimal, premium, editorial | CDN script + `feather.replace()` |
| [Material Symbols](https://fonts.google.com/icons) | Variable weight/fill | Enterprise, Google-adjacent, flexible density | Google Fonts stylesheet + `<span class="material-symbols-outlined">` |
| [Font Awesome](https://fontawesome.com) | Multiple styles | General-purpose, widely recognized | CDN kit or npm; `<i class="fa-solid fa-...">` |

**Two contexts — two different rules:**

**In the UI guide deliverable (`ui-guide.html`):** icon examples are shown as inline `<svg>` elements with their paths written directly. This is correct for a self-contained HTML reference document — it keeps the file dependency-free and makes icons immediately visible without a CDN call or script execution.

**In the actual Tina4 project (templates, components, pages):** use the chosen library's standard integration method — the CDN script pattern, the npm package, or the CSS sprite. Never copy-paste SVG path data into every template. The library handles the icon rendering; you just reference the icon by name. Record the chosen integration method in `DESIGN.md` so the developer session knows exactly how to set it up.

**Universal rules (apply in both contexts):**
- Every icon uses `currentColor` for its stroke or fill — never a hardcoded hex. Icons inherit colour from the parent element's `color` property and automatically adapt to theme changes and disabled states.
- One stroke weight across the entire project — never mix 1.5px and 2px icons in the same product.
- `aria-hidden="true"` on every decorative icon.
- Icons that carry meaning without accompanying text get `role="img"` and `aria-label` on the parent element.
- `focusable="false"` on all inline SVG icons (prevents IE and older browsers from making SVGs keyboard-focusable).
- Never use `<img>` for icons that need colour adaptation via `currentColor`.

**Icon size tokens:**

| Token | Value | Use |
|-------|-------|-----|
| `--icon-xs` | 14px | Inline within caption text, dense table cells |
| `--icon-sm` | 16px | Inline within body text, small badges |
| `--icon-md` | 20px | Default — buttons, form inputs, navigation |
| `--icon-lg` | 24px | Section headers, standalone indicators |
| `--icon-xl` | 32px | Empty states, feature highlights |

**Usage pattern in the UI guide (inline SVG):**
```html
<!-- Decorative icon (has adjacent text label) -->
<svg width="20" height="20" aria-hidden="true" focusable="false" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none">
  <!-- icon paths from chosen library -->
</svg>

<!-- Meaningful icon (no adjacent label) -->
<button aria-label="Delete item">
  <svg width="20" height="20" aria-hidden="true" focusable="false" stroke="currentColor" stroke-width="1.5" fill="none">
    <!-- icon paths -->
  </svg>
</button>
```

**Usage pattern in production (example: Lucide via CDN):**
```html
<!-- In <head> -->
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>

<!-- In the template -->
<i data-lucide="trash-2" aria-hidden="true"></i>

<!-- Before </body> -->
<script>lucide.createIcons();</script>
```

### 3.10 Favicon brief

Record the favicon brief in `DESIGN.md` under `## Favicon Brief`. This is a design decision — the actual favicon package is generated later by tina4-seo, which reads this brief directly.

**What to record:**

| Field | What to write |
|-------|--------------|
| Icon mark | Describe the mark — which element of the logo becomes the favicon (the icon element, a monogram, an initial, a symbol). If no icon element exists, write "none — designer to supply square-safe mark before favicon generation". |
| Light background | Hex for the favicon background on light surfaces (`--bg` or `white` in most cases). |
| Dark background | Hex for the favicon background on dark surfaces (`--dark` or `--bg` dark variant). |
| Icon colour (light) | Hex for the mark itself on the light favicon. Usually `--accent` or `--dark`. |
| Icon colour (dark) | Hex for the mark itself on the dark favicon. Usually `--accent` or `white`. |
| Format preference | SVG with embedded `@media (prefers-color-scheme: dark)` — provides theme-aware behaviour from a single file with no JavaScript. PNG fallback for older browsers. |
| App name | Short display name used for PWA / home-screen icon labels (often the brand name without the legal suffix). |
| RFG package | `pending` until tina4-seo generates it; `complete` once the package is in place. |

**Example DESIGN.md entry:**

```markdown
## Favicon Brief

- Icon mark: The amber triangle icon element from the main logo (leftmost mark in the lockup)
- Light bg: #F4EFE6  (--bg light)  · Icon colour on light: #292627  (--dark)
- Dark bg:  #292627  (--dark)       · Icon colour on dark:  #FAB033  (--accent)
- Format preference: SVG with @media (prefers-color-scheme: dark) embedded; PNG + Apple touch icon fallback
- App name: Elkanah Hardware
- Square-safe mark supplied: yes (icon element is separable from wordmark)
- RFG package: pending — run tina4-seo to generate
```

**Path B — no logo yet:** the favicon brief is provisional. Record the provisional accent and background colours and note "icon mark not yet designed". The logo brief already asks the designer for a square-safe icon variant — reference it here.

---

## Phase 4 — Brand Guidelines (`brand-guidelines.html`)

Build `brand-guidelines.html` and save it to the `design/` folder. This is a self-contained, browser-ready reference document. No build step. No server. It opens directly in a browser.

### Required sections

**Cover**
- Logo as `<img src="[filename]">` at full display size
- Document title and company name
- Company tagline (if one exists)
- Version and date

**Sticky navigation strip**
- Anchor links to each section below
- Active state not required (this is a document, not an app)

**Our Story**
- 2–3 paragraphs drawn from the Phase 1 intake — distilled, not verbatim
- Key milestone facts presented as stat blocks (year + one-line description) — only real milestones, not invented structure
- A pull quote — one sentence from the company's own language that captures the brand in a single line

**Logo**
- Primary lockup demonstrated on: white/light background, dark background, and any additional approved backgrounds
- Icon-only version (if the logo has one) demonstrated the same way
- Clear space rule shown as a visual diagram: the logo with a dashed exclusion zone around it, with a note explaining what the zone is measured by (e.g. "equal to the height of the icon mark on all sides")
- Minimum size note
- Misuse examples — at minimum four: placed on an unapproved background; with opacity reduced; rotated or distorted; with a shadow, glow, or outline effect added. Each marked ✕ with a one-line rule.

**Colour**
- Full-bleed swatches for every palette colour — each swatch shows the colour at scale, with name, hex, and usage role
- A usage rules table: which colour goes where, and what each colour must never be used for

**Typography**
- Specimens of the display face at large scale and the body face at reading scale — using real content from the client's domain, never placeholder text
- The full type scale table with all roles, sizes, and weights
- A note on line-length (keep body text near 65 characters wide)

**Tone of Voice**
- 4 tone attributes, each with a short definition paragraph
- Do / don't copy pairs: two "write this / not this" examples using realistic content — the same information written in the right voice and the wrong voice

**Applications**
- At least 2–3 mockups showing the brand applied in contexts relevant to the client's actual world
- Build these as CSS mockups directly in the HTML — not placeholder grey rectangles
- Examples: product packaging, price label, trade document / letterhead, email footer, social card, vehicle livery, signage — choose what fits the client

### Technical rules for brand-guidelines.html

- Single self-contained HTML file — all CSS inline, no external JS, Google Fonts loaded via `<link>`
- Light and dark theme support: three-state CSS token pattern (`:root` defines the complete light palette; `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` redefines only the tokens; `:root[data-theme="dark"]` repeats the dark definitions so a manual toggle also wins)
- `body` must set an explicit `background` from a token — never transparent
- **Logo is ALWAYS embedded as `<img src="[filename]" alt="[Company]">` — no exceptions.**
- **Never paste SVG path data inline into the HTML.** It does not matter how short the SVG is. It does not matter if it seems convenient. The logo is always a separate file referenced with `<img>`. This rule applies everywhere in both deliverables — cover, sticky nav, topbar, application mockups, every instance.
- If you find yourself writing `<svg` for the logo, stop and replace it with `<img>`.
- Icon SVGs (search icons, chevrons, UI glyphs) are the only SVGs that may appear inline — and only because they are UI elements, not the logo.
- Never invent a logo variant that was not supplied. If the client has only a light-background logo, say so in the document and leave the dark-background logo position empty with a clear note: "Dark variant not supplied — contact designer." Do not fabricate a dark version by inverting colours or applying opacity.
- All colour decisions draw from CSS custom properties, never hardcoded hex in component rules
- Body must never scroll horizontally — wide content gets `overflow-x: auto` on its own container
- All heading text uses `text-wrap: balance`
- Focus states must be visible (`:focus-visible` outline using the accent colour)
- Ghost large section numerals (if used as a design element) are decorative only — `pointer-events: none; user-select: none`
- Include a `@media print` stylesheet block — see rules below

**`@media print` rules for brand-guidelines.html:**
```css
@media print {
  /* Hide interactive and navigational chrome */
  .sticky-nav, .theme-toggle, .back-to-top { display: none !important; }

  /* Force white background and black text — ink-saving and laser-safe */
  body { background: #fff !important; color: #000 !important; }

  /* Preserve brand colours in swatches — use -webkit-print-color-adjust */
  .swatch, .colour-block { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

  /* Show full URLs for links — a printed page can't be clicked */
  a[href]::after { content: " (" attr(href) ")"; font-size: 0.75em; color: #555; }
  a[href^="#"]::after { content: none; } /* Skip internal anchor links */

  /* Page breaks — major sections start on a new page */
  section { break-before: page; }
  section:first-of-type { break-before: auto; }

  /* Avoid orphaned headings at page bottom */
  h1, h2, h3 { break-after: avoid; }
  figure, table { break-inside: avoid; }

  /* Use print-safe font size */
  body { font-size: 11pt; line-height: 1.5; }

  /* Logo at a controlled print size */
  .cover-logo { max-width: 180pt; }
}
```

---

## Phase 5 — UI Guide (`ui-guide.html`)

Build `ui-guide.html` and save it to the `design/` folder. The UI guide is an **interactive** component library — every component demonstrates real hover, focus, active, and disabled states via CSS. It is not a screenshot gallery.

The guide serves two audiences simultaneously:
1. **A human developer** who opens it in a browser and sees how things look and behave
2. **A developer's AI agent** that reads the HTML/CSS source to replicate the same patterns in the actual application — token names, `clamp()` values, class patterns, and interaction behaviour are all directly copyable

Every decision made in Phase 3 must be visible and usable in this file. If a token exists in `DESIGN.md`, it appears in the guide.

### Required layout — responsive by design

The guide's own chrome must be responsive. A developer opening it on a phone or a narrow browser window should be able to use it. Eat your own cooking.

**Top bar (fixed, `z-index: var(--z-topbar)`)**
- Company logo as `<img>`, height 22px, left-aligned
- Title: "UI Guide" — visible on desktop, hidden on mobile (logo is enough)
- Theme toggle button: clicking sets `data-theme="dark"` / `data-theme="light"` on `:root`
- Hamburger menu button: visible only below 768px — opens/closes the sidebar drawer
- `padding-top: env(safe-area-inset-top)` — handles iOS notch and Dynamic Island

**Left sidebar (220px wide desktop, drawer on mobile)**
- On desktop (≥ 768px): sticky alongside main content, always visible
- On mobile (< 768px): hidden off-screen left by default (`transform: translateX(-100%)`); slides in when the hamburger is toggled (JS adds/removes `.open` class); a translucent backdrop covers the main content (`z-index: var(--z-drawer)` − 1); clicking the backdrop closes the drawer
- Section navigation links grouped by category: Foundation / Components
- Active state: `IntersectionObserver` watches each section, sets `.active` on the matching link when the section enters the viewport

**Main content**
- `margin-left: 220px` on desktop; full width on mobile with topbar offset
- Each section: eyebrow label (`--text-overline`), section title (`--text-h2`), optional description (`--text-body`), one or more demo boxes
- Demo boxes: `background: var(--surface)`, `border: 1px solid var(--border)`, `border-radius: var(--radius-lg)`, inner padding `var(--space-6)`
- Within a demo box: a small uppercase label above each group, then the live interactive component
- Demo boxes use `overflow-x: auto` so wide content (tables, code) never causes the page to scroll horizontally

### Utility classes included in the guide's CSS

These go in the guide's `<style>` block and serve as the reference implementation for developers. Include a "Utilities" section showing them.

```css
/* Screen-reader only — hides visually, stays accessible */
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}

/* Truncate text to one line */
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Visually hide an element but keep its space */
.invisible { visibility: hidden; }

/* Remove default list styling */
.list-none { list-style: none; padding: 0; margin: 0; }

/* Focus ring — applied to any element that needs keyboard focus indication */
.focus-ring:focus-visible { box-shadow: var(--focus-ring); outline: none; }
```

### Required sections

---

**Foundation — Icon System**

Show the icon library decision made in Phase 3.9 applied and documented:

- Library name, source URL, and the stroke weight in use — stated once at the top of this section so any developer knows exactly which library and variant to download
- Size scale demo: all five `--icon-*` tokens rendered as a live icon at each size, labelled with token name and pixel value
- Colour behaviour demo: one icon shown in four colours — `--text-1`, `--text-3`, `--accent`, and `--error` — all via `color` on the parent, with `currentColor` on the SVG. Shows that icons need no colour change themselves.
- `aria-hidden` vs `aria-label` demo: two side-by-side examples — a decorative icon next to a button label (hidden), and a standalone icon-only button (labelled) — with the HTML shown beneath each so the pattern is copyable
- Forbidden patterns shown explicitly: icon font markup (`<i class="fa-...">`) and an `<img>` tag used for an icon, each marked ✕ with a one-line reason

**Foundation — Design Tokens**

*Colour palette:*
- Grid of swatch cards — one per CSS custom property
- Each card: full-colour block (min 64px tall), token name in monospace, hex value, usage role
- Organised in groups: Brand palette / Form tokens / Semantic colours / Interaction tokens

*Contrast pairs table:*
- Show each text/background pair with its contrast ratio — pass (≥ 4.5:1 for body, ≥ 3:1 for large) marked ✓, fail marked ✗
- This table documents the accessibility decisions made in Phase 3

*Animation tokens:*
- A live demo row per duration token — a small coloured dot that animates across its container when clicked, so the developer sees `--duration-fast` vs `--duration-slow` directly

*Z-index scale:*
- A stacked-layers diagram showing the scale visually — each layer labelled with token name and value

*Border radius samples:*
- Four boxes each using a named radius token, labelled

*Shadow samples:*
- Three cards each casting the named shadow level, on a contrasting background

---

**Foundation — Typography**

Type scale table: every role rendered as live HTML text at its real size, weight, and face, with a metadata column showing `font-size: var(--token)` and the computed `clamp()` value. Use real content from the client's domain for each row — never "The quick brown fox".

Show the `clamp()` method explicitly:
```
--text-h1: clamp(2rem, 1.5rem + 2.5vw, 3.5rem)
           ↑ min    ↑ fluid midpoint       ↑ max
           320px viewport          1280px viewport
```

Include a line-length demo: a paragraph constrained to `max-width: 65ch` beside one without the constraint, so the developer sees the readability difference.

---

**Foundation — Spacing & Grid**

*Spacing scale:* horizontal bars proportional to each token, labelled with token name and pixel value. A vertical gap demo shows the same spacing as vertical rhythm between text blocks.

*12-column grid:* CSS grid diagram with labelled columns and gutter, showing how content slots into the grid at full and half width.

*Touch target note:* a labelled box showing the minimum 44×44px touch target, with the rule stated: "Every interactive element must be at least 44×44px on mobile — use `min-height: 44px; min-width: 44px` and `display: inline-flex; align-items: center; justify-content: center` on any control."

---

**Components — Buttons**

*Variants:*
- Primary: accent background, contrasting text
- Secondary: surface background, border, dark text
- Ghost: transparent, border on hover only
- Destructive: error colour background, white text
- Dark: `--dark` background, white text

*Sizes:* small (32px height), default (40px), large (48px)

*States — all real, all interactive:*
- Default
- Hover (CSS `:hover` — developer hovers directly)
- Focused: one button shown with `:focus-visible` ring permanently applied via a `.is-focused` class, so the focus ring is visible without keyboard navigation
- Loading: animated CSS spinner inside the button; a JS click handler toggles `.is-loading` on the button and re-enables it after 2s so the developer sees the transition
- Disabled: real `disabled` attribute — the button is actually inert

*Icon variants:*
- Icon + label (icon left of text)
- Icon-only square button (same padding on all sides, `aria-label` shown in the HTML)

*Touch compliance:* all button sizes meet the 44px minimum on their touch axis; the small button uses padding to reach it without changing visual height.

---

**Components — Form Elements**

**Field anatomy — show this first.** A labelled diagram of one complete field:
```
┌─ Label (--label-color) ─────────────────────────────────────────┐
│                                                                   │
│  ┌─ Input (--input-bg, --input-border) ────────────────────────┐ │
│  │  Placeholder (--placeholder-color)                          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Helper text (--helper-color)                                     │
└───────────────────────────────────────────────────────────────────┘
```

Every part of the field has a named token. The diagram shows the token name beside each element.

**Text input — all five states, side by side:**
- Default: placeholder text, `--input-border` border, `--label-color` label
- Hover: `--input-border-hover` border — CSS `:hover`, developer hovers directly
- Focused: `--input-border-focused` border + `--focus-ring` box-shadow + `--label-color-focused` label — CSS `:focus-within` on the field wrapper
- Error: `--input-border-error` border + `--helper-color-error` helper text + `--label-color-error` label — applied via `.has-error` class on the field wrapper
- Disabled: real `disabled` attribute on the input + `--input-bg-disabled` background + `opacity: var(--disabled-opacity)` on the wrapper

**Floating label pattern:** one field variant where the label starts inside the input and animates to the top on focus — implemented with CSS `:focus-within` and `:not(:placeholder-shown)` on the input, no JS.

**Textarea:** same five states, min-height 120px, `resize: vertical` only.

**Select / dropdown:** custom-styled — the native `<select>` has `appearance: none`; the chevron is a CSS `background-image` SVG data URI using `--text-2` as the icon colour. Same five states as text input.

**Search input:** text input with a search icon left-inset using CSS `padding-left` + `background-image`, and a clear button that appears when the input has a value (JS toggles visibility).

**Checkbox:** custom CSS — `<input type="checkbox">` visually hidden, replaced by a styled `<span>`. States: unchecked, checked (accent fill + white checkmark), indeterminate, focused (focus ring on the custom element), disabled. The checkmark is an inline SVG data URI in `background-image` — no icon font dependency.

**Radio:** same treatment as checkbox. Group of three options shown.

**Toggle switch:** clickable via JS — `.toggle input` drives a CSS `::before` pseudo-element track and `::after` thumb. `transition: transform var(--duration-base) var(--ease-out)` on the thumb. States: off, on (accent track), focused (focus ring on the label wrapper), disabled.

**Checkbox group and radio group:** show both as a labelled group with a `<fieldset>` + `<legend>` wrapper — this is the correct semantic structure and a developer should see it used.

---

**Components — Cards**

Three variants:
- **Basic:** title (`--text-h3`) + body paragraph + footer row with a badge and a ghost button. Hover: `--shadow-md` lifts the card, `transition: box-shadow var(--duration-base)`.
- **Stat card:** large number in display size (`--text-h1`, `font-variant-numeric: tabular-nums`) + label + optional trend indicator (up/down arrow in success/error colour). Used for KPI tiles.
- **Accent card:** 4px left border in `--accent`; suitable for featured items, callouts, key facts.

Cards use `min-width: 0` on flex/grid children to prevent overflow in constrained layouts.

---

**Components — Badges / Status Chips**

One row per semantic type: success, warning, error, info, neutral
One brand variant: accent colour (for "New", "Featured", "Sale")
Each badge: small coloured dot + uppercase label text in `--text-overline` size

Two sizes: default (inline) and large (standalone). Show both.

Pill variant: `border-radius: var(--radius-full)` — same tokens, just rounder.

---

**Components — Alerts / Banners**

All four semantic types: success, warning, error, info
Each: semantic icon (inline SVG), bold title, body sentence using real client content, optional dismiss button (×)
Background: the `--[type]-tint` token; left border: the `--[type]` token at full opacity

Inline variant (fits within content flow) and banner variant (full-width, sits below the topbar) — show both.

---

**Components — Tooltips**

CSS-only implementation — no JS. The trigger element has `position: relative`; the tooltip is a `::after` pseudo-element (or a child `[role="tooltip"]` span) that appears on `:hover` and `:focus-within`.

```css
[data-tip] { position: relative; }
[data-tip]::after {
  content: attr(data-tip);
  position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%);
  background: var(--dark); color: var(--bg); font-size: var(--text-caption);
  padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm);
  white-space: nowrap; pointer-events: none;
  opacity: 0; transition: opacity var(--duration-fast) var(--ease-out);
}
[data-tip]:hover::after, [data-tip]:focus-within::after { opacity: 1; }
```

Show four placement variants: top (default), bottom, left, right.

---

**Components — Navigation**

*Tab strip:* at least 4 tabs. Clicking makes it active (JS toggles `.active`). The active indicator is an `--accent`-coloured underline that transitions position using CSS `transition`. A tab panel below the strip shows the corresponding content.

*Breadcrumb:* 3-level example using the client's real content hierarchy. Separator is a CSS `::before` chevron, not an icon glyph. Last item: `aria-current="page"`, no link.

*Pagination:* previous / next buttons + page number chips. Current page: accent background. Disabled previous on page 1, disabled next on last page — real `disabled` or `.is-disabled` with `pointer-events: none`.

---

**Components — Skeleton Loaders**

Three skeleton variants matching the cards in the guide:
- Text block skeleton: grey bars at heading and body widths
- Card skeleton: a card-shaped block with animated shimmer
- Table row skeleton: three rows of column-width bars

Shimmer animation: CSS `@keyframes` linear gradient moving left-to-right, using `--surface-2` as base and a slightly lighter stripe. Wrapped in `@media (prefers-reduced-motion: reduce) { animation: none }`.

---

**Components — Progress / Loading**

*Progress bar (determinate):* a container div + inner fill div. Width set via `style="width: X%"`. Fill uses `--accent`. Animated fill transition: `transition: width var(--duration-slow) var(--ease-out)`. Show at 0%, 45%, and 100% states.

*Progress bar (indeterminate):* a full-width container with an animated fill that cycles left-to-right using `@keyframes`. Used when total progress is unknown.

*Spinner:* a CSS border-trick circle — `border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin var(--duration-slow) linear infinite`. Three sizes: sm (16px), md (24px), lg (40px).

---

**Components — Empty States**

The most-forgotten component. Show one complete empty state:
- Centred layout
- Illustrative icon or SVG (simple, outline-weight, `--text-3` colour)
- Heading: what's empty, using real client content
- Body: why it's empty and what to do about it
- Primary CTA button

---

**Components — Toast / Snackbar**

Fixed-position, bottom-right on desktop, bottom-full-width on mobile. A JS button triggers it; it auto-dismisses after 4s. States: success (green left border), error (red left border), neutral.

`position: fixed; bottom: var(--space-6); right: var(--space-6); z-index: var(--z-toast)`
On mobile: `right: var(--space-4); left: var(--space-4); bottom: calc(var(--space-6) + env(safe-area-inset-bottom))`.

---

**Components — Avatars**

Three sizes: sm (28px), md (40px), lg (56px). Two variants: image (`<img>` within a circle clip) and initials fallback (2-letter `<span>` on an accent or neutral background, coloured deterministically based on the name string). Show both variants at all three sizes.

---

**Components — Data Table**

At least 5 rows of real content from the client's domain.

Column types:
- Text identifier (name, SKU) — left-aligned
- Descriptive text — left-aligned
- Numeric (`font-variant-numeric: tabular-nums`) — right-aligned
- Badge / status chip — centre-aligned
- Action button (ghost or icon-only) — right-aligned

Features:
- Sticky header row (`position: sticky; top: 0`) with `--surface-2` background
- Row hover: `background: var(--hover-tint)`, `transition: background var(--duration-fast)`
- Sortable column headers: chevron icon that rotates on active sort (CSS transform), JS toggles sort direction
- `overflow-x: auto` on the table container — required; the table never causes page-level horizontal scroll
- Table footer: row count label left, previous / next pagination right

---

**Components — Modal / Dialog**

A centred overlay for focused tasks, confirmations, and forms that must interrupt the current flow.

**Pattern: styled `<dialog>` toggled by a `.open` class — NOT `.showModal()`.** This guide controls show/hide with a class and a separate backdrop element so the backdrop, animation, and stacking are fully author-controlled and work in every browser. That choice comes with three UA-stylesheet traps that MUST be handled or the modal silently breaks — see the CSS below.

Structure:
- Markup: a `<div class="modal-backdrop">` sibling followed by a `<dialog class="modal">`. The `.open` class is toggled on BOTH by JS.
- Backdrop: `position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: var(--z-modal-backdrop)` — blur optional (`backdrop-filter: blur(4px)`)
- Dialog: `position: fixed; inset: 0; margin: auto; max-width: 540px; width: calc(100% - var(--space-8)); max-height: 90vh; overflow-y: auto; background: var(--surface); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-modal); padding: var(--space-6)`
- Header: title (H3) + close button (×) right-aligned — `display: flex; justify-content: space-between; align-items: center`
- Body: scrollable content area; `overflow-y: auto; max-height: calc(90vh - 140px)` to keep header and footer visible
- Footer: `display: flex; gap: var(--space-3); justify-content: flex-end` — primary action right, cancel left

Show at minimum: a confirmation modal (title, message, Cancel + Confirm buttons) and a form modal (a short input form with a submit button).

**Required CSS — the three UA traps and their fixes:**
```css
/* TRAP 1: the UA stylesheet applies display:none to a <dialog> with no `open`
   attribute. Our JS toggles a CLASS, not the attribute, so the dialog stays
   display:none regardless of what the rest of our CSS says. Defeat the UA rule
   explicitly, then drive show/hide with visibility + pointer-events. */
dialog.modal {
  display: block;                 /* defeat UA display:none */
  visibility: hidden;             /* hidden but laid out */
  opacity: 0;
  pointer-events: none;
  border: none;                   /* UA gives <dialog> a default border */
  transition: opacity var(--duration-base) var(--ease-out),
              visibility 0s linear var(--duration-base); /* hide AFTER fade-out */
}
dialog.modal.open {
  visibility: visible;
  opacity: 1;
  pointer-events: auto;
  transition: opacity var(--duration-base) var(--ease-out),
              visibility 0s;      /* visible BEFORE fade-in */
}

/* TRAP 2: an invisible backdrop at opacity:0 still paints and still catches
   every click on the page. opacity alone does NOT remove an element from the
   paint or event chain. Gate it with pointer-events. */
.modal-backdrop {
  opacity: 0;
  pointer-events: none;           /* never blocks clicks while closed */
  transition: opacity var(--duration-base) var(--ease-out);
}
.modal-backdrop.open {
  opacity: 1;
  pointer-events: auto;
}
```

**Required JS:**
```js
function openModal(dialog, backdrop) {
  dialog.classList.add('open');
  backdrop.classList.add('open');
  document.body.style.overflow = 'hidden';                 // scroll lock
  dialog.querySelector('button, [href], input, select, textarea')?.focus();
  // TRAP 3: the backdrop needs its OWN click handler — the dialog element
  // never receives a click that lands on the backdrop. {once:true} self-removes
  // so reopening wires up cleanly.
  backdrop.addEventListener('click', () => closeModal(dialog, backdrop), { once: true });
}
function closeModal(dialog, backdrop) {
  dialog.classList.remove('open');
  backdrop.classList.remove('open');
  document.body.style.overflow = '';
}
// Escape closes — NOT automatic without showModal(), so wire it explicitly.
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('dialog.modal.open')
    .forEach(d => closeModal(d, d.previousElementSibling));
});
```

Behaviour:
- Open/close via the `.open` class on both dialog and backdrop (see JS above)
- Close on backdrop click: the `{once:true}` listener added in `openModal`
- Close on Escape: explicit `keydown` handler (the automatic Escape only exists when a dialog is opened with `.showModal()`, which this pattern does not use)
- Focus trap: first focusable element inside modal receives focus on open
- Body scroll lock when modal is open: `document.body.style.overflow = 'hidden'`
- `aria-labelledby` pointing to the dialog title

> **Rule — never hide an interactive overlay with `opacity` alone.** `opacity:0` leaves the element in the paint and event chain: it still catches clicks and, on a `<dialog>`, still sits under the UA `display:none` trap. Use `visibility` + `pointer-events` for show/hide, and when styling a `<dialog>` as a component (not via `.showModal()`) always override the UA `display:none` with an explicit `display`. This applies to the drawer, dropdown menu, and any other overlay in this guide.

---

**Components — Drawer / Slide-over**

A panel that slides in from the right (or left) — used for detail views, settings, and complex filters that don't need a full page. Same `.open`-class + gated-backdrop pattern as the modal (see the overlay rule in the Modal section).

Structure:
- Markup: a `<div class="drawer-backdrop">` sibling followed by an `<aside class="drawer">` (or `<div role="dialog" aria-modal="true">`). JS toggles `.open` on both.
- Backdrop: same as the modal backdrop — `pointer-events` gated by `.open`, `z-index: var(--z-drawer)`
- Panel: `position: fixed; top: 0; right: 0; height: 100%; width: 400px; max-width: 90vw; background: var(--surface); box-shadow: var(--shadow-lg); z-index: calc(var(--z-drawer) + 1); padding: var(--space-6); overflow-y: auto`
- Header: title + close button, same pattern as modal
- Panel slides in with `transform: translateX(100%)` → `translateX(0)` transition, `var(--duration-slow) var(--ease-out)`

**Required CSS — the off-screen-but-focusable trap:**
```css
/* A panel parked off-screen with transform:translateX(100%) is still VISIBLE
   to the accessibility tree and still in the tab order — a keyboard user can
   Tab into a "closed" drawer's controls, and a screen reader still reads them.
   transform alone does not close an overlay. Gate it with visibility. */
.drawer-backdrop {
  opacity: 0;
  pointer-events: none;                 /* never blocks clicks while closed */
  transition: opacity var(--duration-slow) var(--ease-out);
}
.drawer-backdrop.open { opacity: 1; pointer-events: auto; }

.drawer {
  transform: translateX(100%);
  visibility: hidden;                   /* removes it from paint AND tab order */
  transition: transform var(--duration-slow) var(--ease-out),
              visibility 0s linear var(--duration-slow); /* hide AFTER slide-out */
}
.drawer.open {
  transform: translateX(0);
  visibility: visible;
  transition: transform var(--duration-slow) var(--ease-out),
              visibility 0s;            /* visible BEFORE slide-in */
}
```

The JS is the modal's `openModal` / `closeModal` pattern verbatim — toggle `.open` on panel and backdrop, scroll-lock the body, focus the first control on open, add the `{once:true}` backdrop click listener, and close on Escape. On close, also return focus to the element that opened the drawer.

Show: a detail drawer (title + a list of details + action buttons at the bottom) and a filter drawer (form fields + Apply / Reset buttons).

On mobile (< 640px), draw from the bottom instead: `bottom: 0; left: 0; right: 0; width: 100%; height: 85vh; border-radius: var(--radius-lg) var(--radius-lg) 0 0` — and the closed transform becomes `translateY(100%)`.

---

**Components — Dropdown Menu**

A contextual menu that opens below a trigger button — used for actions, navigation, and selection lists.

Structure:
- Trigger: a button (often icon-only with `aria-haspopup="menu"` and `aria-expanded`)
- Menu: `position: absolute; top: calc(100% + var(--space-1)); left: 0; min-width: 160px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); box-shadow: var(--shadow-md); z-index: var(--z-dropdown); padding: var(--space-1) 0`
- Item: `padding: var(--space-2) var(--space-4); cursor: pointer; display: flex; align-items: center; gap: var(--space-2)` — hover uses `--hover-tint`
- Divider: `<hr>` with `margin: var(--space-1) 0; border-color: var(--border)`
- Destructive item: `color: var(--error)`

**Required CSS — closed state removes items from the tab order:**
```css
/* A menu hidden with opacity:0 alone still catches clicks AND keeps every
   menu item in the tab order — a keyboard user tabs through invisible items.
   For a menu, display:none is the correct closed state: it removes the items
   from paint, from clicks, and from the tab order in one declaration. */
.dropdown-menu { display: none; }
.dropdown-menu.open { display: block; }
```
If the menu must animate (fade/scale in), use `visibility: hidden` + `pointer-events: none` + `opacity: 0` in the closed state instead of `display:none` (an element cannot transition out of `display:none`), and add `[hidden]`-style `inert` or move focus out on close so the invisible items are not tabbable mid-animation.

Show at minimum: an "Actions" dropdown with 4–5 items including one divider and one destructive item.

Behaviour:
- Toggle `.open` on the menu; keep `aria-expanded` on the trigger in sync (`true` when open, `false` when closed) — the visual state and the ARIA state must never disagree
- Opens below the trigger (flip to above if insufficient space below, handled via JS measuring `getBoundingClientRect()`)
- Closes on outside click (`document.addEventListener('click', ...)` with `!menu.contains(e.target) && e.target !== trigger`)
- Closes on Escape key, and returns focus to the trigger
- Arrow-key navigation between items (`role="menu"`, `role="menuitem"`)

---

**Components — Accordion / Disclosure**

Vertically stacked panels that expand and collapse — used for FAQs, settings groups, and any long-form content that benefits from progressive disclosure.

Structure:
- Container: `border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden`
- Item: each item is a `<div>` with a header (`<button>`) and a collapsible body
- Header button: `width: 100%; display: flex; justify-content: space-between; align-items: center; padding: var(--space-4) var(--space-5); background: var(--surface); border: none; cursor: pointer; font-weight: 600` — chevron icon rotates 180° when open
- Body: `padding: 0 var(--space-5) var(--space-4); overflow: hidden`
- Between items: `border-top: 1px solid var(--border)`

Show: 4 accordion items with real content. At least one open by default.

Behaviour:
- Height animates open/close: `max-height: 0` → measured `scrollHeight` using JS; `transition: max-height var(--duration-slow) var(--ease-out)`
- Allow multiple open (default) OR single-open mode — show both variations or document the toggle
- `aria-expanded` on the trigger button, `aria-controls` pointing to the body, body has matching `id`
- Each header button has `id` so the body can reference it with `aria-labelledby`

---

**Components — Stepper / Multi-step form**

A horizontal or vertical step indicator showing position within a multi-step flow — used for onboarding, checkout, and complex form wizards.

Structure:
- Stepper bar: `display: flex; align-items: center; gap: 0` — steps connected by a horizontal line
- Step node: `width: 32px; height: 32px; border-radius: var(--radius-full); display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: var(--text-caption); flex-shrink: 0`
  - Completed: `background: var(--success); color: white` — show a checkmark icon instead of number
  - Active: `background: var(--accent); color: white`
  - Upcoming: `background: var(--surface-2); color: var(--text-2); border: 2px solid var(--border)`
- Connector line: `flex: 1; height: 2px; background: var(--border)` — turns `var(--success)` when the step to its left is complete
- Label: below each node, `font-size: var(--text-caption); text-align: center; margin-top: var(--space-1)`
- Below the stepper bar: the active step's form content
- Below the form: navigation buttons — Back (ghost) and Next (primary), or Submit on the last step

Show a 4-step example with step 1 complete, step 2 active, steps 3 and 4 upcoming. Include realistic form fields in the active step panel.

---

**Components — Notification Banner**

A full-width, persistent banner anchored to the top of the page — distinct from Toast (transient) and Alert (inline). Used for system-wide announcements, scheduled downtime, cookie consent, or persistent action prompts that must not be dismissed mid-task.

Structure:
- `position: sticky; top: 0; z-index: calc(var(--z-topbar) - 1)` — sits just below the topbar, or above it for maximum-priority messages
- `width: 100%; padding: var(--space-3) var(--space-5); display: flex; align-items: center; gap: var(--space-4)`
- Left: icon + message text
- Right: optional action link and close button (`×`)
- Variants: info (`--info` background tint), warning (`--warning-tint`), error (`--error-tint`), success (`--success-tint`)

Show all four variants stacked. Each variant uses the matching semantic tint as background and the semantic colour for the icon and border-left accent stripe.

---

**Components — Date / Time Picker**

A calendar-based input for selecting a date or date-range. Show a well-styled input trigger and a dropdown calendar panel.

Structure:
- Trigger: a standard text input with a calendar icon button on the right — `display: flex; align-items: center; border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3)`
- Calendar panel: `position: absolute; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-md); padding: var(--space-4); z-index: var(--z-dropdown); width: 280px`
- Panel header: previous month button ← / month-year label / next month button →
- Day grid: 7 columns (Mon–Sun headers), days as buttons
  - Today: `border: 2px solid var(--accent)`
  - Selected: `background: var(--accent); color: white; border-radius: var(--radius-full)`
  - Hover: `background: var(--hover-tint)`
  - Days outside the current month: `color: var(--text-3); opacity: 0.4`
- Time input row (for datetime picker): hour : minute select elements below the grid

**Note:** for production use, a full-featured date picker almost always warrants a library (Flatpickr, Pikaday, Day.js calendar). The UI guide shows the visual design and component structure — the developer replaces the vanilla JS stub with the chosen library integration, styled to match the token system.

---

**Components — File Upload / Dropzone**

An accessible file input with a drag-and-drop target zone.

Structure:
- Dropzone: `border: 2px dashed var(--border); border-radius: var(--radius-lg); padding: var(--space-12) var(--space-8); display: flex; flex-direction: column; align-items: center; gap: var(--space-3); cursor: pointer; text-align: center`
  - Upload icon (large, `--icon-xl`)
  - Primary text: "Drag files here or click to browse"
  - Secondary text: accepted file types and max size (`font-size: var(--text-caption); color: var(--text-2)`)
- Hidden `<input type="file">` — triggered by clicking the zone
- Active (drag-over) state: `border-color: var(--accent); background: var(--accent-tint)` — updated via `dragenter` / `dragleave` JS events
- Uploaded file list: below the dropzone, each file shown as a row with filename, size, and a remove (×) button

Show: the empty dropzone, the drag-over state (highlight), and a populated state with 2–3 dummy file entries already listed.

---

**Components — Quantity Input**

A numeric stepper control for incrementing and decrementing a count — used in e-commerce, inventory management, and any form with a numeric quantity field.

Structure:
- `display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden`
- Decrement button: `width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; background: var(--surface-2); cursor: pointer; border: none; color: var(--text-1)` — minus icon
- Input: `width: 48px; text-align: center; border: none; border-left: 1px solid var(--border); border-right: 1px solid var(--border); padding: var(--space-2) 0; font-size: var(--text-body); -moz-appearance: textfield` (remove spinner arrows)
- Increment button: same as decrement — plus icon
- Disabled state (at min/max): decrement or increment button uses `opacity: var(--disabled-opacity); cursor: not-allowed; pointer-events: none`

Show: a default state, a disabled-decrement state (value = minimum), a disabled-increment state (value = maximum). Include a label above the control (e.g. "Quantity").

---

**Foundation — Responsive & Mobile**

A dedicated documentation section explaining the responsiveness baked into the UI guide. This makes breakpoints, touch rules, and mobile patterns visible to human developers and AI developer agents reading the guide.

Content to include:

**Breakpoints table:**
| Name | Breakpoint | Changes |
|------|-----------|---------|
| Mobile | `< 640px` | Single-column layout, full-width components, bottom-sheet drawers, stacked navigation |
| Tablet | `640px – 767px` | Two-column grid where appropriate, navigation adjusts |
| Desktop | `≥ 768px` | Sidebar visible, multi-column grid, all desktop patterns active |

**Layout behaviour:**
- Sidebar (220px) is visible on ≥ 768px; off-canvas drawer triggered by hamburger menu on < 768px
- Hamburger icon: `min-width: 44px; min-height: 44px` — touch target rule applies
- Topbar padding: `padding: 0 var(--space-4); padding-top: env(safe-area-inset-top)` — accounts for iOS notch
- Main content: `margin-left: 220px` on desktop, full-width on mobile

**Touch target rule:**
Every interactive element — button, link, icon button, checkbox, radio, dropdown trigger — must be at minimum `44 × 44px` as a clickable/tappable target. This is enforced with `min-height: 44px; min-width: 44px` in the base button and form element CSS. Smaller visual elements (icon-only buttons) use `padding` to expand the hit area without changing the visual size.

**Component mobile behaviour:**
| Component | Mobile adaptation |
|-----------|-----------------|
| Modal | Full-screen on mobile (`width: 100%; height: 100%; border-radius: 0; max-height: 100%`) |
| Drawer | Slides from bottom, 85vh height, rounded top corners |
| Data table | Horizontal scroll (`overflow-x: auto`) inside its container |
| Stepper | Collapses to icon-only nodes (no labels) below 480px |
| Toast | Full-width, pinned to bottom with `env(safe-area-inset-bottom)` gap |
| Dropdown menu | Full-width on narrow screens: `width: 100%; left: 0` |

**CSS pattern used throughout this guide:**
```css
/* Mobile-first: default styles apply to mobile */
.sidebar { display: none; }

/* Tablet+ */
@media (min-width: 640px) { }

/* Desktop */
@media (min-width: 768px) {
  .sidebar { display: block; width: 220px; }
  .main { margin-left: 220px; }
}
```

---

### Technical rules for ui-guide.html

**Structure**
- Single self-contained HTML file — all CSS inline in `<style>`, Google Fonts via `<link>`, no external JS libraries
- All `<style>` at the top of `<head>`, before any content — never inline `style=""` attributes for token-derived values
- `<script>` deferred or at end of `<body>` — no blocking JS

**Responsiveness — the guide itself is responsive**
- Sidebar: 220px fixed on ≥ 768px, off-canvas drawer on < 768px
- Hamburger: visible only on < 768px, positioned in the topbar; JS toggles `.open` on the sidebar and a backdrop overlay
- Main content: full width on mobile, `margin-left: 220px` on desktop — a single CSS custom property `--sidebar-w` controls both
- All demo boxes: `overflow-x: auto` so wide content never causes page-level horizontal scroll
- Topbar: `padding: 0 var(--space-4); padding-top: env(safe-area-inset-top)` — iOS-safe
- Toast: bottom-full-width on mobile, bottom-right on desktop
- Never use `px` widths for layout containers inside demo boxes — use `%`, `ch`, or `fr`

**Typography**
- All `font-size` values come from `--text-*` tokens using `clamp()` — never hardcoded `px` for any text
- `text-wrap: balance` on all headings
- `max-width: var(--max-prose)` on all body paragraphs

**Theming**
- Three-state token pattern: `:root` (light), `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`, `:root[data-theme="dark"]`
- Theme toggle JS: one line — `document.documentElement.dataset.theme = current === 'dark' ? 'light' : 'dark'`
- Every colour value in every component rule comes from a CSS custom property — never a hardcoded hex

**Accessibility**
- `:focus-visible` ring on every interactive element — use `box-shadow: var(--focus-ring)` + `outline: none`, never `outline: none` alone
- `outline: none` without a replacement focus indicator is forbidden — every element the keyboard can reach must show the focus ring
- Every icon button has `aria-label`
- Every image has `alt` — or `alt=""` if purely decorative
- Every form input has an associated `<label>` (via `for`/`id` or wrapping label element) — never `placeholder` as the only label
- Every `<fieldset>` of checkboxes or radios has a `<legend>`
- Colour is never the only carrier of information — every badge, alert, and status also has a text label or icon
- `aria-live="polite"` on toast container so screen readers announce new toasts
- `.sr-only` utility class defined in the CSS — shown in the Utilities section

**Animation**
- All transitions reference `--duration-*` and `--ease-*` tokens — never hardcoded `200ms ease`
- `@media (prefers-reduced-motion: reduce)` sets all duration tokens to `0ms` in `:root` — component code needs no changes

**Logo and assets**
- **Logo is ALWAYS `<img src="[filename]" alt="[Company]">` — never inline SVG paths, never paste `<svg>` markup for the logo, not even once, not even for convenience.** Icon SVGs (UI glyphs, chevrons, search icons) may be inline — the logo may not.
- All icon SVGs are inline in the HTML as `<svg>` elements (they are UI icons, not the logo) — kept small (< 24×24 viewBox, single path)

**Code quality**
- `font-variant-numeric: tabular-nums` on all numeric columns and stat tiles
- `min-width: 0` on all flex/grid children that contain text — prevents overflow
- `min-height: 44px; min-width: 44px` on all interactive controls — touch compliance
- No JavaScript library dependencies — all interactivity is vanilla JS under 100 lines total

---

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

---

## Phase 7 — Website (`website.html`) — Optional

Build a multi-page website as a single self-contained HTML file, saved to the `design/` folder. This phase is optional — only build it when the user explicitly asks for it, or when the chosen mode includes it (see Mode selection at the top of Phase 1).

### Purpose

The website mockup is a high-fidelity, browser-ready reference that shows what the actual product website looks like — not a component library, not a brand reference, but real pages with real content. Any Tina4 developer skill (Python, PHP, Ruby, Node) reads it and implements from it. It is framework-agnostic by design.

### Discovery — do this before writing a single line of HTML

Answer these four questions from the Phase 1 intake and Phase 2 research. Record answers in `DESIGN.md` under `## Website` before building:

1. **What is this site's single job?** (convert visitors to sign-ups / inform / demonstrate capability / direct to the product / showcase work)
2. **What is the visitor's first question when they land?** (What is this? / Can I afford it? / Is this for me? / How does it work?)
3. **What is the one action we want them to take?** (Sign up / Contact / Download / Buy / Read more)
4. **What type of content dominates?** (Narrative story / Feature comparison / Social proof / Exploration / Utility)

These four answers determine the layout archetype. Choose one:

| Archetype | When to use | Layout character |
|-----------|------------|-----------------|
| **Editorial** | Narrative brand, story-first, portfolio | Large type, wide imagery, generous whitespace, reading flow |
| **Product-led** | SaaS, app, tool — demo is the pitch | Hero with live demo/screenshot, feature grid, pricing anchor |
| **Marketplace** | Two-sided, discovery, listings | Search/browse prominent, trust signals, role-based messaging |
| **Storytelling** | Founder brand, mission-driven, social impact | Scroll-driven reveal, timeline, human imagery, pull quotes |
| **Utility** | Dev tool, API, technical service | Dense, scannable, code-forward, minimal decoration |

**The layout archetype is not the same as the brand personality.** A brand can be warm and friendly and still need a Utility archetype because it's a dev tool. Choose the archetype from the site's job, not from how the brand feels.

### Page set

Derive the page set from the discovery answers — do not use a fixed template. Common sets:

| Site type | Typical pages |
|-----------|--------------|
| SaaS / app | Home · Features · Pricing · About · Contact |
| Marketplace | Home · How it works · For [role A] · For [role B] · Contact |
| Services / agency | Home · Services · Work/Portfolio · About · Contact |
| Product / e-commerce | Home · Products · About · Contact |
| Portfolio | Home · Work · About · Contact |
| Documentation product | Home · Features · Docs (link) · Pricing · Contact |

Never produce a page just to fill the set. A page with nothing real to say is not included. Document the chosen pages and the reason for each in `DESIGN.md`.

### Single-file multi-page architecture

All pages live in one `website.html` file. Each page is a `<section class="page" id="page-[name]">`. A small JS router (~25 lines) reads the URL hash and shows only the active page. The browser back button works. The nav highlights the current page. No server is needed — open the file directly in a browser.

```html
<!-- Page container pattern -->
<section class="page" id="page-home" aria-label="Home">
  <!-- page content -->
</section>
<section class="page" id="page-about" aria-label="About" hidden>
  <!-- page content -->
</section>
```

```js
/* Router — place before </body> */
function route() {
  const id = location.hash.replace('#', '') || 'page-home';
  document.querySelectorAll('.page').forEach(p => {
    p.hidden = p.id !== id;
  });
  document.querySelectorAll('[data-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.page === id);
  });
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);
route();
```

Nav links use `href="#page-about"` and `data-page="page-about"`. No library. No build step.

### Layout rules — fight the generic default

The biggest risk is producing the same page every time: centered hero text, three feature cards, CTA strip, footer. This is the AI default and it is forbidden. The layout archetype chosen above must be visible in the structure of every page.

**Anti-patterns to avoid:**
- Centered hero text with a gradient or illustration blob — unless the archetype explicitly calls for it
- Three equal-width cards as the first section after the hero
- A "Why choose us?" section with icon + heading + one-line text
- A CTA strip with a heading and one button, full-width background
- A generic grid of logos for "Trusted by"

**Each page must be designed from its content job, not from a page template.** Ask: what is this page trying to do, and what layout serves that job?

### CSS and token rules

- **All CSS is shared** — defined once in `<style>` in `<head>`, used across all pages
- **Every colour comes from a CSS custom property** — the full token set from Phase 3 is re-declared here (copy from `ui-guide.html`'s `:root` block)
- **Three-state dark mode** — same pattern as brand-guidelines and ui-guide: `:root` (light), `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`, `:root[data-theme="dark"]`
- **Theme toggle** in the nav — same single-line JS as the ui-guide
- **All type sizes** from `--text-*` tokens using `clamp()` — never hardcoded `px`
- **All spacing** from `--space-*` tokens — including `--space-5: 20px`
- **No external CSS frameworks** — no Tailwind, no Bootstrap, no utility-class libraries
- **Google Fonts** via `<link>` in `<head>` — same faces defined in Phase 3

### Required elements on every page

**Shared topbar (identical across all pages):**
- Logo: `<img src="[logo-file]" alt="[Company]">` — never inline SVG for the logo
- Nav links — `data-page` attributes drive the router's active state
- Theme toggle button (moon/sun icon)
- Primary CTA button (the site's main action)
- Hamburger for mobile (`< 768px`)

**Shared footer:**
- Logo (small variant) + tagline
- Site links grouped by category
- Legal line: copyright + privacy + terms

**Page transitions:**
- Fade: `.page { animation: pageFade var(--duration-base) var(--ease-out); }` — applied when a page becomes visible
- Scroll position reset to 0 on every route change (already in the router above)

### Incremental build order for `website.html`

Build section by section using Write then Edit — never try to produce the entire file in one output:

1. Skeleton — `<head>` with full CSS (token system, layout, all component styles needed for the pages) + router JS + shared topbar + shared footer + all `<section class="page">` shells (empty)
2. Home page content
3. Second page content
4. Third page content
5. (Continue for each page in the set)
6. Final pass — verify nav links, theme toggle, mobile hamburger, all route transitions

### Quality checklist before calling Phase 7 done

- [ ] All pages reachable via nav — browser back/forward works
- [ ] Theme toggle works across all pages
- [ ] Logo loads (`<img>` tag, not inline SVG)
- [ ] Mobile hamburger opens/closes the nav drawer on `< 768px`
- [ ] Every touch target ≥ 44×44px
- [ ] No hardcoded hex values in any CSS rule — all tokens
- [ ] No layout anti-patterns from the list above
- [ ] Discovery answers documented in `DESIGN.md` under `## Website`
- [ ] Chosen archetype and page-set rationale recorded in `DESIGN.md`

---

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
