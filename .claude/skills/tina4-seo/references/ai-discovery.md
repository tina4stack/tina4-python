# Phase 3 - AI discovery files

> Reference for the `tina4-seo` skill: Phase 3 (AI discovery files — llms.txt, llms-full.txt, ai.txt). Moved out of `SKILL.md` unchanged.

## Phase 3 — AI discovery files

These files tell AI crawlers what the site is and what it contains before they read a page.
They go at the webroot — in Tina4 projects this is the `src/public/` directory.

### `/llms.txt`

Following the llmstxt.org specification exactly:

```
# [Company name]

> [One paragraph: what the site does, who it serves, and what value it provides.
  Written for an AI system reading it as authoritative context, not a marketing tagline.
  Active voice. Specific. Names the product or service clearly.]

## Key pages
- [Page title]: [absolute URL]
  [One sentence: what this page contains and why it matters for understanding the business]

(repeat for every important page — homepage, about, key product/service pages, contact)

## About
[2–3 sentences about the organisation, its founding, its authority on its topic, and
any credentials or track record relevant to AI citation trustworthiness]

## Contact
[email address or contact URL]
```

Ask for the site purpose and key page descriptions if they cannot be read from the project
files or DESIGN.md.

### `/llms-full.txt`

Extended version for deeper AI indexing. Follows the same format but expands each section:

- Full description of each key page (3–5 sentences)
- Key facts, statistics, or claims the site makes that AI systems should be able to cite
- Author or contributor names and their expertise
- Common questions and their complete answers (draws from any FAQ content found)
- Glossary of product or industry terms the site uses

### `/ai.txt`

One paragraph in plain prose — organisation name, what the site does, who it serves, and
the preferred contact for AI-related enquiries. Format is not yet standardised; keep it
brief and factual.
