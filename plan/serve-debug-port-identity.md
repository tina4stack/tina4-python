# Task: Identity-guard the serve-debug readiness probe (port-identity flake)

Outcome: tests/test_cli_serve_debug_env.py stops flaking when a foreign server
holds the reused ephemeral port. Parity with tina4-ruby PR #95 and the
tina4-nodejs loopBlockWatchdog fix (#111).

## Root cause (evidence from a Ruby CI child serve.log; Python shares the pattern)
- `_free_port()` hands out an ephemeral port (bind :0, close, reuse).
- Under load, a DIFFERENT debug-OFF server (a prior case's lingering child on the
  reused port) already holds it; `TINA4_NO_TAKEOVER=true` stops our debug-on
  child evicting it.
- The old probe hit `/__dev` directly and trusted the first response -- from the
  FOREIGN server -> settled 404 for the debug-true case (wrong answer).
- A 200/404 on the port proves only that SOMETHING listens, not that it is OUR
  child. No identity guard existed. NOT a readiness-timing race, NOT a debug-gate
  bug (env loads before accept; /__dev is a live-gated dispatch stage).

## Scope
- [x] Plant a per-boot UNIQUE readiness route (`/ready_<token>`) only our child
      serves; readiness requires a 200 on THAT before polling `/__dev`.
- [x] Retry on a FRESH port (boot_attempts=5) if the token never appears or the
      child exits (contended port). Always clean up every child (killpg).
- [x] All 4 assertions unchanged (false->404, true->non-404, --production->404,
      missing-env->404); `_poll_dev` keeps the settle window so a debug-off case
      confirms 404 by outlasting it.

## Tests (real, no mocks -- real child process + real HTTP)
- [x] 4 passed single run (py 3.13, macOS).
- [x] 12/12 under CPU load (3 spinners).
- [x] Gate proof: a debug-on server lacking our route 404s `/ready_<token>` while serving /__dev=200.

## Bugs
- [x] Port-identity: foreign server answered the probe -> fixed by the unique-route guard.

## Commits
- (pending  test: identity-guard the serve-debug readiness probe)

## Status: Complete (pending CI + merge)
