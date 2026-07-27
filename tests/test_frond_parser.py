# Tests for tina4_python.frond.parser — the tokens -> AST parse stage (ADR-0004).
#
# These are REAL parses and REAL renders, no mocks: the parser is a pure function
# over a token list, and every render below goes through the real engine against
# real template files on disk.
#
# What this file locks in:
#   1. the AST node shape each construct parses to,
#   2. that the parser — not the interpreter and not the compiler — is the SINGLE
#      owner of structure (the duplicated grouping must not come back),
#   3. that parse() leaves the caller's token list pristine, which the template
#      inheritance path depends on for reconstructing source,
#   4. the AST is cached alongside the tokens and cleared by clear_cache(),
#   5. the render-dependent `strip_before` contract shared by both consumers,
#   6. the malformed-template behaviour that was preserved deliberately.
#
# tests/test_frond.py (behaviour) and tests/test_frond_precompile.py
# (compile-vs-fallback) remain the broader guards.
import pytest

from tina4_python.frond import Frond
from tina4_python.frond import compiler as C
from tina4_python.frond import parser as P


def _ast(source):
    """Tokenize + parse a template source, as the engine does."""
    return P.parse(P._tokenize(source))


def _kinds(nodes):
    return [n.kind for n in nodes]


class TestNodeShapes:
    """Each construct parses to a node that CARRIES its own children."""

    def test_text_and_output(self):
        nodes = _ast("hi {{ name }}!")
        assert _kinds(nodes) == ["text", "output", "text"]
        assert nodes[0].text == "hi "
        assert nodes[1].expr == "name"
        assert nodes[2].text == "!"

    def test_empty_text_token_is_dropped(self):
        # An empty TEXT token contributes nothing; it must not become a node.
        nodes = _ast("{{ a }}{{ b }}")
        assert _kinds(nodes) == ["output", "output"]

    def test_comment_is_a_node_but_renders_nothing(self):
        nodes = _ast("a{# c #}b")
        assert _kinds(nodes) == ["text", "comment", "text"]
        assert Frond().render_string("a{# c #}b", {}) == "ab"

    def test_raw_block_is_plain_text(self):
        # {% raw %} is resolved by the tokenizer, so there is no raw node.
        nodes = _ast("{% raw %}{{ literal }}{% endraw %}")
        assert _kinds(nodes) == ["text"]
        assert nodes[0].text == "{{ literal }}"

    def test_if_carries_its_branches(self):
        nodes = _ast("{% if a %}A{% elseif b %}B{% elif c %}C{% else %}D{% endif %}")
        assert _kinds(nodes) == ["if"]
        branches = nodes[0].branches
        assert [cond for cond, _body in branches] == ["a", "b", "c", None]
        # Every branch body is a parsed node list, not a token list.
        for _cond, body in branches:
            assert _kinds(body) == ["text"]
        assert [body[0].text for _c, body in branches] == ["A", "B", "C", "D"]

    def test_if_without_else_has_no_none_branch(self):
        branches = _ast("{% if a %}A{% endif %}")[0].branches
        assert [cond for cond, _b in branches] == ["a"]

    def test_nested_if_is_nested_in_the_tree(self):
        outer = _ast("{% if a %}x{% if b %}y{% endif %}{% endif %}")[0]
        body = outer.branches[0][1]
        assert _kinds(body) == ["text", "if"]
        assert body[1].branches[0][1][0].text == "y"

    def test_for_header_is_parsed_and_body_carried(self):
        node = _ast("{% for i in items %}{{ i }}{% endfor %}")[0]
        assert node.kind == "for"
        assert (node.key_var, node.value_var, node.iterable) == ("i", None, "items")
        assert _kinds(node.body) == ["output"]
        assert node.else_body == []

    def test_for_key_value_and_else(self):
        node = _ast("{% for k, v in d %}{{ k }}{% else %}NONE{% endfor %}")[0]
        assert (node.key_var, node.value_var, node.iterable) == ("k", "v", "d")
        assert _kinds(node.body) == ["output"]
        assert _kinds(node.else_body) == ["text"]
        assert node.else_body[0].text == "NONE"

    def test_nested_for_is_nested_in_the_tree(self):
        outer = _ast("{% for r in rows %}{% for c in r %}{{ c }}{% endfor %}{% endfor %}")[0]
        assert _kinds(outer.body) == ["for"]
        assert outer.body[0].iterable == "r"

    def test_set_include_and_import_nodes(self):
        assert _ast("{% set n = 1 %}")[0].kind == "set"
        assert _ast('{% include "p.twig" %}')[0].kind == "include"
        assert _ast('{% from "m.twig" import a %}')[0].kind == "from_import"
        assert _ast('{% import "m.twig" as m %}')[0].kind == "import_as"

    def test_body_carrying_delegated_nodes(self):
        for source, kind in [
            ("{% macro m() %}B{% endmacro %}", "macro"),
            ("{% cache 'k' 60 %}B{% endcache %}", "cache"),
            ("{% spaceless %}B{% endspaceless %}", "spaceless"),
            ("{% autoescape false %}B{% endautoescape %}", "autoescape"),
        ]:
            node = _ast(source)[0]
            assert node.kind == kind, source
            assert _kinds(node.body) == ["text"], source
            assert node.body[0].text == "B", source

    def test_live_node_carries_body_and_its_source(self):
        node = _ast('{% live "n" poll 5 %}<p>{{ x }}</p>{% endlive %}')[0]
        assert node.kind == "live"
        assert _kinds(node.body) == ["text", "output", "text"]
        # The live endpoint re-renders from this source text.
        assert node.body_source == "<p>{{ x }}</p>"
        assert node.nested is False

    def test_nested_live_is_recorded_not_raised_at_parse(self):
        # The error must still come from the RENDER, so a live block inside a
        # branch that never renders stays silent.
        node = _ast('{% live "a" sse %}{% live "b" sse %}{% endlive %}{% endlive %}')[0]
        assert node.nested is True

    def test_nested_live_raises_on_render(self):
        with pytest.raises(ValueError, match="nested live blocks are not supported"):
            Frond().render_string(
                '{% live "a" sse %}{% live "b" sse %}{% endlive %}{% endlive %}', {})

    def test_nested_live_inside_false_branch_never_raises(self):
        out = Frond().render_string(
            '{% if flag %}{% live "a" sse %}{% live "b" sse %}{% endlive %}{% endlive %}'
            "{% endif %}ok", {"flag": False})
        assert out == "ok"

    def test_extends_and_block_are_inert_markers(self):
        # Inheritance runs as a SOURCE pass before tokenizing, so these tags are
        # inert by the time the parser sees them and their bodies are NOT grouped.
        nodes = _ast('{% extends "b.twig" %}{% block c %}inner{% endblock %}')
        assert _kinds(nodes) == ["skip", "skip", "text", "skip"]
        assert nodes[0].template == 'extends "b.twig"'
        assert nodes[1].name == "c"

    def test_stray_terminator_and_empty_tag_are_skip_nodes(self):
        """A stray terminator and an empty tag still parse to a no-op node.

        3.13.89 made an UNKNOWN tag raise (it used to leak its body), but these
        two keep the old skip-node behaviour on purpose: neither has a body, so
        neither can expose content that was meant to be gated.
        """
        assert _kinds(_ast("{% endif %}")) == ["skip"]
        assert _kinds(_ast("{%  %}")) == ["skip"]

    def test_an_unknown_tag_raises_at_parse_time(self):
        """3.13.89: {% wibble %} is a typo, and a typo must not parse.

        The NEGATIVE case of the test above. It used to produce a skip node,
        which meant a mistyped guard rendered its body unconditionally.
        """
        with pytest.raises(ValueError, match='unknown tag "wibble"'):
            _ast("{% wibble %}")


class TestParserOwnsStructureAlone:
    """The grouping duplication must not come back."""

    def test_compiler_no_longer_re_derives_structure(self):
        # These were a second, hand-synchronised copy of the engine's token
        # grouping and whitespace pre-pass. The parser owns both now.
        for gone in ("_collect_if", "_collect_for", "_apply_whitespace_control"):
            assert not hasattr(C, gone), \
                f"compiler.{gone} is back — structure must be derived only in parser.py"

    def test_engine_handlers_take_nodes_not_a_token_list(self):
        # _handle_if / _handle_for used to scan a token list from an index; they
        # now receive an already-grouped node.
        from tina4_python.frond import engine as E
        import inspect
        for name in ("_handle_if", "_handle_for", "_handle_cache", "_handle_live",
                     "_handle_spaceless", "_handle_autoescape", "_handle_macro"):
            params = list(inspect.signature(getattr(E.Frond, name)).parameters)
            assert params == ["self", "node", "context"], f"{name}{params}"

    def test_both_consumers_read_the_same_tree(self):
        # One AST object, compiled AND interpreted -> identical bytes.
        source = ("{% for i in items %}{% if i > 1 %}[{{ i }}]{% else %}({{ i }})"
                  "{% endif %}{% endfor %}")
        data = {"items": [1, 2, 3]}
        ast = _ast(source)
        eng = Frond()
        context = {**eng._globals, **data}

        compiled = C.compile_template(ast)
        assert compiled is not None
        assert compiled(eng, dict(context)) == eng._render_nodes(ast, dict(context))


class TestParseDoesNotMutateTokens:
    """The caller's token list stays pristine — the extends path reconstructs
    source from it, so a whitespace trim leaking into the tokens would corrupt
    template inheritance."""

    def test_tokens_are_untouched_by_whitespace_control(self):
        source = "a   {{- x -}}   b"
        tokens = P._tokenize(source)
        before = list(tokens)
        P.parse(tokens)
        assert tokens == before
        # ...and the source can still be rebuilt exactly.
        assert "".join(value for _t, value in tokens) == source

    def test_whitespace_is_still_applied_to_the_nodes(self):
        # Negative half: the trims must land in the TREE even though the tokens
        # are untouched, otherwise "pristine tokens" would just mean "no trim".
        nodes = P.parse(P._tokenize("a   {{- x -}}   b"))
        assert [n.text for n in nodes if n.kind == "text"] == ["a", "b"]

    def test_extends_still_renders_after_a_cached_parse(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (tmp_path / "base.twig").write_text("X\n  {%- block c %}\n  d\n  {%- endblock %}\nY")
        (tmp_path / "kid.twig").write_text(
            '{% extends "base.twig" %}{% block c %} kid {% endblock %}')
        eng = Frond(template_dir=str(tmp_path))
        first = eng.render("kid.twig", {})
        # The second render takes the CACHED path, where source is rebuilt from
        # the cached tokens.
        assert eng.render("kid.twig", {}) == first


class TestAstIsCached:
    def test_file_cache_holds_tokens_and_ast(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (tmp_path / "p.twig").write_text("{% for i in items %}{{ i }}{% endfor %}")
        eng = Frond(template_dir=str(tmp_path))
        assert eng.render("p.twig", {"items": [1, 2]}) == "12"

        tokens, ast, _expires = eng._compiled["p.twig"]
        assert tokens and _kinds(ast) == ["for"]
        # Cached, not re-parsed: the same AST object serves the next render.
        assert eng.render("p.twig", {"items": [3]}) == "3"
        assert eng._compiled["p.twig"][1] is ast

    def test_string_cache_holds_tokens_and_ast(self):
        eng = Frond()
        src = "{% if a %}A{% endif %}"
        eng.render_string(src, {"a": True})
        key = __import__("hashlib").md5(src.encode()).hexdigest()
        tokens, ast = eng._compiled_strings[key]
        assert tokens and _kinds(ast) == ["if"]
        eng.render_string(src, {"a": True})
        assert eng._compiled_strings[key][1] is ast

    def test_clear_cache_clears_the_ast_too(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (tmp_path / "p.twig").write_text("{{ x }}")
        eng = Frond(template_dir=str(tmp_path))
        eng.render("p.twig", {"x": 1})
        eng.render_string("{{ x }}", {"x": 1})
        assert eng._compiled and eng._compiled_strings and eng._compiled_fn

        eng.clear_cache()
        assert eng._compiled == {}
        assert eng._compiled_strings == {}
        assert eng._compiled_fn == {}
        # Still renders (re-tokenizes, re-parses, re-compiles).
        assert eng.render("p.twig", {"x": 2}) == "2"

    def test_dev_mode_reparses_on_edit(self, tmp_path, monkeypatch):
        # Hot-reload must survive AST caching: an edit must be seen.
        monkeypatch.setenv("TINA4_DEBUG", "true")
        f = tmp_path / "d.twig"
        f.write_text("{% for i in items %}{{ i }}{% endfor %}")
        eng = Frond(template_dir=str(tmp_path))
        assert eng.render("d.twig", {"items": [1, 2]}) == "12"
        f.write_text("{% for i in items %}[{{ i }}]{% endfor %}")
        assert eng.render("d.twig", {"items": [1, 2]}) == "[1][2]"


class TestStripBeforeContract:
    """`strip_before` survives to render time ONLY when the thing to trim is
    rendered output. It is both the interpreter's trigger and the compiler's
    fallback signal, so one flag must mean one thing."""

    @pytest.mark.parametrize("source", [
        "text   {{- x }}",                       # left neighbour IS literal text
        "{{- x }}",                              # nothing to the left
        "{% if a %}{{- x }}{% endif %}",         # first node of a body
    ])
    def test_not_flagged_when_the_trim_is_structural(self, source):
        flagged = [n for n in _walk(_ast(source)) if getattr(n, "strip_before", False)]
        assert flagged == []

    @pytest.mark.parametrize("source", [
        "{{ n }}{{- x }}",                       # value output to the left
        "hello  {# c #}{{- x }}",                # comment to the left
        "{% if a %}foo  {% endif %}{{- x }}",    # block output to the left
        "{% set t = 1 %}{{- x }}",               # set to the left
    ])
    def test_flagged_when_the_trim_is_render_dependent(self, source):
        flagged = [n for n in _walk(_ast(source)) if getattr(n, "strip_before", False)]
        assert len(flagged) == 1
        # And the compiler must refuse the whole template for exactly this case.
        assert C.compile_template(_ast(source)) is None

    def test_render_dependent_trim_still_happens(self):
        assert Frond().render_string("{{ n }}{{- x }}", {"n": "hi   ", "x": "X"}) == "hiX"


def _walk(nodes):
    """Every node in a tree, depth first."""
    for node in nodes:
        yield node
        if node.kind == "if":
            for _cond, body in node.branches:
                yield from _walk(body)
        elif node.kind == "for":
            yield from _walk(node.body)
            yield from _walk(node.else_body)
        elif node.kind in ("macro", "cache", "spaceless", "autoescape", "live"):
            yield from _walk(node.body)


class TestMalformedTemplatesBehaveAsBefore:
    """Preserved deliberately: the parse layer relocated this logic, it did not
    redesign it. Each case is what v3 rendered, byte for byte."""

    def test_if_without_endif_swallows_the_rest(self):
        # No endif at depth 0 -> the final branch is never closed, so the
        # construct renders nothing and consumes everything after it.
        assert Frond().render_string("before {% if a %}BODY after", {"a": True}) == "before "

    def test_if_without_endif_keeps_earlier_branches(self):
        assert Frond().render_string("{% if a %}X{% else %}Y no endif", {"a": True}) == "X"
        assert Frond().render_string("{% if a %}X{% else %}Y no endif", {"a": False}) == ""

    def test_malformed_for_renders_its_body_inline_once(self):
        # A for header the regex rejects is NOT grouped: its body renders once
        # inline and the endfor is skipped.
        assert Frond().render_string("pre {% for %}BODY{% endfor %} post",
                                     {}) == "pre BODY post"

    def test_for_without_endfor_still_loops(self):
        assert Frond().render_string("pre {% for i in items %}{{ i }},",
                                     {"items": [1, 2]}) == "pre 1,2,"

    def test_stray_terminators_render_nothing(self):
        assert Frond().render_string("a {% endif %} b", {}) == "a  b"
        assert Frond().render_string("a {% endfor %} b", {}) == "a  b"

    def test_unknown_tag_raises_instead_of_rendering_nothing(self):
        """3.13.89 (Breaking): an unknown tag is an error, not a silent skip.

        Rendering nothing was the SAFE half of the old behaviour; the unsafe half
        was that a BLOCK-shaped typo still rendered its body. Both are gone --
        the template now fails loudly and names the tag.
        """
        with pytest.raises(ValueError, match='unknown tag "wibble"'):
            Frond().render_string("a {% wibble x %} b", {})
        # Negative case: an unknown BLOCK tag must not leak the content between
        # it and its terminator. That was the security-shaped half.
        with pytest.raises(ValueError, match='unknown tag "iff"'):
            Frond().render_string("{% iff admin %}SECRET{% endiff %}", {"admin": False})

    def test_malformed_macro_registers_nothing_and_skips_its_body(self):
        assert Frond().render_string("{% macro %}body{% endmacro %}AFTER", {}) == "AFTER"

    def test_empty_bodies(self):
        assert Frond().render_string("{% if a %}{% endif %}Z", {"a": True}) == "Z"
        assert Frond().render_string("{% for i in items %}{% endfor %}Z",
                                     {"items": [1]}) == "Z"
