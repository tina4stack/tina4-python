# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""A tiny OOXML (.xlsx) writer — Python standard library only.

An .xlsx is a zip of XML parts; this emits exactly the parts this skill needs:
cells (text / number / formula-with-cached-value), fonts, solid fills, thin
borders, column widths, frozen panes, an auto-filter, list data-validation
(dropdowns) and conditional fills. No third-party dependency — the Tina4 way.

Strings are written inline (t="inlineStr"), so a cell whose text begins with "="
is stored verbatim and never becomes a live formula. Formula cells carry their
cached <v> directly, so a viewer that does not recalculate still shows numbers.
"""
import zipfile

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_letter(col):
    """1 -> A, 27 -> AA."""
    s = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return s


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _argb(hex6):
    return "FF" + hex6.upper()


class _Style:
    __slots__ = ("font", "fill", "border", "wrap", "valign", "halign", "numfmt")

    def __init__(self, font, fill, border, wrap, valign, halign, numfmt):
        self.font = font          # (name, size, bold, color6|None)
        self.fill = fill          # hex6 | None
        self.border = border      # bool (thin all round)
        self.wrap = wrap
        self.valign = valign      # "top"/"center"/None
        self.halign = halign      # "center"/None
        self.numfmt = numfmt      # format code string | None

    def key(self):
        return (self.font, self.fill, self.border, self.wrap, self.valign, self.halign, self.numfmt)


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}        # (row, col) -> ("s"|"n"|"f", value, cached, style_id)
        self.widths = {}       # col -> width
        self.freeze_cell = None  # (row, col)
        self.filter_ref = None
        self.validations = []  # (sqref, options_list)
        self.cond_fills = []   # (sqref, equals_text, dxf_id)
        self.max_row = 0
        self.max_col = 0

    def _mark(self, row, col):
        self.max_row = max(self.max_row, row)
        self.max_col = max(self.max_col, col)

    def text(self, row, col, value, style=0):
        self.cells[(row, col)] = ("s", "" if value is None else str(value), None, style)
        self._mark(row, col)

    def number(self, row, col, value, style=0):
        self.cells[(row, col)] = ("n", value, None, style)
        self._mark(row, col)

    def formula(self, row, col, formula, cached, style=0):
        self.cells[(row, col)] = ("f", formula, cached, style)
        self._mark(row, col)

    def set_width(self, col, width):
        self.widths[col] = width

    def freeze(self, row, col):
        self.freeze_cell = (row, col)

    def auto_filter(self, ref):
        self.filter_ref = ref

    def validation(self, sqref, options):
        self.validations.append((sqref, list(options)))

    def cond_fill(self, sqref, equals_text, dxf_id):
        self.cond_fills.append((sqref, equals_text, dxf_id))


class Workbook:
    def __init__(self):
        self.sheets = []
        self._fonts = {}
        self._fills = {"none": 0, "gray125": 1}
        self._borders = {"none": 0, "thin": 1}
        self._numfmts = {}       # code -> id (>=164)
        self._xfs = {}           # style.key() -> index
        self._xf_list = []       # list of _Style in index order
        self._dxfs = []          # list of hex6 (conditional fill bg)
        # xf 0 is the default (unstyled) cell
        self.default_font = ("Calibri", 11, False, None)
        self._intern(_Style(self.default_font, None, False, False, None, None, None))

    # ---- styles -------------------------------------------------------
    def style(self, name="Arial", size=11, bold=False, color=None, fill=None,
              border=False, wrap=False, valign=None, halign=None, numfmt=None):
        return self._intern(_Style((name, size, bold, color), fill, border, wrap, valign, halign, numfmt))

    def _intern(self, st):
        k = st.key()
        if k in self._xfs:
            return self._xfs[k]
        self._fonts.setdefault(st.font, len(self._fonts))
        if st.fill:
            self._fills.setdefault(st.fill, len(self._fills))
        if st.numfmt:
            self._numfmts.setdefault(st.numfmt, 164 + len(self._numfmts))
        idx = len(self._xf_list)
        self._xf_list.append(st)
        self._xfs[k] = idx
        return idx

    def dxf_fill(self, hex6):
        self._dxfs.append(hex6)
        return len(self._dxfs) - 1

    def add_sheet(self, name):
        sh = Sheet(name)
        self.sheets.append(sh)
        return sh

    # ---- rendering ----------------------------------------------------
    def _styles_xml(self):
        fonts = sorted(self._fonts.items(), key=lambda kv: kv[1])
        font_xml = []
        for (nm, sz, bold, color), _ in fonts:
            parts = [f'<sz val="{sz}"/>', f'<name val="{_esc(nm)}"/>']
            if bold:
                parts.insert(0, "<b/>")
            if color:
                parts.append(f'<color rgb="{_argb(color)}"/>')
            font_xml.append("<font>" + "".join(parts) + "</font>")

        fills = sorted(self._fills.items(), key=lambda kv: kv[1])
        fill_xml = []
        for name, _ in fills:
            if name == "none":
                fill_xml.append('<fill><patternFill patternType="none"/></fill>')
            elif name == "gray125":
                fill_xml.append('<fill><patternFill patternType="gray125"/></fill>')
            else:
                fill_xml.append(f'<fill><patternFill patternType="solid">'
                                f'<fgColor rgb="{_argb(name)}"/></patternFill></fill>')

        border_xml = [
            "<border><left/><right/><top/><bottom/><diagonal/></border>",
            ('<border>'
             '<left style="thin"><color rgb="FFBFBFBF"/></left>'
             '<right style="thin"><color rgb="FFBFBFBF"/></right>'
             '<top style="thin"><color rgb="FFBFBFBF"/></top>'
             '<bottom style="thin"><color rgb="FFBFBFBF"/></bottom>'
             '<diagonal/></border>'),
        ]

        numfmt_xml = "".join(f'<numFmt numFmtId="{i}" formatCode="{_esc(code)}"/>'
                             for code, i in sorted(self._numfmts.items(), key=lambda kv: kv[1]))
        numfmts = f'<numFmts count="{len(self._numfmts)}">{numfmt_xml}</numFmts>' if self._numfmts else ""

        xf_xml = []
        for st in self._xf_list:
            font_id = self._fonts[st.font]
            fill_id = self._fills[st.fill] if st.fill else 0
            border_id = 1 if st.border else 0
            numfmt_id = self._numfmts[st.numfmt] if st.numfmt else 0
            attrs = [f'numFmtId="{numfmt_id}"', f'fontId="{font_id}"',
                     f'fillId="{fill_id}"', f'borderId="{border_id}"', 'xfId="0"']
            if font_id:
                attrs.append('applyFont="1"')
            if fill_id:
                attrs.append('applyFill="1"')
            if border_id:
                attrs.append('applyBorder="1"')
            if numfmt_id:
                attrs.append('applyNumberFormat="1"')
            align = ""
            if st.wrap or st.valign or st.halign:
                a = []
                if st.halign:
                    a.append(f'horizontal="{st.halign}"')
                if st.valign:
                    a.append(f'vertical="{st.valign}"')
                if st.wrap:
                    a.append('wrapText="1"')
                attrs.append('applyAlignment="1"')
                align = f'<alignment {" ".join(a)}/>'
            xf_xml.append(f'<xf {" ".join(attrs)}>{align}</xf>' if align
                          else f'<xf {" ".join(attrs)}/>')

        dxf_xml = "".join(f'<dxf><fill><patternFill><bgColor rgb="{_argb(c)}"/>'
                          f'</patternFill></fill></dxf>' for c in self._dxfs)
        dxfs = f'<dxfs count="{len(self._dxfs)}">{dxf_xml}</dxfs>' if self._dxfs else ""

        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<styleSheet xmlns="{_NS_MAIN}">'
                f'{numfmts}'
                f'<fonts count="{len(font_xml)}">{"".join(font_xml)}</fonts>'
                f'<fills count="{len(fill_xml)}">{"".join(fill_xml)}</fills>'
                f'<borders count="2">{"".join(border_xml)}</borders>'
                f'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xf_xml)}">{"".join(xf_xml)}</cellXfs>'
                f'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                f'{dxfs}'
                f'</styleSheet>')

    def _sheet_xml(self, sh):
        views = ""
        if sh.freeze_cell:
            fr, fc = sh.freeze_cell
            top_left = f"{col_letter(fc)}{fr}"
            views = (f'<sheetView workbookViewId="0">'
                     f'<pane xSplit="{fc - 1}" ySplit="{fr - 1}" topLeftCell="{top_left}" '
                     f'activePane="bottomRight" state="frozen"/></sheetView>')
        else:
            views = '<sheetView workbookViewId="0"/>'
        sheet_views = f"<sheetViews>{views}</sheetViews>"

        cols = ""
        if sh.widths:
            col_items = "".join(
                f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>'
                for c, w in sorted(sh.widths.items()))
            cols = f"<cols>{col_items}</cols>"

        rows_xml = []
        by_row = {}
        for (r, c), cell in sh.cells.items():
            by_row.setdefault(r, []).append((c, cell))
        for r in sorted(by_row):
            cells = []
            for c, (kind, value, cached, style) in sorted(by_row[r]):
                ref = f"{col_letter(c)}{r}"
                s_attr = f' s="{style}"' if style else ""
                if kind == "s":
                    cells.append(f'<c r="{ref}"{s_attr} t="inlineStr"><is>'
                                 f'<t xml:space="preserve">{_esc(value)}</t></is></c>')
                elif kind == "n":
                    cells.append(f'<c r="{ref}"{s_attr}><v>{value}</v></c>')
                else:  # formula with cached value
                    cv = "" if cached is None else f"<v>{_esc(cached)}</v>"
                    cells.append(f'<c r="{ref}"{s_attr}><f>{_esc(value)}</f>{cv}</c>')
            rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_data = f'<sheetData>{"".join(rows_xml)}</sheetData>'

        autofilter = f'<autoFilter ref="{sh.filter_ref}"/>' if sh.filter_ref else ""

        cond = ""
        for sqref, equals, dxf_id in sh.cond_fills:
            cond += (f'<conditionalFormatting sqref="{sqref}">'
                     f'<cfRule type="cellIs" dxfId="{dxf_id}" priority="{len(cond) + 1}" operator="equal">'
                     f'<formula>"{_esc(equals)}"</formula></cfRule></conditionalFormatting>')

        dv = ""
        if sh.validations:
            items = "".join(
                f'<dataValidation type="list" allowBlank="1" showInputMessage="1" '
                f'showErrorMessage="1" sqref="{sqref}">'
                f'<formula1>"{_esc(",".join(opts))}"</formula1></dataValidation>'
                for sqref, opts in sh.validations)
            dv = f'<dataValidations count="{len(sh.validations)}">{items}</dataValidations>'

        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<worksheet xmlns="{_NS_MAIN}" xmlns:r="{_NS_R}">'
                f'{sheet_views}{cols}{sheet_data}{autofilter}{cond}{dv}</worksheet>')

    def save(self, path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            sheet_overrides = "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(self.sheets) + 1))
            z.writestr("[Content_Types].xml",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<Types xmlns="{_NS_CT}">'
                       f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       f'<Default Extension="xml" ContentType="application/xml"/>'
                       f'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                       f'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                       f'{sheet_overrides}</Types>')
            z.writestr("_rels/.rels",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<Relationships xmlns="{_NS_PR}">'
                       f'<Relationship Id="rId1" Type="{_NS_R}/officeDocument" Target="xl/workbook.xml"/>'
                       f'</Relationships>')
            sheet_tags = "".join(
                f'<sheet name="{_esc(sh.name)}" sheetId="{i}" r:id="rId{i}"/>'
                for i, sh in enumerate(self.sheets, 1))
            z.writestr("xl/workbook.xml",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_R}">'
                       f'<sheets>{sheet_tags}</sheets></workbook>')
            rels = "".join(
                f'<Relationship Id="rId{i}" Type="{_NS_R}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(self.sheets) + 1))
            rels += (f'<Relationship Id="rId{len(self.sheets) + 1}" Type="{_NS_R}/styles" '
                     f'Target="styles.xml"/>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<Relationships xmlns="{_NS_PR}">{rels}</Relationships>')
            z.writestr("xl/styles.xml", self._styles_xml())
            for i, sh in enumerate(self.sheets, 1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", self._sheet_xml(sh))
