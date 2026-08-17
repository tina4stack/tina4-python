# Release 3.13.104: GIS and OIDC SSO

## Outcome

Ship Feature 137 GIS and Feature 136 configuration-first OIDC SSO at four-language
parity. Python is the GIS reference and consumes the same fixtures as every mirror.

## Scope

- [ ] Replay GIS Point/PointField on current v3
- [ ] Run the shared GIS fixture against real PostGIS
- [ ] Implement OIDC SSO from the approved shared contract
- [ ] Run the shared SSO fixture against real Keycloak and Session storage
- [ ] Update exports, examples, skills and release notes

## Parity

| Feature | Python | PHP | Ruby | Node.js |
| --- | --- | --- | --- | --- |
| GIS | In progress | Owed | Owed | Owed |
| SSO | Owed | Owed | Owed | Owed |

## Tests: real services, positive and negative, no mocks

- [ ] `gis_contract.json`: real PostGIS, fixture read at runtime
- [ ] `sso_contract.json`: real Keycloak, socket and Session provider
- [ ] Named negative controls and mutations turn red
- [ ] Full suite green at release HEAD

## Bugs

- [ ] Record reproduced defects here and close them with regressions

## Commits

- (none)

## Status: In progress

