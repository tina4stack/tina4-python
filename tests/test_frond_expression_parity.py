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
    assert len(CORPUS) == 72
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


def test_json_encode_is_html_escaped_with_raw_as_the_opt_out():
    """``|json_encode`` escapes; ``|json_encode|raw`` does not.

    Python, Ruby and Node always escaped here; PHP alone returned raw JSON, and
    raw JSON dropped into an HTML attribute is an injection vector. PHP was
    changed to match the other three in 3.13.87. The ``<script>`` use case is
    served by an explicit ``|raw`` at the call site.
    """
    engine = Frond()
    ctx = {"data": {"a": 1}}
    assert engine.render_string("{{ data|json_encode }}", ctx) == "{&quot;a&quot;:1}"
    assert engine.render_string("{{ data|json_encode|raw }}", ctx) == '{"a":1}'
