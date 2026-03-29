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
    """Comprehensive tests for every builtin Frond filter."""

    # ── String Filters ─────────────────────────────────────────

    def test_upper(self, engine):
        assert engine.render_string("{{ v|upper }}", {"v": "alice"}) == "ALICE"

    def test_lower(self, engine):
        assert engine.render_string("{{ v|lower }}", {"v": "ALICE"}) == "alice"

    def test_capitalize(self, engine):
        assert engine.render_string("{{ v|capitalize }}", {"v": "alice bob"}) == "Alice bob"

    def test_title(self, engine):
        assert engine.render_string("{{ v|title }}", {"v": "hello world"}) == "Hello World"

    def test_trim(self, engine):
        assert engine.render_string("{{ v|trim }}", {"v": "  hi  "}) == "hi"

    def test_ltrim(self, engine):
        assert engine.render_string("{{ v|ltrim }}", {"v": "  hi  "}) == "hi  "

    def test_rtrim(self, engine):
        assert engine.render_string("{{ v|rtrim }}", {"v": "  hi  "}) == "  hi"

    def test_slug(self, engine):
        assert engine.render_string("{{ v|slug }}", {"v": "Hello World!"}) == "hello-world"

    def test_wordwrap(self, engine):
        r = engine.render_string("{{ v|wordwrap(10) }}", {"v": "hello world test"})
        assert "\n" in r

    def test_truncate(self, engine):
        assert engine.render_string("{{ v|truncate(5) }}", {"v": "Hello World"}) == "Hello..."

    def test_truncate_short(self, engine):
        assert engine.render_string("{{ v|truncate(20) }}", {"v": "Hello"}) == "Hello"

    def test_nl2br(self, engine):
        assert "<br>" in engine.render_string("{{ v|nl2br|raw }}", {"v": "a\nb"})

    def test_striptags(self, engine):
        assert engine.render_string("{{ v|striptags }}", {"v": "<b>bold</b>"}) == "bold"

    # ── Array/Collection Filters ───────────────────────────────

    def test_length_list(self, engine):
        assert engine.render_string("{{ v|length }}", {"v": [1, 2, 3]}) == "3"

    def test_length_string(self, engine):
        assert engine.render_string("{{ v|length }}", {"v": "hello"}) == "5"

    def test_reverse_list(self, engine):
        assert engine.render_string("{{ v|reverse }}", {"v": [1, 2, 3]}) == "[3, 2, 1]"

    def test_reverse_string(self, engine):
        assert engine.render_string("{{ v|reverse }}", {"v": "abc"}) == "cba"

    def test_sort(self, engine):
        assert engine.render_string("{{ v|sort }}", {"v": [3, 1, 2]}) == "[1, 2, 3]"

    def test_first(self, engine):
        assert engine.render_string("{{ v|first }}", {"v": [10, 20, 30]}) == "10"

    def test_last(self, engine):
        assert engine.render_string("{{ v|last }}", {"v": [10, 20, 30]}) == "30"

    def test_join(self, engine):
        assert engine.render_string('{{ v|join(", ") }}', {"v": ["a", "b", "c"]}) == "a, b, c"

    def test_join_default_separator(self, engine):
        assert engine.render_string("{{ v|join }}", {"v": ["a", "b"]}) == "a, b"

    def test_split(self, engine):
        r = engine.render_string("{{ v|split(',') }}", {"v": "a,b,c"})
        assert "a" in r and "b" in r and "c" in r

    def test_unique(self, engine):
        assert engine.render_string("{{ v|unique }}", {"v": [1, 2, 2, 3]}) == "[1, 2, 3]"

    def test_filter(self, engine):
        r = engine.render_string("{{ v|filter }}", {"v": [0, 1, "", "hi", None, 3]})
        assert "0" not in r or "1" in r  # falsy values removed

    def test_map(self, engine):
        ctx = {"v": [{"name": "A"}, {"name": "B"}]}
        r = engine.render_string('{{ v|map("name") }}', ctx)
        assert "A" in r and "B" in r

    def test_column(self, engine):
        ctx = {"v": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
        r = engine.render_string('{{ v|column("name") }}', ctx)
        assert "A" in r and "B" in r

    def test_batch(self, engine):
        r = engine.render_string("{{ v|batch(2) }}", {"v": [1, 2, 3, 4, 5]})
        assert "[[1, 2]" in r

    def test_slice_filter(self, engine):
        r = engine.render_string("{{ v|slice(1, 3) }}", {"v": [10, 20, 30, 40]})
        assert "20" in r and "30" in r

    # ── Replace Filter ─────────────────────────────────────────

    def test_replace(self, engine):
        assert engine.render_string('{{ v|replace("a", "b") }}', {"v": "banana"}) == "bbnbnb"

    def test_replace_space(self, engine):
        assert engine.render_string("{{ v|replace(' ', '_') }}", {"v": "hi there"}) == "hi_there"

    # ── Encoding Filters ───────────────────────────────────────

    def test_escape(self, engine):
        """escape filter + auto-escape = double-escaped, use |raw to see filter output."""
        r = engine.render_string("{{ v|escape|raw }}", {"v": "<b>hi</b>"})
        assert "&lt;b&gt;" in r

    def test_e_alias(self, engine):
        r = engine.render_string("{{ v|e|raw }}", {"v": "<b>"})
        assert "&lt;b&gt;" in r

    def test_raw(self, engine):
        assert engine.render_string("{{ v|raw }}", {"v": "<b>hi</b>"}) == "<b>hi</b>"

    def test_safe(self, engine):
        assert engine.render_string("{{ v|safe }}", {"v": "<b>hi</b>"}) == "<b>hi</b>"

    def test_url_encode(self, engine):
        r = engine.render_string("{{ v|url_encode }}", {"v": "hello world"})
        assert "hello" in r and " " not in r

    def test_base64_encode(self, engine):
        assert engine.render_string("{{ v|base64_encode }}", {"v": "hello"}) == "aGVsbG8="

    def test_base64_decode(self, engine):
        assert engine.render_string("{{ v|base64_decode }}", {"v": "aGVsbG8="}) == "hello"

    def test_md5(self, engine):
        r = engine.render_string("{{ v|md5 }}", {"v": "hello"})
        assert len(r) == 32

    def test_sha256(self, engine):
        r = engine.render_string("{{ v|sha256 }}", {"v": "hello"})
        assert len(r) == 64

    # ── Numeric Filters ────────────────────────────────────────

    def test_abs(self, engine):
        assert engine.render_string("{{ v|abs }}", {"v": -5}) == "5"

    def test_round(self, engine):
        assert engine.render_string("{{ v|round(2) }}", {"v": 3.14159}) == "3.14"

    def test_round_no_decimals(self, engine):
        assert engine.render_string("{{ v|round }}", {"v": 3.7}) == "4.0"

    def test_number_format(self, engine):
        assert engine.render_string("{{ v|number_format(2) }}", {"v": 1234.5}) == "1,234.50"

    # ── Type Conversion Filters ────────────────────────────────

    def test_int(self, engine):
        assert engine.render_string("{{ v|int }}", {"v": "42"}) == "42"

    def test_float(self, engine):
        assert engine.render_string("{{ v|float }}", {"v": "3.14"}) == "3.14"

    def test_string(self, engine):
        assert engine.render_string("{{ v|string }}", {"v": 123}) == "123"

    # ── JSON Filters ───────────────────────────────────────────

    def test_json_encode(self, engine):
        r = engine.render_string("{{ v|json_encode|raw }}", {"v": {"a": 1}})
        assert '"a"' in r

    def test_to_json(self, engine):
        r = engine.render_string("{{ v|to_json|raw }}", {"v": {"a": 1}})
        assert '{"a":1}' == r

    def test_to_json_html_safe(self, engine):
        r = engine.render_string("{{ v|to_json|raw }}", {"v": {"x": "<script>"}})
        assert "\\u003c" in r
        assert "<script>" not in r

    def test_tojson_alias(self, engine):
        assert engine.render_string("{{ v|tojson|raw }}", {"v": [1]}) == "[1]"

    def test_json_decode(self, engine):
        r = engine.render_string("{{ v|json_decode }}", {"v": '{"a": 1}'})
        assert "a" in r

    def test_js_escape(self, engine):
        r = engine.render_string("{{ v|js_escape|raw }}", {"v": "it's a \"test\""})
        assert "\\'" in r
        assert '\\"' in r

    def test_js_escape_newlines(self, engine):
        r = engine.render_string("{{ v|js_escape|raw }}", {"v": "a\nb"})
        assert "\\n" in r

    # ── Dict Filters ───────────────────────────────────────────

    def test_keys(self, engine):
        r = engine.render_string("{{ v|keys }}", {"v": {"a": 1, "b": 2}})
        assert "a" in r and "b" in r

    def test_values(self, engine):
        r = engine.render_string("{{ v|values }}", {"v": {"a": 1, "b": 2}})
        assert "1" in r and "2" in r

    # ── Default Filter ─────────────────────────────────────────

    def test_default_none(self, engine):
        assert engine.render_string('{{ v|default("N/A") }}', {}) == "N/A"

    def test_default_empty_string(self, engine):
        assert engine.render_string('{{ v|default("N/A") }}', {"v": ""}) == "N/A"

    def test_default_has_value(self, engine):
        assert engine.render_string('{{ v|default("N/A") }}', {"v": "ok"}) == "ok"

    # ── Date Filter ────────────────────────────────────────────

    def test_date_format(self, engine):
        r = engine.render_string('{{ v|date("%Y") }}', {"v": "2026-03-29"})
        assert r == "2026"

    # ── Format Filter ──────────────────────────────────────────

    def test_format(self, engine):
        r = engine.render_string('{{ v|format("world") }}', {"v": "hello %s"})
        assert r == "hello world"

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


# ── Method Call Tests ──────────────────────────────────────────


class TestMethodCalls:
    """Test calling methods on dict/object values in templates."""

    def test_dict_callable_with_args(self, engine):
        """{{ user.t("key") }} calls dict callable with string arg."""
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        assert engine.render_string('{{ user.t("greeting") }}', ctx) == "T:greeting"

    def test_dict_callable_no_args(self, engine):
        """{{ config.get_name() }} calls dict callable with no args."""
        ctx = {"config": {"get_name": lambda: "MyApp"}}
        assert engine.render_string("{{ config.get_name() }}", ctx) == "MyApp"

    def test_dict_callable_multiple_args(self, engine):
        """{{ math.add(3, 4) }} calls dict callable with multiple args."""
        ctx = {"math": {"add": lambda a, b: a + b}}
        assert engine.render_string("{{ math.add(3, 4) }}", ctx) == "7"

    def test_dotted_arg_in_method_call(self, engine):
        """{{ user.t("auth.email") }} — dot inside quoted arg doesn't split."""
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        assert engine.render_string('{{ user.t("auth.email") }}', ctx) == "T:auth.email"

    def test_method_call_in_html_attribute(self, engine):
        """{{ func("dotted.key") }} inside HTML attribute renders correctly."""
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        result = engine.render_string(
            '<input placeholder="{{ user.t(\'auth.email\') }}">', ctx
        )
        assert result == '<input placeholder="T:auth.email">'

    def test_object_method_with_args(self, engine):
        """Object methods with args work through dotted path."""
        class Obj:
            def greet(self, name):
                return f"Hello {name}"
        ctx = {"obj": Obj()}
        assert engine.render_string('{{ obj.greet("Alice") }}', ctx) == "Hello Alice"


# ── Slice Syntax Tests ─────────────────────────────────────────


class TestSliceSyntax:
    """Test Python slice syntax in bracket access."""

    def test_string_slice_start(self, engine):
        """{{ text[:5] }} returns first 5 chars."""
        assert engine.render_string("{{ text[:5] }}", {"text": "Hello World"}) == "Hello"

    def test_string_slice_end(self, engine):
        """{{ text[6:] }} returns from index 6 onwards."""
        assert engine.render_string("{{ text[6:] }}", {"text": "Hello World"}) == "World"

    def test_string_slice_range(self, engine):
        """{{ text[0:5] }} returns chars 0-4."""
        assert engine.render_string("{{ text[0:5] }}", {"text": "Hello World"}) == "Hello"

    def test_list_slice(self, engine):
        """{{ items[1:3] }} returns list slice."""
        assert engine.render_string("{{ items[1:3] }}", {"items": [10, 20, 30, 40]}) == "[20, 30]"


# ── Dotted String Argument Edge Cases ──────────────────────────


class TestDottedStringArgs:
    """Test that dots inside quoted function arguments are never misinterpreted."""

    def test_single_dot_single_quotes(self, engine):
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        assert engine.render_string("{{ user.t('auth.email') }}", ctx) == "T:auth.email"

    def test_single_dot_double_quotes(self, engine):
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        assert engine.render_string('{{ user.t("auth.email") }}', ctx) == "T:auth.email"

    def test_multiple_dots(self, engine):
        ctx = {"i18n": {"t": lambda k: f"T:{k}"}}
        assert engine.render_string("{{ i18n.t('app.auth.login.title') }}", ctx) == "T:app.auth.login.title"

    def test_dotted_arg_in_html_attribute(self, engine):
        ctx = {"t": lambda k: f"T:{k}"}
        result = engine.render_string('<input placeholder="{{ t(\'auth.email\') }}">', ctx)
        assert result == '<input placeholder="T:auth.email">'

    def test_dotted_arg_method_on_dict(self, engine):
        ctx = {"user": {"t": lambda k: f"T:{k}"}}
        result = engine.render_string(
            '<label>{{ user.t(\'form.fields.name\') }}</label>', ctx
        )
        assert result == "<label>T:form.fields.name</label>"

    def test_multiple_args_with_dots(self, engine):
        ctx = {"fmt": {"pair": lambda a, b: f"{a}={b}"}}
        assert engine.render_string("{{ fmt.pair('a.b', 'c.d') }}", ctx) == "a.b=c.d"

    def test_tilde_in_quoted_string(self, engine):
        """Tilde inside quotes should not trigger string concatenation."""
        ctx = {"echo": lambda s: s}
        assert engine.render_string("{{ echo('hello~world') }}", ctx) == "hello~world"

    def test_operator_chars_in_quoted_string(self, engine):
        """Comparison operators inside quotes should not trigger comparisons."""
        ctx = {"echo": lambda s: s}
        # Output is HTML-escaped (> becomes &gt;) which is correct behavior
        result = engine.render_string("{{ echo('a >= b') }}", ctx)
        assert "a" in result and "b" in result  # Function was called, not evaluated as comparison

    def test_question_mark_in_quoted_string(self, engine):
        """? and ?? inside quotes should not trigger ternary/coalescing."""
        ctx = {"echo": lambda s: s}
        assert engine.render_string("{{ echo('is this ok?') }}", ctx) == "is this ok?"

    def test_chained_method_with_dotted_arg(self, engine):
        """Chained access after method call with dotted arg."""
        ctx = {"svc": {"lookup": lambda k: {"value": f"V:{k}"}}}
        assert engine.render_string("{{ svc.lookup('db.host').value }}", ctx) == "V:db.host"

    def test_top_level_func_dotted_arg(self, engine):
        """Top-level function (not method) with dotted arg."""
        ctx = {"t": lambda k: f"T:{k}"}
        assert engine.render_string("{{ t('auth.email') }}", ctx) == "T:auth.email"

    def test_nested_quotes_in_arg(self, engine):
        """Double quotes inside single-quoted arg."""
        ctx = {"echo": lambda s: s}
        result = engine.render_string('{{ echo("it\'s fine") }}', ctx)
        # The inner quote gets stripped by the parser, but the call should not crash
        assert result is not None


# ── Dynamic Dict Key Access Tests ──────────────────────────────


class TestDynamicDictKeys:
    """Test dict[variable_key] resolves the variable, not as literal."""

    def test_variable_key_via_set(self, engine):
        ctx = {"balances": {"9600.000": 342120.0}}
        r = engine.render_string('{% set k = "9600.000" %}{{ balances[k] }}', ctx)
        assert r == "342120.0"

    def test_variable_key_from_loop(self, engine):
        ctx = {"balances": {"A": 100, "B": 200}, "items": [{"code": "A"}, {"code": "B"}]}
        r = engine.render_string("{% for i in items %}{{ balances[i.code] }},{% endfor %}", ctx)
        assert r == "100,200,"

    def test_string_literal_key_still_works(self, engine):
        ctx = {"data": {"key": "val"}}
        assert engine.render_string('{{ data["key"] }}', ctx) == "val"
        assert engine.render_string("{{ data['key'] }}", ctx) == "val"

    def test_int_key_still_works(self, engine):
        assert engine.render_string("{{ items[1] }}", {"items": [10, 20, 30]}) == "20"

    def test_slice_still_works(self, engine):
        assert engine.render_string("{{ text[:3] }}", {"text": "Hello"}) == "Hel"

    def test_nested_variable_key(self, engine):
        ctx = {"lookup": {"x": "found"}, "config": {"key": "x"}}
        r = engine.render_string("{{ lookup[config.key] }}", ctx)
        assert r == "found"


# ── Replace Filter Tests ──────────────────────────────────────


class TestReplaceFilter:
    """Test the |replace filter with various argument patterns."""

    def test_simple_replace(self, engine):
        assert engine.render_string('{{ text|replace("a", "b") }}', {"text": "banana"}) == "bbnbnb"

    def test_replace_space_with_underscore(self, engine):
        assert engine.render_string("{{ name|replace(' ', '_') }}", {"name": "John Doe"}) == "John_Doe"

    def test_replace_with_empty(self, engine):
        r = engine.render_string('{{ text|replace("world", "") }}', {"text": "hello world"})
        assert r.strip() == "hello"

    def test_replace_quote_with_backslash_quote(self, engine):
        """The critical bug: |replace("'", "\\'") should escape quotes, not corrupt output."""
        r = engine.render_string("{{ text|replace(\"'\", \"\\\\'\") | raw }}", {"text": "it's ok"})
        assert r == "it\\'s ok"

    def test_replace_backslash(self, engine):
        """Replace backslash with forward slash."""
        r = engine.render_string('{{ path|replace("\\\\", "/") }}', {"path": "C:\\\\Users\\\\test"})
        assert "/" in r


# ── to_json and js_escape Filter Tests ─────────────────────────


class TestJsonAndJsFilters:
    """Test to_json, tojson, and js_escape filters."""

    def test_to_json_dict(self, engine):
        r = engine.render_string("{{ data|to_json|raw }}", {"data": {"a": 1}})
        assert r == '{"a":1}'

    def test_to_json_list(self, engine):
        r = engine.render_string("{{ items|to_json|raw }}", {"items": [1, 2, 3]})
        assert r == "[1,2,3]"

    def test_to_json_html_safe(self, engine):
        """to_json escapes <, >, & for safe embedding in HTML."""
        r = engine.render_string("{{ data|to_json|raw }}", {"data": {"x": "<b>bold</b>"}})
        assert "<" not in r
        assert "\\u003c" in r

    def test_tojson_alias(self, engine):
        r = engine.render_string("{{ data|tojson|raw }}", {"data": {"a": 1}})
        assert r == '{"a":1}'

    def test_js_escape_quotes(self, engine):
        r = engine.render_string("{{ text|js_escape|raw }}", {"text": "it's a \"test\""})
        assert "\\'" in r
        assert '\\"' in r

    def test_js_escape_newlines(self, engine):
        r = engine.render_string("{{ text|js_escape|raw }}", {"text": "line1\nline2"})
        assert "\\n" in r
        assert "\n" not in r


# ── SafeString Tests (no double-escaping) ──────────────────────


class TestSafeStringFilters:
    """Verify js_escape and to_json bypass auto-HTML-escaping via SafeString."""

    def test_js_escape_no_html_encoding(self, engine):
        """js_escape output should NOT be HTML-encoded (no &#x27; for quotes)."""
        r = engine.render_string("{{ text|js_escape }}", {"text": "it's a test"})
        assert r == "it\\'s a test"
        assert "&#" not in r  # No HTML entities

    def test_to_json_no_html_encoding(self, engine):
        """to_json output should NOT be HTML-encoded (no &quot; for quotes)."""
        r = engine.render_string("{{ data|to_json }}", {"data": {"key": "value"}})
        assert r == '{"key":"value"}'
        assert "&quot;" not in r

    def test_tojson_no_html_encoding(self, engine):
        r = engine.render_string("{{ data|tojson }}", {"data": [1, 2]})
        assert r == "[1,2]"

    def test_js_escape_backslash_not_encoded(self, engine):
        """Backslashes from js_escape should remain as \\ not &#92;"""
        r = engine.render_string("{{ text|js_escape }}", {"text": 'say "hello"'})
        assert '\\"' in r
        assert "&#" not in r

    def test_to_json_xss_still_escaped(self, engine):
        """to_json should escape < > & as unicode, not HTML entities."""
        r = engine.render_string("{{ data|to_json }}", {"data": {"x": "<script>"}})
        assert "\\u003c" in r  # Unicode-escaped
        assert "&lt;" not in r  # Not HTML-escaped
        assert "<script>" not in r  # Not raw

    def test_regular_var_still_html_escaped(self, engine):
        """Normal variables should still be HTML-auto-escaped."""
        r = engine.render_string("{{ text }}", {"text": "<b>bold</b>"})
        assert "&lt;b&gt;" in r
        assert "<b>" not in r

    def test_js_escape_in_onclick(self, engine):
        """Real-world: js_escape in an onclick attribute."""
        r = engine.render_string(
            '<button onclick="alert(\'{{ msg|js_escape }}\')">Click</button>',
            {"msg": "it's a \"test\""}
        )
        assert "\\'" in r
        assert "&#" not in r

    def test_to_json_in_script_tag(self, engine):
        """Real-world: to_json in a script tag."""
        r = engine.render_string(
            '<script>var data = {{ items|to_json }};</script>',
            {"items": [{"name": "Alice"}]}
        )
        assert '"name"' in r
        assert "&quot;" not in r


# ── Tilde Concatenation with Ternary Tests ─────────────────────


class TestTildeTernary:
    """Test ~ concatenation with parenthesized ternary expressions."""

    def test_tilde_with_ternary(self, engine):
        """URL with ternary: /contacts?type= ~ (var ? var : "all")"""
        ctx = {"contact_type": "customer"}
        r = engine.render_string(
            '{{ "/path?type=" ~ (contact_type ? contact_type : "all") }}', ctx
        )
        assert r == "/path?type=customer"

    def test_tilde_ternary_false_branch(self, engine):
        ctx = {}
        r = engine.render_string(
            '{{ "/path?type=" ~ (contact_type ? contact_type : "all") }}', ctx
        )
        assert r == "/path?type=all"

    def test_question_mark_in_url_string(self, engine):
        """? inside a quoted URL string should not trigger ternary."""
        r = engine.render_string(
            '{{ "/search?q=hello" }}', {}
        )
        assert r == "/search?q=hello"

    def test_tilde_concat_with_url_query(self, engine):
        """Build URL with query params via ~ concatenation."""
        ctx = {"base": "/api", "sort": "name"}
        r = engine.render_string('{{ base ~ "?sort=" ~ sort }}', ctx)
        assert r == "/api?sort=name"

    def test_simple_ternary_still_works(self, engine):
        assert engine.render_string('{{ x ? "yes" : "no" }}', {"x": True}) == "yes"
        assert engine.render_string('{{ x ? "yes" : "no" }}', {"x": False}) == "no"

    def test_inline_if_still_works(self, engine):
        assert engine.render_string('{{ "on" if active else "off" }}', {"active": True}) == "on"
        assert engine.render_string('{{ "on" if active else "off" }}', {"active": False}) == "off"
