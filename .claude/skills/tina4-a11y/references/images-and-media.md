# Images and media

> Reference for the `tina4-a11y` skill: Phase 5 (images and non-text content, CRITICAL). Moved out of `SKILL.md` unchanged.

## Phase 5 — CRITICAL: Images and non-text content

### 5.1 `<img>` alt text

For every `<img>` tag:
- Decorative images (icons, dividers, backgrounds): `alt=""` (empty string, not missing)
- Informative images: `alt` describing what the image conveys, not what it looks like ("Revenue chart showing 42% growth in Q3", not "chart.png")
- Linked images: `alt` describes the link destination ("Go to homepage"), not the image

### 5.2 `<svg>` used as an icon or illustration

- Decorative: `aria-hidden="true"` + `focusable="false"`
- Meaningful: `role="img"` + `aria-label="[description]"` on the SVG, or `<title>` as the first child of the SVG element

### 5.3 CSS background-image conveying information

CSS backgrounds cannot be described to screen readers. If a `background-image` conveys information (not just decoration), replace it with an `<img>` with alt text.

### 5.4 Video and audio

- Audio: transcript or accessible text equivalent
- Video: captions via `<track kind="captions">` inside `<video>` — not auto-generated
- Purely decorative video: `aria-hidden="true"` and no audio track
