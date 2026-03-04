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
from jinja2 import Environment

import tina4_python
from tina4_python.Template import Template


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


# --- Extensions ---

def test_add_extension():
    Template.add_extension("jinja2.ext.loopcontrols")
    result = Template.render(
        "{% for i in range(5) %}{% if i == 3 %}{% break %}{% endif %}{{ i }}{% endfor %}"
    )
    assert result == "012"


# --- get_environment ---

def test_get_environment():
    env = Template.get_environment()
    assert isinstance(env, Environment)


def test_get_environment_has_custom_items():
    Template.add_filter("test_filter", lambda s: s)
    Template.add_global("test_global", "val")
    Template.add_test("test_test", lambda x: True)
    env = Template.get_environment()
    assert "test_filter" in env.filters
    assert "test_global" in env.globals
    assert "test_test" in env.tests


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
