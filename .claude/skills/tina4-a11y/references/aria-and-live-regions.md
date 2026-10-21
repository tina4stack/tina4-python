# ARIA, live regions and tables

> Reference for the `tina4-a11y` skill: Phase 7 (ARIA states and properties, HIGH), Phase 10 (live regions and dynamic content, MEDIUM) and Phase 11 (tables, MEDIUM). Moved out of `SKILL.md` unchanged.

## Phase 7 — HIGH PRIORITY: ARIA states and properties

ARIA states communicate dynamic changes to assistive technology. Without them, interactive components are invisible to screen readers.

Check every custom interactive component for these required attributes:

| Component | Required ARIA | Notes |
|-----------|--------------|-------|
| Accordion header button | `aria-expanded="true/false"` | Changes on toggle |
| Dropdown trigger | `aria-expanded`, `aria-haspopup="listbox"` or `"menu"` | |
| Modal / dialog | `role="dialog"`, `aria-modal="true"`, `aria-labelledby` (pointing to title) | Native `<dialog>` handles most of this |
| Tab list | `role="tablist"`, `role="tab"`, `role="tabpanel"`; `aria-selected` on tabs; `aria-controls` linking tab to panel | |
| Alert / error | `role="alert"` (errors) or `aria-live="polite"` (status) | |
| Progress bar | `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax` | |
| Toggle / switch | `role="switch"`, `aria-checked="true/false"` | |
| Loading spinner | `role="status"`, `aria-label="Loading"`, `aria-live="polite"` | |
| Tooltip | `role="tooltip"` on tooltip element; `aria-describedby` on trigger | |
| Sortable table header | `aria-sort="ascending/descending/none"` | |
| Selected item in list | `aria-selected="true"` | |
| Disabled control | `aria-disabled="true"` (for custom elements); native `disabled` for real inputs | |

Find each component type in the project, check for the required attributes, and add any missing.

**`aria-atomic` on live regions.** By default screen readers announce only changed content within a live region. If the region's whole content forms a single message (e.g. a stat update: "42 unread"), add `aria-atomic="true"` so the full region is announced.

---

## Phase 10 — MEDIUM PRIORITY: Live regions and dynamic content

Content that updates without a page reload must be announced to screen readers.

### 10.1 `aria-live` regions

- Status messages, success confirmations, loading complete: `aria-live="polite"`
- Error messages, urgent alerts: `aria-live="assertive"` (use sparingly — it interrupts)
- Toast / snackbar container: `aria-live="polite"` + `role="status"`

The live region must exist in the DOM BEFORE content is injected. Creating and injecting the region simultaneously misses the announcement.

### 10.2 Loading states

```html
<div role="status" aria-live="polite" aria-label="Loading">
  <!-- spinner -->
</div>
```

Remove or hide when done and announce completion.

### 10.3 Form submission feedback

After a form submits (success or error), the message must be in a live region OR focus must move to the message so it is announced.

---

## Phase 11 — MEDIUM PRIORITY: Tables

Data tables must be structured so screen readers can understand cell-to-header relationships.

1. Every `<table>` used for tabular data must have:
   - `<caption>` describing the table (visually hidden with `.sr-only` is fine if a visible heading is nearby)
   - `<th>` for header cells, never `<td>` styled to look like a header
   - `scope="col"` on column headers, `scope="row"` on row headers
   - `<thead>` and `<tbody>` (and `<tfoot>` where appropriate)

2. Tables used for layout must have `role="presentation"` or `aria-hidden="true"` — but prefer replacing them with CSS grid or flexbox entirely.
