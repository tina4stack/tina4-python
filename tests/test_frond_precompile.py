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
    # Whitespace control — compiled since A.1 (structural trims baked at compile
    # time). See TestWhitespaceControlCompiles for the byte-identity contract.
    ("A {{- x }} B", {"x": "X"}),                                  # strip-before var (text left)
    ("A {{ x -}} B", {"x": "X"}),                                  # strip-after var
    ("A {{- x -}} B", {"x": "X"}),                                 # both
    ("{%- if x -%}Y{%- endif -%}", {"x": True}),                   # markers on if/endif
    ("before\n  {%- if x %}\n  YES\n  {%- endif %}\nafter", {"x": True}),
    ("a {%- if a %}A{%- elif b %}B{%- else %}C{%- endif %} d", {"a": False, "b": True}),
    ("{% if x -%}   BODY{% endif %}   AFTER", {"x": True}),        # opening -%} trims past endif
    ("start\n{% for i in items -%}\n  {{ i }}\n{%- endfor %}\nend", {"items": [1, 2, 3]}),
    ("{%- for i in items -%} {{ i }} {%- endfor -%}", {"items": [1, 2]}),
    ("L {%- for i in empty %}{{ i }}{%- else %}EMPTY{%- endfor %} R", {"empty": []}),
    ("PRE   {% for i in items %}{{- i }}{% endfor %}", {"items": [1, 2]}),  # strip-before body-first (no-op)
    ("A\n{%- set t = items | length %}\n  n={{ t }}", {"items": [1, 2, 3, 4]}),
]

# Templates that MUST fall back to the interpreter (compile_template -> None),
# yet still render the correct output.
FALLBACK = [
    # Render-dependent strip-before: the left neighbour of `{{- `/`{%- ` is NOT a
    # literal TEXT token, so the interpreter right-strips the LIVE output buffer
    # (a value/block/comment/set output). The compiler cannot bake that, so it
    # correctly falls back for these — the ONE whitespace case left uncompiled.
    ("{{ n }}{{- x }}", {"n": "hi ", "x": "X"}),                   # value output before -}}
    ("hello   {# c #}{{- x }}", {"x": "X"}),                       # comment before -}}
    ("{% if flag %}foo   {% endif %}{{- x }}", {"flag": True, "x": "X"}),  # block output before -}}
    ("{% set t = 1 %}{{- x }}", {"x": "X"}),                       # set (empty append) before -}}
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


# ── A.1: whitespace control (ADR-0001 part 1) ──────────────────────────────
#
# Whitespace-controlled templates used to fall back to the interpreter for the
# WHOLE template; now the structural trims are baked at compile time. These
# lock in (a) that such templates COMPILE (no longer fall back) and (b) that the
# compiled render is BYTE-IDENTICAL to the interpreted render — including the
# newline trimming that is the common real-world case, nested if/for, and the
# quirk where an opening `{% if -%}` also trims past its endif.

WHITESPACE = [
    # (source, data)
    ("A {{- x }} B", {"x": "X"}),
    ("A {{ x -}} B", {"x": "X"}),
    ("A {{- x -}} B", {"x": "X"}),
    ("A   \n  {{- x }}\n   B", {"x": "X"}),
    ("{{ x -}}\n\n   tail", {"x": "X"}),
    ("{%- if x -%}Y{%- endif -%}", {"x": True}),
    ("before\n  {%- if x %}\n  YES\n  {%- endif %}\nafter", {"x": True}),
    ("before\n  {%- if x %}\n  YES\n  {%- endif %}\nafter", {"x": False}),
    ("a\n{% if x -%}\nY\n{% else -%}\nN\n{% endif -%}\nb", {"x": False}),
    ("a {%- if a %}A{%- elif b %}B{%- else %}C{%- endif %} d", {"a": False, "b": True}),
    # opening -%} trims BOTH the first body token AND the token after endif
    ("{% if x -%}   BODY{% endif %}   AFTER", {"x": True}),
    ("{% if x -%}   BODY{% endif %}   AFTER", {"x": False}),
    ("start\n{% for i in items -%}\n  {{ i }},\n{%- endfor %}\nend", {"items": [1, 2, 3]}),
    ("{%- for i in items -%} {{ i }} {%- endfor -%}", {"items": [1, 2, 3]}),
    ("L {%- for i in empty %}{{ i }}{%- else %}  EMPTY  {%- endfor %} R", {"empty": []}),
    ("A{% for i in items -%}  {% if i > 1 -%}  {{ i }}{%- endif %}  {%- endfor %}B",
     {"items": [1, 2, 3]}),
    # strip-before that is the first output-producing token in a body: a no-op in
    # the interpreter (fresh output buffer), so it must still compile identically.
    ("PRE   {% for i in items %}{{- i }};{% endfor %}", {"items": [1, 2, 3]}),
    ("PRE   {% if x %}{{- x }}{% endif %}", {"x": "X"}),
    ("A\n{%- set t = items | length %}\n  n={{ t }}", {"items": [1, 2, 3, 4]}),
]


class TestWhitespaceControlCompiles:
    @pytest.mark.parametrize("source,data", WHITESPACE)
    def test_compiles_and_byte_identical(self, source, data):
        # (a) it now COMPILES (callable, not the None fall-back)...
        assert compile_template(E._tokenize(source)) is not None, \
            "whitespace-controlled template should compile, not fall back"
        # (b) ...and the compiled render is byte-identical to the interpreter.
        assert _compiled(source, data) == _interpret(source, data)

    def test_compiled_path_is_actually_used(self):
        # Prove the whitespace template takes the COMPILED path (a callable is
        # cached under its source-hash key), not the interpreter.
        eng = Frond()
        src = "start\n{% for i in items -%}\n  {{ i }}\n{%- endfor %}\nend"
        key = __import__("hashlib").md5(src.encode()).hexdigest()
        eng.render_string(src, {"items": [1, 2, 3]})
        assert callable(eng._compiled_fn.get(key)), \
            "whitespace-controlled template should cache a compiled fn"

    def test_render_dependent_strip_before_falls_back_but_correct(self):
        # The one uncompiled whitespace case: strip-before whose left neighbour is
        # a value output. Must fall back AND render correctly.
        src = "{{ n }}{{- x }}"
        data = {"n": "hi   ", "x": "X"}
        assert compile_template(E._tokenize(src)) is None
        assert _compiled(src, data) == _interpret(src, data) == "hiX"

    def test_plain_template_unaffected(self):
        # A template with no whitespace markers must be untouched by the pre-pass
        # and still compile byte-identically (guards against over-trimming).
        src = "  hi  {{ x }}  \n  bye  "
        data = {"x": "X"}
        assert compile_template(E._tokenize(src)) is not None
        assert _compiled(src, data) == _interpret(src, data) == "  hi  X  \n  bye  "
