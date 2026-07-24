# Changelog

Tina4 keeps ONE version across all four frameworks (Python, PHP, Ruby, Node.js), so a version
number means the same thing everywhere.

**The authoritative release notes for every shipped version live in the documentation:**
https://tina4.com/python/36-releases

This file is deliberately NOT a copy of those notes. Duplicating them is exactly how a
changelog rots into claiming a version that was never cut, so this file records only
UNRELEASED work. When a version ships, its notes go to the release notes above.

## Unreleased

### Added

3.13.85 is prepared on `v3` and not yet tagged; its full notes ship in the release notes
linked above when it is tagged. The current tagged release is 3.13.84.

In-flight on a feature branch, not yet merged to `v3`:

- `feature/spatial-gis` - `PointField` (SRID-aware, WKT/EWKT/GeoJSON/WKB in, immutable
  lon-first `Point` out), engine-aware spatial DDL with a GiST index, `within_distance()`,
  `order_by_distance()`, `select_distance()`, `intersects()`, `bbox()`, and GeoJSON
  Feature/FeatureCollection output. PostGIS-first; a spatial field on an engine without
  spatial support raises rather than silently creating a wrong column.
- `feature/spatial-gis` - **Fixed** `order_by_distance()` was non-deterministic for
  equidistant rows (distance alone is not a total order and PostgreSQL's sort is not stable),
  which made keyset pagination skip and repeat rows. Now has a stable tiebreak.

### Fixed

- **`tina4 deploy docker` produced images that could not start.** Of the eight
  Dockerfile generators in the stack (four templates in the `tina4` CLI plus one
  in each framework's own CLI), exactly one was correct. Python named
  `python -m tina4_python.cli`, a package with no `__main__.py`, so the container
  died on startup; PHP ran `php index.php <addr>`, but `App::run(?host, port)`
  never reads argv so the address was dropped and production never engaged;
  Node named a path that exists only inside the tina4-nodejs monorepo and
  depended on tsx, which `npm ci --omit=dev` strips. Every generator now names a
  published entry point and requests production. Verified by scaffolding,
  generating, building and running a container for all four languages.
- **`serve` no longer kills PID 1.** The port-reclaim step read `lsof -ti`
  without validating it. Where lsof prints a different shape, a non-numeric field
  coerced to 0 or 1 -- and signalling PID 0 hits every process in the caller's
  own process group. In a container the server IS PID 1, so it killed itself
  (Node logged "Killed existing process on port 7148 (PID: 1 ...)" then exited
  143; PHP logged the same attempt and survived by luck). Reclaiming is now
  skipped inside a container, only all-digit PIDs are accepted, and PID 0, PID 1
  and the current process are never signalled.
