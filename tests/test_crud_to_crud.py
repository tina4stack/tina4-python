# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Behavioural tests for Crud.to_crud (ADR-0094) — a FRONTEND over AutoCrud.

NO MOCKS: a real SQLite database on disk, a real Request, and the real
Crud.to_crud HTML generator rendering the real shipped crud/*.twig templates
through a real Frond engine. The assertions run against the exact bytes the
framework emits.
"""
import os
import re

import pytest

from tina4_python.crud import Crud, AutoCrud
from tina4_python.core.router import Router
from tina4_python.core.request import Request
from tina4_python.database import Database
from tina4_python.orm.model import ORM, bind_database
import tina4_python.orm.model as orm_model
from tina4_python.orm.fields import IntegerField, StringField


class CrudWidget(ORM):
    table_name = "crudwidgets"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    email = StringField()
    age = IntegerField()


# Matches an inline HTML event-handler attribute (onclick=, onsubmit=, …) but
# NOT a JS property assignment (el.onclick = fn), which is CSP-allowed.
INLINE_HANDLER_ATTR = re.compile(r"""\son[a-z]+\s*=\s*["']""")
# Matches an inline style= attribute — dead under default-src 'self' (ADR-0088).
INLINE_STYLE_ATTR = re.compile(r"""\sstyle\s*=\s*["']""")


@pytest.fixture
def project(tmp_path):
    """A clean working directory with a real seeded SQLite DB bound to the model."""
    prev = os.getcwd()
    os.chdir(tmp_path)
    Router.clear()
    AutoCrud.clear()
    Crud._registered_tables.clear()
    db = Database("sqlite:///crud_test.db")
    bind_database(db)
    db.execute(
        "CREATE TABLE crudwidgets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT, email TEXT, age INTEGER)"
    )
    for name, age in (("Alice", 30), ("Bob", 25), ("Charlie", 35)):
        db.insert("crudwidgets", {"name": name, "email": f"{name.lower()}@example.com", "age": age})
    yield tmp_path
    Router.clear()
    AutoCrud.clear()
    Crud._registered_tables.clear()
    orm_model._database = None
    os.chdir(prev)


def _request(path="/admin/crudwidgets", query=None):
    req = Request()
    req.method = "GET"
    req.path = path
    req.query = dict(query or {})
    return req


def _route_strings():
    return [f"{r['method']} {r['path']}" for r in Router.get_routes()]


# ── to_crud with a model ──────────────────────────────────────────────
class TestToCrudModel:
    def test_generates_a_complete_html_page(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="Test CRUD")
        assert "Test CRUD" in html
        assert "<table" in html
        assert "Alice" in html and "Bob" in html and "Charlie" in html

    def test_includes_create_edit_delete_modals(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="Test CRUD")
        for marker in ("modal-create", "modal-edit", "modal-delete",
                       "Create New Record", "Edit Record", "Confirm Delete"):
            assert marker in html

    def test_live_search_input_not_a_submit_form(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget)
        # ADR-0094 search is live/AJAX: a data-crud-search input, no Search button.
        assert "data-crud-search" in html
        assert 'placeholder="Search..."' in html
        assert ">Search</button>" not in html

    def test_sort_and_pager_drive_autocrud_over_ajax(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, limit=2)
        assert "AbortController" in html
        assert "data-crud-body" in html
        assert "data-crud-sort=" in html
        assert "data-crud-page=" in html

    def test_alignment_numeric_right_text_left_no_inline_style(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget)
        # id + age are integer -> text-end; name/email are text -> text-start.
        assert 'class="text-end"' in html
        assert 'class="text-start"' in html
        assert INLINE_STYLE_ATTR.findall(html) == []

    def test_includes_pagination_info(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget)
        assert "Showing 3 of 3 records" in html

    def test_includes_sort_links(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget)
        assert "sort=id" in html
        assert "sort=name" in html
        assert "sort=email" in html

    def test_validation_wiring_present(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget)
        assert "crudShowCreate" in html
        assert "saveRecord" in html
        assert "crudConfirmDelete" in html
        # A failed save surfaces the AutoCrud non-2xx {errors}/{error} inline and
        # keeps the modal open (it checks res.ok, not a false success).
        assert "data-crud-errors" in html
        assert "showErrors" in html
        assert "res.ok" in html

    def test_registers_full_autocrud_backend(self, project):
        Crud.to_crud(_request(), model=CrudWidget)
        routes = _route_strings()
        assert "GET /api/crudwidgets" in routes
        assert "GET /api/crudwidgets/{id}" in routes
        assert "POST /api/crudwidgets" in routes
        assert "PUT /api/crudwidgets/{id}" in routes
        assert "DELETE /api/crudwidgets/{id}" in routes

    def test_registers_no_bespoke_route_of_its_own(self, project):
        Crud.to_crud(_request(), model=CrudWidget)
        table_routes = sorted(r for r in _route_strings() if "/api/crudwidgets" in r)
        assert table_routes == [
            "DELETE /api/crudwidgets/{id}",
            "GET /api/crudwidgets",
            "GET /api/crudwidgets/{id}",
            "POST /api/crudwidgets",
            "PUT /api/crudwidgets/{id}",
        ]

    def test_idempotent_second_call(self, project):
        Crud.to_crud(_request(), model=CrudWidget)
        Crud.to_crud(_request(), model=CrudWidget)
        count = len([r for r in _route_strings() if "/api/crudwidgets" in r])
        assert count == 5


# ── to_crud with a custom sql listing ──────────────────────────────────
class TestToCrudSql:
    def test_sql_shapes_the_grid_model_drives_the_backend(self, project):
        html = Crud.to_crud(
            _request(), model=CrudWidget,
            sql="SELECT id, name, email FROM crudwidgets", title="SQL CRUD",
        )
        assert "SQL CRUD" in html
        assert "Alice" in html and "Bob" in html
        routes = _route_strings()
        assert "GET /api/crudwidgets" in routes
        assert "POST /api/crudwidgets" in routes


# ── search + pagination ─────────────────────────────────────────────────
class TestToCrudSearch:
    def test_filters_records_by_search_term(self, project):
        html = Crud.to_crud(_request(query={"search": "Alice"}), model=CrudWidget, title="Search")
        assert "Alice" in html
        # Bob/Charlie fall out of the server-rendered first page.
        assert "<td" in html
        assert "Bob" not in html
        assert "Charlie" not in html


class TestToCrudPagination:
    def test_first_page(self, project):
        html = Crud.to_crud(_request(query={"page": "1"}), model=CrudWidget, limit=2)
        assert "page 1 of 2" in html
        assert "Next" in html

    def test_second_page(self, project):
        html = Crud.to_crud(_request(query={"page": "2"}), model=CrudWidget, limit=2)
        assert "page 2 of 2" in html
        assert "Prev" in html


# ── model required (ADR-0094) ──────────────────────────────────────────
class TestModelRequired:
    def test_raises_without_model(self, project):
        with pytest.raises(ValueError):
            Crud.to_crud(_request(), title="Broken")

    def test_sql_only_raises(self, project):
        with pytest.raises(ValueError):
            Crud.to_crud(_request(), sql="SELECT id, name FROM crudwidgets")


# ── CSP: zero inline on*= / style= (ADR-0088), mutation-proven ──────────
class TestCsp:
    def test_zero_inline_on_handlers(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="CSP")
        offenders = INLINE_HANDLER_ATTR.findall(html)
        assert offenders == [], f"inline on*= emitted: {offenders}"

    def test_zero_inline_style(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="CSP")
        offenders = INLINE_STYLE_ATTR.findall(html)
        assert offenders == [], f"inline style= emitted: {offenders}"

    def test_gates_are_real_mutation_proof(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="CSP")
        mutated = html.replace("<h2>", '<h2 onclick="x()" style="color:red">', 1)
        assert INLINE_HANDLER_ATTR.findall(mutated) != []
        assert INLINE_STYLE_ATTR.findall(mutated) != []

    def test_actions_wired_with_data_attributes(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="CSP")
        for marker in ('data-crud-action="create"', 'data-crud-action="edit"',
                       'data-crud-action="delete"', 'data-crud-action="save"',
                       'data-crud-action="confirm-delete"', 'data-id="', 'data-crud-mode="'):
            assert marker in html

    def test_actions_bound_through_delegated_listener_in_nonced_script(self, project):
        html = Crud.to_crud(_request(), model=CrudWidget, title="CSP")
        assert "<script nonce=" in html
        assert "addEventListener('click'" in html
        assert "button.dataset.crudAction" in html
        assert "addEventListener('submit'" in html
        assert 'data-crud-form="1"' in html


# ── app template override (src/templates/crud wins) ─────────────────────
class TestAppOverride:
    def test_app_table_template_wins_over_framework(self, project):
        crud_dir = project / "src" / "templates" / "crud"
        crud_dir.mkdir(parents=True)
        (crud_dir / "table.twig").write_text(
            '<div class="app-override-marker">OVERRIDDEN TABLE</div>'
        )
        html = Crud.to_crud(_request(), model=CrudWidget, title="Override")
        assert "app-override-marker" in html
        assert "OVERRIDDEN TABLE" in html
        # The page shell (not overridden) still rendered around it.
        assert "Override" in html
        assert "modal-create" in html


# ── generate_table / generate_form helpers ──────────────────────────────
class TestGenerateTable:
    def test_generates_table_from_records(self, project):
        html = Crud.generate_table(
            [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            table_name="users", primary_key="id",
        )
        assert "<table" in html
        assert "Alice" in html and "Bob" in html
        assert "crudSave" in html
        assert INLINE_HANDLER_ATTR.findall(html) == []
        assert INLINE_STYLE_ATTR.findall(html) == []

    def test_empty_records_message(self, project):
        html = Crud.generate_table([], table_name="users")
        assert "No records found" in html


class TestGenerateForm:
    def test_generates_form_from_fields(self, project):
        html = Crud.generate_form(
            [{"name": "name", "type": "string", "label": "Full Name", "required": True},
             {"name": "email", "type": "string", "label": "Email"}],
            action="/api/users", method="POST",
        )
        assert "<form" in html
        assert "Full Name" in html
        assert 'name="name"' in html
        assert 'name="email"' in html
