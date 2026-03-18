#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import pytest
import os
import json
import base64
from datetime import datetime, date

import tina4_python
from tina4_python.Template import Template
from tina4_python.TwigEngine import TwigEngine


@pytest.fixture(autouse=True)
def reset_template():
    """Reset template engine before each test so tests don't interfere."""
    Template._reset()
    yield
    Template._reset()


# --- Custom Filters ---

def test_add_filter():
    Template.add_filter("shout", lambda s: s.upper() + "!")
    result = Template.render("{{ name|shout }}", {"name": "hello"})
    assert result == "HELLO!"


def test_add_filter_before_init():
    """Filter registered before twig init should be available after rendering."""
    Template.add_filter("reverse_str", lambda s: s[::-1])
    result = Template.render("{{ word|reverse_str }}", {"word": "abcde"})
    assert result == "edcba"


def test_multiple_filters():
    Template.add_filter("double", lambda s: s * 2)
    Template.add_filter("wrap", lambda s: f"[{s}]")
    result = Template.render("{{ val|double|wrap }}", {"val": "ab"})
    assert result == "[abab]"


def test_filter_override():
    """Custom filter can override a built-in filter name."""
    Template.add_filter("base64encode", lambda s: "OVERRIDDEN")
    result = Template.render("{{ val|base64encode }}", {"val": "test"})
    assert result == "OVERRIDDEN"


# --- Custom Globals ---

def test_add_global_function():
    Template.add_global("greet", lambda name: f"Hello, {name}!")
    result = Template.render("{{ greet('World') }}")
    assert result == "Hello, World!"


def test_add_global_value():
    Template.add_global("app_name", "MyApp")
    result = Template.render("Welcome to {{ app_name }}")
    assert result == "Welcome to MyApp"


def test_add_global_before_init():
    """Global registered before twig init should be available after rendering."""
    Template.add_global("version", "1.2.3")
    result = Template.render("v{{ version }}")
    assert result == "v1.2.3"


# --- Custom Tests ---

def test_add_test():
    Template.add_test("even_number", lambda n: n % 2 == 0)
    result = Template.render(
        "{% if val is even_number %}even{% else %}odd{% endif %}",
        {"val": 4}
    )
    assert result == "even"


def test_add_test_false():
    Template.add_test("even_number", lambda n: n % 2 == 0)
    result = Template.render(
        "{% if val is even_number %}even{% else %}odd{% endif %}",
        {"val": 3}
    )
    assert result == "odd"


# --- get_environment ---

def test_get_environment():
    env = Template.get_environment()
    assert isinstance(env, TwigEngine)


def test_get_environment_has_custom_items():
    Template.add_filter("test_filter", lambda s: s)
    Template.add_global("test_global", "val")
    Template.add_test("test_test", lambda x: True)
    env = Template.get_environment()
    assert "test_filter" in env._filters
    assert "test_global" in env._globals
    assert "test_test" in env._tests


# --- Built-in filters still work ---

def test_builtin_filter_nice_label():
    result = Template.render("{{ val|nice_label }}", {"val": "first_name"})
    assert result == "First Name"


def test_builtin_filter_base64encode():
    result = Template.render("{{ val|base64encode }}", {"val": "hello"})
    expected = base64.b64encode(b"hello").decode("utf-8")
    assert result == expected


def test_builtin_filter_json_encode():
    result = Template.render('{{ val|json_encode }}', {"val": {"a": 1}})
    assert json.loads(result) == {"a": 1}


# --- Built-in globals still work ---

def test_builtin_global_json():
    result = Template.render('{{ json.dumps({"key": "value"}) }}')
    assert json.loads(result) == {"key": "value"}


# --- Rendering with data ---

def test_render_with_data():
    result = Template.render("Hello {{ name }}, age {{ age }}", {"name": "Alice", "age": 30})
    assert result == "Hello Alice, age 30"


def test_render_template_string():
    result = Template.render("{% for i in items %}{{ i }} {% endfor %}", {"items": [1, 2, 3]})
    assert result == "1 2 3 "


# --- convert_special_types ---

def test_convert_special_types_datetime():
    dt = datetime(2025, 1, 15, 10, 30, 0)
    result = Template.convert_special_types(dt)
    assert result == "2025-01-15T10:30:00"


def test_convert_special_types_date():
    d = date(2025, 6, 1)
    result = Template.convert_special_types(d)
    assert result == "2025-06-01"


def test_convert_special_types_bytes():
    b = b"hello"
    result = Template.convert_special_types(b)
    assert result == base64.b64encode(b"hello").decode("utf-8")


def test_convert_special_types_nested():
    data = {
        "name": "test",
        "created": datetime(2025, 1, 1),
        "items": [date(2025, 6, 1), b"data", "plain"],
        "nested": {"dt": datetime(2025, 12, 25)}
    }
    result = Template.convert_special_types(data)
    assert result["name"] == "test"
    assert result["created"] == "2025-01-01T00:00:00"
    assert result["items"][0] == "2025-06-01"
    assert result["items"][2] == "plain"
    assert result["nested"]["dt"] == "2025-12-25T00:00:00"


def test_convert_special_types_primitives():
    assert Template.convert_special_types("hello") == "hello"
    assert Template.convert_special_types(42) == 42
    assert Template.convert_special_types(None) is None
    assert Template.convert_special_types(True) is True


# --- _reset ---

def test_reset_clears_state():
    Template.add_filter("temp", lambda s: s)
    Template.add_global("temp_g", "val")
    Template._reset()
    assert Template._custom_filters == {}
    assert Template._custom_globals == {}
    assert Template._custom_tests == {}
    assert Template._custom_extensions == []
    assert Template.twig is None


# ===================================================================
# TwigEngine unit tests
# ===================================================================

class TestTwigVariables:
    def test_simple_variable(self):
        engine = TwigEngine()
        assert engine.render_string("Hello {{ name }}", {"name": "World"}) == "Hello World"

    def test_dot_access(self):
        engine = TwigEngine()
        assert engine.render_string("{{ user.name }}", {"user": {"name": "Alice"}}) == "Alice"

    def test_bracket_access(self):
        engine = TwigEngine()
        assert engine.render_string("{{ user['name'] }}", {"user": {"name": "Bob"}}) == "Bob"

    def test_nested_access(self):
        engine = TwigEngine()
        data = {"a": {"b": {"c": "deep"}}}
        assert engine.render_string("{{ a.b.c }}", data) == "deep"

    def test_undefined_renders_empty(self):
        engine = TwigEngine()
        assert engine.render_string("{{ missing }}") == ""

    def test_numeric_literal(self):
        engine = TwigEngine()
        assert engine.render_string("{{ 42 }}") == "42"

    def test_string_literal(self):
        engine = TwigEngine()
        assert engine.render_string("{{ 'hello' }}") == "hello"


class TestTwigFilters:
    def test_upper(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|upper }}", {"name": "hello"}) == "HELLO"

    def test_lower(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|lower }}", {"name": "HELLO"}) == "hello"

    def test_title(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|title }}", {"name": "hello world"}) == "Hello World"

    def test_length(self):
        engine = TwigEngine()
        assert engine.render_string("{{ items|length }}", {"items": [1, 2, 3]}) == "3"

    def test_default(self):
        engine = TwigEngine()
        assert engine.render_string("{{ missing|default('fallback') }}") == "fallback"

    def test_default_with_value(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|default('fallback') }}", {"name": "Alice"}) == "Alice"

    def test_replace(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|replace('_', ' ') }}", {"name": "hello_world"}) == "hello world"

    def test_json_encode(self):
        engine = TwigEngine()
        result = engine.render_string("{{ data|json_encode }}", {"data": {"a": 1}})
        assert json.loads(result) == {"a": 1}

    def test_join(self):
        engine = TwigEngine()
        assert engine.render_string("{{ items|join(', ') }}", {"items": ["a", "b", "c"]}) == "a, b, c"

    def test_first_last(self):
        engine = TwigEngine()
        assert engine.render_string("{{ items|first }}", {"items": [10, 20, 30]}) == "10"
        assert engine.render_string("{{ items|last }}", {"items": [10, 20, 30]}) == "30"

    def test_filter_chain(self):
        engine = TwigEngine()
        assert engine.render_string("{{ name|upper|length }}", {"name": "hello"}) == "5"

    def test_custom_filter(self):
        engine = TwigEngine()
        engine.add_filter("exclaim", lambda s: s + "!")
        assert engine.render_string("{{ name|exclaim }}", {"name": "hi"}) == "hi!"

    def test_truncate(self):
        engine = TwigEngine()
        result = engine.render_string("{{ text|truncate(5) }}", {"text": "Hello World"})
        assert result == "Hello..."

    def test_striptags(self):
        engine = TwigEngine()
        result = engine.render_string("{{ html|striptags }}", {"html": "<b>bold</b>"})
        assert result == "bold"


class TestTwigControlFlow:
    def test_if_true(self):
        engine = TwigEngine()
        assert engine.render_string("{% if show %}yes{% endif %}", {"show": True}) == "yes"

    def test_if_false(self):
        engine = TwigEngine()
        assert engine.render_string("{% if show %}yes{% endif %}", {"show": False}) == ""

    def test_if_else(self):
        engine = TwigEngine()
        assert engine.render_string("{% if show %}yes{% else %}no{% endif %}", {"show": False}) == "no"

    def test_elif(self):
        engine = TwigEngine()
        tpl = "{% if x == 1 %}one{% elif x == 2 %}two{% else %}other{% endif %}"
        assert engine.render_string(tpl, {"x": 2}) == "two"

    def test_for_loop(self):
        engine = TwigEngine()
        assert engine.render_string("{% for i in items %}{{ i }}{% endfor %}", {"items": [1, 2, 3]}) == "123"

    def test_for_else(self):
        engine = TwigEngine()
        tpl = "{% for i in items %}{{ i }}{% else %}empty{% endfor %}"
        assert engine.render_string(tpl, {"items": []}) == "empty"

    def test_for_loop_vars(self):
        engine = TwigEngine()
        tpl = "{% for i in items %}{{ loop.index }}{% endfor %}"
        assert engine.render_string(tpl, {"items": ["a", "b", "c"]}) == "123"

    def test_for_loop_index0(self):
        engine = TwigEngine()
        tpl = "{% for i in items %}{{ loop.index0 }}{% endfor %}"
        assert engine.render_string(tpl, {"items": ["a", "b"]}) == "01"

    def test_for_loop_first_last(self):
        engine = TwigEngine()
        tpl = "{% for i in items %}{% if loop.first %}F{% endif %}{% if loop.last %}L{% endif %}{% endfor %}"
        assert engine.render_string(tpl, {"items": [1, 2, 3]}) == "FL"

    def test_set(self):
        engine = TwigEngine()
        assert engine.render_string("{% set x = 'hello' %}{{ x }}") == "hello"

    def test_nested_for_if(self):
        engine = TwigEngine()
        tpl = "{% for i in items %}{% if i > 1 %}{{ i }}{% endif %}{% endfor %}"
        assert engine.render_string(tpl, {"items": [1, 2, 3]}) == "23"


class TestTwigExpressions:
    def test_string_concat(self):
        engine = TwigEngine()
        assert engine.render_string("{{ 'hello' ~ ' ' ~ 'world' }}") == "hello world"

    def test_ternary(self):
        engine = TwigEngine()
        assert engine.render_string("{{ 'yes' if show else 'no' }}", {"show": True}) == "yes"
        assert engine.render_string("{{ 'yes' if show else 'no' }}", {"show": False}) == "no"

    def test_comparison(self):
        engine = TwigEngine()
        assert engine.render_string("{% if x > 5 %}big{% endif %}", {"x": 10}) == "big"
        assert engine.render_string("{% if x == 5 %}five{% endif %}", {"x": 5}) == "five"
        assert engine.render_string("{% if x != 5 %}not five{% endif %}", {"x": 3}) == "not five"

    def test_in_operator(self):
        engine = TwigEngine()
        assert engine.render_string("{% if 'a' in items %}yes{% endif %}", {"items": ["a", "b"]}) == "yes"

    def test_not_operator(self):
        engine = TwigEngine()
        assert engine.render_string("{% if not show %}hidden{% endif %}", {"show": False}) == "hidden"

    def test_and_or(self):
        engine = TwigEngine()
        assert engine.render_string("{% if a and b %}both{% endif %}", {"a": True, "b": True}) == "both"
        assert engine.render_string("{% if a or b %}one{% endif %}", {"a": False, "b": True}) == "one"

    def test_is_defined(self):
        engine = TwigEngine()
        assert engine.render_string("{% if x is defined %}yes{% else %}no{% endif %}", {"x": 1}) == "yes"
        assert engine.render_string("{% if y is defined %}yes{% else %}no{% endif %}") == "no"

    def test_is_none(self):
        engine = TwigEngine()
        assert engine.render_string("{% if x is none %}null{% else %}val{% endif %}", {"x": None}) == "null"

    def test_slice(self):
        engine = TwigEngine()
        assert engine.render_string("{{ text[:5] }}", {"text": "Hello World"}) == "Hello"

    def test_list_literal(self):
        engine = TwigEngine()
        assert engine.render_string("{% for i in [1, 2, 3] %}{{ i }}{% endfor %}") == "123"

    def test_function_call(self):
        engine = TwigEngine()
        engine.add_global("greet", lambda n: f"Hi {n}")
        assert engine.render_string("{{ greet('Bob') }}") == "Hi Bob"


class TestTwigInheritance:
    def test_extends_and_block(self, tmp_path):
        base = tmp_path / "base.twig"
        base.write_text("<html>{% block content %}default{% endblock %}</html>")
        child = tmp_path / "child.twig"
        child.write_text("{% extends 'base.twig' %}{% block content %}custom{% endblock %}")

        engine = TwigEngine([str(tmp_path)])
        assert engine.render("child.twig") == "<html>custom</html>"

    def test_include(self, tmp_path):
        partial = tmp_path / "partial.twig"
        partial.write_text("I am partial")
        main = tmp_path / "main.twig"
        main.write_text("Before {% include 'partial.twig' %} After")

        engine = TwigEngine([str(tmp_path)])
        assert engine.render("main.twig") == "Before I am partial After"

    def test_include_ignore_missing(self, tmp_path):
        main = tmp_path / "main.twig"
        main.write_text("Before {% include 'missing.twig' ignore missing %} After")

        engine = TwigEngine([str(tmp_path)])
        assert engine.render("main.twig") == "Before  After"


class TestTwigMacros:
    def test_macro_definition_and_call(self):
        engine = TwigEngine()
        tpl = "{% macro greet(name) %}Hello {{ name }}{% endmacro %}{{ greet('World') }}"
        assert engine.render_string(tpl) == "Hello World"

    def test_macro_with_default(self):
        engine = TwigEngine()
        tpl = "{% macro greet(name='stranger') %}Hi {{ name }}{% endmacro %}{{ greet() }}"
        assert engine.render_string(tpl) == "Hi stranger"

    def test_macro_from_import(self, tmp_path):
        macros = tmp_path / "macros.twig"
        macros.write_text("{% macro bold(text) %}<b>{{ text }}</b>{% endmacro %}")
        main = tmp_path / "main.twig"
        main.write_text("{% from 'macros.twig' import bold %}{{ bold('test') }}")

        engine = TwigEngine([str(tmp_path)])
        assert engine.render("main.twig") == "<b>test</b>"


class TestTwigRaw:
    def test_raw_block(self):
        engine = TwigEngine()
        tpl = "{% raw %}{{ not_rendered }}{% endraw %}"
        assert engine.render_string(tpl) == "{{ not_rendered }}"

    def test_raw_with_tags(self):
        engine = TwigEngine()
        tpl = "{% raw %}{% if true %}yes{% endif %}{% endraw %}"
        assert engine.render_string(tpl) == "{% if true %}yes{% endif %}"


class TestTwigComments:
    def test_comment_removed(self):
        engine = TwigEngine()
        assert engine.render_string("before{# comment #}after") == "beforeafter"

    def test_multiline_comment(self):
        engine = TwigEngine()
        tpl = "before{# this is\na multiline\ncomment #}after"
        assert engine.render_string(tpl) == "beforeafter"
