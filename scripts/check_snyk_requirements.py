#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep ``requirements-snyk.txt`` in lock-step with ``uv.lock``.

Why this file exists at all: tina4-python is a ZERO-runtime-dependency project.
Its ``pyproject.toml`` declares ``dependencies = []`` and moves every third-party
package into ``[project.optional-dependencies]`` (uv extras) and
``[dependency-groups]`` (PEP 735). The Snyk GitHub App cannot resolve that shape
-- it does not read ``uv.lock`` -- so its scan of ``pyproject.toml`` ERRORS with
"Failed to detect issues". That is a scan error, not a vulnerability.

The durable fix on the repo side is a plain, fully-pinned ``requirements.txt``
that Snyk CAN parse, generated FROM ``uv.lock`` so it always reflects the real
resolved graph (all extras + the dev group -- everything that pulls third-party
code). ``requirements-snyk.txt`` at the repo root is that file. It is for Snyk
SCA only; it is NOT the install dependency set (the package installs with zero
dependencies).

This script is the single source of truth for that export AND its drift guard:

    python scripts/check_snyk_requirements.py            # check (CI gate)
    python scripts/check_snyk_requirements.py --write    # regenerate the export

In check mode it regenerates the export from the committed ``uv.lock`` into
memory and asserts it is BYTE-IDENTICAL to the committed ``requirements-snyk.txt``.
On any drift it exits non-zero and prints the exact command to refresh, so a
stale export fails the build instead of silently shipping.

Zero dependencies: standard library only. It shells out to ``uv`` (already
required to work in this repo) and reads/writes two files; it never imports
``tina4_python`` and needs no live services.
"""
import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

# The committed export, relative to the repo root.
EXPORT_PATH = "requirements-snyk.txt"

# The exact uv export invocation baked into the header and re-run by the guard.
# --no-emit-project drops tina4-python itself (it is zero-dependency); the flags
# together pin EVERY resolved third-party package across all extras and the dev
# group with ``==``. --no-header lets this script own the header below;
# --no-annotate/--no-hashes keep it a clean, Snyk-parseable pin list. The output
# is derived from the UNIVERSAL lock, so it is byte-identical on every platform.
UV_EXPORT_ARGS = [
    "export",
    "--frozen",
    "--no-emit-project",
    "--all-extras",
    "--all-groups",
    "--no-hashes",
    "--no-annotate",
    "--no-header",
    "--format",
    "requirements-txt",
]

# Human-readable form of the same command, for the file header.
UV_EXPORT_CMD = "uv " + " ".join(UV_EXPORT_ARGS)
# The one command a developer runs to refresh the export after changing uv.lock.
REFRESH_CMD = "python scripts/check_snyk_requirements.py --write"

HEADER = f"""\
# AUTO-GENERATED -- DO NOT HAND-EDIT.
#
# This file is a pinned requirements export of tina4-python's FULL third-party
# dependency graph, generated from uv.lock for Snyk SCA scanning ONLY. It exists
# because Snyk cannot resolve this project's uv-managed, PEP-735, zero-runtime-
# dependency pyproject.toml and errors on it; this parseable export is what Snyk
# scans instead.
#
# It is NOT the install dependency set: tina4-python is a ZERO-dependency package
# (pyproject.toml declares dependencies = []). Every package below is an OPTIONAL
# extra or a DEV/test tool, pinned here only so the security scanner sees the
# whole resolved surface. Do NOT `pip install -r` this to use tina4-python.
#
# Regenerate (never hand-edit) whenever uv.lock changes:
#     {REFRESH_CMD}
# which runs, from the repo root:
#     {UV_EXPORT_CMD}
#
# scripts/check_snyk_requirements.py gates this in CI: if this file drifts from
# uv.lock the build fails. Keep them in sync by regenerating, not by editing here.
"""


def _uv() -> str:
    """Locate the uv executable or fail with a clear remedy."""
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise RuntimeError(
            "uv is not on PATH. Install it (https://astral.sh/uv) to generate or "
            "check the Snyk requirements export."
        )
    return uv_path


def generate(root: Path) -> str:
    """Return the full expected contents of ``requirements-snyk.txt``.

    Runs ``uv export`` against the committed ``uv.lock`` in ``root`` and prepends
    the fixed header. This is the canonical bytes the committed file must match.
    """
    completed = subprocess.run(
        [_uv(), *UV_EXPORT_ARGS],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return HEADER + completed.stdout


def write(root: Path) -> Path:
    """Regenerate the export and write it to ``requirements-snyk.txt``."""
    target = root / EXPORT_PATH
    target.write_text(generate(root), encoding="utf-8")
    return target


def check(root: Path) -> None:
    """Raise ``ValueError`` if the committed export drifts from ``uv.lock``.

    Byte-for-byte comparison against a freshly generated export. The error names
    the drift and the one command that fixes it.
    """
    target = root / EXPORT_PATH
    expected = generate(root)
    try:
        actual = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(
            f"{EXPORT_PATH} is missing. Generate it with:\n    {REFRESH_CMD}"
        )
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                actual.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=f"{EXPORT_PATH} (committed)",
                tofile=f"{EXPORT_PATH} (from uv.lock)",
            )
        )
        raise ValueError(
            f"{EXPORT_PATH} is out of sync with uv.lock.\n"
            f"Refresh it with:\n    {REFRESH_CMD}\n\n"
            f"{diff}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_snyk_requirements.py",
        description="Check (or regenerate) the Snyk requirements export against uv.lock.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate requirements-snyk.txt from uv.lock instead of checking it",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="repo root (default: the tina4-python checkout this script lives in)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent

    if args.write:
        target = write(root)
        print(f"Wrote {target} from uv.lock ({UV_EXPORT_CMD}).")
        return 0

    try:
        check(root)
    except (ValueError, RuntimeError) as error:
        print(f"FAIL: {error}")
        return 1
    print(f"PASS: {EXPORT_PATH} matches uv.lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
