# Contrast and colour

> Reference for the `tina4-a11y` skill: Phase 8 (colour contrast, HIGH). Moved out of `SKILL.md` unchanged.

## Phase 8 — HIGH PRIORITY: Colour contrast

WCAG 2.1 AA requires:
- **4.5:1** for normal text (< 18pt regular or < 14pt bold)
- **3:1** for large text (≥ 18pt regular or ≥ 14pt bold) and UI components/icons

### 8.1 Compute the contrast ratios

Use this formula on every text/background token pair from DESIGN.md:

```js
function linearize(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
function luminance({ r, g, b }) {
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}
function contrast(rgb1, rgb2) {
  const [L1, L2] = [luminance(rgb1), luminance(rgb2)];
  const [hi, lo] = L1 > L2 ? [L1, L2] : [L2, L1];
  return ((hi + 0.05) / (lo + 0.05)).toFixed(2) + ':1';
}
```

### 8.2 Pairs to test at minimum

- Body text on page background
- Body text on card / surface background
- Link text on page background
- Placeholder text on input background (3:1 minimum)
- Button text on button background (all variants: primary, secondary, destructive)
- Badge text on badge background (all semantic colours)
- Disabled text (may fall below 4.5:1 — noted as an exception)

For any failing pair, propose a corrected hex value that passes while staying as close as possible to the original brand colour. Never silently substitute — flag it, propose, get confirmation.

**Ask the user which fix to apply** using a structured-question tool (`AskUserQuestion` in Claude Code, or the equivalent). For a failing brand accent, offer three concrete options with the exact hex values in each label:

- **Darken the accent** — replace `#FAB033` with `#E89A20` (contrast [X]:1) across the token system
- **Pair with a darker text token** — keep `#FAB033`, use `--text-1` instead of accent on those surfaces (contrast [Y]:1)
- **Keep as-is, log exception** — record in DESIGN.md that this pair is an accepted deviation

Fallback if no structured tool is available: send the same three options as a numbered prose list. Wait for the response before applying any fix — a silent contrast substitution changes the brand look in production.

### 8.3 Colour is not the only indicator

Every place where colour alone communicates meaning (red = error, green = success, coloured dot = status) must also carry a text label, icon, or pattern. Screen readers and colour-blind users cannot see colour.
