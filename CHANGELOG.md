# Changelog

Tina4 keeps ONE version across all four frameworks (Python, PHP, Ruby, Node.js), so a version
number means the same thing everywhere.

**The authoritative release notes for every shipped version live in the documentation:**
https://tina4.com/python/36-releases

This file is deliberately NOT a copy of those notes. Duplicating them is exactly how a
changelog rots into claiming a version that was never cut, so this file records only
UNRELEASED work. When a version ships, its notes go to the release notes above.

## Unreleased

Nothing pending on `v3`. The current release is 3.13.81.

In-flight on a feature branch, not yet merged to `v3`:

- `feature/spatial-gis` - `PointField` (SRID-aware, WKT/EWKT/GeoJSON/WKB in, immutable
  lon-first `Point` out), engine-aware spatial DDL with a GiST index, `within_distance()`,
  `order_by_distance()`, `select_distance()`, `intersects()`, `bbox()`, and GeoJSON
  Feature/FeatureCollection output. PostGIS-first; a spatial field on an engine without
  spatial support raises rather than silently creating a wrong column.
- `feature/spatial-gis` - **Fixed** `order_by_distance()` was non-deterministic for
  equidistant rows (distance alone is not a total order and PostgreSQL's sort is not stable),
  which made keyset pagination skip and repeat rows. Now has a stable tiebreak.
