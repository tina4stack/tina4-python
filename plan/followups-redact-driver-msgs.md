# Task: Follow-ups - redact connection URLs, name the missing driver, SOAP parity, mail encryption (ADR-0071)

**Outcome:** no Python log line or exception prints a connection password; a missing boto3 / pymongo
names the package and the install command; the 10 SOAP payloads are measured; the Messenger obeys
ADR-0071 (ssl is TLS on any port, STARTTLS required, certificates verified, unknown value refused).

Branch: `fix/followups-redact-driver-msgs` (from origin/v3). Lab dir: `/home/andre/followup-python`.

## Scope
- [x] Item 1: backplane "connected to" logs use `redact_url` (Redis + NATS)
- [x] Item 1 sweep: MQTT `parse_url` errors echo the raw URL -> `redact_url`
- [x] Item 2: S3Storage names boto3 + install command; select_storage warning carries it
- [x] Item 2: mongodb cache fallback warning appends the pymongo install hint ONLY when pymongo is missing
- [x] Item 7: 10 SOAP payloads (+2 from the coordinator: UTF-7 DOCTYPE, UTF-16LE without BOM) through the real Request -> WSDL.handle path
- [x] Item 7 defect: UTF-16LE without a BOM EXPANDED a DTD entity -> refuse non-plain-UTF-8 bodies (PHP rule)
- [x] Item 8: ADR-0071 - SMTP transport table, STARTTLS required, verified certs (SMTP + IMAP), unknown value raises

## Parity
| Item | Python |
|------|--------|
| 1 redact backplane URL | ✅ |
| 2 driver install hints | ✅ |
| 7 SOAP parity table     | ✅ (12/12, no EXPANDED) |
| 8 ADR-0071              | ✅ |

## Tests (written first, real - no mocks, positive + negative)
- [x] backplane log never contains the password (real password Redis, real logger) + real pub/sub round trip
- [x] MQTT malformed-URL errors never contain the password
- [x] S3Storage without boto3 (python -S subprocess) raises the install message; select_storage falls back and warns with it
- [x] mongodb cache without pymongo (python -S subprocess) warns with the install hint
- [x] negative control: pymongo present + unreachable Mongo -> no install hint
- [x] ADR-0071 transport table (pure logic), unknown value raises (SMTP + IMAP)
- [x] ssl on a non-465 implicit-TLS port delivers; ssl on a plaintext port fails
- [x] tls against a server without STARTTLS fails; none never upgrades
- [x] untrusted CA fails (SMTP implicit, SMTP STARTTLS, IMAPS, IMAP STARTTLS); trusted via SSL_CERT_FILE succeeds

## Bugs
- [x] backplane logs the raw TINA4_WS_BACKPLANE_URL (password included)
- [x] MQTT parse_url errors echo the raw URL (password included)
- [x] S3Storage missing boto3 -> bare ModuleNotFoundError, no install command
- [x] mongodb cache fallback never says pymongo is missing
- [x] Messenger: ssl on a non-465 port sends in cleartext
- [x] Messenger: SMTP / IMAP TLS never verifies certificates
- [x] Messenger: unknown encryption value silently means plaintext; IMAP unknown value falls back to port logic
- [x] WSDL: a UTF-16LE body without a BOM bypassed the DOCTYPE guard and EXPANDED an internal entity

## Commits
- dfd2560  fix(security): never log a backplane or MQTT URL with its password
- ab825ce  fix(storage,cache): a missing boto3 / pymongo names the package and the install command
- 173edf4  fix(messenger): ADR-0071 - ssl is TLS on any port, STARTTLS required, certificates verified
- e11f652  fix(wsdl): refuse a SOAP body that is not plain UTF-8 before any parse
- 7fa6b3b  fix(wsdl): accept only encoding="UTF-8" (any case) and check the RAW request bytes

Red-first: every new test ran red on the lab against the unfixed tree; 14 mutations
(break each fix) all turned their tests red (lab log /home/andre/followup-python-mutation.log).

## Notes
- Not tested live: NATSBackplane (same one-line redaction; no NATS server on the lab or in CI).
- `redact_url` needs a `scheme://`; a scheme-less MQTT url (`user:pw@host:x`) is not redacted.
- Tina4 CLI `tina4/src/env_config.rs` still lists TINA4_MAIL_TLS_INSECURE (withdrawn by ADR-0071).
- Breaking on purpose (WSDL): a UTF-8-BOM body and an ASCII body declaring ISO-8859-1 are now refused (Malformed XML).

## Status: Complete (full lab suite at the pushed HEAD: see the follow-ups report)
