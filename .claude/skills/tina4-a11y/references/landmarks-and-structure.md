# Landmarks and structure

> Reference for the `tina4-a11y` skill: Phase 2 (page structure and landmarks, CRITICAL) and Phase 14 (heading hierarchy, MEDIUM). Moved out of `SKILL.md` unchanged.

## Phase 2 — CRITICAL: Page structure and landmarks

Screen readers and keyboard users navigate by landmarks. Without them, the page is a flat wall of content.

### 2.1 `<html lang="...">` — required on every page

Every `<html>` element must have a valid BCP 47 language code — e.g. `lang="en-ZA"`, `lang="en-US"`, `lang="fr"`, `lang="de"`. A missing `lang` means screen readers may read the page in the wrong language. For right-to-left languages (Arabic, Hebrew, Persian), also add `dir="rtl"`.

Inline content in a different language than the page must carry its own `lang` attribute:
```html
<p>The French say <span lang="fr">c'est la vie</span> when things go wrong.</p>
```

### 2.2 Landmark roles

Every page must use these semantic elements correctly:

| Element | Rule |
|---------|------|
| `<header>` | Site header at the document root (implicit `role="banner"`). Do NOT add `role="banner"` to nested `<header>` inside `<article>` or `<section>` — those don't get the role. |
| `<nav>` | Every distinct nav must have a unique `aria-label` — `aria-label="Main"`, `aria-label="Footer"`, `aria-label="Breadcrumb"`. |
| `<main>` | Primary content area — exactly one per page. |
| `<aside>` | Supplementary content (sidebars, related links). |
| `<footer>` | Site footer. |
| `<section>` | Must have an accessible name via `aria-labelledby` pointing to its heading, or `aria-label` if it has no visible heading. |

Report every page where any of these are missing or misused, and fix the templates directly.

### 2.3 Skip navigation link

The first focusable element on every page must be a "Skip to main content" link. It may be visually hidden until focused:

```html
<a class="skip-link" href="#main-content">Skip to main content</a>
```

```css
.skip-link {
  position: absolute;
  top: -100%;
  left: var(--space-4, 1rem);
  padding: var(--space-2, 0.5rem) var(--space-4, 1rem);
  background: var(--accent, #000);
  color: #fff;
  font-weight: 600;
  border-radius: 0 0 4px 4px;
  text-decoration: none;
  z-index: 9999;
  transition: top 0.2s;
}
.skip-link:focus {
  top: 0;
}
```

On the `<main>` element: `id="main-content"` with `tabindex="-1"` so it receives programmatic focus without joining the tab order.

### 2.4 Unique page titles

Every page must have a unique, descriptive `<title>` tag. Format: `[Page name] — [Site name]`. A site-wide title repeated on every page ("My Website") fails WCAG 2.4.2 — screen readers announce it on every navigation.

### 2.5 `aria-current="page"` on nav links

The nav link pointing to the current page must carry `aria-current="page"`. Screen readers announce it as "current page":

```html
<nav aria-label="Main">
  <a href="/">Home</a>
  <a href="/products" aria-current="page">Products</a>
  <a href="/contact">Contact</a>
</nav>
```

---

## Phase 14 — MEDIUM PRIORITY: Heading hierarchy

Screen readers use headings as a page table of contents. A broken hierarchy is one of the most common failures (WCAG 1.3.1 Info and Relationships).

1. List every heading in document order per template.
2. Check:
   - Exactly one `<h1>` per page — the page's primary topic
   - No skipped levels (H1 → H3 without an H2)
   - Headings used for structure, not visual size
3. Fix violations directly in the templates.
