# Bubble Chart Enhancement — Interactive Dependency Visualisation

## What It Does

The dev admin metrics bubble chart becomes an interactive force-directed graph showing module health, size, and dependencies at a glance.

## Spec

### Bubbles
- **Size** = LOC or cyclomatic complexity (existing)
- **Colour** = composite health score (green → red gradient)
  - Inputs: complexity (lower = greener), test coverage (tested = greener), dependency count (fewer = greener)
  - Deep green = low complexity + tested + few/no dependencies
  - Deep red = high complexity + untested + many dependencies
  - Gradient between for everything else
- **Ⓣ marker** inside the bubble = matching test file exists
  - `tina4_python/auth/__init__.py` → looks for `tests/test_auth.py`
  - Marker is a circled "T" rendered as SVG text inside the bubble
  - No marker = no tests (immediately visible which modules lack coverage)
- **Ⓓ marker** inside the bubble = has dependencies (imports other modules)
  - Shows which modules are coupled vs standalone
  - Bubble with both Ⓣ and Ⓓ = tested and has dependencies
  - Bubble with Ⓓ but no Ⓣ = coupled AND untested (high risk)

### Arrows
- A → B when module A imports/uses module B
- Direction shows dependency flow
- Data source: `dependency_graph` already collected by metrics tool

### Elastic Lines
- Arrows behave like rubber bands / springs
- Connected bubbles have spring tension between them
- Tightly coupled modules naturally cluster together
- Loosely coupled modules drift apart

### Drag Interaction
- Grab any bubble and drag it
- Connected bubbles follow with spring tension
- Release — everything settles back to force-directed equilibrium
- Lets developer visually inspect what a module is connected to

### Force-Directed Layout
- Bubbles repel each other (charge force)
- Arrows pull connected bubbles together (spring force)
- Equilibrium = natural clustering by coupling
- No external deps — built with vanilla JS + SVG in dev admin

## Data Available (no new collection needed)

The metrics `full_analysis()` already returns:
- `file_metrics[]` — per-file LOC, complexity, maintainability
- `dependency_graph{}` — import/require graph (who imports whom)
- `most_complex_functions[]` — hotspot data

New data needed:
- `has_tests: bool` — does a matching test file exist? (file-based lookup, no tooling)
- `has_docs: bool` — does the file have docstrings? (AST check, already parsed)

## Implementation

All changes are in the dev admin JS (the bubble chart renderer):
1. Add SVG arrow markers between connected bubbles
2. Implement simple force simulation (repulsion + spring attraction)
3. Add drag handlers (mousedown/mousemove/mouseup)
4. Colour bubbles based on test file existence
5. Animation loop: requestAnimationFrame for smooth physics

## Zero Dependencies

No D3, no external libs. Vanilla JS + SVG + requestAnimationFrame.
The physics is ~50 lines (Coulomb repulsion + Hooke spring + velocity damping).

## Applies To

All 4 frameworks — same dev admin JS in Python, PHP, Ruby, Node.js.
