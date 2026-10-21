# Zoom, reflow, motion and sensory

> Reference for the `tina4-a11y` skill: Phase 12 (reduced motion, MEDIUM), Phase 13 (touch target sizes, MEDIUM), Phase 15 (zoom and reflow, HIGH — including Orientation 1.3.4), Phase 16 (text spacing, HIGH), Phase 17 (time and motion limits, MEDIUM), Phase 18 (enhanced screen reader support, OPTIONAL) and Phase 19 (high contrast mode, OPTIONAL). Moved out of `SKILL.md` unchanged.

## Phase 12 — MEDIUM PRIORITY: Reduced motion (WCAG 2.3.3)

Users with vestibular disorders can be harmed by excessive animation. Every animation must respect `prefers-reduced-motion`.

### 12.1 Global CSS rule

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

If using CSS custom properties for durations (e.g. `--duration-base: 200ms`), redefining the duration tokens to `0ms` inside this media query is preferable — it keeps component code clean.

### 12.2 JavaScript-driven animation

For scroll-triggered reveals, parallax, auto-playing carousels:

```js
const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if (!prefersReduced) {
  // run the animation
}
```

### 12.3 Auto-playing carousels

Add a pause button and start paused when `prefers-reduced-motion` is set.

---

## Phase 13 — MEDIUM PRIORITY: Touch target sizes

WCAG 2.1 AA (SC 2.5.5 — AAA in 2.1, promoted to AA in WCAG 2.2 as SC 2.5.8) requires interactive targets of at least **24×24 CSS pixels**. The practical mobile minimum is **44×44px** — used by iOS Human Interface Guidelines and Material Design — and this audit holds elements to that target unless the developer explicitly opts to the WCAG-only 24×24 minimum.

1. Find every `<button>`, `<a>`, `<input>`, `<select>`, custom toggle, and icon button.
2. Check the computed height and width. A visually small element can meet the target with padding:

```css
.icon-button {
  min-width: 44px;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
```

3. Report every element below the chosen minimum and fix with padding rather than changing visual size.

---

## Phase 15 — HIGH PRIORITY: Zoom and reflow (WCAG 1.4.10)

Content must reflow without loss of information or functionality at 320 CSS pixel width (mobile) and up to 400% browser zoom.

1. Test every page at 320px viewport width — must be readable and usable without horizontal scrolling. Horizontal scroll is only permitted on individual wide elements (tables, code blocks, diagrams) inside their own `overflow-x: auto` container.
2. Test at 400% browser zoom on a 1280px viewport — content must reflow to a single column with no clipped text or overlapping elements.
3. Fixed-position headers or overlays that eat viewport space at zoom are a common failure — check they collapse or use dynamic sizing.

### 15.4 Orientation (WCAG 1.3.4, Level AA)

Content must not restrict its view and operation to a single display orientation (portrait or landscape) unless a specific orientation is essential (e.g. a piano app, a cheque-scanning frame).

- Check the CSS for orientation locks — `@media (orientation: portrait)` / `(orientation: landscape)` blocks that hide content or show a "please rotate your device" gate
- Check the PWA manifest — `"orientation": "portrait"` or `"landscape"` locks the installed app. Use `"any"` unless a lock is genuinely essential
- Both portrait and landscape must present the same content and functionality

---

## Phase 16 — HIGH PRIORITY: Text spacing (WCAG 1.4.12)

Users must be able to override text spacing without content being clipped or overlapping. Test with a browser extension or user CSS setting:

- `line-height: 1.5 * font-size`
- `letter-spacing: 0.12 * font-size`
- `word-spacing: 0.16 * font-size`
- Paragraph spacing: `2 * font-size`

Fix any component whose fixed `height` clips text under these settings — replace `height` with `min-height` and let content grow.

---

## Phase 17 — MEDIUM PRIORITY: Time and motion limits

### 17.1 Auto-updating content (WCAG 2.2.4)

Carousels, tickers, news feeds must have controls to pause, stop, or hide the update.

### 17.2 Session timeouts (WCAG 2.2.1)

If the site logs users out after inactivity, warn the user with at least 20 seconds to extend.

### 17.3 No flashing content (WCAG 2.3.1)

No content may flash more than three times per second. This includes attention-grabbing animations, video content (warn about photosensitive content when user-uploaded), and rapidly oscillating loading spinners.

---

## Phase 18 — OPTIONAL: Enhanced screen reader support

These go beyond AA compliance but meaningfully improve the screen reader experience.

### 18.1 Breadcrumbs

```html
<nav aria-label="Breadcrumb">
  <ol>
    <li><a href="/">Home</a></li>
    <li><a href="/products">Products</a></li>
    <li aria-current="page">Widget Pro</li>
  </ol>
</nav>
```

### 18.2 Pagination

Wrap in `<nav aria-label="Pagination">`. Mark current page with `aria-current="page"`. Disabled previous/next: `aria-disabled="true"` on `<a>` tags (or native `disabled` on `<button>`).

### 18.3 Status badges and chips

If a badge communicates status a sighted user reads visually (green "Active" badge), ensure the text label is present — not just the colour dot.

### 18.4 `aria-describedby` for complex fields

If a field has helper text beneath it, link it: `aria-describedby="helper-id"` on the input, `id="helper-id"` on the helper. Screen readers then announce helper text after the label.

### 18.5 PDF and document links

Indicate non-HTML file types in link text or with a visually hidden span:
```html
<a href="/report.pdf">
  Annual Report 2025
  <span class="sr-only">(PDF, opens in new tab)</span>
</a>
```

### 18.6 `target="_blank"`

Links that open a new tab must warn:
```html
<a href="https://example.com" target="_blank" rel="noopener noreferrer">
  Visit our partner site
  <span class="sr-only">(opens in new tab)</span>
</a>
```

---

## Phase 19 — OPTIONAL: High contrast mode (Forced Colors)

Windows High Contrast Mode (Forced Colors) overrides CSS colours with system colours. Components that rely entirely on `background-image`, `box-shadow`, or `filter` for their visual state become invisible.

1. Check every interactive state (focus ring, button hover, checkbox tick, toggle track) for reliance on colour that would be overridden.
2. Use `@media (forced-colors: active)` to restore meaningful indicators:

```css
@media (forced-colors: active) {
  .custom-checkbox::after {
    /* box-shadow is overridden in forced-colors — use border instead */
    border: 2px solid ButtonText;
  }
  :focus-visible {
    outline: 2px solid Highlight;
    outline-offset: 2px;
  }
}
```
