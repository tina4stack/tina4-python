# Phase 5 - Meta tags

> Reference for the `tina4-seo` skill: Phase 5 (meta tags). Moved out of `SKILL.md` unchanged.

## Phase 5 — Meta tags

Audit and fix the base template `<head>`. Every item below must be present, dynamic
(per-page values injected by the template engine), and correct.

### Required on every page

```html
<!-- Character set — must be first -->
<meta charset="UTF-8">

<!-- Viewport -->
<meta name="viewport" content="width=device-width, initial-scale=1">

<!-- Page title — unique per page, format: [Page name] — [Brand name] -->
<title>{{ page_title }} — {{ site_name }}</title>

<!-- Description — 120–160 characters, specific to this page -->
<meta name="description" content="{{ page_description }}">

<!-- Author -->
<meta name="author" content="{{ site_name }}">

<!-- Canonical — absolute URL matching this page exactly -->
<link rel="canonical" href="{{ current_url }}">

<!-- AI snippet permission — grants full extract rights to AI systems -->
<meta name="robots" content="max-snippet:-1, max-image-preview:large, max-video-preview:-1">

<!-- Open Graph -->
<meta property="og:type" content="{{ og_type | default('website') }}">
<meta property="og:title" content="{{ page_title }} — {{ site_name }}">
<meta property="og:description" content="{{ page_description }}">
<meta property="og:image" content="{{ og_image | default(site_default_og_image) }}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{{ current_url }}">
<meta property="og:site_name" content="{{ site_name }}">

<!-- Twitter / X Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{{ page_title }} — {{ site_name }}">
<meta name="twitter:description" content="{{ page_description }}">
<meta name="twitter:image" content="{{ og_image | default(site_default_og_image) }}">
<meta name="twitter:site" content="{{ twitter_handle }}">

<!-- Theme colour — read from DESIGN.md Favicon Brief -->
<meta name="theme-color" media="(prefers-color-scheme: light)" content="{{ brand_accent }}">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="{{ brand_bg_dark }}">
```

**`og:image` default:** create a single branded social share card (1200×630px) using the
brand assets from DESIGN.md. Use this as the site-wide default. Per-page images override
it when available (blog post featured image, product photo, etc.).

**`hreflang`:** add only if the site has multilingual content. Omit otherwise — an incorrect
`hreflang` is worse than none.
