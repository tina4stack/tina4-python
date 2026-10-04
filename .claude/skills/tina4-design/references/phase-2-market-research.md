# Phase 2 - Market Research

> Reference for the `tina4-design` skill: Phase 2 (competitors, colour, typography, motion). Moved out of `SKILL.md` unchanged.

## Phase 2 — Market Research

Do not skip this phase. A well-chosen serif for a law firm and the same serif for a children's toymaker are opposite decisions. The research is what makes one defensible and the other wrong.

### 2.1 Competitor and sector landscape

Use web search to find 4–6 direct competitors or analogous brands in the same industry. For each, note:
- Primary colour palette (dominant hue, secondary, neutral ground)
- Typeface category (geometric sans, humanist sans, slab serif, transitional serif, display/expressive)
- Overall visual register: minimal / bold / warm / technical / playful / premium / utilitarian
- Industry-wide visual conventions — patterns that repeat across most brands in the sector (these exist in almost every mature industry)

Summarise with a single sentence:

> **"The [industry] sector leans [X]. This client should sit [Y] relative to that because [Z]."**

That sentence goes into `DESIGN.md` as the design thesis.

### 2.2 Colour direction

Research how colour functions in this specific sector. Don't apply generic colour psychology — apply sector-specific logic:

| Sector | Colour conventions and their meanings |
|--------|--------------------------------------|
| Hardware / industrial | Amber and yellow read as high-visibility and safety; dark charcoal reads as durability and precision; orange reads as trade and DIY |
| Fintech / banking | Deep navy and charcoal read as stability; bright accent reads as innovation; green reads as growth |
| Healthcare / wellness | White and light blue read as clinical trust; green reads as wellness and nature; earth tones read as holistic |
| Food & beverage | Warm reds and oranges read as appetite and energy; black and gold read as premium; green reads as fresh and natural |
| Legal / professional services | Navy, dark grey, and gold read as authority; serif faces read as establishment |
| Education / EdTech | Blue and purple read as knowledge and creativity; high contrast reads as clarity |
| SaaS / tech | Blues and purples dominate; clean sans-serif is expected; the differentiator is in the accent and the warmth of the neutral |
| Retail | Depends heavily on price-point: discount uses bold primaries and high contrast; premium uses restraint and white space |

State the specific palette direction with a sentence grounded in the sector research, not in preference.

### 2.3 Typography research

Research typeface choices in the sector. Identify:
- What typeface categories the sector's strongest brands use
- What following the category convention costs vs. gains (safety vs. sameness)
- Whether the client's brand personality is better served by a structural/geometric face, a humanist face, a serif, or something expressive

Choose **exactly two typefaces** at this phase:
- **Display / heading**: carries the brand's personality; used at large scale for section headers, hero text, product names; can afford more character
- **Body / UI**: carries information at reading size (14–16px); must be legible at small sizes, on screen and in print; usually a humanist sans or a clear geometric sans

**Rules:**
- Both must be available on Google Fonts. Verify before recommending — load the URL `https://fonts.googleapis.com/css2?family=[Name]` to confirm.
- Declare real fallback stacks: `'Oswald', 'Arial Narrow', sans-serif` — never leave the fallback as just `sans-serif`.
- Never recommend Inter or Space Grotesk as the default "safe" choice. If the sector genuinely calls for them, name the reason.
- The display and body faces must pair deliberately — they should have a clear personality difference that serves a purpose (authority vs. legibility, character vs. clarity).

### 2.4 Motion personality

Research what motion should feel like for this brand. This is separate from timing tokens — those say *how fast*; motion personality says *what it feels like*. A one-sentence motion statement goes into `DESIGN.md` alongside the design thesis and governs every animation decision in the UI guide.

Map the brand's personality to a motion signature:

| Brand personality | Motion signature | Avoid |
|------------------|-----------------|-------|
| Industrial / technical / trade | Functional, precise — enter/exit only, no spring, no overshoot. Motion confirms an action; it doesn't entertain. | Bounce, delayed cascades, anything decorative |
| Professional / B2B services | Composed, efficient — short durations, clean ease-out. Fast enough to feel snappy, slow enough to feel considered. | Springy easing, playful micro-interactions |
| Consumer / lifestyle | Warm, inviting — gentle spring on entrances, slight overshoot on interactive feedback. Motion adds personality. | Robotic linear timing, jarring cuts |
| Premium / luxury | Deliberate, unhurried — longer durations, silky ease-in-out. Never rushed. Each transition is a small ceremony. | Fast snaps, bouncy easing, too many simultaneous animations |
| SaaS / productivity tool | Fast and invisible — motion gets out of the way. Transitions are below 150ms where possible. | Long reveals, staggered cascades, anything that slows the workflow |

State the motion personality as one sentence: *"[Brand] motion is [adjective] — [rule]. [What to avoid]."*
Example: *"Elkanah motion is functional — transitions confirm state changes and nothing more. Never decorative."*

### 2.5 Research summary

Write a compact summary covering all five points above. Store it in `DESIGN.md` under `## Market Research`. This is the "why" behind every Phase 3 decision. When someone asks "why did we choose these colours?" or "why does the UI move like this?" the answer is in this section.
