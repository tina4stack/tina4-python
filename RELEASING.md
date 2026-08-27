# Releasing tina4-python

The tag is what publishes. Pushing a tag matching `[0-9]*.*.*` (e.g. `3.13.121`)
triggers the publish workflow to PyPI. Merging alone never publishes. So the tag
must never go out ahead of the version-bearing files.

## Cutting a release

1. Bump the version in all version-bearing files (see
   `scripts/check_version_consistency.py` for the list).
2. Run the precheck BEFORE tagging:

        python scripts/check_version_consistency.py 3.13.NNN

   It exits non-zero and names any file left behind. Fix, re-run until green.
3. Only then:

        git tag 3.13.NNN && git push origin 3.13.NNN

## Why the precheck exists

A recurring release miss: a bump touches some files but misses others, the tag
goes out ahead of the laggards, and the mismatch only surfaces on the CI publish
gate after the tag is already pushed (3.13.120 shipped this way). The precheck
moves that check left of the tag. It is pure standard library and imports nothing
from the framework, so it runs in a fresh checkout with no install and no
services.

The version currently lives in these locations (the script is the source of
truth for the list):

- `pyproject.toml` -- `[project].version`
- `tina4_python/__init__.py` -- the `_resolve_version()` floor literal
- `CLAUDE.md` -- the `Version X` header line
- `CLAUDE.md` -- the `- Version: X` footer line

The in-suite tests `tests/test_version_constant.py`,
`tests/test_version_consistency.py`, and `tests/test_version_contract.py` remain
the CI backstop -- they assert the same files agree with each other. The precheck
is the complementary pre-tag gate: it takes the INTENDED version as an argument,
so it also catches a bump that was forgotten entirely (where every file still
agrees at the old version and the suite stays green).
