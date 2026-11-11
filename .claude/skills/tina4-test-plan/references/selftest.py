#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Self-test for build_test_plan.py — a real gate, standard library only.

Builds the shipped example-spec.json with the real builder, then asserts the
.xlsx and .pdf it produced by reading their bytes directly (zip + XML for the
workbook, raw object scan for the PDF): the sheets, the one-row-per-case count,
the Result/Priority dropdowns, that no Test-cases cell became a live formula
(a step like "=1+1" stays text), and that the Summary grand total carries a
CACHED value so a non-recalculating viewer shows the count, not a blank. Every
expected number is derived FROM the spec, never hardcoded.

Run (no third-party dependency — the Tina4 way):
    python references/selftest.py

Exit 0 = pass, non-zero = a real failure. Prove it is a gate by mutation: break
the cached-value write in _xlsx.py and watch this go red, then restore.
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
    print(f"  [{'ok ' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label + (f": {detail}" if detail else ""))


def build(spec_path, out_dir, basename):
    proc = subprocess.run([sys.executable, BUILDER, spec_path, out_dir, "--basename", basename],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"builder exited {proc.returncode}")


def sheet_file_for(zf, name):
    """Map a sheet display name to its worksheets/sheetN.xml (N = position)."""
    order = re.findall(r'<sheet name="([^"]+)"', zf.read("xl/workbook.xml").decode())
    return f"xl/worksheets/sheet{order.index(name) + 1}.xml", order


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    expected_cases = sum(len(s["cases"]) for s in spec["sections"])
    print(f"spec: {len(spec['sections'])} sections, {expected_cases} cases expected")

    with tempfile.TemporaryDirectory() as out:
        build(SPEC, out, "selftest")
        xlsx = os.path.join(out, "selftest.xlsx")
        pdf = os.path.join(out, "selftest.pdf")
        prompt = os.path.join(out, "selftest-agent-prompt.md")

        check("xlsx produced", os.path.exists(xlsx))
        check("pdf produced", os.path.exists(pdf))
        check("agent prompt produced", os.path.exists(prompt))
        if not (os.path.exists(xlsx) and os.path.exists(pdf)):
            return 1

        with zipfile.ZipFile(xlsx) as zf:
            check("xlsx is a valid zip", zf.testzip() is None)
            tc_path, order = sheet_file_for(zf, "Test cases")
            sm_path, _ = sheet_file_for(zf, "Summary")
            check("sheet set correct", order == EXPECTED_SHEETS, str(order))

            tc = zf.read(tc_path).decode()
            max_row = max(int(n) for n in re.findall(r'<row r="(\d+)"', tc))
            check("one row per case + header", max_row == expected_cases + 1,
                  f"max_row={max_row}, expected {expected_cases + 1}")
            check("Result dropdown on column J", f'sqref="J2:J{expected_cases + 1}"' in tc)
            check("Priority dropdown on column I", f'sqref="I2:I{expected_cases + 1}"' in tc)
            check("Pass/Fail/Blocked conditional fills", tc.count("<conditionalFormatting") == 3,
                  str(tc.count("<conditionalFormatting")))
            check("no Test-cases cell is a live formula", "<f>" not in tc,
                  "a cell became a formula — a '=...' step would evaluate")

            sm = zf.read(sm_path).decode()
            m = re.search(r'<c r="B7"[^>]*><f>[^<]*</f><v>([^<]*)</v>', sm)
            check("Summary grand-total is cached", bool(m),
                  "B7 has a formula but no cached <v> — non-recalc viewers see blank")
            if m:
                check("cached grand total equals case count", m.group(1) == str(expected_cases),
                      f"cached={m.group(1)}, expected {expected_cases}")

        pdf_bytes = open(pdf, "rb").read()
        check("pdf header", pdf_bytes[:5] == b"%PDF-")
        check("pdf trailer", pdf_bytes.rstrip().endswith(b"%%EOF"))
        check("pdf has pages", pdf_bytes.count(b"/Type /Page ") >= 3,
              str(pdf_bytes.count(b"/Type /Page ")))
        check("pdf carries plan content", b"Coverage at a glance" in pdf_bytes and b"Sign-off" in pdf_bytes)

    # Positive proof that a formula-looking step stays TEXT (not a live formula).
    with tempfile.TemporaryDirectory() as out:
        fspec = os.path.join(out, "f.json")
        json.dump({"project": "F", "date": "2026-01-01", "sections": [
            {"prefix": "X", "group": "G", "area": "A",
             "cases": [["=1+1 typed in the name field", "stored as literal text", "P1"]]}]},
            open(fspec, "w"))
        build(fspec, out, "f")
        with zipfile.ZipFile(os.path.join(out, "f.xlsx")) as zf:
            tc_path, _ = sheet_file_for(zf, "Test cases")
            tc = zf.read(tc_path).decode()
        check("formula-looking step stored as inline text",
              't="inlineStr"' in tc and "=1+1 typed in the name field" in tc and "<f>" not in tc)

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
