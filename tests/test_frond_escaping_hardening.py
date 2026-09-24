# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Frond auto-escaping hardening — F4, F5, F7 (ADR-0077).

These pin that Frond auto-escapes structured values (lists/dicts/objects), that
``js_escape`` / ``e('js')`` neutralise HTML-significant characters, and that the
``e(strategy)`` strategies (js/url/css/html_attr) are honoured instead of
falling back to HTML escaping. Real renders, no mocks. All payloads are inert
markup used only to prove the escaper transforms the dangerous characters.

Mutation proof: revert the escape in ``_eval_var_inner`` / the ``_js_escape``
helper / the strategy dispatch and each test below goes red.
"""

from tina4_python.frond.engine import Frond


class _Obj:
    def __str__(self):
        return "<b>o</b>"


def test_structured_values_are_escaped_on_output():
    # F4: a list/dict/object rendered directly must not emit raw markup.
    engine = Frond()
    assert engine.render_string("{{ items }}", {"items": ["<b>x</b>"]}) == "[&#x27;&lt;b&gt;x&lt;/b&gt;&#x27;]" \
        or "<b>x</b>" not in engine.render_string("{{ items }}", {"items": ["<b>x</b>"]})
    assert "<b>x</b>" not in engine.render_string("{{ d }}", {"d": {"a": "<b>x</b>"}})
    assert "<b>o</b>" not in engine.render_string("{{ o }}", {"o": _Obj()})


def test_plain_strings_still_escape_and_numbers_bools_unchanged():
    # positive/parity: existing behaviour preserved.
    engine = Frond()
    assert engine.render_string("{{ s }}", {"s": "<b>x</b>"}) == "&lt;b&gt;x&lt;/b&gt;"
    assert engine.render_string("{{ n }}", {"n": 5}) == "5"
    assert engine.render_string("{{ t }}", {"t": True}) == "true"
    assert engine.render_string("{{ f }}", {"f": False}) == "false"
    assert engine.render_string("{{ x }}", {"x": None}) == ""


def test_js_escape_neutralises_html_significant_characters():
    # F5: js_escape must not leave < > & / or quotes literal.
    engine = Frond()
    out = engine.render_string("{{ u|js_escape }}", {"u": "</b>&'\""})
    for bad in ("<", ">", "&", "/", "'", '"'):
        assert bad not in out, f"{bad!r} left literal in {out!r}"


def test_e_js_strategy_matches_js_escape():
    engine = Frond()
    a = engine.render_string("{{ u|e('js') }}", {"u": "</b>"})
    b = engine.render_string("{{ u|js_escape }}", {"u": "</b>"})
    assert a == b
    assert "<" not in a and "/" not in a


def test_e_url_strategy_percent_encodes():
    # F7: e('url') is RFC-3986 rawurlencode, not HTML escaping.
    engine = Frond()
    out = engine.render_string("{{ u|e('url') }}", {"u": "a b&c/d"})
    assert out == "a%20b%26c%2Fd"


def test_e_css_strategy_backslash_hex():
    engine = Frond()
    out = engine.render_string("{{ u|e('css') }}", {"u": "a<b"})
    assert "<" not in out and out.startswith("a\\")


def test_e_html_attr_strategy_entities():
    engine = Frond()
    out = engine.render_string("{{ u|e('html_attr') }}", {"u": 'a"b'})
    assert out == "a&#x22;b"


def test_e_unknown_strategy_raises_not_silently_passes():
    engine = Frond()
    import pytest
    with pytest.raises(Exception):
        engine.render_string("{{ u|e('bogus') }}", {"u": "<b>x</b>"})
