"""Frond sandbox hardening — F6 (ADR-0077).

Under sandbox mode a template must not reach a blocked variable through a
dunder attribute walk, nor smuggle one past the allow-list via a set right-hand
side, a for iterable, or an if comparison. Real renders, no mocks.

Mutation proof: revert ``_sandbox_expr_ok`` (or any of its call sites) and each
assertion below goes red.
"""

from tina4_python.frond.engine import Frond


def _sandboxed():
    e = Frond()
    e.sandbox(allowed_filters=["upper"], allowed_tags=["if", "for", "set"],
              allowed_vars=["user"])
    return e


def test_dunder_attribute_walk_is_blocked():
    # Without the dunder gate, a method call on a dunder attribute reaches the
    # object graph. The gate must blank the whole expression instead.
    e = _sandboxed()
    src = "{{ user.__getattribute__('__class__') }}"
    out = e.render_string(src, {"user": "bob"})
    assert out == ""
    assert "class" not in out and "str" not in out


def test_set_cannot_smuggle_a_blocked_variable():
    e = _sandboxed()
    out = e.render_string("{% set user = secret %}{{ user }}", {"secret": "hunter2"})
    assert "hunter2" not in out


def test_for_iterable_cannot_smuggle_a_blocked_variable():
    e = _sandboxed()
    out = e.render_string("{% for x in [secret] %}{{ x }}{% endfor %}",
                          {"secret": "hunter2"})
    assert "hunter2" not in out


def test_if_comparison_cannot_read_a_blocked_variable():
    e = _sandboxed()
    out = e.render_string("{% if secret == 'hunter2' %}YES{% endif %}",
                          {"secret": "hunter2"})
    assert out == ""


def test_allowed_variable_and_filter_still_render():
    # positive: the allow-list still lets the permitted variable through.
    e = _sandboxed()
    assert e.render_string("{{ user|upper }}", {"user": "bob"}) == "BOB"
    assert e.render_string("{% if user == 'bob' %}HI{% endif %}",
                           {"user": "bob"}) == "HI"
