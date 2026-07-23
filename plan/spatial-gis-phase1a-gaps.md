# Task: Spatial Phase 1a — gap tests, select_distance(), intersects()/bbox()

Follow-up to `feature/spatial-gis` e2f0768 (PointField + PostGIS DDL/predicates/GeoJSON).
Closes the remaining Phase 1a checkboxes in
`/Users/andrevanzuydam/IdeaProjects/plan/v3/iot-and-ev-charging.md` and the nine
untested cases from `/Users/andrevanzuydam/IdeaProjects/plan/v3/iot-gis-test-plan.md`.

Branch: `feature/spatial-gis` only. Python master; PHP / Ruby / Node mirrors follow.

## Scope

### Part 1 — the nine missing tests (zero coverage today)
- [x] A1  lat/lon swap is decisive (swapped CPT is 8 021 km away, not < 1 000 km)
- [x] C2  circle, not bounding box (inside the bbox corner, outside the circle)
- [x] C4  antimeridian: 179.9 -> -179.9 at lat 0 is ~22 km, not ~40 000 km
- [x] C5  poles: lat 89.999 distance + radius are finite and sensible
- [x] B5b NULL point is not Null Island (query side)
- [x] B4  SRID mismatch is rejected, not silently reprojected
- [x] C3b deterministic ordering for EQUIDISTANT rows (pagination safety)
- [x] C7  the GiST index is actually used (EXPLAIN, not a seq scan)
- [x] B1b 7-decimal-place coordinates survive store + reload exactly

### Part 2 — the three flagged issues
- [x] `select_distance()` + `_select_params` (SELECT params bind BEFORE where/order)
- [x] `count()` ORDER BY drop — kept, `Breaking:` note in the commit body
- [x] `create_table()` raises for spatial models — kept, contract narrowed in the docstring

### Part 3 — finish Phase 1a
- [x] `intersects(column, geometry)` through the SQLTranslator, coordinates bound
- [x] `bbox(column, min_lon, min_lat, max_lon, max_lat)` likewise

## Real bugs found (proved against real PostGIS BEFORE fixing)
- [x] **`order_by_distance()` ordering was non-deterministic for equidistant rows.**
      Probe: 12 rows at one location, `ORDER BY ST_Distance(...)`, ids
      `[1..12]`; a plain `UPDATE` on three of them (MVCC moves the rows to the
      end of the heap) re-ordered the result to `[4..12, 1, 2, 3]`. Paging over
      that skips and repeats rows. Fixed with a stable secondary sort key (the
      model primary key, supplied by `ORM.query()`); re-probed stable.

## Non-bugs confirmed (the predicate was already right)
- The `ST_DWithin(col, ST_SetSRID(ST_MakePoint(?,?),4326)::geography, ?)`
  predicate DOES use the GiST index: `Index Scan` on
  `spatial_site_location_gist`, 1.7 ms over 5 000 rows; dropping the index
  gives `Seq Scan`, 145 ms. No predicate change needed — C7 locks it in.

## Tests (real PostGIS 16-3.4, no mocks, positive + negative)
tests/test_spatial.py 125 -> 278 (+153). Every new test was confirmed able to FAIL for
its stated reason: 12 one-at-a-time framework mutations, each turning its own tests red
before being reverted. Two first-pass mutations were themselves unfaithful (a geography
`&&`/`_ST_Expand` box is geocentric, not a degree box; a `geometry(Point,...)` column is
still auto-promoted to geography beside a geography literal) and were rewritten rather
than accepted as green. One same-byte-length mutation was masked by CPython's
second-granularity `.pyc` validity check until the harness purged `__pycache__`.

## Verified
macOS (darwin 25.5.0), Python 3.13, PostGIS 16-3.4 + SQLite:
- tests/test_spatial.py 278 passed
- full suite 3810 passed / 111 skipped vs the e2f0768 baseline of 3657 / 111 in the same
  environment (+153, no regressions, identical skip count)
- ruff: no new findings (the 8 pre-existing in orm/model.py are unchanged at HEAD)

## Commits
- 83c712a  select_distance()/_select_params, intersects()/bbox(), stable distance
           ordering tie-break, narrowed create_table() contract, +153 real PostGIS tests

## Status: DONE (Python master). Mirrors to PHP / Ruby / Node still open.
