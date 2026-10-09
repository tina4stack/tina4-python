# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ADR-0094: the AutoCrud list endpoint honours ?search and ?sort/?sort_dir.

NO MOCKS: a real SQLite DB on disk, a real model, the real registered list
handler invoked exactly as the dispatcher does. Asserts search filters the
rows (with a filtered total), and sort/sort_dir orders them.
"""
import asyncio
import json
import os

import pytest

from tina4_python.crud import AutoCrud
from tina4_python.core.router import Router
from tina4_python.core.request import Request
from tina4_python.core.response import Response
from tina4_python.database import Database
from tina4_python.orm.model import ORM, bind_database
import tina4_python.orm.model as orm_model
from tina4_python.orm.fields import IntegerField, StringField


class SearchItem(ORM):
    table_name = "searchitems"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField()
    age = IntegerField()


@pytest.fixture
def seeded(tmp_path):
    prev = os.getcwd()
    os.chdir(tmp_path)
    Router.clear()
    AutoCrud.clear()
    db = Database("sqlite:///search.db")
    bind_database(db)
    db.execute("CREATE TABLE searchitems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER)")
    for name, age in (("Alice", 30), ("Albert", 40), ("Bob", 25), ("Charlie", 35)):
        db.insert("searchitems", {"name": name, "age": age})
    AutoCrud.register(SearchItem)
    yield
    Router.clear()
    AutoCrud.clear()
    orm_model._database = None
    os.chdir(prev)


def _list(query):
    route, params = Router.match("GET", "/api/searchitems")
    assert route is not None
    req = Request()
    req.method = "GET"
    req.path = "/api/searchitems"
    req.query = dict(query)
    resp = Response()
    out = asyncio.run(route["handler"](req, resp))
    return json.loads(out.content)


class TestAutoCrudSearch:
    def test_search_filters_rows_and_total(self, seeded):
        body = _list({"search": "Al"})
        names = [r["name"] for r in body["records"]]
        assert set(names) == {"Alice", "Albert"}
        # The total reflects the FILTERED set, not the whole table.
        assert body["total"] == 2

    def test_empty_search_returns_all(self, seeded):
        body = _list({"search": ""})
        assert body["total"] == 4

    def test_search_no_match(self, seeded):
        body = _list({"search": "zzz"})
        assert body["records"] == []
        assert body["total"] == 0


class TestAutoCrudSort:
    def test_sort_asc(self, seeded):
        body = _list({"sort": "name", "sort_dir": "asc"})
        assert [r["name"] for r in body["records"]] == ["Albert", "Alice", "Bob", "Charlie"]

    def test_sort_desc(self, seeded):
        body = _list({"sort": "age", "sort_dir": "desc"})
        assert [r["age"] for r in body["records"]] == [40, 35, 30, 25]

    def test_unknown_sort_column_is_ignored(self, seeded):
        # ADR-0069 safe: an undeclared sort column is ignored, never an error.
        body = _list({"sort": "DROP TABLE searchitems"})
        assert body["total"] == 4

    def test_search_and_sort_combined(self, seeded):
        body = _list({"search": "Al", "sort": "age", "sort_dir": "desc"})
        assert [r["name"] for r in body["records"]] == ["Albert", "Alice"]
        assert body["total"] == 2
