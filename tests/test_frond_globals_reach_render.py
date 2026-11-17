# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# A template global, filter or test registered through the public class API
# reaches every page that response.render() produces, whenever it is registered
# (ADR-0106 for globals, ADR-0107 for filters and tests).
#
# The response engine used to copy the class globals once, when it was built
# at the first render, so a Frond.add_global() made after that first render
# never reached a page. The auto-wired t() also refused a params map, the shape
# templates use: {{ t("welcome", {"name": n}) }}. Filters and tests were
# drained into the engine the same way, once, at construction. Every case renders a real
# template through a real route and the real front controller.
import json

import pytest

from tina4_python.core.response import set_frond
from tina4_python.core.router import Router, get as route_get
from tina4_python.core.server import _auto_wire_i18n
from tina4_python.frond import Frond
from tina4_python.test_client import TestClient


@pytest.fixture(autouse=True)
def _app(tmp_path, monkeypatch):
    templates = tmp_path / "src" / "templates"
    templates.mkdir(parents=True)
    (templates / "globals.twig").write_text("[{{ early }}][{{ late }}][{{ shared }}]")
    (templates / "call.twig").write_text('{{ shout("hi") }}')
    (templates / "filter.twig").write_text('{{ "hi"|loud }}')
    (templates / "test.twig").write_text("{% if 4 is quad %}yes{% else %}no{% endif %}")
    (templates / "flag.twig").write_text("{% if is_admin %}admin{% else %}guest{% endif %}")
    (templates / "greeting.twig").write_text('{{ t("greeting") }}')
    (templates / "welcome.twig").write_text('{{ t("welcome", {"name": "Ana"}) }}')
    locales = tmp_path / "src" / "locales"
    locales.mkdir()
    (locales / "en.json").write_text(json.dumps({"greeting": "Hello", "welcome": "Welcome, {name}!"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TINA4_LOCALE_DIR", str(locales))
    monkeypatch.setenv("TINA4_LOCALE", "en")

    Router.clear()
    Frond.clear_registry()
    set_frond(None)  # the next response.render builds a fresh engine

    for name in ("globals", "flag", "call", "filter", "test", "greeting", "welcome"):
        def handler_for(template):
            async def handler(request, response):
                return response.render(template, {})
            return handler
        route_get(f"/{name}")(handler_for(f"{name}.twig"))

    yield
    Router.clear()
    Frond.clear_registry()
    set_frond(None)


def page(path: str) -> str:
    response = TestClient().get(path)
    assert response.status == 200
    return response.body.decode()


class TestFrondGlobalsReachRender:
    def test_class_global_registered_before_first_render_reaches_render(self):
        Frond.add_global("early", "E")
        assert page("/globals") == "[E][][]"

    def test_class_global_registered_after_first_render_reaches_render(self):
        assert page("/globals") == "[][][]"  # the response engine now exists
        Frond.add_global("late", "L")
        assert page("/globals") == "[][L][]"

    def test_zero_arg_class_global_registered_after_first_render_is_called(self):
        assert page("/flag") == "guest"
        Frond.add_global("is_admin", lambda: True)  # ADR-0085 auto-call
        assert page("/flag") == "admin"

    def test_callable_class_global_registered_after_first_render_is_called(self):
        assert page("/call") == ""
        Frond.add_global("shout", lambda text: text.upper())
        assert page("/call") == "HI"

    def test_auto_wired_t_translates_a_key(self):
        _auto_wire_i18n()
        assert page("/greeting") == "Hello"

    def test_auto_wired_t_accepts_a_params_map(self):
        _auto_wire_i18n()
        assert page("/welcome") == "Welcome, Ana!"

    def test_auto_wired_t_reaches_every_engine(self):
        _auto_wire_i18n()
        assert Frond("src/templates").render("greeting.twig") == "Hello"

    def test_auto_wired_t_registered_after_first_render_reaches_render(self):
        assert page("/globals") == "[][][]"
        _auto_wire_i18n()
        assert page("/greeting") == "Hello"

    def test_instance_global_on_another_engine_does_not_leak_into_render(self):
        other_engine = Frond("src/templates")
        other_engine.add_global("late", "LEAK")
        assert page("/globals") == "[][][]"
        assert other_engine.render("globals.twig") == "[][LEAK][]"

    def test_instance_global_overrides_class_global(self):
        Frond.add_global("shared", "class")
        assert page("/globals") == "[][][class]"
        from tina4_python.core.response import get_frond
        get_frond().add_global("shared", "instance")
        assert page("/globals") == "[][][instance]"
        assert Frond("src/templates").render("globals.twig") == "[][][class]"


class TestFrondFiltersAndTestsReachRender:
    def test_class_filter_registered_before_first_render_reaches_render(self):
        Frond.add_filter("loud", lambda value: str(value).upper())
        assert page("/filter") == "HI"

    def test_class_filter_registered_after_first_render_reaches_render(self):
        assert page("/filter") == "hi"  # the response engine now exists
        Frond.add_filter("loud", lambda value: str(value).upper())
        assert page("/filter") == "HI"

    def test_class_test_registered_before_first_render_reaches_render(self):
        Frond.add_test("quad", lambda value: value == 4)
        assert page("/test") == "yes"

    def test_class_test_registered_after_first_render_reaches_render(self):
        assert page("/test") == "no"
        Frond.add_test("quad", lambda value: value == 4)
        assert page("/test") == "yes"

    def test_instance_filter_on_another_engine_does_not_leak_into_render(self):
        other_engine = Frond("src/templates")
        other_engine.add_filter("loud", lambda value: "LEAK")
        assert page("/filter") == "hi"
        assert other_engine.render("filter.twig") == "LEAK"

    def test_instance_test_on_another_engine_does_not_leak_into_render(self):
        other_engine = Frond("src/templates")
        other_engine.add_test("quad", lambda value: True)
        assert page("/test") == "no"
        assert other_engine.render("test.twig") == "yes"

    def test_instance_filter_overrides_class_filter(self):
        Frond.add_filter("loud", lambda value: "class")
        assert page("/filter") == "class"
        from tina4_python.core.response import get_frond
        get_frond().add_filter("loud", lambda value: "instance")
        assert page("/filter") == "instance"
        Frond.add_filter("loud", lambda value: "class again")  # a later class change
        assert page("/filter") == "instance"
        assert Frond("src/templates").render("filter.twig") == "class again"
