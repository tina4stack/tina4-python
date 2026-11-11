#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Self-test for build_test_plan.py — a real gate, not a smoke test.

Builds the shipped example-spec.json with the real builder, then asserts the
workbook/PDF/agent-prompt it produced are structurally correct: the sheets, the
case-row count, the Result/Priority dropdowns, and — the fragile bit — that the
Summary totals carry CACHED values so a non-recalculating viewer shows numbers,
not blanks. Every expected number is derived FROM the spec, never hardcoded, so
this stays correct when the example spec changes.

Run (skill tooling only — never an app dependency):
    uv run --no-project --with openpyxl --with reportlab python references/selftest.py

Exit 0 = pass, non-zero = a real failure. Prove it is a gate by mutation: break
something in build_test_plan.py (e.g. the cached-value injection) and watch this
go red, then restore.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.join(HERE, "build_test_plan.py")
SPEC = os.path.join(HERE, "example-spec.json")
EXPECTED_SHEETS = ["Read me", "Summary", "Test data", "Test cases", "Defects"]

failures = []


def check(label, condition, detail=""):
    mark = "ok " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label + (f": {detail}" if detail else ""))


def main():
    from openpyxl import load_workbook

    spec = json.load(open(SPEC, encoding="utf-8"))
    expected_cases = sum(len(s["cases"]) for s in spec["sections"])
    print(f"spec: {len(spec['sections'])} sections, {expected_cases} cases expected")

    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run([sys.executable, BUILDER, SPEC, out, "--basename", "selftest"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            print("FAIL: builder exited non-zero")
            return 1

        xlsx = os.path.join(out, "selftest.xlsx")
        pdf = os.path.join(out, "selftest.pdf")
        prompt = os.path.join(out, "selftest-agent-prompt.md")
        check("xlsx produced", os.path.exists(xlsx))
        check("pdf produced", os.path.exists(pdf))
        check("agent prompt produced", os.path.exists(prompt))
        check("pdf is non-empty", os.path.exists(pdf) and os.path.getsize(pdf) > 2000,
              f"{os.path.getsize(pdf) if os.path.exists(pdf) else 0} bytes")
        if not os.path.exists(xlsx):
            return 1

        wb = load_workbook(xlsx)
        check("sheet set correct", wb.sheetnames == EXPECTED_SHEETS, str(wb.sheetnames))

        tc = wb["Test cases"]
        check("one row per case + header", tc.max_row == expected_cases + 1,
              f"max_row={tc.max_row}, expected {expected_cases + 1}")
        sqrefs = {str(dv.sqref) for dv in tc.data_validations.dataValidation}
        check("Result dropdown on column J", any(s.startswith("J2") for s in sqrefs), str(sqrefs))
        check("Priority dropdown on column I", any(s.startswith("I2") for s in sqrefs), str(sqrefs))

        # A step that looks like a formula must be stored as text, never evaluated.
        formula_steps = [step for s in spec["sections"] for (step, _, _) in s["cases"]
                         if str(step).lstrip().startswith("=")]
        if formula_steps:
            got = [tc.cell(r, 7).data_type for r in range(2, tc.max_row + 1)]
            check("formula-looking steps stored as text", all(t != "f" for t in got),
                  "a step beginning with '=' was stored as a live formula")

        # The fragile part: Summary B7 (grand total) must carry a CACHED <v> value,
        # so a viewer that does not recalculate shows the real count, not a blank.
        idx = wb.sheetnames.index("Summary") + 1
        with zipfile.ZipFile(xlsx) as z:
            xml = z.read(f"xl/worksheets/sheet{idx}.xml").decode("utf-8")
        m = re.search(r'<c r="B7"[^>]*><f>[^<]*</f><v>([^<]*)</v></c>', xml)
        check("Summary grand-total is cached", bool(m),
              "B7 has a formula but no cached <v> — non-recalc viewers see blank")
        if m:
            check("cached grand total equals case count", m.group(1) == str(expected_cases),
                  f"cached={m.group(1)}, expected {expected_cases}")

    print()
    if failures:
        print(f"SELFTEST FAILED ({len(failures)}):")
        for f in failures:
            print("  - " + f)
        return 1
    print(f"SELFTEST PASSED — {expected_cases} cases, all structural checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
