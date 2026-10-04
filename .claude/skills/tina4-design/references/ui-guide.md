# Phase 5 - UI Guide

> Reference for the `tina4-design` skill: Phase 5 (`design/ui-guide.html`). Moved out of `SKILL.md` unchanged.

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
