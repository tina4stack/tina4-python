#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Build a manual test plan (.xlsx, .pdf and agent prompt) from a JSON plan spec.

Standard library only — the .xlsx and .pdf are written by the sibling _xlsx.py
and _pdf.py modules, so using this skill installs nothing (the Tina4 way).

Usage: build_test_plan.py SPEC.json OUT_DIR [--basename NAME] [--xlsx-only]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pdf import Document, text_width  # noqa: E402
from _xlsx import Workbook, col_letter  # noqa: E402

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("spec")
argument_parser.add_argument("out_dir")
argument_parser.add_argument("--basename")
argument_parser.add_argument("--xlsx-only", action="store_true")
args = argument_parser.parse_args()

spec = json.load(open(args.spec, encoding="utf-8"))
PROJECT = spec["project"]
ENV = spec.get("environment", "Test")
URL = spec.get("url", "")
DATE = spec["date"]
BLOCKER_AREAS = ", ".join(spec.get("blocker_areas") or ["security", "data integrity", "login"])
CLEANUP = spec.get("cleanup") or ("After the run, remove or deactivate the test data you created "
                                  "and undo any settings you changed.")
TITLE = f"{PROJECT} - Application Test Plan"
basename = args.basename or re.sub(r"[^a-z0-9]+", "-", PROJECT.lower()).strip("-") + "-test-plan"
os.makedirs(args.out_dir, exist_ok=True)

cases = []
for s in spec["sections"]:
    for i, (step, exp, pri) in enumerate(s["cases"], 1):
        assert pri in ("P1", "P2", "P3"), f"bad priority in {s['prefix']}: {pri}"
        cases.append(dict(id=f"{s['prefix']}-{i:02d}", group=s["group"], area=s["area"],
                          route=s.get("route", ""), role=s.get("role", ""),
                          precondition=s.get("precondition") or "-", step=step, exp=exp, pri=pri))
ids = [c["id"] for c in cases]
assert len(ids) == len(set(ids)), "duplicate test IDs: prefixes must be unique"
groups = list(dict.fromkeys(c["group"] for c in cases))
last = len(cases) + 1

warning_lines = list(spec.get("warnings", []))
if spec.get("sends_real_email"):
    warning_lines.insert(0, "This environment sends REAL email. Use only the test mailboxes listed on 'Test data'.")
warning_lines.append(CLEANUP)
regression_sections = spec.get("regression_priority", [])
if regression_sections:
    warning_lines.append("Regression priority (recently changed): " + ", ".join(regression_sections) + ".")

RESULTS = ["Pass", "Fail", "Blocked", "N/A", "Not run"]


def tally(sel):
    t = dict.fromkeys(RESULTS, 0)
    t["Not run"] = len(sel)
    return len(sel), t


def ratio(a, b):
    return 0 if b == 0 else a / b


# ------------------------------------------------------------------ XLSX
wb = Workbook()
HEADER = wb.style(name="Arial", size=10, bold=True, color="FFFFFF", fill="1F2937",
                  border=True, wrap=True, valign="center")
TITLE_ST = wb.style(name="Arial", size=16, bold=True, wrap=True, valign="top")
H_ST = wb.style(name="Arial", size=11, bold=True, fill="E5E7EB", wrap=True, valign="top")
BODY = wb.style(name="Arial", size=11, wrap=True, valign="top")
AMBER = wb.style(name="Arial", size=10, bold=True, fill="F5A623", wrap=True, valign="top")
CELL = wb.style(name="Arial", size=10, wrap=True, valign="top", border=True)
CELL_P1 = wb.style(name="Arial", size=10, bold=True, wrap=True, valign="top", border=True)
INPUT = wb.style(name="Arial", size=10, wrap=True, valign="top", fill="FFF9C4")
DATA = wb.style(name="Arial", size=10, wrap=True, valign="top")
DATA_B = wb.style(name="Arial", size=10, bold=True, wrap=True, valign="top")
SUM = wb.style(name="Arial", size=11, border=True)
SUM_B = wb.style(name="Arial", size=11, bold=True, border=True)
PCT = wb.style(name="Arial", size=11, border=True, numfmt="0.0%")
PCT_B = wb.style(name="Arial", size=11, bold=True, border=True, numfmt="0.0%")

# --- Read me ---
readme = wb.add_sheet("Read me")
readme.set_width(1, 130)
lines = [
    (TITLE, "t"),
    (f"Environment: {ENV}  |  {URL}  |  Revised {DATE}  |  {len(cases)} test cases", ""),
    ("", ""),
    ("How to use", "h"),
    ("1. Work through the 'Test cases' sheet. Filter by Group, Role or Priority. Test as the role named in each row.", ""),
    ("2. Set Result to Pass, Fail, Blocked or N/A. Fill Tester and Date. Every Fail needs a Defect ID and Notes (screenshot filename).", ""),
    ("3. Log each defect on the 'Defects' sheet. The 'Summary' sheet counts results automatically.", ""),
    ("4. A page the login has no permission for must refuse cleanly (redirect or clear message). That is a Pass, not a bug.", ""),
    ("5. Keep the browser console and network tab open, or read the API responses; any unexpected 4xx / 5xx is a Fail.", ""),
    ("", ""),
    ("Priority", "h"),
    (f"P1 = release blocker: {BLOCKER_AREAS}. P2 = must pass for sign-off. P3 = polish; may be deferred with approval.", ""),
    ("", ""),
    ("Exit criteria", "h"),
    ("- 100% of P1 cases executed and passed. - 95% of P2 passed, remainder with an agreed workaround. - No open P1 or P2 defects. - Sign-off recorded below.", ""),
    ("", ""),
    ("Warnings", "h"),
] + [("- " + w, "") for w in warning_lines] + [
    ("", ""),
    ("Sign-off", "h"),
    ("Tester: ____________________   Build / commit: ____________________   Date: ____________", ""),
    ("Approver: __________________   Decision (Go / No-go): ______________", ""),
]
for r, (txt, kind) in enumerate(lines, 1):
    readme.text(r, 1, txt, {"t": TITLE_ST, "h": H_ST}.get(kind, BODY))

# --- Summary (second sheet) ---
summary = wb.add_sheet("Summary")
summary.text(1, 1, "Execution summary", TITLE_ST)
sum_heads = ["Priority", "Total", "Pass", "Fail", "Blocked", "N/A", "Not run", "% executed", "% passed"]
for c, h in enumerate(sum_heads, 1):
    summary.text(3, c, h, HEADER)
priority_range = f"'Test cases'!$I$2:$I${last}"
result_range = f"'Test cases'!$J$2:$J${last}"
group_range = f"'Test cases'!$B$2:$B${last}"
for i, p in enumerate(["P1", "P2", "P3"], 4):
    summary.text(i, 1, p, SUM)
    n, t = tally([c for c in cases if c["pri"] == p])
    summary.formula(i, 2, f"COUNTIF({priority_range},A{i})", n, SUM)
    for c, res in zip(range(3, 8), RESULTS):
        summary.formula(i, c, f'COUNTIFS({priority_range},$A{i},{result_range},"{res}")', t[res], SUM)
    summary.formula(i, 8, f"IF(B{i}-F{i}=0,0,(C{i}+D{i}+E{i})/(B{i}-F{i}))",
                    ratio(t["Pass"] + t["Fail"] + t["Blocked"], n - t["N/A"]), PCT)
    summary.formula(i, 9, f"IF(B{i}-F{i}=0,0,C{i}/(B{i}-F{i}))", ratio(t["Pass"], n - t["N/A"]), PCT)
summary.text(7, 1, "All", SUM_B)
n_all, t_all = tally(cases)
summary.formula(7, 2, "SUM(B4:B6)", n_all, SUM_B)
for c, res in zip(range(3, 8), RESULTS):
    col = col_letter(c)
    summary.formula(7, c, f"SUM({col}4:{col}6)", t_all[res], SUM_B)
summary.formula(7, 8, "IF(B7-F7=0,0,(C7+D7+E7)/(B7-F7))",
                ratio(t_all["Pass"] + t_all["Fail"] + t_all["Blocked"], n_all - t_all["N/A"]), PCT_B)
summary.formula(7, 9, "IF(B7-F7=0,0,C7/(B7-F7))", ratio(t_all["Pass"], n_all - t_all["N/A"]), PCT_B)
summary.text(9, 1, "Open defects", DATA_B)
summary.formula(9, 2, ('COUNTA(Defects!A2:A201)-COUNTIF(Defects!L2:L201,"Closed")'
                       '-COUNTIF(Defects!L2:L201,"Retest passed")-COUNTIF(Defects!L2:L201,"Won\'t fix")'), 0, DATA)
summary.text(10, 1, "Open P1 defects", DATA_B)
summary.formula(10, 2, ('COUNTIFS(Defects!C2:C201,"P1")-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Closed")'
                        '-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Retest passed")'
                        '-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Won\'t fix")'), 0, DATA)
summary.text(12, 1, "Results by group", DATA_B)
for c, h in enumerate(["Group", "Total"] + RESULTS, 1):
    summary.text(13, c, h, HEADER)
for i, g in enumerate(groups, 14):
    summary.text(i, 1, g, DATA)
    n, t = tally([c for c in cases if c["group"] == g])
    summary.formula(i, 2, f"COUNTIF({group_range},A{i})", n, DATA)
    for c, res in zip(range(3, 8), RESULTS):
        summary.formula(i, c, f'COUNTIFS({group_range},$A{i},{result_range},"{res}")', t[res], DATA)
summary.set_width(1, 40)
for c in range(2, 10):
    summary.set_width(c, 12)

# --- Test data ---
td = wb.add_sheet("Test data")
td.text(1, 1, "ACCOUNTS (fill in before testing; never record real passwords here)", AMBER)
for c, (h, w) in enumerate(zip(["Account", "Role / permissions", "Login email (test mailbox)", "Notes"],
                               [44, 44, 40, 34]), 1):
    td.text(2, c, h, HEADER)
    td.set_width(c, w)
r = 3
for a in spec.get("accounts", []):
    td.text(r, 1, a[0], DATA)
    td.text(r, 2, a[1] if len(a) > 1 else "", DATA)
    td.text(r, 3, "", INPUT)
    td.text(r, 4, a[2] if len(a) > 2 else "", DATA)
    r += 1
r += 1
td.text(r, 1, "SEED DATA (record the known values so each test can be pass / fail)", AMBER)
r += 1
for c, h in enumerate(["Item", "Known value", "Where used", "Notes"], 1):
    td.text(r, c, h, HEADER)
r += 1
for s in spec.get("seed", []):
    td.text(r, 1, s[0], DATA)
    td.text(r, 2, "", INPUT)
    td.text(r, 3, s[1] if len(s) > 1 else "", DATA)
    td.text(r, 4, s[2] if len(s) > 2 else "", DATA)
    r += 1

# --- Test cases ---
tc = wb.add_sheet("Test cases")
heads = ["ID", "Group", "Area", "Route / page", "Role to test as", "Precondition", "Steps",
         "Expected result", "Priority", "Result", "Tester", "Date", "Defect ID", "Notes / evidence"]
widths = [16, 20, 24, 26, 18, 30, 52, 52, 8, 10, 12, 12, 12, 34]
for c, (h, w) in enumerate(zip(heads, widths), 1):
    tc.text(1, c, h, HEADER)
    tc.set_width(c, w)
for r, case in enumerate(cases, 2):
    vals = [case["id"], case["group"], case["area"], case["route"], case["role"], case["precondition"],
            case["step"], case["exp"], case["pri"], "Not run", "", "", "", ""]
    for c, v in enumerate(vals, 1):
        tc.text(r, c, v, CELL_P1 if (c == 9 and case["pri"] == "P1") else CELL)
tc.freeze(2, 2)
tc.auto_filter(f"A1:{col_letter(len(heads))}{last}")
tc.validation(f"J2:J{last}", ["Not run", "Pass", "Fail", "Blocked", "N/A"])
tc.validation(f"I2:I{last}", ["P1", "P2", "P3"])
for txt, color in (("Pass", "C6EFCE"), ("Fail", "FFC7CE"), ("Blocked", "FFEB9C")):
    tc.cond_fill(f"J2:J{last}", txt, wb.dxf_fill(color))

# --- Defects ---
df = wb.add_sheet("Defects")
dhead = ["Defect ID", "Test case ID", "Severity (P1/P2/P3)", "Summary", "Steps to reproduce", "Expected",
         "Actual", "Evidence (screenshot / console)", "Build / commit", "Reported by", "Date", "Status",
         "Fixed in", "Retest result"]
dwidths = [12, 16, 14, 34, 44, 30, 30, 26, 14, 14, 12, 12, 14, 14]
for c, (h, w) in enumerate(zip(dhead, dwidths), 1):
    df.text(1, c, h, HEADER)
    df.set_width(c, w)
df.freeze(2, 1)
df.validation("L2:L201", ["Open", "In progress", "Fixed", "Retest passed", "Closed", "Won't fix"])

xlsx_path = os.path.join(args.out_dir, basename + ".xlsx")
wb.save(xlsx_path)
if args.xlsx_only:
    print(f"{len(cases)} cases -> {xlsx_path}")
    raise SystemExit

# ------------------------------------------------------------------ PDF
W, H = 842, 595
ML = 43


def footer(page, num):
    page.text(ML, H - 12, f"{TITLE}  |  {ENV}  |  {DATE}", 7.5, color="808080")
    label = f"Page {num}"
    page.text(W - ML - text_width(label, 7.5), H - 12, label, 7.5, color="808080")


doc = Document(width=W, height=H, margin=ML, bottom=34, footer=footer)
doc.page.text(ML, doc.y + 22, TITLE, 22, True, "1F2937")
doc.y += 28
doc.para(f"Environment: {ENV} | {URL} | Revised {DATE} | {len(cases)} test cases",
         size=9, color="6B7280", space_after=2)
doc.rule()
intro = [
    "How to use. Test as the role named in each row. Tick Pass or Fail, then enter tester initials, date and a defect ID for every failure. Put a screenshot filename in Notes. A page a login has no permission for must refuse cleanly (redirect or clear message): that is a Pass.",
    f"Priority. P1 = release blocker ({BLOCKER_AREAS}). P2 = must pass for sign-off. P3 = polish, deferrable with approval.",
    "Exit criteria. All P1 cases executed and passed; at least 95% of P2 passed with agreed workarounds for the rest; no open P1 or P2 defects; sign-off recorded.",
    "Warnings. " + " ".join(w if w.endswith(".") else w + "." for w in warning_lines),
    f"Companion workbook. Use {basename}.xlsx for the live results tally, defect log and filtering.",
]
for txt in intro:
    doc.para(txt, size=9.5, color="111827")

scale = (W - 2 * ML) / 210.0
doc.heading("Coverage at a glance")
doc.rule()
cov_rows = []
for g in groups:
    gc = [c for c in cases if c["group"] == g]
    cov_rows.append([g, str(len(gc))] + [str(sum(c["pri"] == p for c in gc)) for p in ("P1", "P2", "P3")])
cov_rows.append(["Total", str(len(cases))]
                + [str(sum(c["pri"] == p for c in cases)) for p in ("P1", "P2", "P3")])
doc.table(["Group", "Cases", "P1", "P2", "P3"], cov_rows,
          [v * scale for v in (110, 25, 25, 25, 25)], total_last=True)

if spec.get("accounts"):
    doc.heading("Test accounts and data to prepare")
    doc.rule()
    prep = [[a[0], a[1] if len(a) > 1 else ""] for a in spec["accounts"]]
    prep += [[s[0], "Seed data" + (f" ({s[1]})" if len(s) > 1 and s[1] else "")] for s in spec.get("seed", [])]
    doc.table(["Item / account", "Role / preparation"], prep, [v * scale for v in (110, 100)], font_size=8.5)

doc.page_break()
case_scale = (W - 2 * ML) / 250.0
case_widths = [v * case_scale for v in (29, 68, 70, 9, 13, 13, 48)]
cur = None
for s in spec["sections"]:
    if s["group"] != cur:
        doc.heading(s["group"])
        doc.rule()
        cur = s["group"]
    meta = f"Role: {s.get('role', '')}"
    if s.get("precondition"):
        meta += f" | Precondition: {s['precondition']}"
    doc.subheading(f"{s['area']}   {s.get('route', '')}", meta=meta)
    rows = [[f"{s['prefix']}-{i:02d}", step, exp, pri, "[  ]", "[  ]", ""]
            for i, (step, exp, pri) in enumerate(s["cases"], 1)]
    doc.table(["ID", "Steps", "Expected result", "Pri", "Pass", "Fail", "Tester / date / defect / notes"],
              rows, case_widths, zebra=("FFFFFF", "F9FAFB"))

doc.page_break()
doc.heading("Sign-off")
doc.rule()
doc.space(6)
signoff = [["Tester", "", "Build / commit", ""], ["Date started", "", "Date finished", ""],
           ["P1 passed / total", "", "P2 passed / total", ""],
           ["Open defects (P1 / P2 / P3)", "", "Decision (Go / No-go)", ""],
           ["Approver name", "", "Signature / date", ""]]
so_scale = (W - 2 * ML) / 260.0
doc.table(["Field", "", "Field", ""], signoff, [v * so_scale for v in (55, 80, 55, 70)],
          font_size=9, header_bg="F3F4F6", header_fg="111827", bold_cols=(0, 2))
doc.save(os.path.join(args.out_dir, basename + ".pdf"))

# ------------------------------------------------------------------ AGENT PROMPT
safety = []
if spec.get("sends_real_email"):
    safety.append("- This environment **sends real email**. Use only the test mailboxes on \"Test data\". "
                  "Never invite, reset or email a real person's address.")
safety += [f"- {r}" for r in spec.get("agent_rules", [])]
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-prompt.md"), encoding="utf-8").read()
for k, v in {"PROJECT": PROJECT, "ENV": ENV, "BASENAME": basename, "URL_PART": f" ({URL})" if URL else "",
             "SECTIONS": ", ".join(s["prefix"] for s in spec["sections"]), "BLOCKERS": BLOCKER_AREAS,
             "SAFETY": "\n".join(safety) or "- No environment-specific rules were given. Ask the tester before anything irreversible."}.items():
    tpl = tpl.replace("{{" + k + "}}", v)
open(os.path.join(args.out_dir, f"{basename}-agent-prompt.md"), "w", encoding="utf-8").write(tpl)
print(f"{len(cases)} cases -> {os.path.join(args.out_dir, basename)}.xlsx / .pdf")
