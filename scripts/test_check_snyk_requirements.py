# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Mutation-proof for the Snyk-requirements drift guard.

The guard asserts ``requirements-snyk.txt`` is byte-identical to a fresh
``uv export`` of ``uv.lock``. These tests prove it is a real gate: the live tree
must pass, and corrupting a single line -- or removing the file -- must make it
FAIL. Every mutation is restored, so the checkout is left untouched.

Run standalone (mirrors the doc-drift gate's mutation tests):
    python -m unittest discover -s scripts -p 'test_check_snyk_requirements.py'
"""
import shutil
import unittest
from pathlib import Path

import check_snyk_requirements as gate

REPO_ROOT = Path(gate.__file__).resolve().parent.parent
EXPORT_FILE = REPO_ROOT / gate.EXPORT_PATH


def _uv_available() -> bool:
    return shutil.which("uv") is not None


@unittest.skipUnless(_uv_available(), "uv is required to exercise the Snyk export guard")
class SnykRequirementsGuardTest(unittest.TestCase):
    def test_repo_is_clean(self):
        # The committed export must already match uv.lock at HEAD.
        gate.check(REPO_ROOT)  # raises on drift; a clean tree returns None

    def test_corrupting_one_line_fails_then_restores(self):
        original = EXPORT_FILE.read_text(encoding="utf-8")
        # Corrupt exactly one line: bump the version on the first pin.
        lines = original.splitlines(keepends=True)
        pin_index = next(
            i for i, line in enumerate(lines)
            if "==" in line and not line.startswith("#")
        )
        lines[pin_index] = lines[pin_index].replace("==", "==9", 1)
        mutated = "".join(lines)
        self.assertNotEqual(mutated, original, "mutation must change the bytes")
        try:
            EXPORT_FILE.write_text(mutated, encoding="utf-8")
            with self.assertRaises(ValueError):
                gate.check(REPO_ROOT)
        finally:
            EXPORT_FILE.write_text(original, encoding="utf-8")
        # And the restored tree passes again -- proving the failure was the mutation.
        gate.check(REPO_ROOT)

    def test_missing_file_fails_then_restores(self):
        original = EXPORT_FILE.read_text(encoding="utf-8")
        try:
            EXPORT_FILE.unlink()
            with self.assertRaises(ValueError):
                gate.check(REPO_ROOT)
        finally:
            EXPORT_FILE.write_text(original, encoding="utf-8")
        gate.check(REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
