# Phase 7 - E-E-A-T and trust signals

> Reference for the `tina4-seo` skill: Phase 7 (E-E-A-T and trust signals). Moved out of `SKILL.md` unchanged.

## Phase 7 — E-E-A-T and trust signals

E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness) is how AI systems and
Google decide whether content can be trusted and cited. Audit and flag:

1. **About page** — exists and is linked from the main navigation? Describes who runs the
   site, their credentials, and the company's history? If missing, flag it and write a
   brief for the developer: what the page should cover.

2. **Author bios** — if the site has a blog, every post links to a named author with a bio
   page that includes credentials. Flag any posts with anonymous bylines.

3. **Contact information** — a real contact method (email, phone, or form) is reachable
   from every page, ideally in the footer. Flag if absent.

4. **Privacy Policy and Terms of Service** — both exist at stable URLs and are linked from
   the footer. Flag if either is missing.

5. **HTTPS** — confirm the site is served entirely over HTTPS. Note any mixed-content
   warnings in the template (http:// asset URLs).

6. **Structured data for authors** — if blog posts exist, generate Person schema for each
   named author linked from their bio page.
