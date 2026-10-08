# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Crud (ADR-0094) — a FRONTEND over AutoCrud.

``Crud.to_crud`` renders a complete server-rendered admin UI (searchable,
sortable, paginated table + create/edit/delete modals) for an ORM model. It
owns NO backend routes: the entire REST backend (GET list, GET /{id}, POST,
PUT, DELETE, secure-by-default) is delegated to :class:`AutoCrud`, and the UI's
JavaScript talks to those routes over ``fetch()``. The HTML comes from four
app-overridable Frond templates under ``crud/`` (page, table, form, modals),
each rendered on its own — the SAME app-first-then-framework resolution the
error pages use — so an app restyles the admin by dropping its own
``src/templates/crud/<name>.twig``, no framework fork.

Usage::

    from tina4_python.crud import Crud
    from src.orm.User import User

    @get("/admin/users")
    async def users_admin(request, response):
        return response(Crud.to_crud(request, model=User, title="Users"))

A custom ``sql`` only shapes the LISTING grid (a filter/join/projection); the
model still drives the columns, the primary key, and every write path, so a
custom listing can never create an unauthenticated or divergent write route.
"""
import html as _html
import json
import re
from pathlib import Path

import tina4_python
from tina4_python.crud import AutoCrud
from tina4_python.frond import Frond


class Crud:
    """Frontend-over-AutoCrud CRUD admin page generator (ADR-0094)."""

    # Track which (prefix, table) pairs have had their AutoCrud routes built,
    # so a second to_crud() does not re-register (and reset a public flag).
    _registered_tables: set = set()

    # ── public entry ────────────────────────────────────────────────────
    @staticmethod
    def to_crud(request, model=None, sql=None, title="CRUD", prefix="/api", limit=10):
        """Render the CRUD admin page for ``model`` and register its AutoCrud routes.

        Args:
            request: the current request (read for page/search/sort/sort_dir + path).
            model: REQUIRED — the ORM model class. Drives columns, pk and the backend.
            sql: optional listing query (inferred from the model when omitted); shapes
                only the displayed grid, never the write/GET backend.
            title: page title (default "CRUD").
            prefix: AutoCrud route prefix (default "/api").
            limit: records per page (default 10).

        Returns:
            The rendered ``crud/page`` template (an HTML string).
        """
        if model is None:
            raise ValueError("Crud.to_crud requires model (an ORM class)")

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        if limit <= 0:
            limit = 10
        title = str(title if title is not None else "CRUD")
        prefix = str(prefix or "/api")

        table_name = model._get_table()
        pk = model._get_pk()
        columns = list(model._fields.keys())

        # Backend: delegate 100% to AutoCrud (idempotent — register once).
        Crud._register_backend(model, prefix)

        query = getattr(request, "query", {}) or {}
        try:
            page = max(int(query.get("page", 1)), 1)
        except (TypeError, ValueError):
            page = 1
        search = str(query.get("search", "") or "").strip()
        sort_col = Crud._sort_column(model, sql, query.get("sort"), pk)
        sort_dir = "desc" if query.get("sort_dir") == "desc" else "asc"
        offset = (page - 1) * limit

        if sql:
            records, total = Crud._fetch_sql_data(model, sql, search, sort_col, sort_dir, limit, offset)
        else:
            records, total = Crud._fetch_model_data(model, search, sort_col, sort_dir, limit, offset)

        total_pages = (-(-total // limit)) if total > 0 else 1
        api_path = f"{prefix}/{table_name}"
        request_path = str(getattr(request, "path", "/") or "/")

        return Crud._render_page(
            title=title, table_name=table_name, pk=pk, columns=columns,
            records=records, page=page, total_pages=total_pages, total=total,
            limit=limit, search=search, sort_col=sort_col, sort_dir=sort_dir,
            api_path=api_path, request_path=request_path, model=model,
        )

    @staticmethod
    def generate_table(records, table_name="data", primary_key="id", editable=True):
        """Render an HTML table fragment from a list of record dicts via crud/table.twig.

        Inline-editable (contenteditable cells + Save/Delete buttons wired through
        the template's delegated listener).
        """
        records = records or []
        columns = list(records[0].keys()) if records else []
        return Crud._render_crud("crud/table.twig", Crud._table_data(
            columns=columns, records=records, pk=str(primary_key),
            table_name=str(table_name), editable=editable, sortable=False,
            inline_script=editable, request_path=None, search="", sort_col=None,
            sort_dir="asc", page=1, limit=10, table_id=f"crud-{table_name}", model=None,
        ))

    @staticmethod
    def generate_form(fields, action="/", method="POST", table_name="data"):
        """Render an HTML form from a list of field-definition dicts via crud/form.twig.

        Each field is ``{name, type, label, value, required, options}``.
        """
        verb = str(method).upper()
        return Crud._render_crud("crud/form.twig", {
            "wrap": True,
            "form_id_attr": "",
            "action": Crud._h(action),
            "form_method": Crud._h(verb),
            "method_override": verb if verb in ("PUT", "PATCH", "DELETE") else None,
            "edit": False,
            "modal_footer": False,
            "submit_button": True,
            "fields": [Crud._build_custom_field(f) for f in (fields or [])],
        })

    # ── backend registration (delegated to AutoCrud) ────────────────────
    @staticmethod
    def _register_backend(model, prefix):
        table = model._get_table()
        key = f"{prefix}::{table}"
        if key in Crud._registered_tables:
            return
        # Only register if the app has not already done so (e.g. a scaffolded
        # admin route that registered it public=True) — re-registering would
        # reset that public flag back to secure.
        if table not in AutoCrud.models():
            AutoCrud.register(model, prefix=prefix)
        Crud._registered_tables.add(key)

    # ── fetch ───────────────────────────────────────────────────────────
    @staticmethod
    def _fetch_model_data(model, search, sort_attr, sort_dir, limit, offset):
        """A page of records from the model (ADR-0069 safe search across its
        string/text columns)."""
        order_attr = sort_attr if sort_attr in model._fields else model._get_pk()
        order_col = model.get_db_column(order_attr)
        order_by = f"{order_col} {sort_dir.upper()}"

        if not search:
            records = model.all(limit=limit, offset=offset, order_by=order_by)
            total = model.count()
        else:
            searchable = [model.get_db_column(name)
                          for name, field in model._fields.items() if field.field_type is str]
            if not searchable:
                records = model.all(limit=limit, offset=offset, order_by=order_by)
                total = model.count()
            else:
                where_clause = " OR ".join(f"{col} LIKE ?" for col in searchable)
                params = [f"%{search}%" for _ in searchable]
                records = model.where(where_clause, params, limit=limit, offset=offset, order_by=order_by)
                total = records.get_total_records()
        return [record.to_dict() for record in records], total

    @staticmethod
    def _fetch_sql_data(model, sql, search, sort_col, sort_dir, limit, offset):
        """A page of rows for a custom listing SQL. The SQL shapes the DISPLAY
        only; writes/GET always go through AutoCrud."""
        db = model._get_db()
        if db is None:
            return [], 0

        base = Crud._strip_order_and_limit(sql)
        if not search:
            query = f"{base} ORDER BY {sort_col} {sort_dir.upper()}"
            count_row = db.fetch_one(f"SELECT COUNT(*) as cnt FROM ({base}) AS _crud_cnt")
            total = int((count_row or {}).get("cnt", 0) or 0)
            result = db.fetch(query, [], limit=limit, offset=offset)
        else:
            columns = Crud._extract_columns(sql)
            search_parts = [f"CAST({col} AS TEXT) LIKE ?" for col in columns]
            where = " OR ".join(search_parts)
            wrapped = f"SELECT * FROM ({base}) AS _crud_sub WHERE {where} ORDER BY {sort_col} {sort_dir.upper()}"
            params = [f"%{search}%" for _ in columns]
            count_row = db.fetch_one(
                f"SELECT COUNT(*) as cnt FROM ({base}) AS _crud_cnt WHERE {where}", params)
            total = int((count_row or {}).get("cnt", 0) or 0)
            result = db.fetch(wrapped, params, limit=limit, offset=offset)

        records = result.records if hasattr(result, "records") else list(result)
        return records, total

    # ── safe sort (ADR-0069) ────────────────────────────────────────────
    @staticmethod
    def _sort_column(model, sql, requested, pk):
        """ADR-0069: ?sort reaches ORDER BY only as a column the source declares —
        a model's declared field or a column of the SQL query's own result set.
        Anything else falls back to the primary key (a bad sort on a rendered page
        is ignored, never an error)."""
        if not requested:
            return pk
        if model is not None and sql is None:
            return model._declared_field_for(requested) or pk
        if model is not None and requested not in Crud._sql_result_columns(model, sql):
            return model._declared_field_for(requested) or pk
        if sql:
            cols = Crud._sql_result_columns(model, sql)
            return requested if requested in cols else pk
        return pk

    @staticmethod
    def _sql_result_columns(model, sql):
        db = model._get_db()
        if db is None:
            return []
        base = Crud._strip_order_and_limit(sql)
        result = db.fetch(f"SELECT * FROM ({base}) AS _crud_sub", [], limit=1)
        rows = result.records if hasattr(result, "records") else list(result)
        return [str(k) for k in rows[0].keys()] if rows else []

    @staticmethod
    def _strip_order_and_limit(sql):
        """The query with any trailing ORDER BY / LIMIT clause removed, line by
        line with plain string operations so it stays linear on any input."""
        lines = str(sql).splitlines(keepends=True)
        out = [Crud._cut_from_keyword(Crud._cut_from_keyword(line, "ORDER BY "), "LIMIT ") for line in lines]
        return "".join(out).strip()

    @staticmethod
    def _cut_from_keyword(line, keyword):
        ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if ending else line
        at = content.lower().find(keyword.lower())
        if at < 0 or len(content) <= at + len(keyword):
            return line
        return content[:at] + ending

    @staticmethod
    def _extract_columns(sql):
        match = re.search(r"SELECT\s+(.+?)\s+FROM", str(sql), re.IGNORECASE | re.DOTALL)
        if not match:
            return ["*"]
        cols_str = match.group(1).strip()
        if cols_str == "*":
            return ["*"]
        columns = []
        for col in cols_str.split(","):
            col = col.strip()
            alias = re.search(r"\bAS\s+(\w+)", col, re.IGNORECASE)
            if alias:
                columns.append(alias.group(1))
            elif "." in col:
                columns.append(col.split(".")[-1].strip())
            else:
                columns.append(col)
        return columns

    # ── rendering ───────────────────────────────────────────────────────
    @staticmethod
    def _render_crud(template_name, data):
        """Render a crud/ template, app-first (src/templates) then framework
        (tina4_python/templates) — the same resolution the error pages use."""
        app_path = Path("src/templates") / template_name
        if app_path.exists():
            return Frond("src/templates").render(template_name, data)
        framework_dir = Path(tina4_python.__file__).resolve().parent / "templates"
        return Frond(str(framework_dir)).render(template_name, data)

    @staticmethod
    def _render_page(*, title, table_name, pk, columns, records, page, total_pages,
                     total, limit, search, sort_col, sort_dir, api_path, request_path, model):
        editable_columns = [c for c in columns if c != pk]

        table_html = Crud._render_crud("crud/table.twig", Crud._table_data(
            columns=columns, records=records, pk=pk, table_name=table_name,
            editable=False, sortable=True, inline_script=False,
            request_path=request_path, search=search, sort_col=sort_col,
            sort_dir=sort_dir, page=page, limit=limit, table_id=None, model=model,
        ))

        modals_html = Crud._render_modals(editable_columns, pk)

        return Crud._render_crud("crud/page.twig", {
            "title": Crud._h(title),
            "search": Crud._h(search),
            "request_path": Crud._h(request_path),
            "info_count": len(records),
            "info_total": total,
            "info_page": page,
            "info_total_pages": total_pages,
            "table_html": table_html,
            "modals_html": modals_html,
            "show_pagination": total_pages > 1,
            "controls": Crud._page_controls(page, total_pages, request_path, search, sort_col, sort_dir, limit),
            "config_json": Crud._js_config(
                api_path=api_path, pk=pk, columns=columns, editable=editable_columns,
                model=model, limit=limit, search=search, sort_col=sort_col,
                sort_dir=sort_dir, page=page,
            ),
        })

    @staticmethod
    def _render_modals(editable_columns, pk):
        return Crud._render_crud("crud/modals.twig", {
            "create_form": Crud._render_modal_form("create", editable_columns, pk, edit=False),
            "edit_form": Crud._render_modal_form("edit", editable_columns, pk, edit=True),
        })

    @staticmethod
    def _render_modal_form(mode, columns, pk, *, edit):
        fields = []
        for col in columns:
            label = Crud._pretty_label(col)
            fields.append({
                "id": f"{mode}-{col}",
                "name": Crud._h(col),
                "label": Crud._h(label),
                "value": "",
                "placeholder": Crud._h(f"Enter {label.lower()}"),
                "type": "text",
                "required_attr": "",
                "input": True,
            })
        return Crud._render_crud("crud/form.twig", {
            "wrap": True,
            "form_id_attr": f' id="form-{mode}"',
            "action": "",
            "form_method": "POST",
            "method_override": None,
            "edit": edit,
            "mode": mode,
            "pk": Crud._h(pk),
            "modal_footer": True,
            "submit_button": False,
            "fields": fields,
        })

    @staticmethod
    def _table_data(*, columns, records, pk, table_name, editable, sortable,
                    inline_script, request_path, search, sort_col, sort_dir,
                    page, limit, table_id, model=None):
        aligns = [Crud._column_alignment(model, col) for col in columns]

        headers = []
        for index, col in enumerate(columns):
            header = {"label": Crud._h(Crud._pretty_label(col)), "align": aligns[index]}
            if sortable:
                next_dir = "desc" if (str(sort_col) == str(col) and sort_dir == "asc") else "asc"
                header["sortable"] = True
                header["col"] = Crud._h(col)
                header["next_dir"] = next_dir
                header["url"] = Crud._sort_url(request_path, col, next_dir, page, search, limit)
                header["indicator"] = Crud._sort_indicator(sort_col, col, sort_dir)
            else:
                header["plain"] = True
            headers.append(header)

        rows = [{"id": Crud._h(Crud._cell_value(record, pk)),
                 "cells": Crud._build_cells(columns, record, editable, aligns)}
                for record in records]

        return {
            "headers": headers,
            "rows": rows,
            "empty": len(records) == 0,
            "colspan": len(columns) + 1,
            "editable": editable,
            "readonly": not editable,
            "inline_script": inline_script,
            "table_name": Crud._h(table_name),
            "table_id_attr": (f' id="{Crud._h(table_id)}"' if table_id else ""),
        }

    @staticmethod
    def _build_cells(columns, record, editable, aligns):
        cells = []
        for index, col in enumerate(columns):
            value = Crud._h(Crud._cell_value(record, col))
            css = aligns[index]
            if editable:
                cells.append(f'<td class="{css}" contenteditable="true" data-field="{Crud._h(col)}">{value}</td>')
            else:
                cells.append(f'<td class="{css}">{value}</td>')
        return "".join(cells)

    @staticmethod
    def _column_alignment(model, col):
        """Numeric columns (int/float) align right; everything else left. With no
        model (the generate_table fragment) every column aligns left."""
        if model is None or col not in getattr(model, "_fields", {}):
            return "text-start"
        field_type = model._fields[col].field_type
        return "text-end" if field_type in (int, float) else "text-start"

    @staticmethod
    def _cell_value(record, col):
        if isinstance(record, dict):
            return record.get(col)
        return getattr(record, col, None)

    @staticmethod
    def _build_custom_field(field):
        name = str(field.get("name", ""))
        label = field.get("label") or name.capitalize()
        value = field.get("value")
        required = " required" if field.get("required") else ""
        base = {
            "id": Crud._h(name),
            "name": Crud._h(name),
            "label": Crud._h(str(label)),
            "value": Crud._h("" if value is None else str(value)),
            "placeholder": "",
            "required_attr": required,
        }
        ftype = field.get("type") or "string"
        ftype = ftype if isinstance(ftype, str) else str(ftype)
        if ftype == "text":
            return {**base, "textarea": True}
        if ftype == "boolean":
            return {**base, "checkbox": True, "checked_attr": (" checked" if value else "")}
        if ftype == "select":
            return {**base, "select": True, "options_html": Crud._build_options(field.get("options"), value)}
        if ftype == "date":
            return {**base, "input": True, "type": "date"}
        if ftype in ("integer", "number", "float", "decimal"):
            return {**base, "input": True, "type": "number"}
        return {**base, "input": True, "type": "text"}

    @staticmethod
    def _build_options(options, selected_value):
        parts = []
        for opt in (options or []):
            selected = " selected" if str(opt.get("value")) == str(selected_value) else ""
            parts.append(f'<option value="{Crud._h(opt.get("value"))}"{selected}>{Crud._h(opt.get("label"))}</option>')
        return "".join(parts)

    # ── pagination controls ─────────────────────────────────────────────
    @staticmethod
    def _page_controls(page, total_pages, request_path, search, sort_col, sort_dir, limit):
        if total_pages <= 1:
            return []
        controls = []
        if page > 1:
            controls.append({"label": "Prev", "page": page - 1, "active": False, "inactive": True,
                             "url": Crud._page_url(request_path, page - 1, search, sort_col, sort_dir, limit)})
        start_page = max(page - 3, 1)
        end_page = min(start_page + 6, total_pages)
        start_page = max(end_page - 6, 1)
        for p in range(start_page, end_page + 1):
            controls.append({"label": p, "page": p, "active": (p == page), "inactive": (p != page),
                             "url": Crud._page_url(request_path, p, search, sort_col, sort_dir, limit)})
        if page < total_pages:
            controls.append({"label": "Next", "page": page + 1, "active": False, "inactive": True,
                             "url": Crud._page_url(request_path, page + 1, search, sort_col, sort_dir, limit)})
        return controls

    @staticmethod
    def _page_url(request_path, p, search, sort_col, sort_dir, limit):
        from urllib.parse import quote
        query = (f"page={p}&search={quote(str(search))}"
                 f"&sort={quote(str(sort_col))}&sort_dir={sort_dir}&limit={limit}")
        return Crud._h(f"{request_path}?{query}")

    @staticmethod
    def _sort_url(request_path, col, next_dir, page, search, limit):
        from urllib.parse import quote
        query = (f"sort={quote(str(col))}&sort_dir={next_dir}"
                 f"&page={page}&search={quote(str(search))}&limit={limit}")
        return Crud._h(f"{request_path}?{query}")

    @staticmethod
    def _sort_indicator(sort_col, col, sort_dir):
        if str(sort_col) != str(col):
            return ""
        arrow = "&#9650;" if sort_dir == "asc" else "&#9660;"
        return f' <span class="sort-indicator">{arrow}</span>'

    # ── JSON config for the nonce'd <script> ────────────────────────────
    @staticmethod
    def _js_config(*, api_path, pk, columns, editable, model, limit, search,
                   sort_col, sort_dir, page):
        aligns = {str(col): Crud._column_alignment(model, col) for col in columns}
        labels = {str(col): Crud._pretty_label(col) for col in columns}
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

    # ── small helpers ───────────────────────────────────────────────────
    @staticmethod
    def _h(text):
        """Escape HTML special characters (<, >, &, ", ')."""
        return _html.escape("" if text is None else str(text), quote=True)

    @staticmethod
    def _pretty_label(col):
        return " ".join(word.capitalize() for word in str(col).split("_"))
