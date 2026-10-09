# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Crud (ADR-0094) — HTML / field / row assembly for the CRUD admin page.

This is the presentation half of :mod:`tina4_python.crud.page`: the pure
functions that turn records, columns and request state into the template
context dicts and HTML fragments the ``crud/`` Frond templates render. It is a
LEAF module — it imports only the stdlib, Frond and the package root, never
``page`` — so ``page`` can build on it without a circular import. ``Crud``
orchestrates (fetch, sort, paginate); this module renders.
"""
import html as _html
import json
from pathlib import Path
from urllib.parse import quote

import tina4_python
from tina4_python.frond import Frond


# ── small helpers ───────────────────────────────────────────────────────
def escape_html(text):
    """Escape HTML special characters (<, >, &, ", ')."""
    return _html.escape("" if text is None else str(text), quote=True)


def pretty_label(col):
    return " ".join(word.capitalize() for word in str(col).split("_"))


def render_template(template_name, data):
    """Render a crud/ template, app-first (src/templates) then framework
    (tina4_python/templates) — the same resolution the error pages use."""
    app_path = Path("src/templates") / template_name
    if app_path.exists():
        return Frond("src/templates").render(template_name, data)
    framework_dir = Path(tina4_python.__file__).resolve().parent / "templates"
    return Frond(str(framework_dir)).render(template_name, data)


# ── table / row assembly ──────────────────────────────────────────────────
def column_alignment(model, col):
    """Numeric columns (int/float) align right; everything else left. With no
    model (the generate_table fragment) every column aligns left."""
    if model is None or col not in getattr(model, "_fields", {}):
        return "text-start"
    field_type = model._fields[col].field_type
    return "text-end" if field_type in (int, float) else "text-start"


def cell_value(record, col):
    if isinstance(record, dict):
        return record.get(col)
    return getattr(record, col, None)


def build_cells(columns, record, editable, aligns):
    cells = []
    for index, col in enumerate(columns):
        value = escape_html(cell_value(record, col))
        css = aligns[index]
        if editable:
            cells.append(f'<td class="{css}" contenteditable="true" data-field="{escape_html(col)}">{value}</td>')
        else:
            cells.append(f'<td class="{css}">{value}</td>')
    return "".join(cells)


def _header(col, align, *, sortable, request_path, search, sort_col, sort_dir, page, limit):
    """One table-header dict — a plain label, or a sortable link carrying the
    next sort direction, URL and the asc/desc indicator for the active column."""
    header = {"label": escape_html(pretty_label(col)), "align": align}
    if not sortable:
        header["plain"] = True
        return header
    next_dir = "desc" if (str(sort_col) == str(col) and sort_dir == "asc") else "asc"
    header["sortable"] = True
    header["col"] = escape_html(col)
    header["next_dir"] = next_dir
    header["url"] = sort_url(request_path, col, next_dir, page, search, limit)
    header["indicator"] = sort_indicator(sort_col, col, sort_dir)
    return header


def table_data(*, columns, records, pk, table_name, editable, sortable,
               inline_script, request_path, search, sort_col, sort_dir,
               page, limit, table_id, model=None):
    aligns = [column_alignment(model, col) for col in columns]

    headers = [_header(col, aligns[index], sortable=sortable, request_path=request_path,
                       search=search, sort_col=sort_col, sort_dir=sort_dir, page=page, limit=limit)
               for index, col in enumerate(columns)]

    rows = [{"id": escape_html(cell_value(record, pk)),
             "cells": build_cells(columns, record, editable, aligns)}
            for record in records]

    return {
        "headers": headers,
        "rows": rows,
        "empty": len(records) == 0,
        "colspan": len(columns) + 1,
        "editable": editable,
        "readonly": not editable,
        "inline_script": inline_script,
        "table_name": escape_html(table_name),
        "table_id_attr": (f' id="{escape_html(table_id)}"' if table_id else ""),
    }


# ── modal + form assembly ─────────────────────────────────────────────────
def render_modals(editable_columns, pk):
    return render_template("crud/modals.twig", {
        "create_form": render_modal_form("create", editable_columns, pk, edit=False),
        "edit_form": render_modal_form("edit", editable_columns, pk, edit=True),
    })


def render_modal_form(mode, columns, pk, *, edit):
    fields = []
    for col in columns:
        label = pretty_label(col)
        fields.append({
            "id": f"{mode}-{col}",
            "name": escape_html(col),
            "label": escape_html(label),
            "value": "",
            "placeholder": escape_html(f"Enter {label.lower()}"),
            "type": "text",
            "required_attr": "",
            "input": True,
        })
    return render_template("crud/form.twig", {
        "wrap": True,
        "form_id_attr": f' id="form-{mode}"',
        "action": "",
        "form_method": "POST",
        "method_override": None,
        "edit": edit,
        "mode": mode,
        "pk": escape_html(pk),
        "modal_footer": True,
        "submit_button": False,
        "fields": fields,
    })


def build_custom_field(field):
    name = str(field.get("name", ""))
    label = field.get("label") or name.capitalize()
    value = field.get("value")
    base = {
        "id": escape_html(name),
        "name": escape_html(name),
        "label": escape_html(str(label)),
        "value": escape_html("" if value is None else str(value)),
        "placeholder": "",
        "required_attr": " required" if field.get("required") else "",
    }
    ftype = field.get("type") or "string"
    ftype = ftype if isinstance(ftype, str) else str(ftype)
    return {**base, **_field_type_attrs(ftype, field, value)}


# The HTML input type each custom-field "type" maps to; anything unlisted is a
# plain text input. text/boolean/select are richer controls handled separately.
_INPUT_TYPES = {
    "date": "date",
    "integer": "number",
    "number": "number",
    "float": "number",
    "decimal": "number",
}


def _field_type_attrs(ftype, field, value):
    """The type-specific attributes merged onto a custom field's base dict."""
    if ftype == "text":
        return {"textarea": True}
    if ftype == "boolean":
        return {"checkbox": True, "checked_attr": (" checked" if value else "")}
    if ftype == "select":
        return {"select": True, "options_html": build_options(field.get("options"), value)}
    return {"input": True, "type": _INPUT_TYPES.get(ftype, "text")}


def build_options(options, selected_value):
    parts = []
    for opt in (options or []):
        selected = " selected" if str(opt.get("value")) == str(selected_value) else ""
        parts.append(f'<option value="{escape_html(opt.get("value"))}"{selected}>{escape_html(opt.get("label"))}</option>')
    return "".join(parts)


# ── pagination controls ───────────────────────────────────────────────────
def page_controls(page, total_pages, request_path, search, sort_col, sort_dir, limit):
    if total_pages <= 1:
        return []
    controls = []
    if page > 1:
        controls.append({"label": "Prev", "page": page - 1, "active": False, "inactive": True,
                         "url": page_url(request_path, page - 1, search, sort_col, sort_dir, limit)})
    start_page = max(page - 3, 1)
    end_page = min(start_page + 6, total_pages)
    start_page = max(end_page - 6, 1)
    for p in range(start_page, end_page + 1):
        controls.append({"label": p, "page": p, "active": (p == page), "inactive": (p != page),
                         "url": page_url(request_path, p, search, sort_col, sort_dir, limit)})
    if page < total_pages:
        controls.append({"label": "Next", "page": page + 1, "active": False, "inactive": True,
                         "url": page_url(request_path, page + 1, search, sort_col, sort_dir, limit)})
    return controls


def page_url(request_path, p, search, sort_col, sort_dir, limit):
    query = (f"page={p}&search={quote(str(search))}"
             f"&sort={quote(str(sort_col))}&sort_dir={sort_dir}&limit={limit}")
    return escape_html(f"{request_path}?{query}")


def sort_url(request_path, col, next_dir, page, search, limit):
    query = (f"sort={quote(str(col))}&sort_dir={next_dir}"
             f"&page={page}&search={quote(str(search))}&limit={limit}")
    return escape_html(f"{request_path}?{query}")


def sort_indicator(sort_col, col, sort_dir):
    if str(sort_col) != str(col):
        return ""
    arrow = "&#9650;" if sort_dir == "asc" else "&#9660;"
    return f' <span class="sort-indicator">{arrow}</span>'


# ── JSON config for the nonce'd <script> ──────────────────────────────────
def js_config(*, api_path, pk, columns, editable, model, limit, search,
              sort_col, sort_dir, page):
    aligns = {str(col): column_alignment(model, col) for col in columns}
    labels = {str(col): pretty_label(col) for col in columns}
    config = {
        "api": api_path,
        "pk": pk,
        "columns": [str(col) for col in columns],
        "editable": [str(col) for col in editable],
        "aligns": aligns,
        "labels": labels,
        "limit": limit,
        "search": str(search),
        "sort": str(sort_col),
        "sort_dir": sort_dir,
        "page": page,
    }
    return (json.dumps(config)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
