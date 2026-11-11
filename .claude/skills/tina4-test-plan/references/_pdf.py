# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""A tiny PDF writer — Python standard library only.

A PDF is a plain object file; this emits the minimum this skill needs: pages
(landscape A4), the two standard Helvetica fonts (no embedding), wrapped text,
tables with wrapped cells and automatic page breaks, filled/stroked rectangles,
and a per-page footer. Text is measured with the published Helvetica AFM widths
so wrapping is real, not guessed. No third-party dependency — the Tina4 way.

Coordinates in the layout API are top-origin (y grows downward); the writer
flips to PDF's bottom-origin space. Content streams are left uncompressed so the
self-test can assert the text it should contain.
"""

# Helvetica AFM advance widths (units per 1000 em) for ASCII 32..126.
_HELV = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556,
    "@": 1015, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778,
    "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556,
    "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556,
    "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722,
    "x": 500, "y": 500, "z": 500, "{": 334, "|": 260, "}": 334, "~": 584,
}
_DEFAULT_W = 556
# Helvetica-Bold is wider; scale up a little so wrapping never overflows.
_BOLD_FACTOR = 1.05


def text_width(s, size, bold=False):
    w = sum(_HELV.get(ch, _DEFAULT_W) for ch in s)
    if bold:
        w *= _BOLD_FACTOR
    return w * size / 1000.0


def _wrap(s, max_w, size, bold=False):
    """Greedy word wrap to max_w points. Long words are hard-split."""
    out = []
    for para in str(s).split("\n"):
        words = para.split(" ")
        line = ""
        for word in words:
            cand = word if not line else line + " " + word
            if text_width(cand, size, bold) <= max_w or not line:
                # a single word longer than the column: hard-split it
                if not line and text_width(word, size, bold) > max_w:
                    piece = ""
                    for ch in word:
                        if text_width(piece + ch, size, bold) > max_w and piece:
                            out.append(piece)
                            piece = ch
                        else:
                            piece += ch
                    line = piece
                else:
                    line = cand
            else:
                out.append(line)
                line = word
        out.append(line)
    return out or [""]


def _pdf_text(s):
    return (str(s).encode("latin-1", "replace").decode("latin-1")
            .replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))


def _rgb(hex6):
    return (int(hex6[0:2], 16) / 255.0, int(hex6[2:4], 16) / 255.0, int(hex6[4:6], 16) / 255.0)


class Page:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ops = []

    def rect(self, x, y_top, w, h, fill=None, stroke=None, line=0.5):
        ll_y = self.h - (y_top + h)
        if fill:
            r, g, b = _rgb(fill)
            self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {ll_y:.2f} {w:.2f} {h:.2f} re f")
        if stroke:
            r, g, b = _rgb(stroke)
            self.ops.append(f"{line:.2f} w {r:.3f} {g:.3f} {b:.3f} RG "
                            f"{x:.2f} {ll_y:.2f} {w:.2f} {h:.2f} re S")

    def text(self, x, baseline_top, s, size, bold=False, color="000000"):
        r, g, b = _rgb(color)
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                        f"{x:.2f} {self.h - baseline_top:.2f} Td ({_pdf_text(s)}) Tj ET")

    def stream(self):
        return "\n".join(self.ops).encode("latin-1", "replace")


class Document:
    """Top-origin flowing layout with automatic pagination."""

    def __init__(self, width=842, height=595, margin=43, bottom=40, footer=None):
        self.w, self.h = width, height
        self.ml = self.mr = margin
        self.mt = margin
        self.mb = bottom
        self.footer = footer          # callable(page, page_number) or None
        self.cx = self.ml
        self.cw = width - self.ml - self.mr
        self.pages = []
        self.y = self.mt
        self._new_page()

    def _new_page(self):
        self.page = Page(self.w, self.h)
        self.pages.append(self.page)
        self.y = self.mt
        if self.footer:
            self.footer(self.page, len(self.pages))

    def page_break(self):
        self._new_page()

    def space(self, h):
        self.y += h

    def _ensure(self, h):
        if self.y + h > self.h - self.mb:
            self._new_page()

    def rule(self, color="F5A623", thickness=2, space_before=2, space_after=6):
        self.y += space_before
        self._ensure(thickness)
        self.page.rect(self.cx, self.y, self.cw, thickness, fill=color)
        self.y += thickness + space_after

    def para(self, text, size=9.5, bold=False, color="111827", leading=None,
             space_after=4, runs=None):
        leading = leading or size + 3.5
        # `runs` lets a paragraph mix bold/plain: list of (text, bold). Width is
        # measured per run; wrapping falls back to the plain path when absent.
        if runs is None:
            lines = _wrap(text, self.cw, size, bold)
            for ln in lines:
                self._ensure(leading)
                self.page.text(self.cx, self.y + size, ln, size, bold, color)
                self.y += leading
        else:
            # simple single-line-friendly mixed runs, wrapped as one logical line
            flat = "".join(t for t, _ in runs)
            lines = _wrap(flat, self.cw, size, False)
            for ln in lines:
                self._ensure(leading)
                self.page.text(self.cx, self.y + size, ln, size, False, color)
                self.y += leading
        self.y += space_after

    def heading(self, text, size=15, color="1F2937", space_before=6, space_after=2):
        self.y += space_before
        self._ensure(size + 4)
        self.page.text(self.cx, self.y + size, text, size, True, color)
        self.y += size + space_after

    def subheading(self, text, size=10.5, color="1D4ED8", meta=None, space_before=8):
        self.y += space_before
        self._ensure(size + 4)
        self.page.text(self.cx, self.y + size, text, size, True, color)
        self.y += size + 2
        if meta:
            self._ensure(11)
            self.page.text(self.cx, self.y + 7.5, meta, 7.5, False, "6B7280")
            self.y += 11

    def table(self, headers, rows, widths, *, font_size=8, header_bg="1F2937",
              header_fg="FFFFFF", grid="D1D5DB", zebra=None, total_last=False,
              pad=3, bold_cols=()):
        leading = font_size + 2

        def row_height(cells):
            n = 1
            for text, w in zip(cells, widths):
                n = max(n, len(_wrap(text, w - 2 * pad, font_size)))
            return n * leading + 2 * pad

        def draw_row(cells, y, bg=None, bold=False):
            h = row_height(cells)
            x = self.cx
            for ci, (text, w) in enumerate(zip(cells, widths)):
                if bg:
                    self.page.rect(x, y, w, h, fill=bg)
                self.page.rect(x, y, w, h, stroke=grid, line=0.4)
                b = bold or ci in bold_cols
                ty = y + pad
                for ln in _wrap(text, w - 2 * pad, font_size):
                    self.page.text(x + pad, ty + font_size, ln, font_size, b,
                                   header_fg if bg == header_bg else "111827")
                    ty += leading
                x += w
            return h

        def draw_header(y):
            return draw_row(headers, y, bg=header_bg)

        self._ensure(row_height(headers) + row_height(rows[0]) if rows else row_height(headers))
        self.y += draw_header(self.y)
        for i, cells in enumerate(rows):
            h = row_height(cells)
            if self.y + h > self.h - self.mb:
                self._new_page()
                self.y += draw_header(self.y)
            bg = None
            if total_last and i == len(rows) - 1:
                bg = "F3F4F6"
            elif zebra:
                bg = zebra[i % 2]
            self.y += draw_row(cells, self.y, bg=bg, bold=total_last and i == len(rows) - 1)

    # ---- serialisation -----------------------------------------------
    def save(self, path):
        objs = []

        def add(body):
            objs.append(body)
            return len(objs)  # 1-based object number

        # 1 catalog, 2 pages, fonts, then page + content pairs
        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                           b"/Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                        b"/Encoding /WinAnsiEncoding >>")
        resources = (f"<< /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >>").encode()

        page_ids = []
        # Reserve the Pages object number before the page objects reference it.
        pages_placeholder = add(b"")  # overwritten once the page ids are known
        for pg in self.pages:
            content = pg.stream()
            stream_num = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
            page_num = add((f"<< /Type /Page /Parent {pages_placeholder} 0 R "
                            f"/MediaBox [0 0 {self.w} {self.h}] "
                            f"/Resources {resources.decode()} "
                            f"/Contents {stream_num} 0 R >>").encode())
            page_ids.append(page_num)
        kids = " ".join(f"{n} 0 R" for n in page_ids)
        objs[pages_placeholder - 1] = (f"<< /Type /Pages /Count {len(page_ids)} "
                                       f"/Kids [{kids}] >>").encode()
        catalog = add(f"<< /Type /Catalog /Pages {pages_placeholder} 0 R >>".encode())

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_pos = len(out)
        out += f"xref\n0 {len(objs) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF\n").encode()
        with open(path, "wb") as f:
            f.write(out)
