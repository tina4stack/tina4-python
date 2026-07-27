"""Frond expression parity gate -- the cross-framework output contract.

WHY THIS FILE EXISTS. "Frond expressions behave the same in all four
frameworks" was an assumption, never a measurement. When it was finally
measured -- 72 expressions rendered through Python, PHP, Ruby and Node against
one identical dataset -- 11 of the 72 disagreed. Booleans disagreed in ALL FOUR
(PHP printed ``false`` as an EMPTY STRING; Ruby was inconsistent with itself;
Python emitted Python's ``True``/``False``), ``{{ not x }}`` was silently
dropped in three, and PHP's ``|json_encode`` skipped HTML escaping. Each
implementation looked correct in isolation, which is exactly why the drift
survived for so long.

So the corpus is no longer a one-off script -- it is a fixture, and it lives in
all four repos as the SAME BYTES:

    tina4-python/tests/fixtures/frond_expression_{corpus,expected}.txt
    tina4-php/tests/fixtures/...
    tina4-ruby/spec/fixtures/...
    tina4-nodejs/test/fixtures/...

``expected.txt`` is a single agreed answer key, not a per-language snapshot. If
one framework drifts, ITS suite goes red while the other three stay green, and
the diff names the expression. Changing the contract on purpose means changing
the answer key in all four repos in the same change -- which is the point.

Keep the dataset below byte-identical to the other three runners.
"""

import pathlib

import pytest

from tina4_python.frond.engine import Frond

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# The shared dataset. Must stay identical across all four frameworks -- an
# expression can only be compared if it is fed the same values.
CONTEXT = {
    "name": "Andre",
    "lower_name": "andre van zuydam",
    "padded": "  pad  ",
    "empty_str": "",
    "n": 5,
    "f": 1234.5678,
    "neg": -42,
    "t": True,
    "f_bool": False,
    "nil_val": None,
    "user": {"name": "Ann", "addr": {"city": "CPT"}},
    "list": ["a", "b", "c"],
    "map": {"a": 1, "b": 2},
    "html": "<b>&x</b>",
    # Non-finite floats: the tina4-php#184 payload. JSON has no Infinity or
    # NaN, so both must serialize as null in every framework.
    "inf_val": float("inf"),
    "nan_map": {"v": float("nan")},
}


def _load(path):
    """Parse a ``label<sep>value`` fixture into an ordered list of pairs."""
    sep = "|" if path.name.endswith("corpus.txt") else "\t"
    pairs = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        label, _, rest = line.partition(sep)
        pairs.append((label, rest))
    return pairs


CORPUS = _load(FIXTURES / "frond_expression_corpus.txt")
EXPECTED = dict(_load(FIXTURES / "frond_expression_expected.txt"))


def test_corpus_and_answer_key_line_up():
    """Guard the guard: a corpus entry with no expected value would otherwise
    pass by never being asserted."""
    assert len(CORPUS) == 82
    assert {label for label, _ in CORPUS} == set(EXPECTED)


@pytest.mark.parametrize("label,source", CORPUS, ids=[c[0] for c in CORPUS])
def test_expression_matches_cross_framework_contract(label, source):
    engine = Frond()
    assert engine.render_string(source, dict(CONTEXT)) == EXPECTED[label]


# -- Named regressions for the three bugs the corpus actually caught ----------
# The parametrised gate above would catch these too, but only as "some line
# changed". These name the behaviour, and each carries the NEGATIVE case that
# was failing before the fix.


def test_booleans_render_lowercase_true_false():
    """3.13.87 contract: a boolean renders lowercase ``true``/``false``.

    Breaking vs the old Python master, which emitted ``True``/``False``.
    Lowercase is the only form usable in a template (``data-active="true"`` is
    testable from JS; ``True`` needs special-casing) and it never renders blank
    the way PHP's old empty-string ``false`` did.

    Both output paths are asserted: ``render_string`` goes through the COMPILED
    path (``compiler._tostr``), and a construct the compiler declines falls back
    to the INTERPRETER (``engine.Frond._to_output``). Editing only one of them
    changes nothing while the suite still passes -- that happened.
    """
    engine = Frond()
    ctx = {"t": True, "f": False, "n": 5}
    assert engine.render_string("{{ t }}", ctx) == "true"
    assert engine.render_string("{{ f }}", ctx) == "false"
    assert engine.render_string("{{ n > 3 }}", ctx) == "true"
    assert engine.render_string("{{ n < 3 }}", ctx) == "false"
    # A false boolean must NOT vanish -- the PHP bug this contract retired.
    assert engine.render_string("[{{ f }}]", ctx) == "[false]"
    # An integer 1 still renders as 1 (the coercion uses `is True` identity,
    # because 1 == True in Python).
    assert engine.render_string("{{ one }}", {"one": 1}) == "1"
    # Interpreted path: {% macro %} is not compiled, so this template falls
    # back to _render_nodes and must agree byte-for-byte.
    macro = "{% macro show(v) %}{{ v }}{% endmacro %}{{ show(f) }}|{{ show(t) }}"
    assert engine.render_string(macro, ctx) == "false|true"


def test_not_operator_in_a_standalone_output_expression():
    """``{{ not x }}`` renders the boolean instead of being silently dropped.

    Every logical operator was matched WITH surrounding spaces, so a LEADING
    ``not`` (nothing to its left) matched none of them, fell through to the
    variable-resolution tail, and was looked up as a variable literally named
    "not x" -- which rendered EMPTY. ``{% if not x %}`` and ``x and not y``
    always worked, so the operator logic was fine; only the standalone output
    expression was lost. Before booleans rendered lowercase, a dropped
    expression and ``False -> ''`` were indistinguishable, which is why it hid.
    """
    engine = Frond()
    ctx = {"t": True, "f": False}
    assert engine.render_string("{{ not t }}", ctx) == "false"
    assert engine.render_string("{{ not f }}", ctx) == "true"
    assert engine.render_string("{{ not missing }}", ctx) == "true"
    # The same operator through the paths that always worked -- they must not
    # drift away from the standalone form.
    assert engine.render_string("{% if not f %}Y{% else %}N{% endif %}", ctx) == "Y"
    assert engine.render_string("{{ t and not f }}", ctx) == "true"
    assert engine.render_string("{{ not t ? 'A' : 'B' }}", ctx) == "B"
    # NEGATIVE: an identifier that merely starts with "not" is a variable, and
    # "not" inside a string literal is text. Neither is the operator.
    assert engine.render_string("{{ notes }}", {"notes": None}) == ""
    assert engine.render_string("{{ nothing }}", {"nothing": "x"}) == "x"
    assert engine.render_string('{{ "not a var" }}', ctx) == "not a var"


def test_json_encode_emits_json_that_is_valid_in_a_script_block():
    """``|json_encode`` output must parse as JSON AND run as JavaScript.

    3.13.88 reverts 3.13.87's HTML-escaping of this filter. Entity-encoding the
    payload produced ``{&quot;a&quot;:1}``, which is a SyntaxError inside
    ``<script>`` -- it broke the filter's primary use in all four frameworks at
    once. The safe form escapes only the characters that are dangerous in HTML,
    as JSON ``\\uXXXX`` escapes, which keeps the result valid JSON, valid
    JavaScript, unable to terminate a ``</script>``, and safe in a single-quoted
    attribute. Same model as Jinja2's ``tojson``.
    """
    engine = Frond()
    assert engine.render_string("{{ data|json_encode }}", {"data": {"a": 1}}) == '{"a":1}'
    # Negative case: the escaped characters must be \uXXXX, never HTML entities,
    # and </script> must not survive intact.
    out = engine.render_string("{{ data|json_encode }}", {"data": {"x": "</script>&'"}})
    assert out == '{"x":"\\u003c/script\\u003e\\u0026\\u0027"}'
    assert "&quot;" not in out and "</script>" not in out
    # |raw is now a no-op rather than the required opt-out.
    assert engine.render_string("{{ data|json_encode|raw }}", {"data": {"a": 1}}) == '{"a":1}'


def test_json_encode_never_emits_a_non_finite_literal(tmp_path):
    """tina4-php#184 (justin-k-bruce): a non-finite value must become ``null``.

    The four frameworks each failed differently -- Python wrote a bare
    ``Infinity`` (not JSON), PHP's json_encode returned false (empty output),
    Ruby fell back to inspect output. Node was the only one already correct.
    ``null`` is what ``JSON.stringify`` has always produced and the only answer
    the JSON grammar allows.
    """
    engine = Frond()
    inf, nan = float("inf"), float("nan")
    assert engine.render_string("{{ v|json_encode }}", {"v": inf}) == "null"
    assert engine.render_string("{{ v|json_encode }}", {"v": -inf}) == "null"
    assert engine.render_string("{{ v|json_encode }}", {"v": nan}) == "null"
    assert engine.render_string("{{ v|json_encode }}", {"v": {"a": 1, "b": inf}}) == '{"a":1,"b":null}'
    assert engine.render_string("{{ v|json_encode }}", {"v": [1, nan]}) == "[1,null]"
    # Negative case: none of the old failure outputs may appear, and the result
    # must never be empty -- an empty payload is a silent, invisible failure.
    for bad in ("Infinity", "NaN", "false", "=>"):
        assert bad not in engine.render_string("{{ v|json_encode }}", {"v": {"b": inf}})
    assert engine.render_string("{{ v|json_encode }}", {"v": inf}) != ""


def test_block_set_captures_its_body_instead_of_printing_it():
    """{% set name %}...{% endset %} binds the rendered body (3.13.89).

    Core syntax in BOTH reference engines, and broken identically in all four
    frameworks until now: the body rendered inline where it stood and the
    variable was never assigned.
    """
    engine = Frond()
    ctx = {"n": "Andre"}
    assert engine.render_string("{% set g %}Hi {{ n }}{% endset %}[{{ g }}]", dict(ctx)) == "[Hi Andre]"
    # Negative case: the old bug printed the body first and left the variable
    # empty. Neither may happen -- the body must not appear before the "[".
    out = engine.render_string("{% set g %}Hi {{ n }}{% endset %}[{{ g }}]", dict(ctx))
    assert not out.startswith("Hi")
    assert "[]" not in out
    # A loop inside the body renders into the capture, not to the page.
    assert engine.render_string(
        "{% set g %}{% for i in [1,2] %}{{ i }}{% endfor %}{% endset %}[{{ g }}]", {}
    ) == "[12]"
    # Nesting: the inner endset must not close the outer block.
    assert engine.render_string(
        "{% set a %}A{% set b %}B{% endset %}{{ b }}{% endset %}[{{ a }}]", {}
    ) == "[AB]"


def test_block_set_capture_is_safe_and_the_inline_form_still_works():
    """The capture is already-escaped output, so it is not escaped again.

    Twig and Jinja2 both mark a captured block safe. A value interpolated INTO
    the body is still escaped on the way in -- the escaping happens once, in the
    right place.
    """
    engine = Frond()
    # Escaped once on the way in, not twice on the way out.
    assert engine.render_string(
        "{% set g %}{{ h }}{% endset %}[{{ g }}]", {"h": "<b>&x</b>"}
    ) == "[&lt;b&gt;&amp;x&lt;/b&gt;]"
    # Literal markup in the body is template text and stays as written.
    assert engine.render_string("{% set g %}<b>hi</b>{% endset %}[{{ g }}]", {}) == "[<b>hi</b>]"
    # Negative case: the inline assignment form is untouched, including an "="
    # inside a quoted value -- that must NOT be read as the block form.
    assert engine.render_string('{% set g = "x" %}[{{ g }}]', {}) == "[x]"
    assert engine.render_string('{% set g = "a = b" %}[{{ g }}]', {}) == "[a = b]"


def test_an_unknown_tag_raises_instead_of_leaking_its_body():
    """A typo'd tag must fail loudly, not render the content it was gating.

    THE security-shaped one. {% iff user.is_admin %}...{% endiff %} used to
    render the admin block UNCONDITIONALLY: the unknown tag emitted nothing and
    its body was parsed as ordinary content, so a reviewer read a guard that was
    not there. Twig and Jinja2 both raise on an unknown tag. There is no
    user-extension point for tags, so an unknown name is always a mistake.
    """
    engine = Frond()
    with pytest.raises(ValueError, match='unknown tag "iff"'):
        engine.render_string("{% iff admin %}SECRET{% endiff %}", {"admin": False})
    with pytest.raises(ValueError, match='unknown tag "frobnicate"'):
        engine.render_string("{% frobnicate 42 %}", {})
    # Negative case 1: every real tag still parses.
    assert engine.render_string(
        "{% if 1 %}x{% endif %}{% for i in [1] %}{{ i }}{% endfor %}"
        "{% raw %}{{ q }}{% endraw %}{% spaceless %} a {% endspaceless %}"
        "{% autoescape true %}y{% endautoescape %}", {}
    ) == "x1{{ q }} a y"
    # Negative case 2: a STRAY terminator is not an unknown tag. It stays a
    # silent no-op -- it was always one, and unlike an unknown tag it cannot
    # expose gated content.
    assert engine.render_string("A{% endif %}B", {}) == "AB"


def test_json_encode_and_to_json_and_tojson_are_one_behaviour():
    """The three spellings must not drift apart -- they share one serializer."""
    engine = Frond()
    ctx = {"v": {"a": 1, "u": "a/b", "n": "caf\u00e9", "bad": float("inf")}}
    out = engine.render_string("{{ v|json_encode }}", ctx)
    assert out == engine.render_string("{{ v|to_json }}", ctx)
    assert out == engine.render_string("{{ v|tojson }}", ctx)
    # Slashes stay unescaped and non-ASCII stays raw -- PHP alone used to write
    # "a\\/b", and Python alone used to write "caf\\u00e9".
    assert '"u":"a/b"' in out
    assert "caf\u00e9" in out
