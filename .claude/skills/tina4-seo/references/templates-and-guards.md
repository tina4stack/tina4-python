# Templates and guards

> Reference for the `tina4-seo` skill: DESIGN.md SEO section, plan structure, relationship to other tina4 skills, and the avoid-list. Moved out of `SKILL.md` unchanged.

## DESIGN.md SEO section

Append the following to `design/DESIGN.md` once the audit is complete:

```markdown
## SEO/AISO

### Structured data
- Organization ID: https://[domain]/#organization
- Schema types implemented: [list]
- Schema types not applicable: [list with reason]

### AI discovery
- /llms.txt: [date generated]
- /llms-full.txt: [date generated]

### Key SEO decisions
- [date]: [decision] — [reason]
```

---

## Plan structure

Create `plan/seo/PLAN.md` in the project:

```markdown
# SEO/AISO Plan — [Project Name]

**Outcome:** Full SEO and AISO coverage — structured data, AI discovery files, corrected
robots.txt and sitemap, meta tags in base template, content audit complete, favicon package
generated.

## Scope
- [ ] Phase 1: Discovery audit complete — current state documented
- [ ] Phase 1.5: Intake gate — environment + business data + scope locked
- [ ] Phase 1.6: URL mode decided and recorded
- [ ] Phase 2: Structured data — applicable schema types generated (skipped types recorded as "unlocked when")
- [ ] Phase 3: AI discovery files — llms.txt, llms-full.txt, ai.txt created
- [ ] Phase 4: robots.txt — AI crawlers allowed; sitemap.xml generated (or deferred for non-prod)
- [ ] Phase 4.5: Staging safeguards (only if environment = staging)
- [ ] Phase 5: Meta tags — base template complete and dynamic
- [ ] Phase 6: Content audit — headings, semantic HTML, alt text, entities, linking
- [ ] Phase 7: E-E-A-T signals — about page, authors, contact, legal, HTTPS confirmed
- [ ] Phase 8: Favicon package — SVG + RFG package generated and linked
- [ ] Phase 9: Handoff report — DESIGN.md updated, full report delivered
- [ ] Phase 9.5: Pre-launch checklist written (only if environment != production)

## Bugs
(none yet)

## Commits
(none yet)

## Status: Not Started
```

---

## Relationship to other tina4 skills

| Skill | Relationship |
|-------|-------------|
| **tina4-design** | Runs first. tina4-seo reads DESIGN.md as its source of truth — company name, logo, colours, social profiles, favicon brief. Never duplicate intake. |
| **tina4-developer-*** | Implements the template changes. tina4-seo tells the developer what to add and where; the developer skill handles framework-specific wiring. |
| **tina4-a11y** | Handles WCAG 2.1 AA compliance — keyboard navigation, ARIA states, focus indicators, `<html lang="...">`. Overlap with tina4-seo on alt text, semantic HTML, and page titles — if both are running, do those items once in whichever runs first. |

## Avoid these defaults

- Do not generate structured data without reading the actual page content first — invented
  schema facts do more harm than no schema
- Do not add `noindex` or `noai` meta tags anywhere unless the developer explicitly confirms
  a page should be excluded
- Do not hotlink to the logo URL in structured data without confirming the URL is permanent
  and publicly accessible (not a local dev URL, not a signed CDN URL)
- Do not block any AI crawler in robots.txt unless the developer explicitly asks for it and
  explains why
- Do not generate a sitemap entry for authenticated, admin, or checkout pages
- Do not emit `[COMPANY_NAME]` or `123 Placeholder Street` literals in required JSON-LD fields — omit the schema type entirely instead
- Do not use the current localhost or staging URL as if it were production — use `{{ env.SITE_URL }}` or `https://REPLACE_WITH_PROD_DOMAIN` with a pre-launch checklist
- Do not emit `LocalBusiness`, `Product`, `Person`, or `AggregateRating` schema unless the developer confirmed the required data at Phase 1.5 intake
- Do not put a live `Sitemap:` directive in a staging `robots.txt` — staging must be non-indexable
