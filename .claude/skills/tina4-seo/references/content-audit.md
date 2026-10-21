# Phase 6 - Content audit

> Reference for the `tina4-seo` skill: Phase 6 (content audit). Moved out of `SKILL.md` unchanged.

## Phase 6 — Content audit

Read each key page template and check the following. Fix violations directly in the
template files and report every change.

### 6.1 Heading hierarchy

- Every page has exactly one `<h1>` — the page's primary topic
- Heading levels are not skipped (H1 → H2 → H3, never H1 → H3)
- Headings are used for structure, not visual size — if a heading is used only because it
  looks bigger, it is wrong

### 6.2 `<html lang="...">` — required on every page

Screen readers, translation tools, and search engines all use this to determine the page language. A missing or wrong `lang` breaks entity resolution for AI systems and pronunciation for screen readers.

- Find every `<html>` tag in the template layer
- Ensure `lang="[BCP 47 code]"` is set — e.g. `lang="en-ZA"`, `lang="en-US"`, `lang="fr"`, `lang="de"`
- If the site is multilingual, the value must be dynamic per page
- Add `dir="rtl"` for right-to-left languages (Arabic, Hebrew, Persian)

### 6.3 Semantic HTML

AI parsers weight semantic elements heavily. Check that:
- `<main>` wraps the primary page content (once per page)
- `<article>` wraps self-contained content (blog posts, news items)
- `<nav>` wraps navigation menus
- `<section>` groups thematically related content and has a heading
- `<header>` and `<footer>` are used at page level correctly
- No `<div>` is used where a semantic element fits

### 6.4 Image alt text

Find every `<img>` tag. Flag:
- Missing `alt` attribute entirely
- Empty `alt=""` on a non-decorative image
- Generic values: `"image"`, `"photo"`, `"logo"`, the filename as the alt text

For each flagged image, read the surrounding context and suggest descriptive alt text.
Fix template-level images (logo, icons, UI images) directly. For content images, provide
the corrected attribute and show where to apply it.

### 6.5 Entity consistency

AI systems recognise entities (people, organisations, products) by consistent name usage.
Check:
- The organisation name is spelled identically on every page, in every meta tag, and in
  all structured data. Any variation breaks AI entity recognition.
- Author names are consistent across bylines, bios, and schema.
- Product or service names are consistent in copy, headings, and schema.

Report every inconsistency with file and line number. Fix it.

### 6.6 Internal linking structure

AI systems use internal links to map content relationships.
- The homepage links to all major section landing pages
- Each content page links to related pages
- Anchor text is descriptive ("view Cape Town office spaces") not generic ("click here")
- Key pages are not orphaned (reachable from at least one other page via a link)

Identify the most important pages, check that they are linked from relevant locations,
and suggest a hub/spoke structure where appropriate.
