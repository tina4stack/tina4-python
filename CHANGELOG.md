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

- **MQTT 3.1.1 client** (`Mqtt` / `MqttMessage`), zero-dependency (stdlib `socket`/`struct`/`ssl`),
  verified against a real broker with no mocks. Publish/subscribe/consume, QoS 0/1, retained, Last
  Will, per-client TLS, QoS 2 refused loudly. Takes the family to **98 built-in features**.

3.13.83 is prepared on `v3` and not yet tagged; its full notes ship in the release notes linked
above when it is tagged. The current tagged release is 3.13.82.

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

- **Security: the bundled Swagger UI static assets now honour the swagger gate.** `/swagger`,
  `/swagger/`, `/swagger/index.html` and `/swagger/oauth2-redirect.html` were served from the
  framework's own public directory BEFORE route matching (with directory-index resolution turning
  `/swagger` into `swagger/index.html`), so a production server with `TINA4_SWAGGER_ENABLED=false`
  still served the whole UI while `/swagger/openapi.json` correctly 404'd. Static serving now checks
  the gate before it resolves an index. Bite-verified lock-in test. (python#97)
- **The startup banner advertises only a surface that answers.** The `Swagger:` and `Dashboard:`
  rows printed unconditionally, so a production log claimed a dev surface was exposed and a
  developer following the link hit a 404. Each row is now built by one pure helper of
  (port, swagger_enabled, dev_admin_enabled), unit tested rather than inferred from stdout.
  (python#99)
- **MQTT TLS tests verify the CA before trusting it.** A stale CA file in the shared temp directory
  made six TLS tests FAIL instead of skip, in all four frameworks, pointing at correct TLS code.
  The suites now confirm the CA actually validates the broker certificate before treating the TLS
  environment as present. (python#98)

