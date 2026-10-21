# Forms

> Reference for the `tina4-a11y` skill: Phase 6 (forms, CRITICAL). Moved out of `SKILL.md` unchanged.

## Phase 6 — CRITICAL: Forms

### 6.1 Every input has an associated label

Every `<input>`, `<textarea>`, and `<select>` must have a label via `for`/`id`, wrapping `<label>`, or `aria-labelledby`. `placeholder` is NOT a label substitute — it disappears when typing starts.

```html
<label for="email">Email</label>
<input id="email" type="email" autocomplete="email">
```

### 6.2 Required fields

Mark with `required` (or `aria-required="true"` for custom components). Never rely on an asterisk (*) alone — add `aria-label` including "required" or a `<span class="sr-only"> (required)</span>` after the label text.

### 6.3 Error messages

When a field has an error:
- The error must be associated with the field via `aria-describedby`
- `aria-invalid="true"` must be set on the field
- The error must not rely on colour alone — include an icon or the word "Error:"

```html
<input id="email" type="email" aria-describedby="email-error" aria-invalid="true">
<span id="email-error" role="alert">Error: Enter a valid email address.</span>
```

### 6.4 Grouped controls

Checkboxes and radio buttons in a group must be wrapped in `<fieldset>` with a `<legend>` naming the group.

### 6.5 Submit button

Every form must have a clearly labelled submit button. Icon-only submit buttons must have `aria-label`.

### 6.6 Autocomplete

Personal data fields must have the appropriate `autocomplete` attribute (WCAG 1.3.5). Reference the MDN autocomplete token list. Common values:

| Field type | `autocomplete` value |
|-----------|---------------------|
| Full name | `name` |
| Given name | `given-name` |
| Family name | `family-name` |
| Email | `email` |
| Phone | `tel` |
| Street address | `street-address` |
| Postal code | `postal-code` |
| Country | `country-name` |
| Current password | `current-password` |
| New password | `new-password` |
| One-time code | `one-time-code` |
| Credit card number | `cc-number` |
