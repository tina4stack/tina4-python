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

The field/row/HTML assembly lives in :mod:`tina4_python.crud.page_render`; this
module owns orchestration (backend registration, fetch, safe sort, pagination).
"""
import re

from tina4_python.crud import AutoCrud
from tina4_python.crud import page_render as render


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

        limit = Crud._coerce_limit(limit)
        title = str(title if title is not None else "CRUD")
        prefix = str(prefix or "/api")

        table_name = model._get_table()
        pk = model._get_pk()
        columns = list(model._fields.keys())

        # Backend: delegate 100% to AutoCrud (idempotent — register once).
        Crud._register_backend(model, prefix)

        page, search, sort_col, sort_dir, offset = Crud._list_params(request, model, sql, pk, limit)

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
    def _coerce_limit(limit):
        """A positive int page size, defaulting to 10 for bad/non-positive input."""
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return 10
        return limit if limit > 0 else 10

    @staticmethod
    def _list_params(request, model, sql, pk, limit):
        """Read page/search/sort/sort_dir from the request query and derive the
        offset. The sort column is resolved ADR-0069-safely via _sort_column."""
        query = getattr(request, "query", {}) or {}
        try:
            page = max(int(query.get("page", 1)), 1)
        except (TypeError, ValueError):
            page = 1
        search = str(query.get("search", "") or "").strip()
        sort_col = Crud._sort_column(model, sql, query.get("sort"), pk)
        sort_dir = "desc" if query.get("sort_dir") == "desc" else "asc"
        offset = (page - 1) * limit
        return page, search, sort_col, sort_dir, offset

    @staticmethod
    def generate_table(records, table_name="data", primary_key="id", editable=True):
        """Render an HTML table fragment from a list of record dicts via crud/table.twig.

        Inline-editable (contenteditable cells + Save/Delete buttons wired through
        the template's delegated listener).
        """
        records = records or []
        columns = list(records[0].keys()) if records else []
        return render.render_template("crud/table.twig", render.table_data(
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
        return render.render_template("crud/form.twig", {
            "wrap": True,
            "form_id_attr": "",
            "action": render.escape_html(action),
            "form_method": render.escape_html(verb),
            "method_override": verb if verb in ("PUT", "PATCH", "DELETE") else None,
            "edit": False,
            "modal_footer": False,
            "submit_button": True,
            "fields": [render.build_custom_field(f) for f in (fields or [])],
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
        order_by = Crud._model_order_by(model, sort_attr, sort_dir)
        where_clause, params = Crud._model_search(model, search)
        if where_clause:
            records = model.where(where_clause, params, limit=limit, offset=offset, order_by=order_by)
            total = records.get_total_records()
        else:
            records = model.all(limit=limit, offset=offset, order_by=order_by)
            total = model.count()
        return [record.to_dict() for record in records], total

    @staticmethod
    def _model_order_by(model, sort_attr, sort_dir):
        """The ORDER BY clause for a model listing — the requested sort attribute
        if it is a declared field, else the primary key."""
        order_attr = sort_attr if sort_attr in model._fields else model._get_pk()
        return f"{model.get_db_column(order_attr)} {sort_dir.upper()}"

    @staticmethod
    def _model_search(model, search):
        """ADR-0069 safe search: (where_clause, params) OR'ing LIKE %search%
        across the model's own declared string columns, or (None, []) when there
        is no search term or no searchable column."""
        if not search:
            return None, []
        searchable = [model.get_db_column(name)
                      for name, field in model._fields.items() if field.field_type is str]
        if not searchable:
            return None, []
        where_clause = " OR ".join(f"{col} LIKE ?" for col in searchable)
        return where_clause, [f"%{search}%" for _ in searchable]

    @staticmethod
    def _fetch_sql_data(model, sql, search, sort_col, sort_dir, limit, offset):
        """A page of rows for a custom listing SQL. The SQL shapes the DISPLAY
        only; writes/GET always go through AutoCrud."""
        db = model._get_db()
        if db is None:
            return [], 0

        base = Crud._strip_order_and_limit(sql)
        order = f"ORDER BY {sort_col} {sort_dir.upper()}"
        if not search:
            total = Crud._sql_count(db, f"SELECT COUNT(*) as cnt FROM ({base}) AS _crud_cnt", [])
            result = db.fetch(f"{base} {order}", [], limit=limit, offset=offset)
        else:
            columns = Crud._extract_columns(sql)
            where = " OR ".join(f"CAST({col} AS TEXT) LIKE ?" for col in columns)
            params = [f"%{search}%" for _ in columns]
            total = Crud._sql_count(
                db, f"SELECT COUNT(*) as cnt FROM ({base}) AS _crud_cnt WHERE {where}", params)
            result = db.fetch(
                f"SELECT * FROM ({base}) AS _crud_sub WHERE {where} {order}", params, limit=limit, offset=offset)

        records = result.records if hasattr(result, "records") else list(result)
        return records, total

    @staticmethod
    def _sql_count(db, count_sql, params):
        """Run a COUNT(*) listing query and return the integer total (0 on none)."""
        count_row = db.fetch_one(count_sql, params) if params else db.fetch_one(count_sql)
        return int((count_row or {}).get("cnt", 0) or 0)

    # ── safe sort (ADR-0069) ────────────────────────────────────────────
    @staticmethod
    def _sort_column(model, sql, requested, pk):
        """ADR-0069: ?sort reaches ORDER BY only as a column the source declares —
        a model's declared field or a column of the SQL query's own result set.
        Anything else falls back to the primary key (a bad sort on a rendered page
        is ignored, never an error)."""
        if not requested:
            return pk
        if sql is None:
            return Crud._declared_or_pk(model, requested, pk)
        return Crud._sql_sort_column(model, sql, requested, pk)

    @staticmethod
    def _declared_or_pk(model, requested, pk):
        """The requested name if the model declares it as a field, else the pk."""
        if model is None:
            return pk
        return model._declared_field_for(requested) or pk

    @staticmethod
    def _sql_sort_column(model, sql, requested, pk):
        """Resolve ?sort against a custom listing SQL: honour it only if it is a
        column of the query's own result set, else fall back (declared field/pk)."""
        if requested in Crud._sql_result_columns(model, sql):
            return requested
        return Crud._declared_or_pk(model, requested, pk)

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

    # ── page rendering (assembly delegated to page_render) ──────────────
    @staticmethod
    def _render_page(*, title, table_name, pk, columns, records, page, total_pages,
                     total, limit, search, sort_col, sort_dir, api_path, request_path, model):
        editable_columns = [c for c in columns if c != pk]

        table_html = render.render_template("crud/table.twig", render.table_data(
            columns=columns, records=records, pk=pk, table_name=table_name,
            editable=False, sortable=True, inline_script=False,
            request_path=request_path, search=search, sort_col=sort_col,
            sort_dir=sort_dir, page=page, limit=limit, table_id=None, model=model,
        ))

        modals_html = render.render_modals(editable_columns, pk)

        return render.render_template("crud/page.twig", {
            "title": render.escape_html(title),
            "search": render.escape_html(search),
            "request_path": render.escape_html(request_path),
            "info_count": len(records),
            "info_total": total,
            "info_page": page,
            "info_total_pages": total_pages,
            "table_html": table_html,
            "modals_html": modals_html,
            "show_pagination": total_pages > 1,
            "controls": render.page_controls(page, total_pages, request_path, search, sort_col, sort_dir, limit),
            "config_json": render.js_config(
                api_path=api_path, pk=pk, columns=columns, editable=editable_columns,
                model=model, limit=limit, search=search, sort_col=sort_col,
                sort_dir=sort_dir, page=page,
            ),
        })
