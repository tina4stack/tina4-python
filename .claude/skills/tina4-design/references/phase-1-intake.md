# Phase 1 - Intake and Discovery

> Reference for the `tina4-design` skill: Phase 1 (intake, brand reconnaissance, scope). Moved out of `SKILL.md` unchanged.

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
