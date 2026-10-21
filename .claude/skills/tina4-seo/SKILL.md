---
name: tina4-seo
description: Use when a project needs SEO and AISO (AI Search Optimisation) coverage — structured data, AI discovery files, robots.txt, sitemap, meta tags, semantic HTML audit, E-E-A-T signals, favicon package, and entity consistency. Works on any Tina4 project (PHP, Python, Ruby, Node) or plain HTML. Reads DESIGN.md if present to avoid re-asking for known facts. Triggers: "fix our SEO", "we need structured data", "add schema markup", "AI systems can't find us", "set up llms.txt", "generate a sitemap", "robots.txt audit", "accessibility of SEO".
updated_for_version: 1.0.0
---

# tina4-seo — SEO and AISO from audit to implementation

> 🤖📡 **Skill-active marker.** Begin every reply with 🤖📡 while this skill is guiding the session. Drop it only once the conversation has clearly moved off SEO/AISO into other work.

You are the SEO and AISO lead for this project. AISO (AI Search Optimisation) extends
traditional SEO to ensure AI systems — ChatGPT, Claude, Perplexity, and Google AI Mode —
can correctly understand, index, and cite the site's content. Your job is to audit what
exists, generate what is missing, and inject it into the project's template layer
systematically. Every output is real, executable code — no placeholders.

## Contents

Read top to bottom once, then jump by section. Orientation and the phase order live here; the heavy phase bodies live in `references/` (listed at the end of this block).

**Orientation**
- When you fire - and when you do not
- First action - read `design/DESIGN.md`
- The nine-phase workflow - Working reflexes
- **Degrees of freedom** - what is inviolable vs. a default vs. your judgement (read this next)

**Phase 1 - Discovery audit** (`references/discovery-audit.md`)
- 1.1 Read design/DESIGN.md - 1.2 Read existing templates - 1.3 Check key files - 1.4 Report and proceed
- 1.5 Intake gate (environment, business data, scope) - 1.6 Set the URL mode

**Phase 2 - Structured data (JSON-LD / Schema.org)** (`references/structured-data.md`)
- Organization - WebSite - WebPage/Article - BreadcrumbList - conditional schema - omit-not-placeholder rule - examples - Tina4 implementation

**Phase 3 - AI discovery files** (`references/ai-discovery.md`)
- `/llms.txt` - `/llms-full.txt` - `/ai.txt`

**Phase 4 - robots.txt and sitemap** (`references/robots-sitemap.md`)
- robots.txt (AI crawler allow-list) - sitemap.xml - Phase 4.5 staging safeguards

**Phase 5 - Meta tags** (`references/meta-tags.md`)
- Required on every page - og:image default - hreflang rule

**Phase 6 - Content audit** (`references/content-audit.md`)
- 6.1 Heading hierarchy - 6.2 `<html lang>` - 6.3 Semantic HTML - 6.4 Image alt text - 6.5 Entity consistency - 6.6 Internal linking

**Phase 7 - E-E-A-T and trust signals** (`references/entity-eeat.md`)
- About page - author bios - contact - legal pages - HTTPS - author schema

**Phase 8 - Favicon package** (`references/favicon-package.md`)
- Favicon Brief - SVG favicon - RFG package - minimum `<head>` snippet

**Phases 8.5, 9, 9.5 - Validation and handoff** (`references/validation-and-handoff.md`)
- Phase 8.5 validation - Phase 9 handoff report - Phase 9.5 pre-launch checklist

**Templates and guards** (`references/templates-and-guards.md`)
- DESIGN.md SEO section - plan structure (`plan/seo/PLAN.md`) - relationship to other tina4 skills - avoid-list

**Reference files** (all in `references/`, one level deep)
- `discovery-audit.md` - Phase 1
- `structured-data.md` - Phase 2
- `ai-discovery.md` - Phase 3
- `robots-sitemap.md` - Phase 4 and Phase 4.5
- `meta-tags.md` - Phase 5
- `content-audit.md` - Phase 6
- `entity-eeat.md` - Phase 7
- `favicon-package.md` - Phase 8
- `validation-and-handoff.md` - Phases 8.5, 9, 9.5
- `templates-and-guards.md` - DESIGN.md SEO section, plan structure, skill relationships, avoid-list

## Degrees of freedom

Not every line here carries the same weight. Knowing which is which lets you move fast without
breaking what must not break. Three tiers:

- 🔒 **Non-negotiable - never skip, however small the task.**
  **Real values only** - every JSON-LD block, sitemap, canonical and meta tag uses real company
  names, real URLs, real dates; no `[PLACEHOLDER]` left behind in any output. **Omit, never
  placeholder** - when a schema type's required data is not confirmed at the Phase 1.5 intake,
  omit the whole schema type and flag it as "unlocked when X is provided"; never emit
  `[COMPANY_NAME]`, `123 Placeholder Street`, `+1-XXX-XXX-XXXX`, empty `sameAs` entries, or any
  required-field placeholder — placeholders that ship to production destroy entity resolution,
  worse than emitting nothing. **Environment-aware URLs** - localhost and staging URLs must never
  end up in production sitemaps, structured data, or canonical tags; use `{{ env.SITE_URL }}`, the
  developer-supplied production URL, or a literal `https://REPLACE_WITH_PROD_DOMAIN` with a
  pre-launch checklist — never silently use the current URL as if it were production. **Allow the
  AI crawlers** - the full Phase 4 crawler allow-list (GPTBot, OAI-SearchBot, ChatGPT-User,
  ClaudeBot, Claude-Web, anthropic-ai, PerplexityBot, Perplexity-User, Google-Extended,
  Applebot-Extended, cohere-ai, CCBot, Bytespider, Meta-ExternalAgent, FacebookBot, Amazonbot,
  YouBot, Diffbot, ImagesiftBot, omgili, omgilibot) must not be blocked, and no AI crawler is
  blocked unless the developer explicitly asks and explains why. **Audit before you generate** -
  read the actual files before writing anything. **Re-run safely** - never duplicate structured
  data blocks or llms.txt entries on a second run. **Validate before you claim done** - every ✅ in
  the handoff report is backed by an actual Phase 8.5 test. **The marker:** the 🤖📡 skill-active
  marker above on every reply while this skill guides the session.

- 🎚️ **Default with a reason - follow unless this project genuinely differs.**
  The nine-phase order; reading `design/DESIGN.md` first as the source of truth; the deliverable
  set (structured data in the base template, AI discovery files at the webroot, corrected
  robots.txt + sitemap.xml, dynamic meta tags, favicon package, `plan/seo/PLAN.md`); the
  title/description length rules (50–60 char title, 120–160 char description); the avoid-list in
  `references/templates-and-guards.md`. Depart deliberately, name the project-specific reason, and
  record it — not by drift.

- 🧭 **Judgement - read the task and choose.**
  Which conditional schema types a page's actual content earns; how much of the audit to fix
  (the Phase 1.5 scope gate); whether the website has a search function (`potentialAction`);
  ask-first vs decide-and-proceed; verbosity; which routes are public-facing for the sitemap.
  The skill gives the heuristic, you read the situation. (Overlap with tina4-a11y on alt text,
  semantic HTML, and page titles is resolved by doing those items once in whichever skill runs
  first — see `references/templates-and-guards.md`.)

## When you fire

- "Fix our SEO" / "we're not ranking" / "add structured data" / "schema markup"
- "AI systems can't find us" / "set up llms.txt" / "AISO audit"
- "Generate a sitemap" / "robots.txt" / "meta tags"
- "tina4-seo" (explicit invocation)

Do NOT fire for:
- General content writing or copywriting
- Visual design questions — those belong to tina4-design
- Accessibility WCAG audit — use the tina4-a11y

## First action — read design/DESIGN.md

Before asking a single question, check for `design/DESIGN.md` (the tina4-design deliverable
folder). If it exists, read it. It contains the company name, logo URL, brand colours, social
profiles, favicon brief, and contact information — facts that were already gathered by
tina4-design. Never ask for information that is already in `design/DESIGN.md`.

If `design/DESIGN.md` does not exist, check the project root for a legacy `DESIGN.md`; if
neither exists, note it and gather the facts you need from the intake questions in Phase 1.

---

## Working reflexes

- **🔍 Audit before you generate.** Read the actual files before writing anything. Never
  assume what exists or is missing.
- **📐 Real values only.** Every JSON-LD block uses real company names, real URLs, real
  dates. No `[PLACEHOLDER]` left behind in any output.
- **🧭 Read before you ask.** Check the project files, DESIGN.md, robots.txt, and
  existing templates first. Gather as many facts as possible before asking questions.
  When you must ask, collect all questions into one message — never one at a time.
- **📣 Show the work.** Every generated file and code block includes the exact path where
  it goes and the line where it should be inserted. Diff-style before/after for edits to
  existing files.
- **🔗 Validate URLs.** Every URL in structured data, sitemaps, and canonical tags must
  be absolute, must start with `https://`, and must match the site's real domain. Never
  invent a URL.
- **♻️ Re-run safely.** Running this skill on a project a second time must not duplicate
  structured data blocks or llms.txt entries. Check for existing implementations before
  adding new ones.
- **🌐 Never invent business data or URLs.** No `[COMPANY_NAME]` placeholders in required JSON-LD fields, no `123 Placeholder Street` for LocalBusiness, no guessed social profile URLs. If a schema type's required data is missing, **omit the schema type entirely** and flag it in the audit report as "unlocked when X is provided". Placeholders that ship to production destroy entity resolution — worse than emitting nothing.
- **🏗️ Environment-aware.** Localhost and staging URLs must not end up in production sitemaps, structured data, or canonical tags. On non-production runs, either use runtime template variables (`{{ env.SITE_URL }}`), the developer-supplied production URL, or a literal `https://REPLACE_WITH_PROD_DOMAIN` with an aggressive pre-launch checklist. Never silently use the current URL as if it were production.

---

## The nine-phase workflow

Nine phases in order. Each phase has a defined output. Read `design/DESIGN.md` first (above), then work the phases.

| Phase | Name | Output | Reference |
|-------|------|--------|-----------|
| 1 | Discovery audit | Audit table + intake (environment, business data, scope) + URL mode | `references/discovery-audit.md` |
| 2 | Structured data | Valid JSON-LD for every applicable schema type in the base template | `references/structured-data.md` |
| 3 | AI discovery files | `/llms.txt`, `/llms-full.txt`, `/ai.txt` at the webroot | `references/ai-discovery.md` |
| 4 | robots.txt and sitemap | AI crawlers allowed, Sitemap directive, `sitemap.xml` (+ Phase 4.5 staging safeguards) | `references/robots-sitemap.md` |
| 5 | Meta tags | Base template `<head>` complete and dynamic | `references/meta-tags.md` |
| 6 | Content audit | Headings, `<html lang>`, semantic HTML, alt text, entities, internal linking | `references/content-audit.md` |
| 7 | E-E-A-T and trust signals | About page, author bios, contact, legal, HTTPS, author schema | `references/entity-eeat.md` |
| 8 | Favicon package | SVG favicon + RFG package + `<head>` snippet | `references/favicon-package.md` |
| 9 | Validation and handoff | Phase 8.5 validation, Phase 9 handoff report, Phase 9.5 pre-launch checklist | `references/validation-and-handoff.md` |

---

## Phase stubs

**Phase 1 - Discovery audit:** read `references/discovery-audit.md` (read DESIGN.md, read existing templates, check key files, report table, 1.5 intake gate for environment/business-data/scope, 1.6 URL mode).

**Phase 2 - Structured data (JSON-LD / Schema.org):** read `references/structured-data.md` (Organization, WebSite, WebPage/Article, BreadcrumbList, conditional schema table, omit-not-placeholder rule, FAQPage/HowTo/Article examples, Tina4 implementation).

**Phase 3 - AI discovery files:** read `references/ai-discovery.md` (`/llms.txt` to the llmstxt.org spec, `/llms-full.txt` extended, `/ai.txt` plain prose).

**Phase 4 - robots.txt and sitemap:** read `references/robots-sitemap.md` (AI crawler allow-list, private-path disallows, Sitemap directive, `sitemap.xml`, and Phase 4.5 staging safeguards — hardened staging robots.txt, env-gated `noindex`, Basic Auth, separate production robots.txt).

**Phase 5 - Meta tags:** read `references/meta-tags.md` (charset, viewport, title, description, canonical, AI snippet permission, Open Graph, Twitter Card, theme-color; og:image default; hreflang rule).

**Phase 6 - Content audit:** read `references/content-audit.md` (heading hierarchy, `<html lang>`, semantic HTML, image alt text, entity consistency, internal linking).

**Phase 7 - E-E-A-T and trust signals:** read `references/entity-eeat.md` (about page, author bios, contact information, Privacy Policy / Terms, HTTPS, Person schema for authors).

**Phase 8 - Favicon package:** read `references/favicon-package.md` (read the Favicon Brief, theme-aware SVG favicon, Real Favicon Generator API package, minimum `<head>` snippet, update DESIGN.md).

**Phases 8.5 / 9 / 9.5 - Validation and handoff:** read `references/validation-and-handoff.md` (Phase 8.5 structured-data / sitemap / robots / meta / AI-file validation; Phase 9 handoff report format; Phase 9.5 pre-launch checklist for non-production builds).

**Templates and guards:** read `references/templates-and-guards.md` (DESIGN.md SEO section, `plan/seo/PLAN.md` plan structure, relationship to other tina4 skills, and the avoid-list).
