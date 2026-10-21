# Phase 4 - robots.txt and sitemap (and Phase 4.5 - Staging safeguards)

> Reference for the `tina4-seo` skill: Phase 4 (robots.txt and sitemap) and Phase 4.5 (staging safeguards). Moved out of `SKILL.md` unchanged.

## Phase 4 — robots.txt and sitemap

### robots.txt

Read the current file. Fix it to:

1. **Allow all AI crawlers.** Ensure none of the following are blocked by a wildcard
   `User-agent: *` Disallow or by an explicit block:

   ```
   User-agent: GPTBot
   Allow: /

   User-agent: OAI-SearchBot
   Allow: /

   User-agent: ChatGPT-User
   Allow: /

   User-agent: ClaudeBot
   Allow: /

   User-agent: Claude-Web
   Allow: /

   User-agent: anthropic-ai
   Allow: /

   User-agent: PerplexityBot
   Allow: /

   User-agent: Perplexity-User
   Allow: /

   User-agent: Google-Extended
   Allow: /

   User-agent: Applebot-Extended
   Allow: /

   User-agent: cohere-ai
   Allow: /

   User-agent: CCBot
   Allow: /

   User-agent: Bytespider
   Allow: /

   User-agent: Meta-ExternalAgent
   Allow: /

   User-agent: FacebookBot
   Allow: /

   User-agent: Amazonbot
   Allow: /

   User-agent: YouBot
   Allow: /

   User-agent: Diffbot
   Allow: /

   User-agent: ImagesiftBot
   Allow: /

   User-agent: omgili
   Allow: /

   User-agent: omgilibot
   Allow: /
   ```

2. **Still disallow private paths.** Keep `Disallow` rules for `/admin/`, `/dashboard/`,
   `/api/`, `/checkout/`, and any authenticated or private paths.

3. **Add the Sitemap directive:**
   ```
   Sitemap: https://[domain]/sitemap.xml
   ```

4. **Check for `noai` / `noml` meta tags** in the base template. These silently block AI
   indexing even when robots.txt allows. If found, remove them unless they are intentional
   (ask the developer to confirm).

### sitemap.xml

Generate `/sitemap.xml` (or update it if one exists) covering every public URL.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">

  <url>
    <loc>https://[domain]/</loc>
    <lastmod>[ISO date]</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>

  <!-- Key landing pages: priority 0.8, changefreq monthly -->
  <!-- Blog/article pages: priority 0.6, changefreq monthly -->
  <!-- Utility pages (contact, about, privacy): priority 0.4, changefreq yearly -->

</urlset>
```

**In Tina4 projects:** generate the sitemap dynamically from the route list rather than
maintaining a static file. Ask the developer which routes are public-facing.

---

## Phase 4.5 — Staging safeguards (when environment = staging)

When Phase 1.5 detected a staging environment, harden the staging deployment so it cannot be indexed and cannot beat the production version in search:

### Hardened staging `robots.txt`

Write this to the staging deployment's `robots.txt` — NOT the production one:

```
# Staging environment — indexing blocked
User-agent: *
Disallow: /
```

**Do NOT include** a `Sitemap:` directive on staging. A sitemap on staging tells crawlers where the staging URLs live even when disallowed.

### Global `noindex` on staging pages

Add to the base template `<head>` **behind an environment check** so it applies only on staging:

```html
{% if env == 'staging' %}
<meta name="robots" content="noindex, nofollow">
{% endif %}
```

Or the framework-native equivalent. Never leave this permanently in the template — it must gate on env, otherwise production ships with `noindex` and drops off search entirely.

### HTTP Basic Auth (recommended)

If the framework supports it, put staging behind HTTP Basic Auth. This is the most reliable way to keep staging out of search — crawlers cannot index what they cannot access.

### Separate production `robots.txt` for deploy

Write the production `robots.txt` (with AI crawler allow rules + real Sitemap directive from Phase 4) to a file the developer can deploy alongside their production build — for example `deploy/robots.production.txt` — and add a line to the pre-launch checklist:

> `[ ] Replace robots.txt with deploy/robots.production.txt on production deploy`

The staging file must never reach production, and the production file must never sit on staging.
