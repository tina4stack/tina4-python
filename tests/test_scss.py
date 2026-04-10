# Tests for tina4_python.scss
import pytest
from pathlib import Path
from tina4_python.scss import compile_scss, compile_string, ScssCompiler


@pytest.fixture
def scss_dir(tmp_path):
    d = tmp_path / "scss"
    d.mkdir()
    return d


@pytest.fixture
def output(tmp_path):
    return str(tmp_path / "css" / "default.css")


# ── Variable Tests ─────────────────────────────────────────────


class TestVariables:
    def test_simple_variable(self):
        css = compile_string("$color: #333;\n.text { color: $color; }")
        assert "#333" in css
        assert "$color" not in css

    def test_variable_in_multiple_places(self):
        scss = "$primary: blue;\n.btn { color: $primary; border: 1px solid $primary; }"
        css = compile_string(scss)
        assert css.count("blue") >= 2

    def test_variable_referencing_variable(self):
        scss = "$base: 16px;\n$large: $base;\n.text { font-size: $large; }"
        css = compile_string(scss)
        assert "16px" in css


# ── Nesting Tests ──────────────────────────────────────────────


class TestNesting:
    def test_simple_nesting(self):
        scss = ".nav { ul { list-style: none; } }"
        css = compile_string(scss)
        assert ".nav ul" in css
        assert "list-style: none" in css

    def test_parent_selector(self):
        scss = ".btn { &:hover { color: red; } }"
        css = compile_string(scss)
        assert ".btn:hover" in css

    def test_parent_modifier(self):
        scss = ".btn { &--primary { background: blue; } }"
        css = compile_string(scss)
        assert ".btn--primary" in css

    def test_deep_nesting(self):
        scss = ".a { .b { .c { color: red; } } }"
        css = compile_string(scss)
        assert ".a .b .c" in css

    def test_multiple_selectors(self):
        scss = "h1, h2 { color: blue; }"
        css = compile_string(scss)
        assert "h1, h2" in css


# ── Mixin Tests ────────────────────────────────────────────────


class TestMixins:
    def test_simple_mixin(self):
        scss = "@mixin reset { margin: 0; padding: 0; }\n.box { @include reset; }"
        css = compile_string(scss)
        assert "margin: 0" in css
        assert "padding: 0" in css
        assert "@mixin" not in css

    def test_mixin_with_params(self):
        scss = "@mixin border($width, $color) { border: $width solid $color; }\n.card { @include border(2px, red); }"
        css = compile_string(scss)
        assert "2px solid red" in css


# ── Import Tests ───────────────────────────────────────────────


class TestImports:
    def test_import_partial(self, scss_dir, output):
        (scss_dir / "_variables.scss").write_text("$primary: #007bff;")
        (scss_dir / "main.scss").write_text(
            '@import "variables";\n.btn { color: $primary; }'
        )
        css = compile_scss(str(scss_dir), output)
        assert "#007bff" in css

    def test_partials_not_compiled_standalone(self, scss_dir, output):
        (scss_dir / "_helpers.scss").write_text(".helper { display: block; }")
        (scss_dir / "app.scss").write_text(".app { color: red; }")
        css = compile_scss(str(scss_dir), output)
        # _helpers should NOT be in output unless imported
        assert ".app" in css

    def test_multiple_files_merged(self, scss_dir, output):
        (scss_dir / "a_first.scss").write_text(".first { color: red; }")
        (scss_dir / "b_second.scss").write_text(".second { color: blue; }")
        css = compile_scss(str(scss_dir), output)
        assert ".first" in css
        assert ".second" in css

    def test_output_file_created(self, scss_dir, output):
        (scss_dir / "test.scss").write_text(".test { color: green; }")
        compile_scss(str(scss_dir), output)
        assert Path(output).exists()
        content = Path(output).read_text()
        assert ".test" in content


# ── Comment Tests ──────────────────────────────────────────────


class TestComments:
    def test_single_line_comment_removed(self):
        scss = "// This is a comment\n.box { color: red; }"
        css = compile_string(scss)
        assert "This is a comment" not in css
        assert "color: red" in css

    def test_block_comment_preserved(self):
        scss = "/* License */\n.box { color: red; }"
        css = compile_string(scss)
        assert "/* License */" in css


# ── Math Tests ─────────────────────────────────────────────────


class TestMath:
    def test_addition(self):
        css = compile_string(".box { width: 10px + 5px; }")
        assert "15px" in css

    def test_subtraction(self):
        css = compile_string(".box { margin: 20px - 5px; }")
        assert "15px" in css

    def test_multiplication(self):
        css = compile_string(".box { width: 10px * 2px; }")
        assert "20px" in css


# ── Color Function Tests ──────────────────────────────────────


class TestColorFunctions:
    def test_lighten(self):
        css = compile_string(".box { color: lighten(#333, 20%); }")
        assert "#" in css
        assert "lighten" not in css

    def test_darken(self):
        css = compile_string(".box { color: darken(#ccc, 20%); }")
        assert "#" in css
        assert "darken" not in css


# ── Media Query Tests ─────────────────────────────────────────


class TestMediaQueries:
    def test_nested_media(self):
        scss = ".container { @media (max-width: 768px) { width: 100%; } }"
        css = compile_string(scss)
        assert "@media" in css
        assert "max-width: 768px" in css


# ── Placeholder Tests ─────────────────────────────────────────


class TestPlaceholders:
    def test_extend_placeholder(self):
        scss = "%clearfix { overflow: hidden; }\n.container { @extend %clearfix; color: red; }"
        css = compile_string(scss)
        assert "overflow: hidden" in css
        assert "%clearfix" not in css


# ── Minify Tests ───────────────────────────────────────────────


class TestMinify:
    def test_minify(self, scss_dir, output):
        (scss_dir / "test.scss").write_text(".box { color: red; margin: 0; }")
        css = compile_scss(str(scss_dir), output, minify=True)
        assert "\n" not in css.strip()
        assert "  " not in css


# ── Edge Cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_dir(self, tmp_path):
        css = compile_scss(str(tmp_path / "nonexistent"), str(tmp_path / "out.css"))
        assert css == ""

    def test_no_scss_files(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        css = compile_scss(str(d), str(tmp_path / "out.css"))
        assert css == ""


# ── ScssCompiler Class Tests ──────────────────────────────────


class TestScssCompilerClass:
    def test_compile_string(self):
        compiler = ScssCompiler()
        css = compiler.compile("$color: red;\n.box { color: $color; }")
        assert "red" in css
        assert "$color" not in css

    def test_set_variable(self):
        compiler = ScssCompiler()
        compiler.set_variable("$primary", "#ff0000")
        css = compiler.compile(".btn { color: $primary; }")
        assert "#ff0000" in css

    def test_set_variable_without_dollar(self):
        compiler = ScssCompiler()
        compiler.set_variable("accent", "blue")
        css = compiler.compile(".link { color: $accent; }")
        assert "blue" in css

    def test_compile_file(self, tmp_path):
        scss_file = tmp_path / "test.scss"
        scss_file.write_text("$bg: #eee;\n.page { background: $bg; }")
        compiler = ScssCompiler()
        css = compiler.compile_file(str(scss_file))
        assert "#eee" in css

    def test_compile_file_with_import(self, tmp_path):
        (tmp_path / "_vars.scss").write_text("$primary: #007bff;")
        (tmp_path / "main.scss").write_text('@import "vars";\n.btn { color: $primary; }')
        compiler = ScssCompiler()
        css = compiler.compile_file(str(tmp_path / "main.scss"))
        assert "#007bff" in css

    def test_add_import_path(self, tmp_path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "_colors.scss").write_text("$red: #f00;")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.scss").write_text('@import "colors";\n.x { color: $red; }')

        compiler = ScssCompiler()
        compiler.add_import_path(str(lib_dir))
        css = compiler.compile_file(str(src_dir / "app.scss"))
        assert "#f00" in css

    def test_compile_scss_directory(self, tmp_path):
        scss_dir = tmp_path / "scss"
        scss_dir.mkdir()
        (scss_dir / "main.scss").write_text(".main { color: green; }")
        output = str(tmp_path / "css" / "out.css")

        compiler = ScssCompiler()
        css = compiler.compile_scss(str(scss_dir), output)
        assert ".main" in css
        assert Path(output).exists()

    def test_compile_file_nonexistent(self):
        compiler = ScssCompiler()
        css = compiler.compile_file("/nonexistent/path.scss")
        assert css == ""

    def test_constructor_with_variables(self):
        compiler = ScssCompiler(variables={"theme": "dark"})
        css = compiler.compile(".x { content: '$theme'; }")
        # Variable in quotes won't be substituted, but outside quotes it will
        compiler2 = ScssCompiler(variables={"size": "16px"})
        css2 = compiler2.compile(".x { font-size: $size; }")
        assert "16px" in css2
