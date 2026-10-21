# Phase 8.5 - Validation, Phase 9 - Handoff report, Phase 9.5 - Pre-launch checklist

> Reference for the `tina4-seo` skill: Phase 8.5 (validation), Phase 9 (handoff report), and Phase 9.5 (pre-launch checklist). Moved out of `SKILL.md` unchanged.

## Phase 8.5 — Validation

Before writing the handoff report, validate every generated artifact. Never claim complete without proof.

### Structured data validation

- **Google Rich Results Test** — paste each page URL into https://search.google.com/test/rich-results and confirm every schema type is detected with zero errors and zero critical warnings. Non-critical warnings (missing optional fields) can be listed but not blocking.
- **Schema.org validator** — https://validator.schema.org/ for a stricter cross-check.

For each page tested, record: URL, schema types detected, error count. A page with any error is not done.

### Sitemap and robots validation

- **Sitemap** — fetch `/sitemap.xml`, confirm HTTP 200, valid XML, and every `<loc>` matches an actual 200-response URL. A sitemap entry that 404s hurts more than not being listed at all.
- **robots.txt** — fetch `/robots.txt`, confirm the Sitemap directive resolves, and no wildcard `User-agent: *` `Disallow: /` accidentally blocks the whole site.

### Meta tag validation

- **Open Graph** — https://www.opengraph.xyz/ or the Facebook Sharing Debugger. Confirm the og:image renders at 1200×630px on a preview.
- **Twitter / X Card** — X retired the standalone card validator (`cards-dev.twitter.com/validator`) in 2023. Validate by drafting a post with the URL in the X composer and confirming the card preview renders, or use a third-party OG/Twitter preview tool (e.g. https://www.opengraph.xyz/). The `twitter:*` tags are still read by X and several other platforms, so keep them.

### AI discovery files

- **`/llms.txt`, `/llms-full.txt`, `/ai.txt`** — confirm each responds with HTTP 200 and `Content-Type: text/plain`. A file served as `text/html` is silently rejected by most AI crawlers.

Record validation results in the handoff report — every ✅ must be backed by an actual test.

---

## Phase 9 — Handoff report

Generate a complete audit summary in this format. Every cell contains a real value —
never "see above" or "completed".

```
## SEO/AISO Audit Report — [Project Name]  [date]

### Structured data implemented
Organization:     ✅  https://[domain]/#organization
WebSite:          ✅  SearchAction: [yes / no — no search function]
WebPage:          ✅  implemented on [N] pages
BreadcrumbList:   ✅  implemented on all non-homepage pages
FAQPage:          ✅  [page URL]  |  ❌  not applicable (no FAQ content found)
LocalBusiness:    ❌  not applicable (no physical address)
Article:          ✅  implemented on [N] blog posts
Person/Author:    ✅  [author name]  |  ❌  no blog / no named authors

### AI crawler access (robots.txt)
GPTBot:           ✅ allowed   OAI-SearchBot:   ✅ allowed
ChatGPT-User:     ✅ allowed   ClaudeBot:       ✅ allowed
PerplexityBot:    ✅ allowed   Perplexity-User: ✅ allowed
Google-Extended:  ✅ allowed   CCBot:           ✅ allowed
Bytespider:       ✅ allowed   Meta-ExternalAgent: ✅ allowed
Sitemap directive: ✅ https://[domain]/sitemap.xml

### AI discovery files
/llms.txt:        ✅  [N] key pages listed
/llms-full.txt:   ✅  generated
/ai.txt:          ✅  generated

### Sitemap
/sitemap.xml:     ✅  [N] URLs, lastmod set, all priorities assigned

### Meta tags (base template)
description:      ✅  dynamic per page
canonical:        ✅  dynamic per page
og:image:         ✅  default 1200×630px social card created at /[path]
Twitter Card:     ✅  summary_large_image
theme-color:      ✅  light [hex] / dark [hex]
AI snippet perms: ✅  max-snippet:-1 set

### Content audit
Heading hierarchy: ✅ / ⚠️ [N] violations fixed
Semantic HTML:     ✅ / ⚠️ [N] issues fixed
Image alt text:    ✅ / ⚠️ [N] images corrected
Entity consistency: ✅ "[canonical name]" used consistently
Internal linking:  ✅ / ⚠️ [note any orphaned pages]

### E-E-A-T signals
About page:       ✅ / ❌ missing — [action required]
Author bios:      ✅ / ❌ / N/A
Contact in footer: ✅ / ❌
Privacy Policy:   ✅ / ❌
HTTPS:            ✅ / ⚠️ mixed content on [page]

### Favicon
SVG favicon:      ✅ /favicon.svg — dark/light mode via media query
PNG fallback:     ✅ /favicons/favicon-32x32.png
Apple touch icon: ✅ /favicons/apple-touch-icon.png
Web manifest:     ✅ /favicons/site.webmanifest
RFG package:      ✅ complete  |  ⏳ pending — [reason]

### Files changed
[List every file that was created or modified, with a one-line description]
- src/templates/main.html — structured data, meta tags, favicon links
- public/robots.txt — added AI crawler allow rules and Sitemap directive
- public/sitemap.xml — generated from route list
- public/llms.txt — created
- public/llms-full.txt — created
- public/favicon.svg — created
- public/favicons/ — RFG package extracted
- DESIGN.md — Favicon Brief updated to "RFG package: complete"
```

---

## Phase 9.5 — Pre-launch checklist (when environment != production)

If Phase 1.5 selected anything other than production, write `plan/seo/PRE-LAUNCH-CHECKLIST.md`. This is the one file the developer works through before flipping the site live. Every skipped or placeholder-carrying item lands here as a concrete task with a file path.

Template:

```markdown
# Pre-launch SEO checklist — [Project Name]

Environment at build time: [Localhost / Staging without prod URL / Staging with known prod URL]
Production URL: [known URL / "not yet decided"]

Work through every item below before deploying to production.

## URL substitution (if `REPLACE_WITH_PROD_DOMAIN` literals were used)

- [ ] Global search-and-replace `REPLACE_WITH_PROD_DOMAIN` → `[actual prod domain]` across the project
  - Files known to contain it: [list every file path found]

## URL substitution (if `{{ env.SITE_URL }}` was used)

- [ ] Confirm `SITE_URL` environment variable is set on the production host to `https://[actual prod domain]`
- [ ] Confirm the template engine resolves `{{ env.SITE_URL }}` correctly on production (do one test request)

## Files that were skipped and must be regenerated on production

- [ ] `sitemap.xml` — skipped because no production URL was available. Regenerate with real URLs by re-running tina4-seo in production environment, OR generate now with the confirmed prod URL and drop into `/public/sitemap.xml`
- [ ] `/llms.txt` — same
- [ ] `/llms-full.txt` — same

## robots.txt swap (if staging was in play)

- [ ] Replace the hardened staging `robots.txt` with `deploy/robots.production.txt` on production deploy
- [ ] Remove any `{% if env == 'staging' %}<meta name="robots" content="noindex">` blocks from templates OR confirm the env check resolves to false on production

## Structured data — schema types unlocked by more data

Every schema type below was skipped or reduced because required data was not confirmed at build time. Once the data exists, re-run tina4-seo OR add manually:

- [ ] `LocalBusiness` — unlocked when a physical address is added (address, city, postal code, country, opening hours)
- [ ] `Person` — unlocked when named authors are added to blog posts (name, jobTitle, bio, sameAs)
- [ ] `Product` — unlocked when product data is complete (name, image URL, price, currency, availability)
- [ ] `AggregateRating` — unlocked when real reviews exist (ratingValue, reviewCount)
- [ ] `contactPoint` telephone on Organization — unlocked when support phone is confirmed
- [ ] `sameAs` additions — add social profile URLs as they become available

## Validation — repeat every Phase 8.5 test with the real production URL

- [ ] Rich Results Test on every key production URL
- [ ] Sitemap XML validates and every `<loc>` returns 200
- [ ] `robots.txt` resolves and no `Disallow: /` remains
- [ ] Open Graph preview renders on the Facebook Sharing Debugger
- [ ] `/llms.txt`, `/llms-full.txt`, `/ai.txt` all serve `Content-Type: text/plain`

## First 24 hours after go-live

- [ ] Submit sitemap to Google Search Console
- [ ] Submit sitemap to Bing Webmaster Tools
- [ ] Confirm no unexpected `noindex` shipped to production
- [ ] Check Search Console for immediate crawl errors

Status: In Progress
```

Save this file, tell the user it exists, and add its path to the Phase 9 handoff report under a new **Pre-launch checklist** row.
