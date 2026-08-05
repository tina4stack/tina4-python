# Task: Bound the database connect (TINA4_DATABASE_CONNECT_TIMEOUT)

## Goal
A database connect that blocks forever hangs the application with no log, no error and no
signal. Bound every adapter's connect on the shared four-framework contract.

## Context — what Python actually had
The grep that suggested Python was "closest" hit a COMMENT, not code:

    tina4_python/database/firebird.py:121
    # behind NAT timeouts, server-side ConnectionIdleTimeout, or Docker

That line documents `_DEAD_CONN_MARKERS`, the substrings used to detect an ALREADY-DEAD socket
mid-request and transparently reconnect. It has nothing to do with bounding a connect. The
other hits are in `sqlite.py` and are the sqlite3 LOCK WAIT (`timeout=30`, `PRAGMA
busy_timeout`) — how long to wait for another writer's lock, also not a connect bound.

**Python was exactly as unbounded as PHP and Ruby.** No adapter passed any connect timeout.

## Contract (identical in all four frameworks)
    name:      TINA4_DATABASE_CONNECT_TIMEOUT
    unit:      SECONDS
    default:   10
    <= 0:      disables the bound (unbounded, the old behaviour)
    garbage:   warn and use 10
    on expiry: raise naming the host, the port, the elapsed seconds, and the variable

## Adapter enumeration — mechanism per adapter, MEASURED not assumed
Probed against a real accept-and-never-reply server on the lab (Ubuntu 24.04.4, Python 3.13.3),
bound set to 2s, hard-killed at 25-30s:

| Adapter  | connect blocks? | Native option            | Native honoured?      | Shipped mechanism            |
|----------|-----------------|--------------------------|-----------------------|------------------------------|
| sqlite   | NO (local file) | n/a                      | n/a                   | none needed — see note        |
| postgres | YES             | `connect_timeout` (libpq)| YES — fired at 2.01s  | native only                   |
| mysql    | YES             | `connection_timeout`     | YES — fired at 2.08s  | native only                   |
| mssql    | YES             | `login_timeout`          | **NO — killed at 25s**| native + watchdog thread      |
| odbc     | YES             | `timeout` (LOGIN_TIMEOUT)| driver-dependent      | native + watchdog thread      |
| firebird | YES             | none exists              | n/a — killed at 30s   | watchdog thread               |
| mongodb  | NO (lazy)       | `connectTimeoutMS`       | ctor returns in 0.09s | native, bounds deferred connect|

Notes:
- **sqlite** opens a local file; there is no peer that can accept and go silent. Its existing
  `timeout=30` is the WRITE-LOCK wait and repurposing it would break contention handling.
- **mssql** is the surprise. `login_timeout=2`, `timeout=2` and both together ALL failed to
  return against a black-holed peer. FreeTDS applies login_timeout to establishing the
  connection; a peer that accepts and then goes silent gets past it and wedges on the login
  response. The watchdog is what actually guarantees the bound.
- **firebird** has no connect-timeout parameter at all (`firebird.driver` 2.0.2 `connect()`
  signature verified; `fdb` likewise). The work is inside fbclient via ctypes, so no Python
  socket timeout can reach it.
- **mongodb**'s `MongoClient` is lazy — it returns without dialling — so its connect cannot
  hang. `connectTimeoutMS` makes the same variable govern the deferred connect on first use.
  Server SELECTION keeps pymongo's own default: it is a retry loop around bounded connects.

## Scope
- [x] Shared resolver + deadline + watchdog in `tina4-python/tina4_python/database/adapter.py`
- [x] Wire every blocking adapter
- [x] Named regression tests, positive + negative, against a REAL black-hole socket server
- [x] Confirm the tests FAIL before the fix (all four killed at 40s, exit 137, no summary)
- [x] Mutation-prove every gate (8 mutations, all RED, all restored byte-exact)
- [x] Full suite on the lab

## Not done / not verifiable here
- **ODBC has no live test.** This project deliberately provisions no ODBC service in the lab
  or in CI (`tests/conftest.py` documents it), and pyodbc cannot import without the system
  unixODBC library. The bound is implemented and watchdog-backed so it holds whatever driver
  is loaded, but it is NOT live-verified. Its pure endpoint parser IS tested, including that
  it never leaks UID/PWD into an expiry message.
- **Deferring the connect out of `Database.__init__`** is a separate architectural issue
  (no-network-io-in-a-constructor). Bounding is not deferring; not touched here.

## Status: Complete
