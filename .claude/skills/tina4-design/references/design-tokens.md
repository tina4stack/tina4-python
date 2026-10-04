# Phase 3 - Design Tokens

> Reference for the `tina4-design` skill: Phase 3 (design system decisions, including the Favicon Brief). Moved out of `SKILL.md` unchanged.

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
