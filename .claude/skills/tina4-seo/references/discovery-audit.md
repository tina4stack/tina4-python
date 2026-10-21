# Phase 1 - Discovery audit

> Reference for the `tina4-seo` skill: Phase 1 (discovery audit, intake gate, URL mode). Moved out of `SKILL.md` unchanged.

## Phase 1 — Discovery audit

Read the project files and report the current state before writing any code.

### 1.1 Read design/DESIGN.md

If present, extract:
- Company name (exact, canonical spelling)
- Logo file path and URL
- Brand colours (`--accent`, `--bg`)
- Social profile URLs
- Favicon brief (icon mark, colours, app name)
- Contact information
- "Next Steps" section (to confirm tina4-design has completed its handoff checklist)

### 1.2 Read existing templates

Find the base HTML template — the file where `<head>` is defined for all pages. In Tina4
projects this is typically:
- **PHP:** `src/templates/main.html` or `src/templates/index.html`
- **Python:** `src/templates/main.html`
- **Ruby:** `lib/tina4/public/` or `src/templates/`
- **Node:** `src/templates/` or `views/`
- **Plain HTML:** the shared `<head>` include or the index.html itself

Read it. Extract:
- Existing meta tags (description, canonical, og:*, twitter:*)
- Existing structured data (`<script type="application/ld+json">`)
- Existing favicon links
- `<title>` pattern (static or dynamic)
- `<html lang="...">` — note if present

### 1.3 Check key files

Check each of the following. Report exists / missing / broken:

| File | Location | Check |
|------|----------|-------|
| `robots.txt` | domain root | Present? Any AI bots blocked? Sitemap directive present? |
| `sitemap.xml` | domain root or `/public/` | Present? All URLs included? `lastmod` set? |
| `/llms.txt` | domain root | Present? Follows llmstxt.org spec? |
| `/llms-full.txt` | domain root | Present? |
| `/ai.txt` | domain root | Present? |
| `DESIGN.md` | `design/` folder | Present? Favicon brief complete? |

### 1.4 Report and proceed

Report the audit results as a ✅/❌/⚠️ table before proceeding:

```
SEO/AISO Discovery Audit — [Project Name]

Meta tags:         ⚠️  description present but no og:image
Canonical tags:    ❌  missing on all pages
Structured data:   ❌  none found
robots.txt:        ⚠️  exists but GPTBot and ClaudeBot are blocked
sitemap.xml:       ❌  missing
llms.txt:          ❌  missing
llms-full.txt:     ❌  missing
Favicon:           ⚠️  PNG only — no SVG, no Apple touch icon

Working through each item in priority order.
```

### 1.5 Intake gate — environment, business data, and scope

After the audit table, do ONE round-trip intake covering three things: **where the site is running**, **what business data is genuinely known**, and **how much of the audit to fix**. Wait for a response before writing any code. Do not silently proceed.

**Preferred: use a structured-question tool** (`AskUserQuestion` in Claude Code, or the equivalent in the current agent harness) with three questions in the same call:

---

**Question 1 — Environment (single-select):**

- **Production — live URL** — the current URL is the real domain; use it everywhere
- **Staging with known prod URL** — the site runs on a staging domain, but the developer knows what the production URL will be; use the prod URL in structured data / canonicals / sitemap, harden the staging robots.txt
- **Staging only — no prod URL yet** — no production domain confirmed; skip URL-dependent artifacts, emit a pre-launch checklist
- **Localhost only** — running on `localhost` or a dev machine; skip URL-dependent artifacts, emit a pre-launch checklist

If Staging + known prod is picked, follow up with a text field for the production URL.

---

**Question 2 — What business data is known? (multi-select):**

- Physical address / service area (unlocks `LocalBusiness`)
- Named authors / bylines (unlocks `Person` + `author` on `Article`)
- Product data — name, price, image (unlocks `Product`)
- Reviews / ratings — real, verifiable (unlocks `AggregateRating` on `Product`)
- Social profile URLs — LinkedIn, Twitter/X, Facebook (unlocks `sameAs` on `Organization`)
- Contact email
- Support phone (unlocks `contactPoint` telephone on `Organization`)
- Company founding date / history (adds `foundingDate` to `Organization`)

Whatever is NOT ticked: the skill omits the corresponding schema type or field entirely. The audit report flags them as "unlocked when [data] is provided" so the developer knows what's not being emitted and why.

Follow-up text fields collect only what was ticked — never ask for data that was not selected.

---

**Question 3 — Scope (single-select):**

- **Fix everything** — proceed through all phases in order
- **Critical only** — structured data + AI crawlers + meta tags, skip content audit / E-E-A-T / favicon
- **Let me scope** — user picks what to skip via a follow-up multi-select: skip checkout template, skip robots.txt, skip llms-full.txt, skip favicon package, skip content audit

---

**Fallback if no structured tool is available:** send the same three questions as a numbered prose list, one after the other or bundled.

**Wait for the response.** All three answers gathered in ONE round trip, then proceed to Phase 2 with the environment + data set + scope locked. On a subsequent run of this skill, this intake fires again — the user always gets to correct any of the three.

### 1.6 Set the URL mode for the rest of the run

Based on the environment answer, every downstream phase behaves differently. Record the decision in `plan/seo/PLAN.md` so a re-run picks it up:

| Environment | Structured data URL | Canonical / og:url | sitemap.xml | llms.txt | robots.txt |
|-------------|---------------------|--------------------|-------------|----------|------------|
| Production | Real prod URL | Real prod URL | Generated with real URLs | Generated with real URLs | Standard — allow AI crawlers + Sitemap directive |
| Staging + known prod | Real prod URL | Real prod URL | Generated with prod URLs | Generated with prod URLs | Staging gets HARDENED (see Phase 4.5); prod robots.txt written to a separate file for deploy |
| Staging only | `{{ env.SITE_URL }}` if templates support it; else `https://REPLACE_WITH_PROD_DOMAIN` | Same | **Skipped** — checklist item | **Skipped** — checklist item | HARDENED for staging; prod version deferred |
| Localhost only | `{{ env.SITE_URL }}` if templates support it; else `https://REPLACE_WITH_PROD_DOMAIN` | Same | **Skipped** — checklist item | **Skipped** — checklist item | **Skipped** — checklist item |

**Prefer runtime template variables** where the framework supports them (Tina4 templates, Django, Rails, Node view engines all do). Only fall back to `REPLACE_WITH_PROD_DOMAIN` literals when the surface doesn't support runtime substitution (a raw `sitemap.xml`, a static `llms.txt`).

**Skipped items become checklist items** in `plan/seo/PRE-LAUNCH-CHECKLIST.md` — see Phase 9.5.
