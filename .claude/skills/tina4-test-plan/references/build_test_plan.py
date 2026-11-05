#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Build a manual test plan (.xlsx, .pdf and agent prompt) from a JSON plan spec.

Usage: build_test_plan.py SPEC.json OUT_DIR [--basename NAME] [--xlsx-only]
Needs: openpyxl, reportlab. Skill tooling only, never a framework dependency.
"""
import argparse
import json
import os
import re
import shutil
import zipfile

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

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

# ------------------------------------------------------------------ XLSX
FONT_NAME = "Arial"
thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
header_fill = PatternFill("solid", fgColor="1F2937")
amber = PatternFill("solid", fgColor="F5A623")
grey = PatternFill("solid", fgColor="E5E7EB")
input_fill = PatternFill("solid", fgColor="FFF9C4")
wrap = Alignment(wrap_text=True, vertical="top")


def head(worksheet, row, labels, widths=None):
    for c, h in enumerate(labels, 1):
        cell = worksheet.cell(row, c, h)
        cell.font = Font(name=FONT_NAME, bold=True, color="FFFFFF", size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = border
        if widths:
            worksheet.column_dimensions[get_column_letter(c)].width = widths[c - 1]


warning_lines = list(spec.get("warnings", []))
if spec.get("sends_real_email"):
    warning_lines.insert(0, "This environment sends REAL email. Use only the test mailboxes listed on 'Test data'.")
warning_lines.append(CLEANUP)
regression_sections = spec.get("regression_priority", [])
if regression_sections:
    warning_lines.append("Regression priority (recently changed): " + ", ".join(regression_sections) + ".")

workbook = Workbook()
worksheet = workbook.active
worksheet.title = "Read me"
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
    c = worksheet.cell(r, 1, txt)
    c.font = Font(name=FONT_NAME, size=16 if kind == "t" else 11, bold=kind in ("t", "h"))
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if kind == "h":
        c.fill = grey
worksheet.column_dimensions["A"].width = 130

test_data_sheet = workbook.create_sheet("Test data")
test_data_sheet["A1"] = "ACCOUNTS (fill in before testing; never record real passwords here)"
head(test_data_sheet, 2, ["Account", "Role / permissions", "Login email (test mailbox)", "Notes"], [44, 44, 40, 34])
r = 3
for a in spec.get("accounts", []):
    for c, v in enumerate([a[0], a[1] if len(a) > 1 else "", "", a[2] if len(a) > 2 else ""], 1):
        test_data_sheet.cell(r, c, v)
    test_data_sheet.cell(r, 3).fill = input_fill
    r += 1
r += 1
test_data_sheet.cell(r, 1, "SEED DATA (record the known values so each test can be pass / fail)")
seed_title = r
r += 1
head(test_data_sheet, r, ["Item", "Known value", "Where used", "Notes"])
r += 1
for s in spec.get("seed", []):
    for c, v in enumerate([s[0], "", s[1] if len(s) > 1 else "", s[2] if len(s) > 2 else ""], 1):
        test_data_sheet.cell(r, c, v)
    test_data_sheet.cell(r, 2).fill = input_fill
    r += 1
for row in test_data_sheet.iter_rows():
    for cell in row:
        if cell.font.color is None or cell.font.color.rgb != "00FFFFFF":
            cell.font = Font(name=FONT_NAME, size=10, bold=cell.row in (1, seed_title))
        cell.alignment = wrap
for rr in (1, seed_title):
    test_data_sheet.cell(rr, 1).fill = amber

test_cases_sheet = workbook.create_sheet("Test cases")
heads = ["ID", "Group", "Area", "Route / page", "Role to test as", "Precondition", "Steps",
         "Expected result", "Priority", "Result", "Tester", "Date", "Defect ID", "Notes / evidence"]
head(test_cases_sheet, 1, heads, [16, 20, 24, 26, 18, 30, 52, 52, 8, 10, 12, 12, 12, 34])
for r, case in enumerate(cases, 2):
    vals = [case["id"], case["group"], case["area"], case["route"], case["role"], case["precondition"],
            case["step"], case["exp"], case["pri"], "Not run", "", "", "", ""]
    for c, v in enumerate(vals, 1):
        cell = test_cases_sheet.cell(r, c, v)
        if isinstance(v, str):
            cell.data_type = "s"  # a step such as "=1+1 in the name field" is text, never a formula
        cell.font = Font(name=FONT_NAME, size=10, bold=(c == 9 and case["pri"] == "P1"))
        cell.alignment = wrap
        cell.border = border
last = len(cases) + 1
test_cases_sheet.freeze_panes = "B2"
test_cases_sheet.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{last}"
result_validation = DataValidation(type="list", formula1='"Not run,Pass,Fail,Blocked,N/A"', allow_blank=False)
test_cases_sheet.add_data_validation(result_validation)
result_validation.add(f"J2:J{last}")
priority_validation = DataValidation(type="list", formula1='"P1,P2,P3"', allow_blank=False)
test_cases_sheet.add_data_validation(priority_validation)
priority_validation.add(f"I2:I{last}")
for txt, color in (("Pass", "C6EFCE"), ("Fail", "FFC7CE"), ("Blocked", "FFEB9C")):
    test_cases_sheet.conditional_formatting.add(f"J2:J{last}", CellIsRule(
        operator="equal", formula=[f'"{txt}"'], fill=PatternFill("solid", bgColor=color, fgColor=color)))

defects_sheet = workbook.create_sheet("Defects")
head(defects_sheet, 1, ["Defect ID", "Test case ID", "Severity (P1/P2/P3)", "Summary", "Steps to reproduce", "Expected",
             "Actual", "Evidence (screenshot / console)", "Build / commit", "Reported by", "Date", "Status",
             "Fixed in", "Retest result"], [12, 16, 14, 34, 44, 30, 30, 26, 14, 14, 12, 12, 14, 14])
for r in range(2, 202):
    for c in range(1, 15):
        defects_sheet.cell(r, c).font = Font(name=FONT_NAME, size=10)
        defects_sheet.cell(r, c).alignment = wrap
status_validation = DataValidation(type="list", formula1='"Open,In progress,Fixed,Retest passed,Closed,Won\'t fix"')
defects_sheet.add_data_validation(status_validation)
status_validation.add("L2:L201")
defects_sheet.freeze_panes = "A2"

# openpyxl stores formulas without results, sign_off_rows viewers that do not recalculate show blanks;
# cache the values for the initial all "Not run" state alongside each formula.
cached = {}


def fcell(worksheet, row, col, formula, value):
    worksheet.cell(row, col, formula)
    cached[f"{get_column_letter(col)}{row}"] = value


def ratio(a, b):
    return 0 if b == 0 else a / b


RESULTS = ["Pass", "Fail", "Blocked", "N/A", "Not run"]


def tally(sel):
    t = dict.fromkeys(RESULTS, 0)
    t["Not run"] = len(sel)
    return len(sel), t


summary_sheet = workbook.create_sheet("Summary", 1)
summary_sheet["A1"] = "Execution summary"
summary_sheet["A1"].font = Font(name=FONT_NAME, size=14, bold=True)
head(summary_sheet, 3, ["Priority", "Total", "Pass", "Fail", "Blocked", "N/A", "Not run", "% executed", "% passed"])
priority_range = f"'Test cases'!$I$2:$I${last}"
result_range = f"'Test cases'!$J$2:$J${last}"
group_range = f"'Test cases'!$B$2:$B${last}"
rows_tot = []
for i, p in enumerate(["P1", "P2", "P3"], 4):
    summary_sheet.cell(i, 1, p)
    n, t = tally([c for c in cases if c["pri"] == p])
    rows_tot.append((n, t))
    fcell(summary_sheet, i, 2, f"=COUNTIF({priority_range},A{i})", n)
    for c, res in zip(range(3, 8), RESULTS):
        fcell(summary_sheet, i, c, f'=COUNTIFS({priority_range},$A{i},{result_range},"{res}")', t[res])
    fcell(summary_sheet, i, 8, f"=IF(B{i}-F{i}=0,0,(C{i}+D{i}+E{i})/(B{i}-F{i}))",
          ratio(t["Pass"] + t["Fail"] + t["Blocked"], n - t["N/A"]))
    fcell(summary_sheet, i, 9, f"=IF(B{i}-F{i}=0,0,C{i}/(B{i}-F{i}))", ratio(t["Pass"], n - t["N/A"]))
summary_sheet.cell(7, 1, "All")
n_all, t_all = tally(cases)
fcell(summary_sheet, 7, 2, "=SUM(B4:B6)", n_all)
for c, res in zip(range(3, 8), RESULTS):
    L = get_column_letter(c)
    fcell(summary_sheet, 7, c, f"=SUM({L}4:{L}6)", t_all[res])
fcell(summary_sheet, 7, 8, "=IF(B7-F7=0,0,(C7+D7+E7)/(B7-F7))",
      ratio(t_all["Pass"] + t_all["Fail"] + t_all["Blocked"], n_all - t_all["N/A"]))
fcell(summary_sheet, 7, 9, "=IF(B7-F7=0,0,C7/(B7-F7))", ratio(t_all["Pass"], n_all - t_all["N/A"]))
for r in range(4, 8):
    for c in range(1, 10):
        cell = summary_sheet.cell(r, c)
        cell.font = Font(name=FONT_NAME, bold=(r == 7))
        cell.border = border
        if c >= 8:
            cell.number_format = "0.0%"
summary_sheet["A9"] = "Open defects"
cached["B9"] = cached["B10"] = 0
summary_sheet["B9"] = ('=COUNTA(Defects!A2:A201)-COUNTIF(Defects!L2:L201,"Closed")'
            '-COUNTIF(Defects!L2:L201,"Retest passed")-COUNTIF(Defects!L2:L201,"Won\'t fix")')
summary_sheet["A10"] = "Open P1 defects"
summary_sheet["B10"] = ('=COUNTIFS(Defects!C2:C201,"P1")-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Closed")'
             '-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Retest passed")'
             '-COUNTIFS(Defects!C2:C201,"P1",Defects!L2:L201,"Won\'t fix")')
summary_sheet["A9"].font = summary_sheet["A10"].font = Font(name=FONT_NAME, bold=True)
summary_sheet["A12"] = "Results by group"
summary_sheet["A12"].font = Font(name=FONT_NAME, bold=True, size=12)
head(summary_sheet, 13, ["Group", "Total"] + RESULTS)
for i, g in enumerate(groups, 14):
    summary_sheet.cell(i, 1, g).font = Font(name=FONT_NAME)
    n, t = tally([c for c in cases if c["group"] == g])
    fcell(summary_sheet, i, 2, f"=COUNTIF({group_range},A{i})", n)
    for c, res in zip(range(3, 8), RESULTS):
        fcell(summary_sheet, i, c, f'=COUNTIFS({group_range},$A{i},{result_range},"{res}")', t[res])
summary_sheet.column_dimensions["A"].width = 40
for c in "BCDEFGHI":
    summary_sheet.column_dimensions[c].width = 12

xlsx_path = os.path.join(args.out_dir, basename + ".xlsx")
workbook.save(xlsx_path)


def inject_cached_values(path, sheet_xml, values):
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == sheet_xml:
                xml = data.decode("utf-8")
                for ref, val in values.items():
                    pat = re.compile(rf'<c r="{ref}"([^>]*)><f>(.*?)</f>(?:<v\s*/>|<v>[^<]*</v>)?</c>')
                    xml, n = pat.subn(lambda m: f'<c r="{ref}"{m.group(1)}><f>{m.group(2)}</f><v>{val!r}</v></c>', xml)
                    assert n == 1, f"could not cache Summary!{ref}"
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(tmp, path)


inject_cached_values(xlsx_path, f"xl/worksheets/sheet{workbook.sheetnames.index('Summary') + 1}.xml", cached)
if args.xlsx_only:
    print(f"{len(cases)} cases -> {xlsx_path}")
    raise SystemExit

# ------------------------------------------------------------------ PDF
W, H = landscape(A4)
ORANGE = colors.HexColor("#F5A623")
DARK = colors.HexColor("#1F2937")
LINE = colors.HexColor("#D1D5DB")
pdf_styles = dict(
    title=ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=DARK),
    sub=ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.grey, leading=12),
    h1=ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=DARK, spaceBefore=6, spaceAfter=2),
    h2=ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#1D4ED8"), spaceBefore=8),
    meta=ParagraphStyle("m", fontName="Helvetica", fontSize=7.5, textColor=colors.HexColor("#6B7280"), leading=10),
    body=ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=13),
    cell=ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10),
    cellb=ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=8, leading=10),
    table_header=ParagraphStyle("hd", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white),
)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 8 * mm, f"{TITLE}  |  {ENV}  |  {DATE}")
    canvas.drawRightString(W - 15 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def rule():
    t = Table([[""]], colWidths=[W - 30 * mm], rowHeights=[2])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 2, ORANGE)]))
    return t


doc = BaseDocTemplate(os.path.join(args.out_dir, basename + ".pdf"), pagesize=landscape(A4),
                      leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=TITLE, author=f"{PROJECT} QA")
doc.addPageTemplates([PageTemplate(id="p", onPage=footer, frames=[Frame(
    15 * mm, 14 * mm, W - 30 * mm, H - 28 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])

n1 = lambda case, p: sum(c["pri"] == p for c in case)
story = [Paragraph(esc(TITLE), pdf_styles["title"]),
         Paragraph(f"Environment: <b>{esc(ENV)}</b> | {esc(URL)} | Revised {DATE} | {len(cases)} test cases", pdf_styles["sub"]),
         Spacer(1, 8), rule(), Spacer(1, 6)]
intro = [
    "<b>How to use.</b> Test as the role named in each row. Tick Pass or Fail, then enter tester initials, date and a defect ID for every failure. Put a screenshot filename in Notes. A page a login has no permission for must refuse cleanly (redirect or clear message): that is a Pass.",
    f"<b>Priority.</b> P1 = release blocker ({esc(BLOCKER_AREAS)}). P2 = must pass for sign-off. P3 = polish, deferrable with approval.",
    "<b>Exit criteria.</b> All P1 cases executed and passed; at least 95% of P2 passed with agreed workarounds for the rest; no open P1 or P2 defects; sign-off recorded.",
    "<b>Warnings.</b> " + esc(" ".join(w if w.endswith(".") else w + "." for w in warning_lines)),
    f"<b>Companion workbook.</b> Use {esc(basename)}.xlsx for the live results tally, defect log and filtering.",
]
for txt in intro:
    story += [Paragraph(txt, pdf_styles["body"]), Spacer(1, 4)]

story += [Spacer(1, 6), Paragraph("Coverage at a glance", pdf_styles["h1"]), rule(), Spacer(1, 4)]
rows = [[Paragraph(h, pdf_styles["table_header"]) for h in ("Group", "Cases", "P1", "P2", "P3")]]
for g in groups:
    group_cases = [c for c in cases if c["group"] == g]
    rows.append([Paragraph(esc(g), pdf_styles["cell"])] + [Paragraph(str(n), pdf_styles["cell"]) for n in
                (len(group_cases), n1(group_cases, "P1"), n1(group_cases, "P2"), n1(group_cases, "P3"))])
rows.append([Paragraph("Total", pdf_styles["cellb"])] + [Paragraph(str(n), pdf_styles["cellb"]) for n in
            (len(cases), n1(cases, "P1"), n1(cases, "P2"), n1(cases, "P3"))])
t = Table(rows, colWidths=[110 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                       ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F4F6")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
story.append(t)

if spec.get("accounts"):
    story += [Spacer(1, 10), Paragraph("Test accounts and data to prepare", pdf_styles["h1"]), rule(), Spacer(1, 4)]
    prep = [(a[0], a[1] if len(a) > 1 else "") for a in spec["accounts"]]
    prep += [(s[0], "Seed data" + (f" ({s[1]})" if len(s) > 1 and s[1] else "")) for s in spec.get("seed", [])]
    story.append(Table([[Paragraph(esc(a), pdf_styles["cell"]), Paragraph(esc(b), pdf_styles["cell"])] for a, b in prep],
                       colWidths=[110 * mm, 150 * mm],
                       style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")])))
story.append(PageBreak())

column_widths = [29 * mm, 68 * mm, 70 * mm, 9 * mm, 13 * mm, 13 * mm, 48 * mm]
scale = (W - 30 * mm) / sum(column_widths)
column_widths = [c * scale for c in column_widths]
cur = None
for s in spec["sections"]:
    lead = []
    if s["group"] != cur:
        if cur is not None:
            story.append(Spacer(1, 6))
        lead = [Paragraph(esc(s["group"]), pdf_styles["h1"]), rule()]
        cur = s["group"]
    precondition = s.get("precondition")
    section_heading = [Paragraph(f'{esc(s["area"])} <font size="7.5" color="#6B7280">{esc(s.get("route", ""))}</font>', pdf_styles["h2"]),
          Paragraph(f'Role: {esc(s.get("role", ""))}' + (f" | Precondition: {esc(precondition)}" if precondition else ""), pdf_styles["meta"])]
    rows = [[Paragraph(h, pdf_styles["table_header"]) for h in ("ID", "Steps", "Expected result", "Pri", "Pass", "Fail", "Tester / date / defect / notes")]]
    for i, (step, exp, pri) in enumerate(s["cases"], 1):
        rows.append([Paragraph(f'{s["prefix"]}-{i:02d}', pdf_styles["cell"]), Paragraph(esc(step), pdf_styles["cell"]),
                     Paragraph(esc(exp), pdf_styles["cell"]), Paragraph(f"<b>{pri}</b>" if pri == "P1" else pri, pdf_styles["cell"]),
                     Paragraph("[  ]", pdf_styles["cell"]), Paragraph("[  ]", pdf_styles["cell"]), ""])
    t = Table(rows, colWidths=column_widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")])]))
    story.append(KeepTogether(lead + section_heading + [t]))

story += [PageBreak(), Paragraph("Sign-off", pdf_styles["h1"]), rule(), Spacer(1, 10)]
sign_off_rows = [["Tester", "", "Build / commit", ""], ["Date started", "", "Date finished", ""],
      ["P1 passed / total", "", "P2 passed / total", ""], ["Open defects (P1 / P2 / P3)", "", "Decision (Go / No-go)", ""],
      ["Approver name", "", "Signature / date", ""]]
t = Table([[Paragraph(c, pdf_styles["cellb"] if i % 2 == 0 else pdf_styles["cell"]) for i, c in enumerate(r)] for r in sign_off_rows],
          colWidths=[55 * mm, 80 * mm, 55 * mm, 70 * mm], rowHeights=[12 * mm] * len(sign_off_rows))
t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9CA3AF")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                       ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F3F4F6"))]))
story.append(t)
doc.build(story)
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
