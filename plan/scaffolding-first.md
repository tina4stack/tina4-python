# Plan: Scaffolding-first — a generator for every feature, with `# your code here` placeholders

## Why
The 3.13.60 skills eval (`evaluate-skills/run-3.13.60/TAKEAWAYS.md` §6) proved the token-efficient,
correct pattern: **deterministic scaffolding for the ~80% boilerplate + a grounded model for the ~20%
custom logic — no stochastic model in the boilerplate path.** Today that isn't fully deliverable:
1. **Skills don't lead with scaffolding.** The reuse ladder says "does Tina4 already do it" but never
   "scaffold it first with `tina4 generate`". Scaffolding is buried, not the default move.
2. **Generators don't leave placeholders.** `generate route` emits *full* CRUD logic (or nothing for a
   custom route) — there's no clear `# your code here` marker telling the AI/dev exactly where the
   custom 20% goes. So the model rewrites the whole thing instead of filling a gap.
3. **Coverage is uneven.** Generators exist for model/route/crud/migration/middleware/test/form/view/
   auth — but NOT for service (scheduler), queue (producer/consumer), validator, seeder, websocket,
   event listener, mcp-tool, cache, i18n, graphql, email. "Scaffolding for every feature" is unmet.
4. **The scaffolder repeats the secure-by-default footgun** — `generate route --model` puts `@noauth()`
   on the `create` (POST) handler (cli/__init__.py:857): public writes, same bug we just fixed in
   AutoCrud. The scaffolder must be secure-by-default too.

## The three pillars

### A. The AI-FILL placeholder convention (the core idea)  — SHIPPED (python `c0b2085`)
Every generated file scaffolds the *wiring* (imports, decorator, signature, registration) and marks
the *custom logic* with ONE unmistakable, AI-fillable block — a tight fill-spec, not a bare `# TODO`:
```python
    # ─── AI-FILL: create_product ─────────────────────────────────────
    # Intent:  validate the body and persist a new product
    # Given:   request.body -> dict of fields
    # Use:     Product.create(request.body)   (a REAL, grounded symbol)
    # Return:  response(item.to_dict(), 201)
    # Ground:  tina4_context("create ORM record and return 201", "python")
    raise NotImplementedError("create_product: persist and return the new record")
    # ─────────────────────────────────────────────────────────────────
```
Rationale: `raise NotImplementedError` makes an unfilled scaffold **fail loudly** (never silently ship
a stub); the greppable `AI-FILL` banner lets a human or agent jump to every gap; and the
`Intent/Given/Use/Return/Ground` spec (≤6 lines, `Use:` naming only symbols verified in live source)
means an AI completes it *correctly and idiomatically* instead of guessing — the scaffold itself is an
anti-drift anchor. CRUD-shaped generators (crud/form/view + `route --model`) emit working code (the
boilerplate IS the feature) with a lighter `# ─── EXTEND ───` marker at the extension point; logic-shaped
generators (custom route, service, queue consumer, validator, seeder, websocket, listener) emit wiring +
the AI-FILL placeholder. Implemented via the `_ai_fill()` / `_extend()` helpers in `cli/__init__.py`.

### B. A generator for every feature (fill the gaps), each secure-by-default
| Feature | Command | Scaffolds (wiring) | Placeholder holds |
|---|---|---|---|
| custom route | `generate route <name>` (no --model) | decorator + `@secured` on writes + signature | the handler body |
| service/scheduler | `generate service <Name> --every 5m` | `ServiceRunner.register(...)` + fn | the task body |
| queue | `generate queue <topic>` | producer `.push()` + consumer `.consume()` + `job.complete()` | the consume body |
| validator | `generate validator <Name>` | `Validator` rules skeleton | the rule set |
| seeder | `generate seeder <Model>` | `FakeData` loop + `seed_orm` | the field mapping |
| websocket | `generate websocket <path>` | `on_message`/`broadcast` handler | the message body |
| listener | `generate listener <event>` | `@on("<event>")` + signature | the reaction body |
| mcp-tool | `generate mcp-tool <name>` | `McpServer`/`mcp_tool` registration | the tool body |
Reuse ladder still applies: e.g. `crud` remains AutoCrud-first; a generated custom route is for the
cases AutoCrud can't express (the §6 custom 20%: ordering, auth nuance, business rules).

### C. Skills lead with scaffolding
- **Working Method**: insert a **Scaffold** step before Build — "scaffold the boilerplate with
  `tina4 generate <feature>`, then fill only the `# your code here` placeholder." Update the phase table.
- **Reuse ladder**: new rung near the top — *"Can a generator scaffold it? `tina4 generate <feature>`
  → then fill the placeholder."* — above "write the minimum".
- Document the full `generate` surface + the placeholder convention + the "boilerplate deterministic,
  custom grounded" split from the eval. All 4 dev skills + maintainer.

## Fix carried along
Remove `@noauth()` from the write handler(s) the route generator emits (secure-by-default), mirroring
the 3.13.62/63 AutoCrud fix. A `--public` flag is the explicit opt-out, same as AutoCrud's `public=True`.

## Scope / sequencing
- **Reference: python first**, then parity to php/ruby/node (each framework's generator + templates).
- **MVP order (highest leverage first):** (1) placeholder convention + fix the route-generator footgun;
  (2) skills scaffolding emphasis (the adoption lever — cheap, immediate); (3) the missing generators
  (service, queue, validator, seeder, websocket, listener), one at a time with a REAL test that the
  generated file imports/registers and the placeholder raises NotImplementedError; (4) parity.

## Tests (real, no mocks)
Per generator: run it into a temp project, assert the file exists at the convention path, **imports
cleanly**, registers its route/service/consumer, and the placeholder raises `NotImplementedError`
until filled. Secure-by-default: a generated write route has no `_noauth` unless `--public`.

## Status
- [x] **Python MVP shipped** — `feat/scaffolding-first` `c0b2085`: secure-by-default `_gen_route`
  (`@noauth` gone from reads+create; `--public` opt-in on writes only; auth generator left public),
  AI-FILL convention (`_ai_fill`/`_extend`), 6 new generators (service/queue/validator/seeder/
  websocket/listener). Tests: 58 scaffolding + full suite **3354 passed / 0 failed** (independently
  re-run). tina4_context MCP was unreachable → grounded on skill + live source (every symbol file:line'd).
- [x] Skills scaffolding emphasis (this file's SKILL.md edits).
- [ ] **Parity** — php / ruby / node workers in flight (`feat/scaffolding-first` off `v3` each).
- [ ] Verify parity suites · update all skills + docs · release + validate · reindex corpus.
```
