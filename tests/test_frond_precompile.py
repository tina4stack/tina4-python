# Tests for tina4_python.frond.compiler — the AOT template precompiler (ADR-0001).
#
# These are REAL renders, no mocks: every case renders a real template through
# the real engine and asserts the AOT-compiled output is byte-identical to the
# interpreted output, and that unsupported constructs fall back to the
# interpreter (correct output, just not compiled). The full Frond suite
# (tests/test_frond.py) is the broader behaviour guard; this file locks in the
# compiler's compile-vs-fallback contract and the dev hot-reload guarantee.
import pytest

from tina4_python.frond import Frond
from tina4_python.frond import engine as E
from tina4_python.frond.compiler import compile_template


def _interpret(source, data):
    """Render `source` through the pure interpreter (never the compiler)."""
    eng = Frond()
    context = {**eng._globals, **(data or {})}
    return eng._render_tokens(list(E._tokenize(source)), context)


def _compiled(source, data):
    """Render `source` through render_string, which prefers the AOT path."""
    return Frond().render_string(source, data)


# Representative templates that MUST compile (the common hot path).
COMPILABLE = [
    ("{{ name }}", {"name": "World"}),
    ("{{ user.name }} <{{ user.email }}>", {"user": {"name": "A&B<>", "email": "a@b.com"}}),
    ("{{ price | number_format(2) }}", {"price": 1234.5}),
    ("{{ text | upper | truncate(5) }}", {"text": "hello world"}),
    ("{{ 'yes' if flag else 'no' }}", {"flag": True}),
    ("{{ loop_free ? 'a' : 'b' }}", {"loop_free": 0}),
    ("{{ missing ?? 'default' }}", {"missing": None}),
    ("{% if a %}A{% elif b %}B{% else %}C{% endif %}", {"a": False, "b": True}),
    ("{% if a %}A{% elseif b %}B{% else %}C{% endif %}", {"a": False, "b": False}),
    ("{% if x > 3 %}big{% endif %}", {"x": 5}),
    ("{% for i in items %}{{ i }},{% endfor %}", {"items": [1, 2, 3]}),
    ("{% for k, v in d %}{{ k }}={{ v }};{% endfor %}", {"d": {"x": 1, "y": 2}}),
    ("{% for idx, x in items %}{{ idx }}:{{ x }} {% endfor %}", {"items": ["a", "b"]}),
    ("{% for x in empty %}{{ x }}{% else %}EMPTY{% endfor %}", {"empty": []}),
    ("{% for x in items %}{% if x > 2 %}[{{ x }}]{% else %}({{ x }}){% endif %}{% endfor %}",
     {"items": [1, 2, 3]}),
    ("{% for row in rows %}{% for c in row %}{{ c }}{% endfor %}|{% endfor %}",
     {"rows": [[1, 2], [3, 4]]}),
    ("{% set total = items | length %}n={{ total }}", {"items": [1, 2, 3, 4]}),
    ("{% for i in items %}{{ loop.index }}/{{ loop.length }}"
     "{{ loop.first ? '<' : '' }}{{ loop.last ? '>' : '' }} {% endfor %}", {"items": [1, 2, 3]}),
    ("plain text, no tags at all", {}),
    ("{# a comment #}visible{# another #}", {}),
    ("{% raw %}{{ literal }}{% endraw %}{{ real }}", {"real": "R"}),
]

# Templates that MUST fall back to the interpreter (compile_template -> None),
# yet still render the correct output.
FALLBACK = [
    ("A {{- x }} B", {"x": "X"}),                                  # whitespace control
    ("{%- if x -%}Y{%- endif -%}", {"x": True}),                   # whitespace control
    ('{% include "missing.twig" ignore missing %}Z', {}),          # include
    ("{% autoescape false %}{{ h }}{% endautoescape %}", {"h": "<b>x</b>"}),  # autoescape
    ("{% spaceless %}<p> <b>x</b> </p>{% endspaceless %}", {}),    # spaceless
    ("{% cache 'k' 60 %}cached{% endcache %}", {}),                # cache block
    ("{% block c %}inline{% endblock %}", {}),                     # bare block
]


class TestCompiledMatchesInterpreted:
    @pytest.mark.parametrize("source,data", COMPILABLE)
    def test_byte_identical(self, source, data):
        assert compile_template(E._tokenize(source)) is not None, "expected this template to compile"
        assert _compiled(source, data) == _interpret(source, data)


class TestFallback:
    @pytest.mark.parametrize("source,data", FALLBACK)
    def test_falls_back_but_correct(self, source, data):
        # compile_template refuses the template (returns None)...
        assert compile_template(E._tokenize(source)) is None, "expected this template to fall back"
        # ...and the engine still renders it correctly via the interpreter.
        assert _compiled(source, data) == _interpret(source, data)

    def test_extends_is_not_compiled(self):
        # Template inheritance is handled above the token walk; the compiler
        # must refuse it so the extends machinery runs on the interpreter path.
        src = '{% extends "base.twig" %}{% block c %}hi{% endblock %}'
        assert compile_template(E._tokenize(src)) is None


class TestCompiledPathIsUsed:
    def test_engine_caches_a_callable_for_supported_template(self):
        eng = Frond()
        src = "{% for i in items %}{{ i }}{% endfor %}"
        key = __import__("hashlib").md5(src.encode()).hexdigest()
        eng.render_string(src, {"items": [1, 2, 3]})
        assert callable(eng._compiled_fn.get(key)), "supported template should cache a compiled fn"

    def test_engine_caches_none_for_unsupported_template(self):
        eng = Frond()
        src = '{% include "x.twig" ignore missing %}'
        key = __import__("hashlib").md5(src.encode()).hexdigest()
        eng.render_string(src, {})
        assert key in eng._compiled_fn and eng._compiled_fn[key] is None

    def test_sandbox_never_uses_compiled_path(self):
        eng = Frond()
        eng.sandbox(allowed_filters=["upper"], allowed_tags=["if"], allowed_vars=["x"])
        # A blocked variable is silently dropped by the sandbox (interpreter gate).
        out = eng.render_string("{{ x }}{{ secret }}", {"x": "OK", "secret": "LEAK"})
        assert out == "OK"

    def test_file_render_uses_compiled_path_in_prod(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TINA4_DEBUG", raising=False)
        (tmp_path / "p.twig").write_text("{% for i in items %}{{ i }}{% endfor %}")
        eng = Frond(template_dir=str(tmp_path))
        assert eng.render("p.twig", {"items": [1, 2, 3]}) == "123"
        assert callable(eng._compiled_fn.get("p.twig"))


class TestDevHotReloadPreserved:
    def test_edit_recompiles_in_debug_mode(self, tmp_path, monkeypatch):
        # In dev mode the compiled fn is keyed by a source hash, so editing the
        # template file recompiles instead of serving a stale compiled render.
        monkeypatch.setenv("TINA4_DEBUG", "true")
        f = tmp_path / "d.twig"
        f.write_text("v1: {{ x }}")
        eng = Frond(template_dir=str(tmp_path))
        assert eng.render("d.twig", {"x": "A"}) == "v1: A"
        f.write_text("v2: {{ x }}")
        assert eng.render("d.twig", {"x": "A"}) == "v2: A"


class TestCompileErrorsNeverBreakRender:
    def test_none_on_bad_tokens_falls_back(self):
        # A malformed for (no `in`) is not compiled; the render must not raise.
        src = "{% for %}{{ x }}{% endfor %}after"
        # compile refuses it; the engine falls back to the interpreter.
        assert compile_template(E._tokenize(src)) is None
        assert _compiled(src, {"x": "z"}) == _interpret(src, {"x": "z"})
