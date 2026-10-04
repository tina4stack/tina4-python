# Phase 7 - Website

> Reference for the `tina4-design` skill: Phase 7 (optional `design/website.html`). Moved out of `SKILL.md` unchanged.

## Phase 7 — Website (`website.html`) — Optional

Build a multi-page website as a single self-contained HTML file, saved to the `design/` folder. This phase is optional — only build it when the user explicitly asks for it, or when the chosen mode includes it (see Mode selection at the top of Phase 1).

### Purpose

The website mockup is a high-fidelity, browser-ready reference that shows what the actual product website looks like — not a component library, not a brand reference, but real pages with real content. Any Tina4 developer skill (Python, PHP, Ruby, Node) reads it and implements from it. It is framework-agnostic by design.

### Discovery — do this before writing a single line of HTML

Answer these four questions from the Phase 1 intake and Phase 2 research. Record answers in `DESIGN.md` under `## Website` before building:

1. **What is this site's single job?** (convert visitors to sign-ups / inform / demonstrate capability / direct to the product / showcase work)
2. **What is the visitor's first question when they land?** (What is this? / Can I afford it? / Is this for me? / How does it work?)
3. **What is the one action we want them to take?** (Sign up / Contact / Download / Buy / Read more)
4. **What type of content dominates?** (Narrative story / Feature comparison / Social proof / Exploration / Utility)

These four answers determine the layout archetype. Choose one:

| Archetype | When to use | Layout character |
|-----------|------------|-----------------|
| **Editorial** | Narrative brand, story-first, portfolio | Large type, wide imagery, generous whitespace, reading flow |
| **Product-led** | SaaS, app, tool — demo is the pitch | Hero with live demo/screenshot, feature grid, pricing anchor |
| **Marketplace** | Two-sided, discovery, listings | Search/browse prominent, trust signals, role-based messaging |
| **Storytelling** | Founder brand, mission-driven, social impact | Scroll-driven reveal, timeline, human imagery, pull quotes |
| **Utility** | Dev tool, API, technical service | Dense, scannable, code-forward, minimal decoration |

**The layout archetype is not the same as the brand personality.** A brand can be warm and friendly and still need a Utility archetype because it's a dev tool. Choose the archetype from the site's job, not from how the brand feels.

### Page set

Derive the page set from the discovery answers — do not use a fixed template. Common sets:

| Site type | Typical pages |
|-----------|--------------|
| SaaS / app | Home · Features · Pricing · About · Contact |
| Marketplace | Home · How it works · For [role A] · For [role B] · Contact |
| Services / agency | Home · Services · Work/Portfolio · About · Contact |
| Product / e-commerce | Home · Products · About · Contact |
| Portfolio | Home · Work · About · Contact |
| Documentation product | Home · Features · Docs (link) · Pricing · Contact |

Never produce a page just to fill the set. A page with nothing real to say is not included. Document the chosen pages and the reason for each in `DESIGN.md`.

### Single-file multi-page architecture

All pages live in one `website.html` file. Each page is a `<section class="page" id="page-[name]">`. A small JS router (~25 lines) reads the URL hash and shows only the active page. The browser back button works. The nav highlights the current page. No server is needed — open the file directly in a browser.

```html
<!-- Page container pattern -->
<section class="page" id="page-home" aria-label="Home">
  <!-- page content -->
</section>
<section class="page" id="page-about" aria-label="About" hidden>
  <!-- page content -->
</section>
```

```js
/* Router — place before </body> */
function route() {
  const id = location.hash.replace('#', '') || 'page-home';
  document.querySelectorAll('.page').forEach(p => {
    p.hidden = p.id !== id;
  });
  document.querySelectorAll('[data-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.page === id);
  });
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);
route();
```

Nav links use `href="#page-about"` and `data-page="page-about"`. No library. No build step.

### Layout rules — fight the generic default

The biggest risk is producing the same page every time: centered hero text, three feature cards, CTA strip, footer. This is the AI default and it is forbidden. The layout archetype chosen above must be visible in the structure of every page.

**Anti-patterns to avoid:**
- Centered hero text with a gradient or illustration blob — unless the archetype explicitly calls for it
- Three equal-width cards as the first section after the hero
- A "Why choose us?" section with icon + heading + one-line text
- A CTA strip with a heading and one button, full-width background
- A generic grid of logos for "Trusted by"

**Each page must be designed from its content job, not from a page template.** Ask: what is this page trying to do, and what layout serves that job?

### CSS and token rules

- **All CSS is shared** — defined once in `<style>` in `<head>`, used across all pages
- **Every colour comes from a CSS custom property** — the full token set from Phase 3 is re-declared here (copy from `ui-guide.html`'s `:root` block)
- **Three-state dark mode** — same pattern as brand-guidelines and ui-guide: `:root` (light), `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`, `:root[data-theme="dark"]`
- **Theme toggle** in the nav — same single-line JS as the ui-guide
- **All type sizes** from `--text-*` tokens using `clamp()` — never hardcoded `px`
- **All spacing** from `--space-*` tokens — including `--space-5: 20px`
- **No external CSS frameworks** — no Tailwind, no Bootstrap, no utility-class libraries
- **Google Fonts** via `<link>` in `<head>` — same faces defined in Phase 3

### Required elements on every page

**Shared topbar (identical across all pages):**
- Logo: `<img src="[logo-file]" alt="[Company]">` — never inline SVG for the logo
- Nav links — `data-page` attributes drive the router's active state
- Theme toggle button (moon/sun icon)
- Primary CTA button (the site's main action)
- Hamburger for mobile (`< 768px`)

**Shared footer:**
- Logo (small variant) + tagline
- Site links grouped by category
- Legal line: copyright + privacy + terms

**Page transitions:**
- Fade: `.page { animation: pageFade var(--duration-base) var(--ease-out); }` — applied when a page becomes visible
- Scroll position reset to 0 on every route change (already in the router above)

### Incremental build order for `website.html`

Build section by section using Write then Edit — never try to produce the entire file in one output:

1. Skeleton — `<head>` with full CSS (token system, layout, all component styles needed for the pages) + router JS + shared topbar + shared footer + all `<section class="page">` shells (empty)
2. Home page content
3. Second page content
4. Third page content
5. (Continue for each page in the set)
6. Final pass — verify nav links, theme toggle, mobile hamburger, all route transitions

### Quality checklist before calling Phase 7 done

- [ ] All pages reachable via nav — browser back/forward works
- [ ] Theme toggle works across all pages
- [ ] Logo loads (`<img>` tag, not inline SVG)
- [ ] Mobile hamburger opens/closes the nav drawer on `< 768px`
- [ ] Every touch target ≥ 44×44px
- [ ] No hardcoded hex values in any CSS rule — all tokens
- [ ] No layout anti-patterns from the list above
- [ ] Discovery answers documented in `DESIGN.md` under `## Website`
- [ ] Chosen archetype and page-set rationale recorded in `DESIGN.md`
