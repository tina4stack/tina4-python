"""Regression: {% import "file" as alias %} must not shift macro arguments.

The bug: _handle_import_as built the alias namespace with
``type("MacroNamespace", (), macros)()``. Installing plain functions as CLASS
attributes makes every attribute access return a BOUND METHOD, so the namespace
instance was passed as the first positional argument and every real argument
landed one parameter to the right:

    {% import "macros.twig" as m %}{{ m.greet("Andre") }}
    -> <p>Andre, <MacroNamespace object at 0x...>!</p>     (name got the namespace)

``{% from "file" import name %}`` was ALWAYS correct because it registers the
function directly in the context with no class in between. Both import forms must
therefore render IDENTICALLY -- that equivalence is the contract these tests lock.

Fix: build the namespace with types.SimpleNamespace(**macros), whose attribute
access returns the stored function itself (no descriptor binding).

No mocks: every test writes REAL template files to a real temp directory and
renders them through the real Frond engine.
"""

import re
import tempfile
from pathlib import Path

import pytest

from tina4_python.frond import Frond


MACRO_LIB = (
    "{% macro greet(name, greeting='Hello') %}"
    "<p>{{ greeting }}, {{ name }}!</p>"
    "{% endmacro %}"
    "{% macro shout(word) %}"
    "<b>{{ word }}</b>"
    "{% endmacro %}"
    "{% macro three(a, b, c) %}"
    "[{{ a }}|{{ b }}|{{ c }}]"
    "{% endmacro %}"
)


@pytest.fixture()
def frond(tmp_path):
    """A real Frond engine over a real directory holding a real macro library."""
    (tmp_path / "macros.twig").write_text(MACRO_LIB)
    return Frond(str(tmp_path)), tmp_path


def _render(engine_and_dir, name, source):
    engine, directory = engine_and_dir
    (directory / name).write_text(source)
    return engine.render(name, {})


# --------------------------------------------------------------------------
# POSITIVE: the aliased macro receives the arguments it was actually given.
# --------------------------------------------------------------------------

def test_import_as_single_arg_binds_to_first_param(frond):
    """One argument lands in the FIRST parameter, and the default still applies."""
    out = _render(frond, "one.twig",
                  '{% import "macros.twig" as m %}{{ m.greet("Andre") }}')
    assert out == "<p>Hello, Andre!</p>"


def test_import_as_multiple_args_are_not_shifted(frond):
    """Two arguments fill the first TWO parameters, in order."""
    out = _render(frond, "two.twig",
                  '{% import "macros.twig" as m %}{{ m.greet("Andre", "Hi") }}')
    assert out == "<p>Hi, Andre!</p>"


def test_import_as_three_args_all_arrive_in_order(frond):
    """A no-default macro proves ordering across more than two params."""
    out = _render(frond, "three.twig",
                  '{% import "macros.twig" as m %}{{ m.three(1, 2, 3) }}')
    assert out == "[1|2|3]"


def test_import_as_defaulted_param_keeps_its_default(frond):
    """An omitted defaulted param must use its default, not the next argument."""
    out = _render(frond, "dflt.twig",
                  '{% import "macros.twig" as m %}{{ m.greet("Zoe") }}')
    assert "Hello" in out, "the greeting default was dropped"
    assert out == "<p>Hello, Zoe!</p>"


def test_import_as_exposes_every_macro_in_the_file(frond):
    """The alias is a namespace over ALL macros in the imported file."""
    out = _render(frond, "many.twig",
                  '{% import "macros.twig" as m %}'
                  '{{ m.shout("hey") }}{{ m.greet("Ann") }}')
    assert out == "<b>hey</b><p>Hello, Ann!</p>"


# --------------------------------------------------------------------------
# NEGATIVE: the namespace object itself must never reach the output.
# These are the assertions that FAIL on the pre-fix code.
# --------------------------------------------------------------------------

def test_namespace_object_never_leaks_into_output(frond):
    """The repr of the namespace must not be rendered as an argument value."""
    out = _render(frond, "leak.twig",
                  '{% import "macros.twig" as m %}{{ m.greet("Andre") }}')
    assert "MacroNamespace" not in out
    assert "SimpleNamespace" not in out
    assert "namespace(" not in out
    assert not re.search(r"0x[0-9a-f]+", out), f"an object address leaked: {out!r}"
    assert "<p" in out, "the macro body should still have rendered"


def test_import_as_does_not_swallow_the_last_argument(frond):
    """Shifting by one silently DROPPED the final argument -- it must arrive."""
    out = _render(frond, "nodrop.twig",
                  '{% import "macros.twig" as m %}{{ m.three("a", "b", "c") }}')
    assert out == "[a|b|c]"
    assert "c" in out, "the last argument was dropped by an argument shift"


# --------------------------------------------------------------------------
# CONTRACT: the two import forms must behave identically.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("call,expected", [
    ('greet("Andre")',        "<p>Hello, Andre!</p>"),
    ('greet("Andre", "Hi")',  "<p>Hi, Andre!</p>"),
    ('shout("x")',            "<b>x</b>"),
])
def test_import_as_matches_from_import_exactly(frond, call, expected):
    """{% import as %} and {% from import %} must produce the SAME bytes."""
    engine, directory = frond
    name = call.split("(")[0]

    # NB: build these with concatenation, never %-formatting -- Twig's {% %}
    # tags collide with Python's % operator and raise before the render runs.
    as_out = _render(frond, "cmp_as.twig",
                     '{% import "macros.twig" as m %}{{ m.' + call + ' }}')
    from_out = _render(frond, "cmp_from.twig",
                       '{% from "macros.twig" import ' + name + ' %}{{ ' + call + ' }}')

    assert as_out == from_out, (
        f"import-as and from-import disagree: {as_out!r} != {from_out!r}"
    )
    assert as_out == expected
