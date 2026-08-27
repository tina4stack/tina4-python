#!/usr/bin/env python3
"""Pre-tag version-consistency precheck.

Assert that EVERY version-bearing file in the checkout carries the intended
release version BEFORE a tag is cut -- so a partial bump is caught left of the
tag, not on the CI publish gate after the tag is already pushed.

Motivated by a recurring release miss: a bump touches some files but misses
others, the tag goes out ahead of the laggards, and the mismatch only surfaces
when the publish workflow re-checks (3.13.120 shipped this way). This script
moves that check into the release worker's hands as one fast command:

    python scripts/check_version_consistency.py 3.13.121

It reads each file and compares the version it declares to the version you
passed. It exits 0 when they all agree, and non-zero -- naming each file left
behind and the wrong value it still carries -- when any disagree.

Zero dependencies: standard library only (``tomllib`` is stdlib on the 3.12+
this framework targets). It never imports ``tina4_python``; it only reads files
as text, so it runs anywhere a checkout does, with no install and no services.

The in-suite tests (``tests/test_version_constant.py``,
``tests/test_version_consistency.py``, ``tests/test_version_contract.py``)
remain the CI backstop -- they assert the same files agree with each other. This
script is the complementary *pre-tag* gate: it takes the INTENDED version as an
argument, so it also catches "forgot to bump at all" (where every file still
agrees at the OLD version and the suite stays green).
"""
import argparse
import re
import sys
import tomllib
from pathlib import Path

# The floor literal inside tina4_python/__init__.py's _resolve_version(). Same
# pattern tests/test_version_constant.py uses; last match is the floor literal.
_FLOOR_LITERAL_RE = re.compile(r'return\s+"(\d+\.\d+\.\d+)"')
# CLAUDE.md header line: "Version 3.13.121 - Lightweight Python web framework..."
_CLAUDE_HEADER_RE = re.compile(r"^Version (\d+\.\d+\.\d+)\b", re.MULTILINE)
# CLAUDE.md footer line(s): "- Version: 3.13.121"
_CLAUDE_FOOTER_RE = re.compile(r"^- Version:\s*(\d+\.\d+\.\d+)", re.MULTILINE)


def _pyproject_versions(text: str) -> list[str]:
    """The [project].version declared in pyproject.toml (parsed, not grepped)."""
    version = tomllib.loads(text).get("project", {}).get("version")
    return [version] if version else []


def _init_floor_versions(text: str) -> list[str]:
    """The last-resort floor literal in _resolve_version()."""
    matches = _FLOOR_LITERAL_RE.findall(text)
    return [matches[-1]] if matches else []


def _claude_header_versions(text: str) -> list[str]:
    return _CLAUDE_HEADER_RE.findall(text)


def _claude_footer_versions(text: str) -> list[str]:
    return _CLAUDE_FOOTER_RE.findall(text)


# Every location the release version lives, as (relative path, human label,
# extractor). The extractor returns EVERY version it finds at that location; the
# location passes when the list is non-empty and every entry equals the expected
# version. Keep this list complete: a version-bearing file missing here is a file
# the precheck cannot catch drifting.
CHECKS = [
    ("pyproject.toml", "[project].version", _pyproject_versions),
    ("tina4_python/__init__.py", "_resolve_version() floor literal", _init_floor_versions),
    ("CLAUDE.md", "header 'Version X'", _claude_header_versions),
    ("CLAUDE.md", "footer '- Version: X'", _claude_footer_versions),
]


def check(root: Path, expected: str) -> list[tuple[str, str, str, list[str], str]]:
    """Run every check against ``root``; return (path, label, status, found, detail)."""
    results = []
    for relative_path, label, extract in CHECKS:
        path = root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            results.append((relative_path, label, "FAIL", [], "file not found"))
            continue
        found = extract(text)
        if not found:
            results.append((relative_path, label, "FAIL", [], "no version literal found"))
        elif all(version == expected for version in found):
            results.append((relative_path, label, "PASS", found, ""))
        else:
            wrong = sorted({version for version in found if version != expected})
            results.append((relative_path, label, "FAIL", found, f"found {', '.join(wrong)}"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_version_consistency.py",
        description="Assert every version-bearing file agrees with the intended "
                    "release version, BEFORE a tag is cut.",
    )
    parser.add_argument("expected", help="the intended release version, e.g. 3.13.121")
    parser.add_argument(
        "--root", default=None,
        help="repo root to check (default: the tina4-python checkout this script lives in)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    expected = args.expected.strip()

    results = check(root, expected)
    print(f"Version consistency check against {expected}")
    print(f"root: {root}")

    path_width = max(len(relative_path) for relative_path, *_ in results)
    label_width = max(len(label) for _, label, *_ in results)
    failures = []
    for relative_path, label, status, found, detail in results:
        found_str = ", ".join(found) if found else "(none)"
        line = f"  {status}  {relative_path:<{path_width}}  {label:<{label_width}}  {found_str}"
        if status == "FAIL":
            line += f"   ({detail}; expected {expected})"
            failures.append((relative_path, label, detail))
        print(line)

    print()
    if failures:
        print(f"FAIL: {len(failures)} version-bearing location(s) disagree with {expected}:")
        for relative_path, label, detail in failures:
            print(f"  - {relative_path} ({label}): {detail}, expected {expected}")
        print("A partial bump was left behind. Fix the file(s) above, then re-run before tagging.")
        return 1

    print(f"PASS: all {len(results)} version-bearing locations carry {expected}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
