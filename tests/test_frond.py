# Tests for tina4_python.frond
import pytest
from pathlib import Path
from tina4_python.frond import Frond


@pytest.fixture
def engine(tmp_path):
    """Frond engine with temp template dir."""
    return Frond(template_dir=str(tmp_path))


@pytest.fixture
def tpl_dir(tmp_path):
    """Template directory path."""
    return tmp_path


# ── Variable Tests ──────────────────────────────────────────────


class TestVariables:
    def test_simple_variable(self, engine):
        assert engine.render_string("Hello {{ name }}", {"name": "World"}) == "Hello World"

    def test_dotted_access(self, engine):
        assert engine.render_string("{{ user.name }}", {"user": {"name": "Alice"}}) == "Alice"

    def test_array_access(self, engine):
        assert engine.render_string("{{ items[0] }}", {"items": ["first", "second"]}) == "first"

    def test_missing_variable(self, engine):
        assert engine.render_string("{{ missing }}", {}) == ""

    def test_auto_escape_html(self, engine):
        result = engine.render_string("{{ text }}", {"text": "<b>bold</b>"})
        assert "&lt;b&gt;" in result

    def test_raw_filter_no_escape(self, engine):
        result = engine.render_string("{{ text | raw }}", {"text": "<b>bold</b>"})
        assert result == "<b>bold</b>"

    def test_string_concatenation(self, engine):
        result = engine.render_string('{{ "Hello " ~ name ~ "!" }}', {"name": "World"})
        assert result == "Hello World!"

    def test_ternary(self, engine):
        assert engine.render_string('{{ active ? "yes" : "no" }}', {"active": True}) == "yes"
        assert engine.render_string('{{ active ? "yes" : "no" }}', {"active": False}) == "no"

    def test_null_coalescing(self, engine):
        assert engine.render_string('{{ name ?? "default" }}', {"name": None}) == "default"
        assert engine.render_string('{{ name ?? "default" }}', {"name": "Alice"}) == "Alice"


# ── Filter Tests ────────────────────────────────────────────────


class TestFilters:
    def test_upper(self, engine):
        assert engine.render_string("{{ name | upper }}", {"name": "alice"}) == "ALICE"

    def test_lower(self, engine):
        assert engine.render_string("{{ name | lower }}", {"name": "ALICE"}) == "alice"

    def test_capitalize(self, engine):
        assert engine.render_string("{{ name | capitalize }}", {"name": "alice"}) == "Alice"

    def test_default(self, engine):
        assert engine.render_string('{{ x | default("N/A") }}', {}) == "N/A"
        assert engine.render_string('{{ x | default("N/A") }}', {"x": "val"}) == "val"

    def test_length(self, engine):
        assert engine.render_string("{{ items | length }}", {"items": [1, 2, 3]}) == "3"

    def test_join(self, engine):
        result = engine.render_string('{{ items | join(", ") }}', {"items": ["a", "b", "c"]})
        assert result == "a, b, c"

    def test_truncate(self, engine):
        result = engine.render_string("{{ text | truncate(5) }}", {"text": "Hello World"})
        assert result == "Hello..."

    def test_slug(self, engine):
        result = engine.render_string("{{ title | slug }}", {"title": "Hello World!"})
        assert result == "hello-world"

    def test_json_encode(self, engine):
        result = engine.render_string("{{ data | json_encode | raw }}", {"data": {"a": 1}})
        assert '"a": 1' in result

    def test_number_format(self, engine):
        result = engine.render_string("{{ price | number_format(2) }}", {"price": 1234.5})
        assert result == "1,234.50"

    def test_nl2br(self, engine):
        result = engine.render_string("{{ text | nl2br | raw }}", {"text": "a\nb"})
        assert "<br>" in result

    def test_striptags(self, engine):
        result = engine.render_string("{{ html | striptags }}", {"html": "<b>bold</b>"})
        assert result == "bold"

    def test_replace(self, engine):
        result = engine.render_string('{{ text | replace("world", "frond") }}', {"text": "hello world"})
        assert result == "hello frond"

    def test_chained_filters(self, engine):
        result = engine.render_string("{{ name | trim | upper }}", {"name": "  alice  "})
        assert result == "ALICE"

    def test_md5(self, engine):
        result = engine.render_string("{{ text | md5 }}", {"text": "hello"})
        assert len(result) == 32

    def test_first_last(self, engine):
        assert engine.render_string("{{ items | first }}", {"items": [1, 2, 3]}) == "1"
        assert engine.render_string("{{ items | last }}", {"items": [1, 2, 3]}) == "3"

    def test_reverse(self, engine):
        result = engine.render_string("{{ items | reverse | join }}", {"items": ["a", "b", "c"]})
        assert result == "c, b, a"

    def test_sort(self, engine):
        result = engine.render_string("{{ items | sort | join }}", {"items": ["c", "a", "b"]})
        assert result == "a, b, c"

    def test_keys_values(self, engine):
        data = {"name": "Alice", "age": "30"}
        result = engine.render_string("{{ d | keys | join }}", {"d": data})
        assert "name" in result

    def test_custom_filter(self, engine):
        engine.add_filter("double", lambda v: str(v) * 2)
        assert engine.render_string("{{ x | double }}", {"x": "ha"}) == "haha"


# ── If/Else Tests ───────────────────────────────────────────────


class TestIfElse:
    def test_if_true(self, engine):
        result = engine.render_string("{% if show %}yes{% endif %}", {"show": True})
        assert result == "yes"

    def test_if_false(self, engine):
        result = engine.render_string("{% if show %}yes{% endif %}", {"show": False})
        assert result == ""

    def test_if_else(self, engine):
        tpl = "{% if active %}on{% else %}off{% endif %}"
        assert engine.render_string(tpl, {"active": True}) == "on"
        assert engine.render_string(tpl, {"active": False}) == "off"

    def test_elseif(self, engine):
        tpl = "{% if x == 1 %}one{% elseif x == 2 %}two{% else %}other{% endif %}"
        assert engine.render_string(tpl, {"x": 1}) == "one"
        assert engine.render_string(tpl, {"x": 2}) == "two"
        assert engine.render_string(tpl, {"x": 3}) == "other"

    def test_elif(self, engine):
        tpl = "{% if x == 1 %}one{% elif x == 2 %}two{% endif %}"
        assert engine.render_string(tpl, {"x": 2}) == "two"

    def test_comparison_operators(self, engine):
        assert engine.render_string("{% if x > 5 %}yes{% endif %}", {"x": 10}) == "yes"
        assert engine.render_string("{% if x < 5 %}yes{% endif %}", {"x": 3}) == "yes"
        assert engine.render_string("{% if x >= 5 %}yes{% endif %}", {"x": 5}) == "yes"
        assert engine.render_string("{% if x != 5 %}yes{% endif %}", {"x": 3}) == "yes"

    def test_and_or(self, engine):
        assert engine.render_string("{% if a and b %}yes{% endif %}", {"a": True, "b": True}) == "yes"
        assert engine.render_string("{% if a and b %}yes{% endif %}", {"a": True, "b": False}) == ""
        assert engine.render_string("{% if a or b %}yes{% endif %}", {"a": False, "b": True}) == "yes"

    def test_not(self, engine):
        assert engine.render_string("{% if not hidden %}show{% endif %}", {"hidden": False}) == "show"

    def test_is_defined(self, engine):
        assert engine.render_string("{% if x is defined %}yes{% endif %}", {"x": 1}) == "yes"
        assert engine.render_string("{% if x is defined %}yes{% endif %}", {}) == ""

    def test_is_empty(self, engine):
        assert engine.render_string("{% if items is empty %}empty{% endif %}", {"items": []}) == "empty"

    def test_is_even_odd(self, engine):
        assert engine.render_string("{% if n is even %}yes{% endif %}", {"n": 4}) == "yes"
        assert engine.render_string("{% if n is odd %}yes{% endif %}", {"n": 3}) == "yes"

    def test_in_operator(self, engine):
        assert engine.render_string('{% if "a" in items %}yes{% endif %}', {"items": ["a", "b"]}) == "yes"
        assert engine.render_string('{% if "c" in items %}yes{% endif %}', {"items": ["a", "b"]}) == ""

    def test_nested_if(self, engine):
        tpl = "{% if a %}{% if b %}both{% endif %}{% endif %}"
        assert engine.render_string(tpl, {"a": True, "b": True}) == "both"


# ── For Loop Tests ──────────────────────────────────────────────


class TestForLoop:
    def test_simple_for(self, engine):
        result = engine.render_string("{% for item in items %}{{ item }}{% endfor %}", {"items": ["a", "b", "c"]})
        assert result == "abc"

    def test_loop_index(self, engine):
        result = engine.render_string("{% for item in items %}{{ loop.index }}{% endfor %}", {"items": ["a", "b"]})
        assert result == "12"

    def test_loop_first_last(self, engine):
        tpl = "{% for item in items %}{% if loop.first %}F{% endif %}{% if loop.last %}L{% endif %}{% endfor %}"
        assert engine.render_string(tpl, {"items": ["a", "b", "c"]}) == "FL"

    def test_loop_length(self, engine):
        result = engine.render_string("{% for item in items %}{{ loop.length }}{% endfor %}", {"items": [1, 2, 3]})
        assert result == "333"

    def test_for_else(self, engine):
        tpl = "{% for item in items %}{{ item }}{% else %}empty{% endfor %}"
        assert engine.render_string(tpl, {"items": []}) == "empty"
        assert engine.render_string(tpl, {"items": ["x"]}) == "x"

    def test_for_key_value(self, engine):
        tpl = "{% for k, v in data %}{{ k }}={{ v }} {% endfor %}"
        result = engine.render_string(tpl, {"data": {"a": 1, "b": 2}})
        assert "a=1" in result
        assert "b=2" in result

    def test_nested_for(self, engine):
        tpl = "{% for g in groups %}{% for i in g %}{{ i }}{% endfor %},{% endfor %}"
        result = engine.render_string(tpl, {"groups": [[1, 2], [3, 4]]})
        assert result == "12,34,"

    def test_loop_even_odd(self, engine):
        tpl = "{% for i in items %}{% if loop.even %}E{% else %}O{% endif %}{% endfor %}"
        assert engine.render_string(tpl, {"items": [1, 2, 3, 4]}) == "OEOE"


# ── Set / Include / Extends Tests ──────────────────────────────


class TestSetIncludeExtends:
    def test_set_variable(self, engine):
        result = engine.render_string('{% set greeting = "Hello" %}{{ greeting }}', {})
        assert result == "Hello"

    def test_set_with_concat(self, engine):
        result = engine.render_string('{% set msg = "Hi " ~ name %}{{ msg }}', {"name": "Alice"})
        assert result == "Hi Alice"

    def test_include(self, engine, tpl_dir):
        (tpl_dir / "partial.html").write_text("Hello {{ name }}")
        result = engine.render_string('{% include "partial.html" %}', {"name": "World"})
        assert result == "Hello World"

    def test_include_ignore_missing(self, engine):
        result = engine.render_string('{% include "nope.html" ignore missing %}', {})
        assert result == ""

    def test_include_missing_raises(self, engine):
        with pytest.raises(FileNotFoundError):
            engine.render_string('{% include "nope.html" %}', {})

    def test_extends_and_blocks(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text("<h1>{% block title %}Default{% endblock %}</h1><div>{% block content %}{% endblock %}</div>")
        (tpl_dir / "page.html").write_text('{% extends "base.html" %}{% block title %}My Page{% endblock %}{% block content %}Hello{% endblock %}')
        result = engine.render("page.html", {})
        assert "<h1>My Page</h1>" in result
        assert "<div>Hello</div>" in result

    def test_extends_default_block(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text("{% block title %}Default Title{% endblock %}")
        (tpl_dir / "page.html").write_text('{% extends "base.html" %}')
        result = engine.render("page.html", {})
        assert result == "Default Title"

    def test_extends_with_leading_whitespace(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text("<html><body>{% block content %}default{% endblock %}</body></html>")
        (tpl_dir / "page.html").write_text('  {% extends "base.html" %}\n{% block content %}<h1>Hello</h1>{% endblock %}')
        result = engine.render("page.html", {})
        assert "<html><body>" in result
        assert "<h1>Hello</h1>" in result

    def test_extends_with_leading_newlines(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text("<html><body>{% block content %}default{% endblock %}</body></html>")
        (tpl_dir / "page.html").write_text('\n\n{% extends "base.html" %}\n{% block content %}<h1>Hello</h1>{% endblock %}')
        result = engine.render("page.html", {})
        assert "<html><body>" in result
        assert "<h1>Hello</h1>" in result

    def test_extends_with_variables_in_blocks(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text(
            '<!DOCTYPE html>\n<html>\n<head><title>{% block title %}Default{% endblock %}</title></head>\n'
            '<body>\n{% block content %}{% endblock %}\n</body>\n</html>'
        )
        (tpl_dir / "error.html").write_text(
            '\n{% extends "base.html" %}\n'
            '{% block title %}Error {{ code }}{% endblock %}\n'
            '{% block content %}<div class="card"><h1>{{ code }}</h1><p>{{ msg }}</p></div>{% endblock %}'
        )
        result = engine.render("error.html", {"code": 500, "msg": "Internal Server Error"})
        assert "<title>Error 500</title>" in result
        assert "<h1>500</h1>" in result
        assert "Internal Server Error" in result
        assert "<html>" in result

    def test_extends_with_include_in_block(self, engine, tpl_dir):
        (tpl_dir / "base.html").write_text("<main>{% block content %}{% endblock %}</main>")
        (tpl_dir / "partial.html").write_text("<p>{{ message }}</p>")
        (tpl_dir / "page.html").write_text(
            '\n{% extends "base.html" %}\n'
            '{% block content %}{% include "partial.html" %}{% endblock %}'
        )
        result = engine.render("page.html", {"message": "Included!"})
        assert "<main>" in result
        assert "<p>Included!</p>" in result


# ── Whitespace Control Tests ────────────────────────────────────


class TestWhitespaceControl:
    def test_strip_before(self, engine):
        result = engine.render_string("hello  {{- name }}", {"name": "world"})
        assert result == "helloworld"

    def test_strip_after(self, engine):
        result = engine.render_string("{{ name -}}  there", {"name": "hello"})
        assert result == "hellothere"


# ── Comment Tests ───────────────────────────────────────────────


class TestComments:
    def test_comment_removed(self, engine):
        result = engine.render_string("before{# comment #}after", {})
        assert result == "beforeafter"
        assert "comment" not in result


# ── Global and Custom Test ──────────────────────────────────────


class TestGlobals:
    def test_global_variable(self, engine):
        engine.add_global("app_name", "Tina4")
        assert engine.render_string("{{ app_name }}", {}) == "Tina4"

    def test_data_overrides_global(self, engine):
        engine.add_global("name", "Global")
        assert engine.render_string("{{ name }}", {"name": "Local"}) == "Local"


# ── Macro Tests ─────────────────────────────────────────────────


class TestMacros:
    def test_simple_macro(self, engine):
        tpl = '{% macro greet(name) %}Hello {{ name }}{% endmacro %}{{ greet("World") | raw }}'
        result = engine.render_string(tpl, {})
        assert "Hello World" in result


# ── Form Token Tests ───────────────────────────────────────────


class TestFormToken:
    def test_form_token_function_call(self, engine):
        """{{ form_token() }} renders a hidden input with a JWT."""
        result = engine.render_string("{{ form_token() | raw }}", {})
        assert '<input type="hidden" name="formToken" value="' in result
        # JWT has 3 dot-separated parts
        import re
        token_match = re.search(r'value="([^"]+)"', result)
        assert token_match
        token = token_match.group(1)
        parts = token.split(".")
        assert len(parts) == 3, f"Expected 3 JWT parts, got {len(parts)}"

    def test_form_token_variable(self, engine):
        """{{ form_token }} as a callable global renders properly."""
        result = engine.render_string("{{ form_token() | raw }}", {})
        assert "formToken" in result

    def test_form_token_filter(self, engine):
        """{{ "" | form_token }} works as a filter."""
        result = engine.render_string('{{ "" | form_token | raw }}', {})
        assert '<input type="hidden" name="formToken" value="' in result

    def test_form_token_is_valid_jwt(self, engine):
        """The generated token is a valid JWT that Auth can validate."""
        import re
        from tina4_python.auth import Auth

        result = engine.render_string("{{ form_token() | raw }}", {})
        token_match = re.search(r'value="([^"]+)"', result)
        assert token_match
        token = token_match.group(1)

        auth = Auth()
        payload = auth.valid_token(token)
        assert payload is not None
        assert payload.get("type") == "form"

    def test_form_token_with_descriptor(self, engine):
        """{{ "admin" | form_token }} includes context in payload."""
        import re
        from tina4_python.auth import Auth

        result = engine.render_string('{{ "admin" | form_token | raw }}', {})
        token_match = re.search(r'value="([^"]+)"', result)
        assert token_match
        token = token_match.group(1)

        auth = Auth()
        payload = auth.get_payload(token)
        assert payload is not None
        assert payload.get("type") == "form"
        assert payload.get("context") == "admin"


# ── Raw Block Tests ────────────────────────────────────────────


class TestRawBlock:
    def test_raw_preserves_var_syntax(self, engine):
        src = "{% raw %}{{ name }}{% endraw %}"
        assert engine.render_string(src, {"name": "Alice"}) == "{{ name }}"

    def test_raw_preserves_block_syntax(self, engine):
        src = "{% raw %}{% if true %}yes{% endif %}{% endraw %}"
        assert engine.render_string(src, {}) == "{% if true %}yes{% endif %}"

    def test_raw_mixed_with_normal(self, engine):
        src = "Hello {{ name }}! {% raw %}{{ not_parsed }}{% endraw %} done"
        assert engine.render_string(src, {"name": "World"}) == "Hello World! {{ not_parsed }} done"

    def test_multiple_raw_blocks(self, engine):
        src = "{% raw %}{{ a }}{% endraw %} mid {% raw %}{{ b }}{% endraw %}"
        assert engine.render_string(src, {}) == "{{ a }} mid {{ b }}"

    def test_raw_block_multiline(self, engine):
        src = "{% raw %}\n{{ var }}\n{% tag %}\n{% endraw %}"
        assert engine.render_string(src, {}) == "\n{{ var }}\n{% tag %}\n"


# ── From Import Tests ──────────────────────────────────────────


class TestFromImport:
    def test_from_import_basic(self, engine, tpl_dir):
        (tpl_dir / "macros.twig").write_text(
            '{% macro greeting(name) %}Hello {{ name }}!{% endmacro %}'
        )
        src = '{% from "macros.twig" import greeting %}{{ greeting("World") }}'
        assert engine.render_string(src, {}) == "Hello World!"

    def test_from_import_multiple(self, engine, tpl_dir):
        (tpl_dir / "helpers.twig").write_text(
            '{% macro bold(t) %}B{{ t }}B{% endmacro %}'
            '{% macro italic(t) %}I{{ t }}I{% endmacro %}'
        )
        src = '{% from "helpers.twig" import bold, italic %}{{ bold("hi") }} {{ italic("there") }}'
        result = engine.render_string(src, {})
        assert "BhiB" in result
        assert "IthereI" in result

    def test_from_import_selective(self, engine, tpl_dir):
        (tpl_dir / "mix.twig").write_text(
            '{% macro used(x) %}[{{ x }}]{% endmacro %}'
            '{% macro unused(x) %}{{{ x }}}{% endmacro %}'
        )
        src = '{% from "mix.twig" import used %}{{ used("ok") }}'
        result = engine.render_string(src, {})
        assert "[ok]" in result

    def test_from_import_subdirectory(self, engine, tpl_dir):
        subdir = tpl_dir / "macros"
        subdir.mkdir(exist_ok=True)
        (subdir / "forms.twig").write_text(
            '{% macro field(label, name) %}{{ label }}:{{ name }}{% endmacro %}'
        )
        src = '{% from "macros/forms.twig" import field %}{{ field("Name", "name") }}'
        result = engine.render_string(src, {})
        assert "Name:name" in result


# ── Spaceless Tag Tests ────────────────────────────────────────


class TestSpaceless:
    def test_spaceless_removes_whitespace_between_tags(self, engine):
        src = "{% spaceless %}<div>  <p>  Hello  </p>  </div>{% endspaceless %}"
        result = engine.render_string(src, {})
        assert result == "<div><p>  Hello  </p></div>"

    def test_spaceless_preserves_content_whitespace(self, engine):
        src = "{% spaceless %}<span>  text  </span>{% endspaceless %}"
        result = engine.render_string(src, {})
        assert result == "<span>  text  </span>"

    def test_spaceless_multiline(self, engine):
        src = "{% spaceless %}\n<div>\n    <p>Hi</p>\n</div>\n{% endspaceless %}"
        result = engine.render_string(src, {})
        assert "<div><p>" in result
        assert "</p></div>" in result

    def test_spaceless_with_variables(self, engine):
        src = "{% spaceless %}<div>  <span>{{ name }}</span>  </div>{% endspaceless %}"
        result = engine.render_string(src, {"name": "Alice"})
        assert result == "<div><span>Alice</span></div>"


# ── Autoescape Tag Tests ──────────────────────────────────────


class TestAutoescape:
    def test_autoescape_false_disables_escaping(self, engine):
        src = '{% autoescape false %}{{ html }}{% endautoescape %}'
        result = engine.render_string(src, {"html": "<b>bold</b>"})
        assert result == "<b>bold</b>"

    def test_autoescape_true_keeps_escaping(self, engine):
        src = '{% autoescape true %}{{ html }}{% endautoescape %}'
        result = engine.render_string(src, {"html": "<b>bold</b>"})
        assert "&lt;b&gt;" in result

    def test_autoescape_false_with_filters(self, engine):
        src = '{% autoescape false %}{{ name | upper }}{% endautoescape %}'
        result = engine.render_string(src, {"name": "alice"})
        assert result == "ALICE"

    def test_autoescape_false_multiple_variables(self, engine):
        src = '{% autoescape false %}{{ a }} {{ b }}{% endautoescape %}'
        result = engine.render_string(src, {"a": "<i>x</i>", "b": "<b>y</b>"})
        assert result == "<i>x</i> <b>y</b>"


# ── Inline If Expression Tests ────────────────────────────────


class TestInlineIf:
    def test_inline_if_true(self, engine):
        src = "{{ 'yes' if active else 'no' }}"
        result = engine.render_string(src, {"active": True})
        assert result == "yes"

    def test_inline_if_false(self, engine):
        src = "{{ 'yes' if active else 'no' }}"
        result = engine.render_string(src, {"active": False})
        assert result == "no"

    def test_inline_if_with_variable(self, engine):
        src = "{{ name if name else 'Anonymous' }}"
        result = engine.render_string(src, {"name": "Alice"})
        assert result == "Alice"

    def test_inline_if_with_missing_variable(self, engine):
        src = "{{ name if name else 'Anonymous' }}"
        result = engine.render_string(src, {})
        assert result == "Anonymous"

    def test_inline_if_with_comparison(self, engine):
        src = "{{ 'adult' if age >= 18 else 'minor' }}"
        result = engine.render_string(src, {"age": 21})
        assert result == "adult"

    def test_inline_if_numeric(self, engine):
        src = "{{ count if count else 0 }}"
        result = engine.render_string(src, {"count": 5})
        assert result == "5"


# ── Token Pre-Compilation (Cache) Tests ────────────────────────


class TestTokenCache:
    def test_render_string_cache_same_output(self, engine):
        """Second render_string call produces the same output (using cache)."""
        src = "Hello {{ name }}!"
        data = {"name": "World"}
        first = engine.render_string(src, data)
        second = engine.render_string(src, data)
        assert first == second == "Hello World!"

    def test_render_string_cache_different_data(self, engine):
        """Cached tokens work with different data on each call."""
        src = "{{ greeting }}, {{ name }}!"
        r1 = engine.render_string(src, {"greeting": "Hi", "name": "Alice"})
        r2 = engine.render_string(src, {"greeting": "Bye", "name": "Bob"})
        assert r1 == "Hi, Alice!"
        assert r2 == "Bye, Bob!"

    def test_render_file_cache_same_output(self, engine, tpl_dir):
        """Second file render produces the same output (using cache)."""
        (tpl_dir / "cached.html").write_text("<p>{{ msg }}</p>")
        first = engine.render("cached.html", {"msg": "hello"})
        second = engine.render("cached.html", {"msg": "hello"})
        assert first == second == "<p>hello</p>"

    def test_render_file_cache_different_data(self, engine, tpl_dir):
        """Cached file tokens work with different data."""
        (tpl_dir / "cached2.html").write_text("{{ x }} + {{ y }}")
        r1 = engine.render("cached2.html", {"x": 1, "y": 2})
        r2 = engine.render("cached2.html", {"x": 10, "y": 20})
        assert r1 == "1 + 2"
        assert r2 == "10 + 20"

    def test_cache_invalidation_on_file_change(self, engine, tpl_dir):
        """In dev mode, cache invalidates when file mtime changes."""
        import os
        import time
        os.environ["TINA4_DEBUG"] = "true"
        try:
            tpl = tpl_dir / "changing.html"
            tpl.write_text("Version 1: {{ v }}")
            r1 = engine.render("changing.html", {"v": "a"})
            assert r1 == "Version 1: a"

            # Change file content (touch to update mtime)
            time.sleep(0.05)
            tpl.write_text("Version 2: {{ v }}")
            r2 = engine.render("changing.html", {"v": "b"})
            assert r2 == "Version 2: b"
        finally:
            os.environ.pop("TINA4_DEBUG", None)

    def test_clear_cache(self, engine):
        """clear_cache() empties both caches."""
        engine.render_string("{{ x }}", {"x": 1})
        assert len(engine._compiled_strings) > 0
        engine.clear_cache()
        assert len(engine._compiled_strings) == 0
        assert len(engine._compiled) == 0

    def test_render_string_with_for_loop_cached(self, engine):
        """Complex template with for loop works correctly from cache."""
        src = "{% for i in items %}{{ i }},{% endfor %}"
        data = {"items": [1, 2, 3]}
        first = engine.render_string(src, data)
        second = engine.render_string(src, data)
        assert first == second == "1,2,3,"

    def test_render_string_with_if_cached(self, engine):
        """Template with conditionals works correctly from cache."""
        src = "{% if show %}visible{% else %}hidden{% endif %}"
        r1 = engine.render_string(src, {"show": True})
        r2 = engine.render_string(src, {"show": False})
        assert r1 == "visible"
        assert r2 == "hidden"
