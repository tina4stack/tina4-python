# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regression: a route path param like {id} must match an INTEGER primary key.

An untyped path param is captured as a str; SQLite gives a TEXT operand numeric
affinity, so `WHERE id = ?` bound with str "2" matches INTEGER 2. This is the
master contract the other frameworks mirror (tina4-ruby had a bug where its
path captures arrived as ASCII-8BIT and bound as a BLOB, which skips affinity,
so GET /api/users/{id} 404'd a real row). No mocks: real Router + real SQLite.
"""

import pytest

from tina4_python.core.router import Router, get
from tina4_python.database import Database


@pytest.fixture(autouse=True)
def clear_routes():
    Router.clear()
    yield
    Router.clear()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "database.db")
    d = Database(f"sqlite:///{path}")
    d.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    d.execute("INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Carol')")
    try:
        yield d
    finally:
        d.close()


class TestPathParamIntegerPkLookup:
    def test_untyped_param_is_str_and_matches_integer_pk(self, db):
        @get("/api/users/{id}")
        async def handler(request, response):  # noqa: ANN001
            pass

        route, params = Router.match("GET", "/api/users/2")
        assert route is not None
        assert params["id"] == "2"
        assert isinstance(params["id"], str)

        # The router's captured param, bound through a real SQLite connection,
        # must find Bob via TEXT->INTEGER numeric affinity.
        result = db.fetch("SELECT name FROM users WHERE id = ?", [params["id"]])
        assert result.records == [{"name": "Bob"}]

    def test_typed_int_param_is_int_and_matches(self, db):
        @get("/api/things/{id:int}")
        async def handler(request, response):  # noqa: ANN001
            pass

        route, params = Router.match("GET", "/api/things/3")
        assert route is not None
        assert isinstance(params["id"], int)
        assert params["id"] == 3

        result = db.fetch("SELECT name FROM users WHERE id = ?", [params["id"]])
        assert result.records == [{"name": "Carol"}]
