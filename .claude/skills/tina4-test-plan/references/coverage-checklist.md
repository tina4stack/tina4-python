# Coverage checklist for a manual test plan

A plan that only checks "page loads and happy path works" is a smoke test. Before building the spec,
walk this list against the app and add sections for every item that applies. Derive the page list from
the router / nav / API routes, never from memory, then diff it against the plan.

## Discovery (do first)
- List every route in the frontend router and every API endpoint (`tina4 routes` in a Tina4 project).
  Each user-facing page needs a section; each state-changing endpoint needs at least one case (directly
  or via its page).
- Read the project's plan/ docs, recent commits and `git status` to find recently changed areas; mark them
  as regression priority.
- Identify roles and permission sets, the flows that move money or stock if the app has them, and every
  email the app sends.

## Per page
- Loads with real figures (state the expected value from seed data, not "figures render").
- Search / filter / paginate / empty state / no-results state.
- Create, edit (reload and confirm persisted), delete or deactivate, reactivate.
- Validation: blank required fields, duplicates, very long input, special characters and emoji,
  HTML / script and SQL-looking input, negative / zero / decimal / huge numbers, leading/trailing spaces.
- Double-click submit creates one record; lost connection during submit neither loses nor duplicates.

## Authorisation and scope (usually missing from naive plans)
- Each role opening each other portal / admin URL directly: refused cleanly.
- API called without a token, with an expired token, and with the wrong role's token: 401/403, no data.
- Object-level access: change IDs in URLs and API paths to another user's / customer's / team's records.
- Read-only permission: buttons hidden AND the write endpoint refuses.
- Privilege escalation (granting oneself a role); impersonation / role switching and its audit log.
- Sensitive fields (cost prices, other customers' data) absent from every lower-privilege response,
  including AI assistants and exports.

## Tina4 specifics (read the route source, do not guess)
- Write routes need a Bearer token by default. List every route opened with `@noauth()` (`.no_auth` in
  Ruby, `.noAuth()` in Node.js); each one must be public on purpose, with a case that proves the rest refuse.
- GET routes are public unless marked `@secured()` (`.secure()`). Every GET that returns private data
  needs a case with no token.
- With `TINA4_CSRF=true`, a write with no form token is refused. `@no_csrf()` is for webhooks only.
- `TINA4_DEBUG` is false on the environment under test: no debug overlay, `/__dev/` is not served, and
  error pages show no stack trace.
- `/health` answers, and `data/.broken/` stays empty after the run. Decide if `/swagger` should be
  reachable on this environment, then write that as a case.
- A fresh database reaches the expected schema with `tina4 migrate`; seeds give the known values.
- Queue jobs finish, a failed job is visible, and a redelivered job has no double effect (delivery is
  at least once).
- WebSocket pages reconnect after a dropped connection and refuse a client with no valid token.

## Authentication and account flows
- Wrong password, unknown user (same message and timing), lockout / rate limit, deactivated user.
- Session expiry, logout in one tab, Back button after logout, deep link while signed out.
- Password reset: expiry, single use, tampered token, superseded link, signed-in user clicking a link.
- Invite / first sign-in / forced password change; resend invite; reuse of one-time password.
- Email change requires current password and re-verification; weak / mismatched / reused passwords.
- Notification emails: arrive, correct From / content / links, correct rendering in major clients.
- Public forms (register, contact, applications): validation, duplicates, spam / rate limit, escaping.

## Money, stock and data integrity (skip what the app does not have)
- Full document lifecycle end to end (draft > approve > deliver > invoice > credit note > complete),
  with totals and tax recomputed independently.
- Issued documents are immutable; numbering sequential with no gaps or duplicates.
- Receipts and payments: full, partial, over, zero, negative; duplicate submit; closed period.
- Ledger: trial balance balances, control accounts equal sub-ledgers, balance sheet balances,
  tax return agrees with posted entries.
- Stock moves by the right quantity on receive / deliver; backorders; over-receiving refused.
- Credit limits and holds: over-limit order held, release needs its permission.
- Concurrency: two users editing the same record or posting the same document.

## Cross-cutting
- Responsive widths (phone / tablet / laptop), at least three browsers including Safari / iOS.
- Keyboard-only operation, visible focus, modal focus trap, screen-reader labels.
- Performance on realistic data volume with a stated time budget.
- Refresh and deep link on every route; console and network free of unexpected errors.
- Locale: currency, tax rate, dates and timezones around midnight.

## Plan quality bar
- Every case: ID, role, precondition, steps, expected result that can be judged pass or fail, priority.
- A seed-data table with known values; test accounts per role and permission set; test mailboxes.
- Dependencies between cases stated (run lifecycle before ledger checks).
- Exit criteria, defect log, sign-off, and a clean-up step. Warn if the environment sends real email.
