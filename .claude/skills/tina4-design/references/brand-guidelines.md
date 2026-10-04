# Phase 4 - Brand Guidelines

> Reference for the `tina4-design` skill: Phase 4 (`design/brand-guidelines.html`). Moved out of `SKILL.md` unchanged.

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
