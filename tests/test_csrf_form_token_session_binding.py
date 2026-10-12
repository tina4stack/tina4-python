# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# A form token rendered during a request is bound to that request's session.
#
# The CSRF check compares a token's session_id with the session of the write
# that carries it, but it can only do so when the token HAS a session_id. The
# rendered token never had one: form_token() read a process-wide id that no
# dispatch path set, so a token rendered for one browser was accepted on a
# write carrying any other browser's session cookie. These tests render the
# token through the real front controller, in one browser, and post it in
# another.
import os
import re

import pytest

from tina4_python.auth import get_token
from tina4_python.cache import ResponseCache
from tina4_python.core.middleware import CsrfMiddleware, Middleware
from tina4_python.core.router import Router, get as route_get, middleware, post as route_post
from tina4_python.frond.engine import Frond
from tina4_python.test_client import TestClient


@pytest.fixture(autouse=True)
def _app(tmp_path, monkeypatch):
    (tmp_path / "src" / "templates").mkdir(parents=True)
    (tmp_path / "src" / "templates" / "form.twig").write_text("{{ form_token_value() }}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TINA4_CSRF", "true")
    monkeypatch.setenv("TINA4_SECRET", "test-csrf-secret-0123456789abcdef")
    monkeypatch.setenv("TINA4_SESSION_PATH", str(tmp_path / "sessions"))
    Router.clear()
    saved = list(Middleware.get_global())
    Middleware._global_middleware = [CsrfMiddleware]

    @route_get("/login")
    async def login(request, response):
        request.session.set("token", get_token({"user": "victim"}))
        return response.json({"logged_in": True})

    @route_get("/form")
    async def form(request, response):
        request.session.set("seen", True)
        return response.render("form.twig", {})

    @route_get("/fresh")
    async def fresh(request, response):
        return response.render("form.twig", {})

    @middleware(ResponseCache)
    @route_get("/cached")
    async def cached(request, response):
        return response.render("form.twig", {})

    @route_post("/save")
    async def save(request, response):
        return response.json({"saved": True})

    yield
    Router.clear()
    Middleware._global_middleware = saved


class Browser:
    """One cookie jar, sent with every request through the real dispatcher."""

    def __init__(self):
        self.client = TestClient()
        self.cookies = {}

    def _headers(self):
        if not self.cookies:
            return {}
        return {"cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def _keep(self, response):
        for value in response.get_all("set-cookie"):
            name, rest = value.split("=", 1)
            self.cookies[name] = rest.split(";", 1)[0]
        return response

    def get(self, path):
        return self._keep(self.client.get(path, headers=self._headers()))

    def post(self, path, token):
        return self._keep(self.client.post(path, json={"formToken": token}, headers=self._headers()))


def _rendered_token(browser, path="/form"):
    token = browser.get(path).text().strip()
    assert re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", token), token
    return token


def test_a_token_rendered_for_one_session_is_refused_on_another():
    attacker, victim = Browser(), Browser()
    stolen = _rendered_token(attacker)
    victim.get("/login")
    _rendered_token(victim)

    assert victim.post("/save", stolen).status == 403


def test_a_token_rendered_for_a_session_passes_on_that_session():
    victim = Browser()
    victim.get("/login")
    own = _rendered_token(victim)

    assert victim.post("/save", own).status == 200


def test_a_page_that_writes_no_session_still_binds_and_keeps_the_session():
    # Nothing else stores the session on /fresh, so without a marker it would
    # send no cookie, and the visitor's own POST would arrive under a new id.
    visitor, other = Browser(), Browser()
    token = _rendered_token(visitor, "/fresh")
    assert visitor.cookies, "rendering a bound token must leave a session cookie"
    visitor.get("/login")
    other.get("/login")

    assert visitor.post("/save", token).status == 200
    assert other.post("/save", token).status == 403


def test_a_cached_page_does_not_replay_one_visitors_token_to_the_next():
    # The session cookie is set after the response cache decides to store the
    # page, so a page whose token is bound to a NEW session must not be stored:
    # every later visitor would be served the first visitor's token.
    first, second = Browser(), Browser()
    first_token = _rendered_token(first, "/cached")
    second_token = _rendered_token(second, "/cached")

    assert first.post("/save", first_token).status != 403
    assert second.post("/save", second_token).status != 403


def test_a_render_outside_a_request_is_unbound():
    token = str(Frond().render_string("{{ form_token_value() }}")).strip()
    from tina4_python.auth import Auth
    assert "session_id" not in Auth(secret=os.environ["TINA4_SECRET"]).get_payload(token)


def test_a_dispatch_does_not_leave_its_session_bound_afterwards():
    # An embedder awaits handle() in its own task; a token it renders after the
    # request is finished belongs to no request and must not carry its session.
    import asyncio
    from tina4_python.auth import Auth
    from tina4_python.core.request import Request
    from tina4_python.core.server import handle

    async def dispatch_then_render():
        scope = {"type": "http", "method": "GET", "path": "/form", "query_string": b"",
                 "headers": [], "client": ("127.0.0.1", 1)}
        await handle(Request.from_scope(scope, b""))
        return str(Frond().render_string("{{ form_token_value() }}")).strip()

    token = asyncio.run(dispatch_then_render())
    assert "session_id" not in Auth(secret=os.environ["TINA4_SECRET"]).get_payload(token)
