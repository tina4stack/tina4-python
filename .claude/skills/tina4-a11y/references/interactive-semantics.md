# Interactive element semantics

> Reference for the `tina4-a11y` skill: Phase 9 (interactive element semantics, HIGH — including Label in Name 2.5.3 and Content on hover/focus 1.4.13). Moved out of `SKILL.md` unchanged.

## Phase 9 — HIGH PRIORITY: Interactive element semantics

### 9.1 Buttons vs links

- `<a>` (link): navigates to a URL. Must have `href`. If it has no `href`, it is not a link — change to `<button>`.
- `<button>`: performs an action (submit, open modal, toggle menu). Does not navigate.
- Find every `<a>` used for actions (`href="javascript:void(0)"`, `href="#"`, `onclick`) and replace with `<button>`.
- Find every `<div>` or `<span>` used as a button and replace with a native `<button>`.

### 9.2 Icon-only buttons

Every button that shows only an icon and no visible text must have `aria-label`:

```html
<button aria-label="Close menu">
  <svg aria-hidden="true" focusable="false">...</svg>
</button>
```

### 9.3 Link purpose

Every `<a>` must make sense out of context. "Click here", "Read more", and "Learn more" are not accessible — the link text or its `aria-label` must describe the destination.

For "Read more" links in card lists, use `aria-label` to add context:
```html
<a href="/post/1" aria-label="Read more about Cape Brew Co case study">Read more</a>
```

### 9.4 The `title` attribute is not an accessible label

`title` shows a browser tooltip on hover only — it is inaccessible to keyboard, touch, and inconsistent for screen readers.

- Find every `title` on interactive elements: `<button title="...">`, `<a title="...">`, `<input title="...">`
- If the title carries essential information: replace with `aria-label`, `aria-describedby` + a visible or `.sr-only` element, or a proper visible label
- `title` on `<iframe>` is REQUIRED and correct — keep those

### 9.5 Label in Name (WCAG 2.5.3, Level A)

When a control has BOTH visible text AND an accessible name (`aria-label` / `aria-labelledby`), the visible text must be contained — word-for-word — within the accessible name. Voice-control users say what they see ("click Submit"); if the accessible name doesn't contain the visible label, the command fails silently.

**The common failure:**
```html
<!-- BROKEN: visible text "Submit" is not in the accessible name "Send form" -->
<button aria-label="Send form">Submit</button>

<!-- BROKEN: visible text "Get started" not in the accessible name -->
<a href="/signup" aria-label="Create your account">Get started</a>
```

**The fix — the accessible name must start with (or contain) the visible text:**
```html
<button aria-label="Submit registration">Submit</button>   <!-- "Submit" is contained ✓ -->
<a href="/signup" aria-label="Get started with a free account">Get started</a>  <!-- ✓ -->
```

**Audit rule:** find every interactive element that has both visible text content AND an `aria-label` / `aria-labelledby`. For each, confirm the visible text string is a substring of the accessible name (case-insensitive). Where it isn't, either extend the aria-label to include the visible text, or drop the aria-label if the visible text alone is a sufficient name. Icon-only buttons (no visible text) are exempt — 9.2 already covers them.

### 9.6 Content on hover or focus (WCAG 1.4.13, Level AA)

Any content that appears on hover or focus — tooltips, custom dropdowns, popovers, definition bubbles — must satisfy three behaviours:

1. **Dismissable** — the user can dismiss it with `Escape` (or moving focus) WITHOUT moving the pointer. A tooltip that only disappears when the mouse leaves fails this.
2. **Hoverable** — the user can move the pointer onto the appeared content without it vanishing (so they can read a tooltip that overlaps other content, or click a link inside a popover).
3. **Persistent** — it stays visible until the user dismisses it, moves focus/hover away, or the information is no longer valid. It must not auto-hide on a timer.

```js
// Dismissable: Escape closes the tooltip without the pointer moving
tooltipTrigger.addEventListener('keydown', e => {
  if (e.key === 'Escape') hideTooltip();
});
```
```css
/* Hoverable: a gap-free bridge so moving onto the tooltip doesn't trigger mouseleave.
   Keep the tooltip inside the trigger's hover region, or add an invisible bridge. */
.tooltip { pointer-events: auto; }
```

**Audit rule:** for every hover/focus-triggered popover, verify Escape dismisses it, the pointer can reach it, and nothing auto-hides it on a timeout. CSS-only `:hover` tooltips usually fail Dismissable and Hoverable — flag them and add the JS behaviours.
