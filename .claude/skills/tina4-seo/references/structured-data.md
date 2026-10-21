# Phase 2 - Structured data (JSON-LD / Schema.org)

> Reference for the `tina4-seo` skill: Phase 2 (structured data). Moved out of `SKILL.md` unchanged.

## Phase 2 — Structured data (JSON-LD / Schema.org)

Generate valid JSON-LD for every applicable schema type. Each block goes inside a
`<script type="application/ld+json">` tag in `<head>`. Multiple schema types may be
combined in one script block or kept separate — separate is easier to maintain.

**Read the page content before generating each type.** Never invent facts — if a field
value is not known, omit the field rather than filling it with a guess.

### Required on every project

**Before generating any schema:** grep the target templates for existing `<script type="application/ld+json">` blocks. If a block for the same `@type` already exists, replace it — do not append a duplicate. On a second run of this skill, this check is what prevents doubled Organization or WebSite entities from confusing crawlers.

**Organization** — the entity anchor. Every other schema type references this.

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://[domain]/#organization",
  "name": "[Canonical company name — exact spelling from DESIGN.md]",
  "url": "https://[domain]",
  "logo": {
    "@type": "ImageObject",
    "url": "https://[domain]/[logo-file-path]",
    "width": "[px]",
    "height": "[px]"
  },
  "contactPoint": {
    "@type": "ContactPoint",
    "contactType": "customer support",
    "email": "[contact email]"
  },
  "sameAs": [
    "[LinkedIn URL]",
    "[Twitter/X URL]",
    "[Facebook URL]"
  ]
}
```

**`sameAs` rule:** include only URLs that actually exist. Never emit empty strings or `[LinkedIn URL]` placeholders — an empty `sameAs` entry breaks entity resolution. If a social profile is absent from DESIGN.md, omit that array position entirely.

**WebSite** — enables sitelinks searchbox in Google; required for AI entity resolution.

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": "https://[domain]/#website",
  "url": "https://[domain]",
  "name": "[Site name]",
  "publisher": { "@id": "https://[domain]/#organization" },
  "potentialAction": {
    "@type": "SearchAction",
    "target": {
      "@type": "EntryPoint",
      "urlTemplate": "https://[domain]/search?q={search_term_string}"
    },
    "query-input": "required name=search_term_string"
  }
}
```
Omit `potentialAction` if the site has no search function.

### Page-level schema

**WebPage or Article** — add to every key page. Use `Article` for blog/news content,
`WebPage` for static pages.

```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "@id": "https://[domain]/[page-path]#webpage",
  "url": "https://[domain]/[page-path]",
  "name": "[Page title]",
  "description": "[120–160 character description]",
  "isPartOf": { "@id": "https://[domain]/#website" },
  "about": { "@id": "https://[domain]/#organization" },
  "inLanguage": "[BCP 47 code — e.g. en-ZA, en-US, fr, de]",
  "datePublished": "[ISO 8601]",
  "dateModified": "[ISO 8601]"
}
```

**Page title and description length rules** — these govern both the JSON-LD `name`/`description` and the `<title>`/`<meta name="description">` tags:
- `<title>` — 50–60 characters. Google truncates around 60. Format: `[Page name] — [Brand name]`.
- Meta description — 120–160 characters. Longer descriptions are truncated in the SERP.
- Open Graph description — 120–200 characters. Different platforms truncate at different points.
- **Every page has a unique title and unique description** — sitewide duplicates are the most common ranking bug.

**BreadcrumbList** — on every non-homepage. Communicates site hierarchy to AI.

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://[domain]" },
    { "@type": "ListItem", "position": 2, "name": "[Section]", "item": "https://[domain]/[section]" },
    { "@type": "ListItem", "position": 3, "name": "[Page]", "item": "https://[domain]/[section]/[page]" }
  ]
}
```

### Conditional schema — generate only when applicable

| Type | When to generate |
|------|-----------------|
| **Person / Author** | Site has a blog, named authors, or a founder bio page |
| **FAQPage** | Any page contains questions and answers (including implied Q&A in body copy) |
| **HowTo** | Any page explains a process or steps |
| **LocalBusiness** | Company has a physical address or defined service area |
| **Product + AggregateRating** | Site sells products and has reviews/ratings |
| **ItemList** | Any page lists multiple items (locations, products, blog posts, features) |
| **Event** | Site promotes events with dates and locations |
| **Course** | Site offers courses or educational content |

Read each page's actual content before deciding whether to generate these types.

**Cross-reference the business-data intake (Phase 1.5, Question 2).** A schema type gates on BOTH the content signal (does the page actually have the data?) AND the business-data flag from the intake (did the developer confirm the data is real?). If either is missing, omit the schema type. Do NOT emit a `LocalBusiness` block just because the page has an address in the footer — the developer must have confirmed the physical location is theirs and the fields are complete.

### The omit-not-placeholder rule — required schema fields

Every schema type has some required fields. When the developer's intake did not confirm those fields as known, **omit the whole schema type**. Never emit:

- `"name": "[COMPANY_NAME]"`
- `"telephone": "+1-XXX-XXX-XXXX"`
- `"streetAddress": "123 Placeholder Street"`
- `"priceCurrency": "USD"` when the currency isn't known
- Empty `sameAs` array entries or `[LinkedIn URL]` string literals

For OPTIONAL fields inside an otherwise-known schema, omit only the field. Example: an `Organization` block with `name` and `url` but no `telephone` is fine — drop the `contactPoint` entirely rather than placeholder its phone number. A partial `Organization` with `name` and `url` and one confirmed social profile URL in `sameAs` still emits — dropping only unknowns.

The audit report says the type was skipped and what unlocks it:

```
FAQPage:        ❌ not applicable (no FAQ content found)
HowTo:          ⏳ unlocked when the developer confirms "Adding a widget" is a real process
LocalBusiness:  ⏳ unlocked when a physical address is confirmed (business-data intake)
Product:        ⏳ unlocked when product name, price, currency, and image are confirmed
```

### URL substitution in every JSON-LD block

Every `@id`, `url`, `logo.url`, `sameAs[]`, `mainEntityOfPage`, and `potentialAction.target.urlTemplate` in the JSON-LD emitted by Phase 2 uses the URL mode set in Phase 1.6. Never hardcode the current URL when the environment is not production.

### FAQPage example

Fires on any page with Q&A pairs, including implied Q&A in body copy.

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "[Full question text]",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "[Full answer text — plain text, no HTML tags]"
      }
    }
  ]
}
```

### HowTo example

Fires on any page explaining a process or steps.

```json
{
  "@context": "https://schema.org",
  "@type": "HowTo",
  "name": "[Process name]",
  "description": "[One sentence describing the outcome]",
  "step": [
    {
      "@type": "HowToStep",
      "position": 1,
      "name": "[Step name]",
      "text": "[Step instructions]"
    }
  ]
}
```

### Article example — with Open Graph article properties

For blog posts and news content, use `Article` in JSON-LD AND add these Open Graph properties to `<head>`:

```html
<meta property="og:type" content="article">
<meta property="article:published_time" content="[ISO 8601]">
<meta property="article:modified_time" content="[ISO 8601]">
<meta property="article:author" content="[Author name or URL to author profile]">
<meta property="article:section" content="[Category — e.g. Tutorials, News]">
<meta property="article:tag" content="[Tag 1]">
```

### Tina4 implementation

In a Tina4 project, structured data goes in the base template, not repeated in every route.
For page-specific schema (Article, WebPage, BreadcrumbList), use the template engine to
inject dynamic values:

**PHP example:**
```html
<!-- In src/templates/main.html, inside <head> -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "url": "{{ current_url }}",
  "name": "{{ page_title }} — {{ site_name }}",
  "dateModified": "{{ page_modified | date('Y-m-d') }}"
}
</script>
```

**Python / Ruby / Node:** same pattern using the framework's template syntax.

For static HTML projects: generate one JSON-LD block per page and insert it directly.
