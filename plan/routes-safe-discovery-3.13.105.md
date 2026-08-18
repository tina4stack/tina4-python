# `tina4 routes` safe discovery — 3.13.105

## Contract

`tina4 routes` is a read-only inspection command. It discovers canonical route
files, prints the registered method/path/auth/handler data, and exits zero. It
must not execute the project's server entrypoint, open a browser, bind or take
over a port, or remain running.

## Implementation

- Reproduce with a real child CLI process and an `app.py` that must not run.
- Discover `src/` through the framework's normal module discovery path.
- Keep empty-route output and the existing table format stable.
- Run the targeted regression and the complete suite on the lab host as root.

## Verification

- Targeted route contract: 1 passed.
- Full suite: 5,433 passed, 263 skipped, 2 failed on missing MySQL/MSSQL lab
  credentials. Neither failure touches route discovery.

## Parity

The same observable contract is locked in PHP, Ruby, and Node.js. Language
internals may differ; all four commands must remain finite and network-free.
