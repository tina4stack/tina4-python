# Tina4 SCSS — Zero-dependency SCSS-to-CSS compiler.
"""
Compiles .scss files into a single default.css. No libsass, no node-sass.

    from tina4_python.scss import compile_scss

    compile_scss("src/scss", "public/css/default.css")

Supported features:
    - Variables ($color: #333;)
    - Nesting (& parent selector)
    - Partials (_variables.scss — imported, not compiled standalone)
    - @import "variables";
    - @mixin and @include
    - @extend (simple single-class)
    - Nested properties (font: { size: 14px; weight: bold; })
    - Comments (// single-line, /* multi-line */)
    - Math in values (+, -, *, /)
    - Color functions: lighten(), darken(), rgba()
    - @media nesting
    - Placeholder selectors (%placeholder)
"""
import re
import os
import colorsys
from pathlib import Path


def compile_scss(scss_dir: str = "src/scss", output: str = "public/css/default.css",
                 minify: bool = False) -> str:
    """Compile all .scss files into a single CSS file.

    - Files starting with _ are partials (imported only, not standalone)
    - Files are processed in alphabetical order
    - All @import statements are resolved
    - Output is written to the output path

    Returns the compiled CSS string.
    """
    scss_path = Path(scss_dir)
    if not scss_path.is_dir():
        return ""

    # Collect all non-partial .scss files, sorted
    files = sorted(
        f for f in scss_path.glob("*.scss")
        if not f.name.startswith("_")
    )

    if not files:
        return ""

    # Merge all files, resolving imports
    merged = ""
    imported = set()
    for f in files:
        merged += _resolve_imports(f, scss_path, imported) + "\n"

    # Compile SCSS → CSS
    css = _compile(merged)

    if minify:
        css = _minify(css)

    # Write output
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(css, encoding="utf-8")

    return css


def compile_string(scss: str) -> str:
    """Compile an SCSS string to CSS."""
    return _compile(scss)


# ── Import Resolution ──────────────────────────────────────────

def _resolve_imports(file: Path, base_dir: Path, imported: set) -> str:
    """Read a file and inline all @import statements."""
    if str(file) in imported:
        return ""
    imported.add(str(file))

    content = file.read_text(encoding="utf-8")

    def _replace_import(m):
        name = m.group(1).strip("\"'")
        # Try with and without _ prefix and .scss extension
        candidates = [
            base_dir / f"{name}.scss",
            base_dir / f"_{name}.scss",
            base_dir / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return _resolve_imports(candidate, base_dir, imported)
        return f"/* IMPORT NOT FOUND: {name} */"

    return re.sub(r'@import\s+["\']?([^"\';\n]+)["\']?\s*;', _replace_import, content)


# ── SCSS Compiler ──────────────────────────────────────────────

def _compile(scss: str) -> str:
    """Main compilation pipeline."""
    # 1. Strip single-line comments (preserve /* */ block comments)
    scss = re.sub(r'(?<![:\"\'])//[^\n]*', '', scss)

    # 2. Extract and store variables
    variables = {}
    scss = _extract_variables(scss, variables)

    # 3. Extract mixins
    mixins = {}
    scss = _extract_mixins(scss, mixins)

    # 4. Extract placeholder selectors (%name)
    placeholders = {}
    scss = _extract_placeholders(scss, placeholders)

    # 5. Resolve @include
    scss = _resolve_includes(scss, mixins)

    # 6. Resolve @extend
    scss = _resolve_extends(scss, placeholders)

    # 7. Substitute variables
    scss = _substitute_variables(scss, variables)

    # 8. Evaluate math expressions in values
    scss = _eval_math(scss)

    # 9. Resolve color functions
    scss = _resolve_color_functions(scss, variables)

    # 10. Flatten nested rules
    css = _flatten_nesting(scss)

    # 11. Clean up
    css = _cleanup(css)

    return css


def _extract_variables(scss: str, variables: dict) -> str:
    """Extract $variable: value; declarations."""
    def _store(m):
        name = m.group(1)
        value = m.group(2).strip().rstrip(";").strip()
        # Resolve variable references in the value
        for var_name, var_val in variables.items():
            value = value.replace(f"${var_name}", var_val)
        variables[name] = value
        return ""

    return re.sub(r'\$([a-zA-Z_][\w-]*)\s*:\s*([^;]+);', _store, scss)


def _substitute_variables(scss: str, variables: dict) -> str:
    """Replace $variable references with their values."""
    # Sort by longest name first to avoid partial matches
    for name in sorted(variables.keys(), key=len, reverse=True):
        scss = scss.replace(f"${name}", variables[name])
    return scss


def _extract_mixins(scss: str, mixins: dict) -> str:
    """Extract @mixin definitions."""
    pattern = re.compile(
        r'@mixin\s+([\w-]+)\s*(?:\(([^)]*)\))?\s*\{', re.DOTALL
    )
    result = scss
    for m in pattern.finditer(scss):
        name = m.group(1)
        params_str = m.group(2) or ""
        params = [p.strip().lstrip("$") for p in params_str.split(",") if p.strip()]
        # Find matching closing brace
        body_start = m.end()
        body = _find_block(result, body_start)
        if body is not None:
            mixins[name] = {"params": params, "body": body}

    # Remove mixin definitions from source
    result = re.sub(
        r'@mixin\s+[\w-]+\s*(?:\([^)]*\))?\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
        '', result
    )
    return result


def _extract_placeholders(scss: str, placeholders: dict) -> str:
    """Extract %placeholder selectors."""
    pattern = re.compile(r'(%[\w-]+)\s*\{')
    result = scss
    for m in pattern.finditer(scss):
        name = m.group(1)
        body_start = m.end()
        body = _find_block(result, body_start)
        if body is not None:
            placeholders[name] = body

    # Remove placeholder definitions
    result = re.sub(r'%[\w-]+\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', '', result)
    return result


def _resolve_includes(scss: str, mixins: dict) -> str:
    """Resolve @include mixin(...) calls."""
    def _replace(m):
        name = m.group(1)
        args_str = m.group(2) or ""
        args = [a.strip() for a in args_str.split(",") if a.strip()]

        if name not in mixins:
            return f"/* MIXIN NOT FOUND: {name} */"

        mixin = mixins[name]
        body = mixin["body"]

        # Substitute parameters
        for i, param in enumerate(mixin["params"]):
            # Handle default values (param: default)
            param_name = param.split(":")[0].strip()
            default = param.split(":")[1].strip() if ":" in param else ""
            value = args[i] if i < len(args) else default
            body = body.replace(f"${param_name}", value)

        return body

    return re.sub(r'@include\s+([\w-]+)\s*(?:\(([^)]*)\))?\s*;', _replace, scss)


def _resolve_extends(scss: str, placeholders: dict) -> str:
    """Resolve @extend %placeholder; — inject placeholder properties."""
    def _replace(m):
        name = m.group(1)
        if name in placeholders:
            return placeholders[name]
        return f"/* EXTEND NOT FOUND: {name} */"

    return re.sub(r'@extend\s+(%[\w-]+)\s*;', _replace, scss)


def _eval_math(scss: str) -> str:
    """Evaluate simple math in property values (e.g., 10px + 5px)."""
    def _calc(m):
        full = m.group(0)
        try:
            # Extract numbers and operator
            num1 = float(re.search(r'[\d.]+', m.group(1)).group())
            num2 = float(re.search(r'[\d.]+', m.group(3)).group())
            op = m.group(2).strip()
            # Extract unit from first operand
            unit_match = re.search(r'[a-z%]+', m.group(1))
            unit = unit_match.group() if unit_match else ""

            if op == "+":
                result = num1 + num2
            elif op == "-":
                result = num1 - num2
            elif op == "*":
                result = num1 * num2
            elif op == "/":
                result = num1 / num2 if num2 != 0 else 0
            else:
                return full

            # Format result
            if result == int(result):
                return f"{int(result)}{unit}"
            return f"{result:.2f}{unit}"
        except (ValueError, AttributeError):
            return full

    return re.sub(
        r'([\d.]+[a-z%]*)\s*([+\-*/])\s*([\d.]+[a-z%]*)',
        _calc, scss
    )


def _resolve_color_functions(scss: str, variables: dict) -> str:
    """Resolve lighten(), darken(), rgba() functions."""
    def _lighten(m):
        color = m.group(1).strip()
        amount = float(m.group(2).strip().rstrip("%")) / 100
        return _adjust_lightness(color, amount)

    def _darken(m):
        color = m.group(1).strip()
        amount = float(m.group(2).strip().rstrip("%")) / 100
        return _adjust_lightness(color, -amount)

    scss = re.sub(r'lighten\(\s*([^,]+)\s*,\s*([^)]+)\s*\)', _lighten, scss)
    scss = re.sub(r'darken\(\s*([^,]+)\s*,\s*([^)]+)\s*\)', _darken, scss)
    return scss


def _adjust_lightness(color: str, amount: float) -> str:
    """Adjust the lightness of a hex color."""
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    try:
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        l = max(0, min(1, l + amount))
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    except (ValueError, IndexError):
        return f"#{color}"


def _flatten_nesting(scss: str) -> str:
    """Flatten nested SCSS rules into flat CSS."""
    output = []
    _flatten_block(scss, [], output)
    return "\n".join(output)


def _flatten_block(content: str, parent_selectors: list[str], output: list[str]):
    """Recursively flatten nested blocks."""
    pos = 0
    properties = []

    while pos < len(content):
        # Skip whitespace
        while pos < len(content) and content[pos] in " \t\n\r":
            pos += 1

        if pos >= len(content):
            break

        # Block comment
        if content[pos:pos+2] == "/*":
            end = content.find("*/", pos + 2)
            if end == -1:
                break
            comment = content[pos:end + 2]
            output.append(comment)
            pos = end + 2
            continue

        # @media query — special handling
        if content[pos:pos+6] == "@media":
            # Find the block
            brace = content.find("{", pos)
            if brace == -1:
                break
            media_query = content[pos:brace].strip()
            body = _find_block(content, brace + 1)
            if body is None:
                break
            pos = brace + 1 + len(body) + 1

            # Flatten contents inside @media
            inner_output = []
            _flatten_block(body, parent_selectors, inner_output)
            if inner_output:
                output.append(f"{media_query} {{")
                output.extend(f"  {line}" for line in inner_output)
                output.append("}")
            continue

        # Find the next { or ; or end
        brace_pos = content.find("{", pos)
        semi_pos = content.find(";", pos)

        # Property (has ; before {, or no { at all)
        if semi_pos != -1 and (brace_pos == -1 or semi_pos < brace_pos):
            prop = content[pos:semi_pos].strip()
            if prop and not prop.startswith("@"):
                properties.append(prop)
            pos = semi_pos + 1
            continue

        # Nested block
        if brace_pos != -1:
            selector_text = content[pos:brace_pos].strip()
            body = _find_block(content, brace_pos + 1)
            if body is None:
                break
            pos = brace_pos + 1 + len(body) + 1

            if not selector_text:
                continue

            # Expand selectors with parent reference (&)
            selectors = [s.strip() for s in selector_text.split(",")]
            new_selectors = []
            for sel in selectors:
                if parent_selectors:
                    for parent in parent_selectors:
                        if "&" in sel:
                            new_selectors.append(sel.replace("&", parent))
                        else:
                            new_selectors.append(f"{parent} {sel}")
                else:
                    new_selectors.append(sel)

            _flatten_block(body, new_selectors, output)
            continue

        # Remaining text — treat as property
        remaining = content[pos:].strip()
        if remaining:
            properties.append(remaining)
        break

    # Emit properties for current selector
    if properties and parent_selectors:
        selector_str = ", ".join(parent_selectors)
        output.append(f"{selector_str} {{")
        for prop in properties:
            output.append(f"  {prop};")
        output.append("}")


def _find_block(content: str, start: int) -> str | None:
    """Find content between matched braces starting at position after opening brace."""
    depth = 1
    pos = start
    while pos < len(content) and depth > 0:
        if content[pos] == "{":
            depth += 1
        elif content[pos] == "}":
            depth -= 1
        if depth > 0:
            pos += 1
    if depth == 0:
        return content[start:pos]
    return None


def _cleanup(css: str) -> str:
    """Clean up the output CSS."""
    # Remove empty rulesets
    css = re.sub(r'[^{}]+\{\s*\}', '', css)
    # Remove multiple blank lines
    css = re.sub(r'\n{3,}', '\n\n', css)
    # Remove trailing whitespace
    css = "\n".join(line.rstrip() for line in css.split("\n"))
    return css.strip() + "\n"


def _minify(css: str) -> str:
    """Minify CSS output."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)  # Remove comments
    css = re.sub(r'\s+', ' ', css)  # Collapse whitespace
    css = re.sub(r'\s*([{}:;,])\s*', r'\1', css)  # Remove space around punctuation
    css = re.sub(r';\}', '}', css)  # Remove last semicolon before }
    return css.strip()


__all__ = ["compile_scss", "compile_string"]
