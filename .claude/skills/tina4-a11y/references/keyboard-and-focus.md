# Keyboard and focus

> Reference for the `tina4-a11y` skill: Phase 3 (keyboard navigation, CRITICAL) and Phase 4 (visible focus indicators, CRITICAL). Moved out of `SKILL.md` unchanged.

## Phase 3 — CRITICAL: Keyboard navigation

Every action available by mouse must be reachable and operable by keyboard alone.

### 3.1 Tab order audit

Tab through every page. Report:
- Elements that receive focus but should not (`div`, `span`, or `img` with `tabindex="0"`)
- Interactive elements that do not receive focus (clickable `div`s, `span`s, or `<a>` with no `href`)
- Focus order that does not follow visual reading order (top-left → bottom-right)

### 3.2 `tabindex` rules

- `tabindex="0"` — use only on elements that are genuinely interactive and cannot be a native `<button>` or `<a>`
- `tabindex="-1"` — use for elements that receive programmatic focus only (modal dialogs, skip-link targets)
- `tabindex` > 0 — forbidden. Breaks the natural tab order.

### 3.3 Keyboard operability for custom components

For any interactive element that is not a native HTML control, implement the expected keyboard behaviour:

| Component | Expected keys |
|-----------|--------------|
| Button (custom) | `Enter` and `Space` activate |
| Link (custom) | `Enter` activates |
| Dropdown menu | `Enter`/`Space` open; arrow keys navigate items; `Escape` closes |
| Modal / dialog | `Escape` closes; focus trapped inside while open |
| Accordion | `Enter`/`Space` toggle panel; arrow keys move between headers |
| Tabs | Arrow keys switch tabs; `Enter`/`Space` activate |
| Checkbox (custom) | `Space` toggles |
| Date picker | Arrow keys navigate calendar; `Escape` closes; `Enter` selects |

### 3.4 Focus trap in modals — prefer native `<dialog>`

Modern browsers handle focus trap, backdrop, and Escape automatically when the dialog is opened with `.showModal()`:

```html
<dialog id="my-dialog" aria-labelledby="dialog-title">
  <h2 id="dialog-title">Confirm delete</h2>
  <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
  <button type="button">Delete</button>
</dialog>
```
```js
document.getElementById('my-dialog').showModal();  // focus trap free
```

Only implement the manual trap pattern below when using a custom overlay that cannot be a native `<dialog>` (non-modal drawers, custom in-page popovers):

```js
function trapFocus(element) {
  const focusable = element.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), ' +
    'select:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
  );
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  element.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}
```

Return focus to the triggering element when the dialog closes.

---

## Phase 4 — CRITICAL: Visible focus indicators

Every focusable element must show a clearly visible focus indicator. `outline: none` with no replacement fails WCAG 2.4.7.

1. Find every instance of `outline: none` or `outline: 0` in the stylesheets.
2. For each: check whether a replacement focus indicator exists (a `box-shadow`, a `border`, a background change). If not, add one.
3. The replacement must have a contrast ratio of at least 3:1 against the adjacent colour (WCAG 1.4.11).

Recommended pattern using the DESIGN.md token system:

```css
:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--accent-tint, rgba(0,0,0,0.1)),
              0 0 0 1px var(--accent, #000);
}

/* Remove the ring on mouse clicks but keep it for keyboard */
:focus:not(:focus-visible) {
  box-shadow: none;
}
```

Never use `:focus` alone to suppress the ring — use `:focus:not(:focus-visible)` so keyboard users still see it.
