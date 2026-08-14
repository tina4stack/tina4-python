# Python 3.13.100 version consistency

## Outcome

Every Python package version source reports `3.13.100`.

## Scope

- [x] Compare `pyproject.toml`, `uv.lock`, and the packaged fallback literal.
- [x] Prove the existing consistency regression fails.
- [x] Update the lockfile and fallback literal.
- [x] Re-run the focused regression.

## Parity

| Version source | Status |
|---|---|
| `pyproject.toml` | ✅ `3.13.100` |
| `uv.lock` | ✅ `3.13.100` |
| packaged fallback | ✅ `3.13.100` |

## Tests

- [x] `uv run pytest -q tests/test_version_constant.py`

## Bugs

- [x] The release bump left the packaged fallback at `3.13.99`.

## Commits

- This change: complete the Python `3.13.100` version bump.

## Status: Complete
