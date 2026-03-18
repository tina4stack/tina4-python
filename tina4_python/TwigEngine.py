#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
"""Lightweight Twig-compatible template engine for Tina4.

Zero external dependencies. Supports the Twig/Jinja2 subset used by Tina4:

- Variable interpolation: {{ var }}, {{ var.attr }}, {{ var['key'] }}
- Template inheritance: {% extends %}, {% block %}...{% endblock %}
- Control flow: {% if %}, {% elif %}, {% else %}, {% for %}, {% set %}
- Includes: {% include 'file.twig' %}, {% include 'file' ignore missing %}
- Macros: {% macro name(args) %}...{% endmacro %}, {% from 'file' import name %}
- Raw blocks: {% raw %}...{% endraw %}
- Comments: {# ... #}
- Filters: |safe, |default, |e, |json_encode, |replace, |title, |length, |upper, |lower, |string
- Loop vars: loop.index, loop.index0, loop.first, loop.last, loop.length
- Expressions: slice [start:end], concat ~, ternary (x if cond else y), arithmetic, comparisons
- Globals: callable functions registered as template globals
"""

__all__ = ["TwigEngine", "TemplateNotFound"]

import html as _html
import json as _json
import os
import re


class TemplateNotFound(Exception):
    """Raised when a template file cannot be found in any search path."""
    pass


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_COMMENT = "comment"
_TOKEN_RAW = "raw"
_TOKEN_TAG = "tag"
_TOKEN_VAR = "var"
_TOKEN_TEXT = "text"

# Regex to split template into tokens: comments, raw blocks, tags, variables, text
_TOKENIZE_RE = re.compile(
    r"(\{#.*?#\})"           # {# comment #}
    r"|(\{%\s*raw\s*%\}.*?\{%\s*endraw\s*%\})"  # {% raw %}...{% endraw %}
    r"|(\{%.*?%\})"          # {% tag %}
    r"|(\{\{.*?\}\})",       # {{ variable }}
    re.DOTALL,
)


def _tokenize(source):
    """Split template source into a list of (type, content) tokens."""
    tokens = []
    pos = 0
    for m in _TOKENIZE_RE.finditer(source):
        # Text before match
        if m.start() > pos:
            tokens.append((_TOKEN_TEXT, source[pos:m.start()]))
        if m.group(1):  # comment
            tokens.append((_TOKEN_COMMENT, m.group(1)))
        elif m.group(2):  # raw block
            inner = m.group(2)
            # Strip {% raw %} and {% endraw %}
            inner = re.sub(r'^\{%\s*raw\s*%\}', '', inner)
            inner = re.sub(r'\{%\s*endraw\s*%\}$', '', inner)
            tokens.append((_TOKEN_RAW, inner))
        elif m.group(3):  # tag
            tokens.append((_TOKEN_TAG, m.group(3)))
        elif m.group(4):  # variable
            tokens.append((_TOKEN_VAR, m.group(4)))
        pos = m.end()
    if pos < len(source):
        tokens.append((_TOKEN_TEXT, source[pos:]))
    return tokens


# ---------------------------------------------------------------------------
# AST Nodes
# ---------------------------------------------------------------------------

class _TextNode:
    __slots__ = ('text',)
    def __init__(self, text):
        self.text = text

class _VarNode:
    __slots__ = ('expr',)
    def __init__(self, expr):
        self.expr = expr

class _RawNode:
    __slots__ = ('text',)
    def __init__(self, text):
        self.text = text

class _IfNode:
    __slots__ = ('branches',)  # list of (condition_expr, body_nodes); last may have condition=None (else)
    def __init__(self):
        self.branches = []

class _ForNode:
    __slots__ = ('var_name', 'var_name2', 'iter_expr', 'body', 'else_body')
    def __init__(self, var_name, var_name2, iter_expr):
        self.var_name = var_name
        self.var_name2 = var_name2  # for key, value pairs
        self.iter_expr = iter_expr
        self.body = []
        self.else_body = []

class _SetNode:
    __slots__ = ('var_name', 'expr')
    def __init__(self, var_name, expr):
        self.var_name = var_name
        self.expr = expr

class _BlockNode:
    __slots__ = ('name', 'body')
    def __init__(self, name):
        self.name = name
        self.body = []

class _ExtendsNode:
    __slots__ = ('template_name',)
    def __init__(self, template_name):
        self.template_name = template_name

class _IncludeNode:
    __slots__ = ('template_name', 'ignore_missing')
    def __init__(self, template_name, ignore_missing=False):
        self.template_name = template_name
        self.ignore_missing = ignore_missing

class _MacroNode:
    __slots__ = ('name', 'args', 'body')
    def __init__(self, name, args):
        self.name = name
        self.args = args  # list of (arg_name, default_value_expr_or_None)
        self.body = []

class _ImportNode:
    __slots__ = ('template_name', 'names')  # names: list of (import_name, alias_or_None)
    def __init__(self, template_name, names):
        self.template_name = template_name
        self.names = names

class _CallMacroNode:
    __slots__ = ('name', 'args')
    def __init__(self, name, args):
        self.name = name
        self.args = args  # list of expression strings


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _strip_tag(tok):
    """Strip {% and %} from a tag token."""
    return tok[2:-2].strip()

def _strip_var(tok):
    """Strip {{ and }} from a variable token."""
    return tok[2:-2].strip()

def _extract_string(s):
    """Extract a quoted string value, handling both ' and "."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse(tokens, stop_tags=None):
    """Parse tokens into an AST node list. Returns (nodes, remaining_tokens)."""
    if stop_tags is None:
        stop_tags = set()
    nodes = []
    i = 0
    while i < len(tokens):
        ttype, tcontent = tokens[i]

        if ttype == _TOKEN_TEXT:
            nodes.append(_TextNode(tcontent))
            i += 1

        elif ttype == _TOKEN_RAW:
            nodes.append(_RawNode(tcontent))
            i += 1

        elif ttype == _TOKEN_COMMENT:
            i += 1  # skip

        elif ttype == _TOKEN_VAR:
            expr = _strip_var(tcontent)
            nodes.append(_VarNode(expr))
            i += 1

        elif ttype == _TOKEN_TAG:
            tag_content = _strip_tag(tcontent)

            # Check stop tags
            for st in stop_tags:
                if tag_content == st or tag_content.startswith(st + " ") or tag_content.startswith(st + "("):
                    return nodes, tokens[i:]

            # extends
            if tag_content.startswith("extends "):
                tpl_name = _extract_string(tag_content[8:].strip())
                nodes.append(_ExtendsNode(tpl_name))
                i += 1

            # block
            elif tag_content.startswith("block "):
                block_name = tag_content[6:].strip()
                i += 1
                body, rest = _parse(tokens[i:], {"endblock"})
                node = _BlockNode(block_name)
                node.body = body
                nodes.append(node)
                # Skip endblock
                if rest:
                    rest = rest[1:]
                i = len(tokens) - len(rest)

            # for
            elif tag_content.startswith("for "):
                parts = tag_content[4:].strip()
                m = re.match(r'(\w+)\s*,\s*(\w+)\s+in\s+(.+)', parts)
                if m:
                    var1, var2, iter_expr = m.group(1), m.group(2), m.group(3).strip()
                    node = _ForNode(var1, var2, iter_expr)
                else:
                    m = re.match(r'(\w+)\s+in\s+(.+)', parts)
                    if m:
                        var1, iter_expr = m.group(1), m.group(2).strip()
                        node = _ForNode(var1, None, iter_expr)
                    else:
                        nodes.append(_TextNode(f"<!-- parse error: {tag_content} -->"))
                        i += 1
                        continue
                i += 1
                body, rest = _parse(tokens[i:], {"endfor", "else"})
                node.body = body
                if rest and _strip_tag(rest[0][1]) == "else":
                    rest = rest[1:]
                    else_body, rest = _parse(rest, {"endfor"})
                    node.else_body = else_body
                if rest:
                    rest = rest[1:]  # skip endfor
                nodes.append(node)
                i = len(tokens) - len(rest)

            # if
            elif tag_content.startswith("if "):
                node = _IfNode()
                cond = tag_content[3:].strip()
                i += 1
                body, rest = _parse(tokens[i:], {"endif", "elif", "else"})
                node.branches.append((cond, body))
                while rest:
                    next_tag = _strip_tag(rest[0][1])
                    if next_tag == "endif":
                        rest = rest[1:]
                        break
                    elif next_tag.startswith("elif "):
                        cond = next_tag[5:].strip()
                        rest = rest[1:]
                        body, rest = _parse(rest, {"endif", "elif", "else"})
                        node.branches.append((cond, body))
                    elif next_tag == "else":
                        rest = rest[1:]
                        body, rest = _parse(rest, {"endif"})
                        node.branches.append((None, body))
                    else:
                        break
                if rest and _strip_tag(rest[0][1]) == "endif":
                    rest = rest[1:]
                nodes.append(node)
                i = len(tokens) - len(rest)

            # set
            elif tag_content.startswith("set "):
                parts = tag_content[4:].strip()
                eq_pos = parts.find("=")
                if eq_pos != -1:
                    var_name = parts[:eq_pos].strip()
                    expr = parts[eq_pos+1:].strip()
                    nodes.append(_SetNode(var_name, expr))
                i += 1

            # include
            elif tag_content.startswith("include "):
                rest_str = tag_content[8:].strip()
                ignore_missing = "ignore missing" in rest_str
                rest_str = rest_str.replace("ignore missing", "").strip()
                tpl_name = _extract_string(rest_str)
                nodes.append(_IncludeNode(tpl_name, ignore_missing))
                i += 1

            # macro
            elif tag_content.startswith("macro "):
                rest_str = tag_content[6:].strip()
                m = re.match(r'(\w+)\s*\(([^)]*)\)', rest_str)
                if m:
                    name = m.group(1)
                    args_str = m.group(2).strip()
                    args = []
                    if args_str:
                        for arg in args_str.split(","):
                            arg = arg.strip()
                            if "=" in arg:
                                aname, adefault = arg.split("=", 1)
                                args.append((aname.strip(), adefault.strip()))
                            else:
                                args.append((arg, None))
                    node = _MacroNode(name, args)
                    i += 1
                    body, rest = _parse(tokens[i:], {"endmacro"})
                    node.body = body
                    if rest:
                        rest = rest[1:]  # skip endmacro
                    nodes.append(node)
                    i = len(tokens) - len(rest)
                else:
                    i += 1

            # from ... import ...
            elif tag_content.startswith("from "):
                m = re.match(r'from\s+["\']([^"\']+)["\']\s+import\s+(.+)', tag_content)
                if m:
                    tpl_name = m.group(1)
                    imports_str = m.group(2).strip()
                    names = []
                    for part in imports_str.split(","):
                        part = part.strip()
                        if " as " in part:
                            orig, alias = part.split(" as ", 1)
                            names.append((orig.strip(), alias.strip()))
                        else:
                            names.append((part, None))
                    nodes.append(_ImportNode(tpl_name, names))
                i += 1

            else:
                # Unknown tag — pass through as text
                nodes.append(_TextNode(tcontent))
                i += 1
        else:
            i += 1

    return nodes, []


# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------

class _Undefined:
    """Represents an undefined variable (renders as empty string)."""
    def __str__(self):
        return ""
    def __bool__(self):
        return False
    def __iter__(self):
        return iter([])
    def __len__(self):
        return 0
    def __getattr__(self, name):
        return _Undefined()
    def __getitem__(self, key):
        return _Undefined()

_UNDEFINED = _Undefined()


def _eval_expr(expr, context, filters=None, globals_dict=None):
    """Evaluate a Twig expression string in the given context."""
    if filters is None:
        filters = {}
    if globals_dict is None:
        globals_dict = {}

    expr = expr.strip()
    if not expr:
        return _UNDEFINED

    # Handle filter chains: expr | filter1 | filter2(arg)
    # Need to be careful with | inside strings and parentheses
    parts = _split_filters(expr)
    if len(parts) > 1:
        value = _eval_expr(parts[0], context, filters, globals_dict)
        for filt in parts[1:]:
            value = _apply_filter(value, filt.strip(), context, filters, globals_dict)
        return value

    # Ternary: value if condition else other
    # Match "X if Y else Z" but not inside strings
    m = re.match(r'^(.+?)\s+if\s+(.+?)\s+else\s+(.+)$', expr)
    if m:
        cond_val = _eval_expr(m.group(2), context, filters, globals_dict)
        if cond_val:
            return _eval_expr(m.group(1), context, filters, globals_dict)
        else:
            return _eval_expr(m.group(3), context, filters, globals_dict)

    # String concatenation with ~
    if '~' in expr:
        parts = _split_on_tilde(expr)
        if len(parts) > 1:
            return "".join(str(_eval_expr(p, context, filters, globals_dict)) for p in parts)

    # Comparison and logical operators
    for op, py_op in [(' and ', ' and '), (' or ', ' or ')]:
        if op in expr:
            parts = expr.split(op, 1)
            left = _eval_expr(parts[0], context, filters, globals_dict)
            right = _eval_expr(parts[1], context, filters, globals_dict)
            if py_op == ' and ':
                return left and right
            else:
                return left or right

    # not operator
    if expr.startswith("not "):
        return not _eval_expr(expr[4:], context, filters, globals_dict)

    # Comparison operators
    for op in ['!=', '==', '>=', '<=', '>', '<']:
        if op in expr:
            parts = expr.split(op, 1)
            if len(parts) == 2:
                left = _eval_expr(parts[0], context, filters, globals_dict)
                right = _eval_expr(parts[1], context, filters, globals_dict)
                if op == '==':
                    return left == right
                elif op == '!=':
                    return left != right
                elif op == '>':
                    return left > right
                elif op == '<':
                    return left < right
                elif op == '>=':
                    return left >= right
                elif op == '<=':
                    return left <= right

    # 'in' operator: "x in y"
    m = re.match(r'^(.+?)\s+in\s+(.+)$', expr)
    if m:
        item = _eval_expr(m.group(1), context, filters, globals_dict)
        collection = _eval_expr(m.group(2), context, filters, globals_dict)
        try:
            return item in collection
        except TypeError:
            return False

    # 'is' tests: "x is defined", "x is not none"
    custom_tests = context.get("_twig_custom_tests", {})
    m = re.match(r'^(.+?)\s+is\s+not\s+(\w+)$', expr)
    if m:
        return not _eval_test(m.group(1), m.group(2), context, filters, globals_dict, custom_tests)
    m = re.match(r'^(.+?)\s+is\s+(\w+)$', expr)
    if m:
        return _eval_test(m.group(1), m.group(2), context, filters, globals_dict, custom_tests)

    # Arithmetic: +, -, *, /, %
    for op in ['+', '-', '*', '/', '%']:
        # Don't split on - if it's a negative number or inside brackets
        if op in expr:
            parts = _split_arithmetic(expr, op)
            if parts and len(parts) == 2:
                try:
                    left = _eval_expr(parts[0], context, filters, globals_dict)
                    right = _eval_expr(parts[1], context, filters, globals_dict)
                    if op == '+':
                        return float(left) + float(right)
                    elif op == '-':
                        return float(left) - float(right)
                    elif op == '*':
                        return float(left) * float(right)
                    elif op == '/':
                        return float(left) / float(right) if float(right) != 0 else 0
                    elif op == '%':
                        return float(left) % float(right) if float(right) != 0 else 0
                except (ValueError, TypeError):
                    pass

    # Parenthesized expression
    if expr.startswith('(') and expr.endswith(')'):
        return _eval_expr(expr[1:-1], context, filters, globals_dict)

    # String literal
    if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
        return expr[1:-1]

    # Numeric literal
    try:
        if '.' in expr:
            return float(expr)
        return int(expr)
    except ValueError:
        pass

    # Boolean / None
    if expr == 'true' or expr == 'True':
        return True
    if expr == 'false' or expr == 'False':
        return False
    if expr == 'none' or expr == 'None' or expr == 'null':
        return None

    # List literal [a, b, c]
    if expr.startswith('[') and expr.endswith(']'):
        inner = expr[1:-1].strip()
        if not inner:
            return []
        items = _split_args(inner)
        return [_eval_expr(item, context, filters, globals_dict) for item in items]

    # Dict literal {key: val}
    if expr.startswith('{') and expr.endswith('}'):
        inner = expr[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for pair in _split_args(inner):
            if ':' in pair:
                k, v = pair.split(':', 1)
                result[_eval_expr(k, context, filters, globals_dict)] = _eval_expr(v, context, filters, globals_dict)
        return result

    # Function call: name(args)
    m = re.match(r'^(\w[\w.]*)\s*\(([^)]*)\)$', expr)
    if m:
        func_name = m.group(1)
        args_str = m.group(2).strip()
        func = _resolve_var(func_name, context, globals_dict)
        if callable(func):
            if args_str:
                args = [_eval_expr(a, context, filters, globals_dict) for a in _split_args(args_str)]
                return func(*args)
            return func()
        return _UNDEFINED

    # Variable access with optional slice: var.attr['key'][0:5]
    return _resolve_var_with_slice(expr, context, globals_dict)


def _eval_test(expr, test_name, context, filters, globals_dict, custom_tests=None):
    """Evaluate an 'is' test."""
    value = _eval_expr(expr, context, filters, globals_dict)
    # Check custom tests first
    if custom_tests and test_name in custom_tests:
        return custom_tests[test_name](value)
    if test_name == "defined":
        return not isinstance(value, _Undefined)
    elif test_name == "none" or test_name == "null":
        return value is None
    elif test_name == "true":
        return value is True
    elif test_name == "false":
        return value is False
    elif test_name == "empty":
        return not value
    elif test_name == "string":
        return isinstance(value, str)
    elif test_name == "number":
        return isinstance(value, (int, float))
    elif test_name == "iterable":
        return hasattr(value, '__iter__')
    return False


def _resolve_var(name, context, globals_dict):
    """Resolve a dotted/bracketed variable name in context, then globals."""
    parts = _parse_var_path(name)
    if not parts:
        return _UNDEFINED

    # Try context first
    first = parts[0]
    if first in context:
        obj = context[first]
    elif first in globals_dict:
        obj = globals_dict[first]
    else:
        return _UNDEFINED

    for part in parts[1:]:
        obj = _access(obj, part)
        if isinstance(obj, _Undefined):
            return obj
    return obj


def _resolve_var_with_slice(expr, context, globals_dict):
    """Resolve variable with optional slice operations."""
    expr = expr.strip()

    # Handle slice: var[:200] or var[0:5]
    m = re.match(r'^(.+?)\[(\d*):(\d*)\]$', expr)
    if m:
        obj = _resolve_var(m.group(1).strip(), context, globals_dict)
        start = int(m.group(2)) if m.group(2) else None
        end = int(m.group(3)) if m.group(3) else None
        try:
            return obj[start:end]
        except (TypeError, AttributeError):
            return _UNDEFINED

    return _resolve_var(expr, context, globals_dict)


def _parse_var_path(name):
    """Parse 'a.b["c"][0]' into ['a', 'b', 'c', 0]."""
    parts = []
    current = ""
    i = 0
    while i < len(name):
        ch = name[i]
        if ch == '.':
            if current:
                parts.append(current)
                current = ""
            i += 1
        elif ch == '[':
            if current:
                parts.append(current)
                current = ""
            # Find matching ]
            j = name.index(']', i)
            key = name[i+1:j].strip()
            # String key or numeric index
            if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                parts.append(key[1:-1])
            elif key.isdigit():
                parts.append(int(key))
            else:
                parts.append(key)  # variable reference
            i = j + 1
        else:
            current += ch
            i += 1
    if current:
        parts.append(current)
    return parts


def _access(obj, key):
    """Access obj.key or obj[key], returning _UNDEFINED on failure."""
    if isinstance(obj, _Undefined):
        return _UNDEFINED
    # Numeric index
    if isinstance(key, int):
        try:
            return obj[key]
        except (IndexError, KeyError, TypeError):
            return _UNDEFINED
    # String key — try dict first, then attribute
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        return _UNDEFINED
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        pass
    try:
        return getattr(obj, key)
    except AttributeError:
        return _UNDEFINED


def _split_filters(expr):
    """Split expression on | for filter chains, respecting strings and parens."""
    parts = []
    current = ""
    depth = 0
    in_str = None
    for ch in expr:
        if in_str:
            current += ch
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
            current += ch
        elif ch in ('(', '[', '{'):
            depth += 1
            current += ch
        elif ch in (')', ']', '}'):
            depth -= 1
            current += ch
        elif ch == '|' and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def _split_on_tilde(expr):
    """Split on ~ for string concatenation, respecting strings."""
    parts = []
    current = ""
    in_str = None
    for ch in expr:
        if in_str:
            current += ch
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
            current += ch
        elif ch == '~':
            parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return parts if len(parts) > 1 else [expr]


def _split_args(s):
    """Split comma-separated arguments respecting nesting and strings."""
    args = []
    current = ""
    depth = 0
    in_str = None
    for ch in s:
        if in_str:
            current += ch
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
            current += ch
        elif ch in ('(', '[', '{'):
            depth += 1
            current += ch
        elif ch in (')', ']', '}'):
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            args.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        args.append(current.strip())
    return args


def _split_arithmetic(expr, op):
    """Split on arithmetic operator, respecting strings and brackets."""
    depth = 0
    in_str = None
    # Search from right to left for + and -, left to right for * / %
    positions = []
    for i, ch in enumerate(expr):
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch in ('(', '[', '{'):
            depth += 1
        elif ch in (')', ']', '}'):
            depth -= 1
        elif ch == op and depth == 0 and i > 0:
            positions.append(i)
    if not positions:
        return None
    # Use last position for +/-, first for */% (operator precedence)
    pos = positions[-1] if op in ('+', '-') else positions[0]
    left = expr[:pos].strip()
    right = expr[pos+1:].strip()
    if left and right:
        return [left, right]
    return None


# ---------------------------------------------------------------------------
# Built-in filters
# ---------------------------------------------------------------------------

def _apply_filter(value, filter_expr, context, filters, globals_dict):
    """Apply a filter to a value."""
    # Parse filter name and args: "replace('_', ' ')"
    m = re.match(r'(\w+)\s*\((.+)\)$', filter_expr)
    if m:
        fname = m.group(1)
        args_str = m.group(2)
        args = [_eval_expr(a, context, filters, globals_dict) for a in _split_args(args_str)]
    else:
        fname = filter_expr.strip()
        args = []

    # Check custom filters first
    if fname in filters:
        return filters[fname](value, *args)

    # Built-in filters
    if fname == "safe":
        return _SafeString(str(value)) if value is not None else _SafeString("")
    elif fname == "e" or fname == "escape":
        return _html.escape(str(value)) if value is not None else ""
    elif fname == "default":
        if value is None or isinstance(value, _Undefined) or value == "":
            return args[0] if args else ""
        return value
    elif fname == "json_encode":
        return _json.dumps(value)
    elif fname == "length":
        try:
            return len(value)
        except TypeError:
            return 0
    elif fname == "upper":
        return str(value).upper()
    elif fname == "lower":
        return str(value).lower()
    elif fname == "title":
        return str(value).title()
    elif fname == "capitalize":
        return str(value).capitalize()
    elif fname == "trim" or fname == "strip":
        return str(value).strip()
    elif fname == "replace":
        if len(args) >= 2:
            return str(value).replace(str(args[0]), str(args[1]))
        return str(value)
    elif fname == "string":
        return str(value) if value is not None else ""
    elif fname == "int":
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0
    elif fname == "float":
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    elif fname == "abs":
        try:
            return abs(value)
        except TypeError:
            return value
    elif fname == "join":
        sep = args[0] if args else ""
        try:
            return sep.join(str(x) for x in value)
        except TypeError:
            return str(value)
    elif fname == "first":
        try:
            return value[0]
        except (IndexError, TypeError, KeyError):
            return _UNDEFINED
    elif fname == "last":
        try:
            return value[-1]
        except (IndexError, TypeError, KeyError):
            return _UNDEFINED
    elif fname == "reverse":
        try:
            return list(reversed(value))
        except TypeError:
            return value
    elif fname == "sort":
        try:
            return sorted(value)
        except TypeError:
            return value
    elif fname == "keys":
        if isinstance(value, dict):
            return list(value.keys())
        return []
    elif fname == "values":
        if isinstance(value, dict):
            return list(value.values())
        return []
    elif fname == "items":
        if isinstance(value, dict):
            return list(value.items())
        return []
    elif fname == "batch":
        size = int(args[0]) if args else 1
        return [value[i:i+size] for i in range(0, len(value), size)]
    elif fname == "format":
        try:
            return str(value) % tuple(args) if args else str(value)
        except (TypeError, ValueError):
            return str(value)
    elif fname == "striptags":
        return re.sub(r'<[^>]+>', '', str(value))
    elif fname == "truncate":
        length = int(args[0]) if args else 255
        s = str(value)
        if len(s) > length:
            return s[:length] + "..."
        return s
    elif fname == "nl2br":
        return str(value).replace('\n', '<br>')
    elif fname == "raw":
        return _SafeString(str(value)) if value is not None else _SafeString("")

    # Unknown filter — return value unchanged
    return value


class _SafeString(str):
    """Marker class for strings that should not be auto-escaped."""
    pass


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class _Renderer:
    """Renders an AST node list into a string."""

    def __init__(self, engine, context, auto_escape=True):
        self.engine = engine
        self.context = dict(context)
        self.auto_escape = auto_escape
        self._macros = {}

    def render(self, nodes):
        parts = []
        extends_tpl = None
        blocks = {}

        for node in nodes:
            if isinstance(node, _ExtendsNode):
                extends_tpl = node.template_name
            elif isinstance(node, _BlockNode):
                blocks[node.name] = node.body
                if extends_tpl is None:
                    # Render block content directly if not extending
                    parts.append(self._render_nodes(node.body))
            elif isinstance(node, _MacroNode):
                self._macros[node.name] = node
                self.context[node.name] = self._make_macro_callable(node)
            elif isinstance(node, _ImportNode):
                self._handle_import(node)
            elif extends_tpl is None:
                parts.append(self._render_node(node))

        if extends_tpl:
            return self._render_inheritance(extends_tpl, blocks)

        return "".join(parts)

    def _render_inheritance(self, parent_name, child_blocks):
        """Render template with inheritance."""
        parent_source = self.engine._load_template(parent_name)
        parent_tokens = _tokenize(parent_source)
        parent_nodes, _ = _parse(parent_tokens)

        # Find parent blocks and override with child blocks
        result_nodes = self._merge_blocks(parent_nodes, child_blocks)
        return self.render(result_nodes)

    def _merge_blocks(self, nodes, child_blocks):
        """Replace block nodes with child overrides."""
        result = []
        for node in nodes:
            if isinstance(node, _BlockNode):
                if node.name in child_blocks:
                    result.append(_BlockNode.__new__(_BlockNode))
                    result[-1].name = node.name
                    result[-1].body = child_blocks[node.name]
                else:
                    result.append(node)
            elif isinstance(node, _ExtendsNode):
                result.append(node)
            else:
                result.append(node)
        return result

    def _render_nodes(self, nodes):
        return "".join(self._render_node(n) for n in nodes)

    def _render_node(self, node):
        if isinstance(node, _TextNode):
            return node.text

        elif isinstance(node, _RawNode):
            return node.text

        elif isinstance(node, _VarNode):
            value = _eval_expr(node.expr, self.context, self.engine._filters, self.engine._globals)
            if isinstance(value, _Undefined):
                return ""
            if isinstance(value, _SafeString):
                return str(value)
            s = str(value)
            if self.auto_escape and not isinstance(value, _SafeString):
                return _html.escape(s)
            return s

        elif isinstance(node, _IfNode):
            for cond, body in node.branches:
                if cond is None:  # else
                    return self._render_nodes(body)
                val = _eval_expr(cond, self.context, self.engine._filters, self.engine._globals)
                if val:
                    return self._render_nodes(body)
            return ""

        elif isinstance(node, _ForNode):
            iter_val = _eval_expr(node.iter_expr, self.context, self.engine._filters, self.engine._globals)
            if isinstance(iter_val, _Undefined) or iter_val is None:
                return self._render_nodes(node.else_body)
            try:
                items = list(iter_val)
            except TypeError:
                return self._render_nodes(node.else_body)
            if not items:
                return self._render_nodes(node.else_body)

            parts = []
            total = len(items)
            old_var = self.context.get(node.var_name)
            old_var2 = self.context.get(node.var_name2) if node.var_name2 else None
            old_loop = self.context.get("loop")

            for idx, item in enumerate(items):
                loop = {
                    "index": idx + 1,
                    "index0": idx,
                    "first": idx == 0,
                    "last": idx == total - 1,
                    "length": total,
                    "revindex": total - idx,
                    "revindex0": total - idx - 1,
                }
                self.context["loop"] = type('Loop', (), loop)()

                if node.var_name2:
                    # key, value iteration
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        self.context[node.var_name] = item[0]
                        self.context[node.var_name2] = item[1]
                    else:
                        self.context[node.var_name] = idx
                        self.context[node.var_name2] = item
                else:
                    self.context[node.var_name] = item

                parts.append(self._render_nodes(node.body))

            # Restore context
            if old_var is not None:
                self.context[node.var_name] = old_var
            elif node.var_name in self.context:
                del self.context[node.var_name]
            if node.var_name2:
                if old_var2 is not None:
                    self.context[node.var_name2] = old_var2
                elif node.var_name2 in self.context:
                    del self.context[node.var_name2]
            if old_loop is not None:
                self.context["loop"] = old_loop
            elif "loop" in self.context:
                del self.context["loop"]

            return "".join(parts)

        elif isinstance(node, _SetNode):
            value = _eval_expr(node.expr, self.context, self.engine._filters, self.engine._globals)
            self.context[node.var_name] = value
            return ""

        elif isinstance(node, _BlockNode):
            return self._render_nodes(node.body)

        elif isinstance(node, _IncludeNode):
            try:
                source = self.engine._load_template(node.template_name)
                tokens = _tokenize(source)
                nodes, _ = _parse(tokens)
                child = _Renderer(self.engine, self.context, self.auto_escape)
                child._macros = dict(self._macros)
                return child.render(nodes)
            except TemplateNotFound:
                if node.ignore_missing:
                    return ""
                raise

        elif isinstance(node, _MacroNode):
            self._macros[node.name] = node
            # Register macro as a callable in context so {{ macro_name(args) }} works
            self.context[node.name] = self._make_macro_callable(node)
            return ""

        elif isinstance(node, _ImportNode):
            self._handle_import(node)
            return ""

        elif isinstance(node, _CallMacroNode):
            return self._call_macro(node.name, node.args)

        return ""

    def _handle_import(self, node):
        """Import macros from another template."""
        try:
            source = self.engine._load_template(node.template_name)
            tokens = _tokenize(source)
            nodes, _ = _parse(tokens)
            # Extract macros from the imported template
            for n in nodes:
                if isinstance(n, _MacroNode):
                    for imp_name, alias in node.names:
                        if n.name == imp_name:
                            key = alias or imp_name
                            self._macros[key] = n
                            # Register as a callable in context
                            self.context[key] = self._make_macro_callable(n)
        except TemplateNotFound:
            pass

    def _make_macro_callable(self, macro_node):
        """Create a callable that renders a macro."""
        renderer = self
        def call_macro(*args, **kwargs):
            return renderer._call_macro_node(macro_node, args, kwargs)
        return call_macro

    def _call_macro_node(self, macro_node, args, kwargs):
        """Execute a macro with given arguments."""
        # Build macro context
        macro_ctx = dict(self.context)
        for i, (arg_name, default_expr) in enumerate(macro_node.args):
            if i < len(args):
                macro_ctx[arg_name] = args[i]
            elif arg_name in kwargs:
                macro_ctx[arg_name] = kwargs[arg_name]
            elif default_expr is not None:
                macro_ctx[arg_name] = _eval_expr(default_expr, self.context, self.engine._filters, self.engine._globals)
            else:
                macro_ctx[arg_name] = _UNDEFINED

        child = _Renderer(self.engine, macro_ctx, self.auto_escape)
        child._macros = dict(self._macros)
        return _SafeString(child._render_nodes(macro_node.body))


# ---------------------------------------------------------------------------
# Public API: TwigEngine
# ---------------------------------------------------------------------------

class TwigEngine:
    """Lightweight Twig-compatible template engine.

    Drop-in replacement for Jinja2's Environment + FileSystemLoader.

    Usage::

        engine = TwigEngine(["/path/to/templates", "/fallback/templates"])
        engine.add_filter("money", lambda v: f"{float(v):,.2f}")
        engine.add_global("APP_NAME", "My App")
        html = engine.render("pages/home.twig", {"title": "Hello"})
    """

    def __init__(self, search_paths=None):
        self._search_paths = search_paths or []
        if isinstance(self._search_paths, str):
            self._search_paths = [self._search_paths]
        self._filters = {}
        self._globals = {}
        self._tests = {}
        self._cache = {}  # template_name → source

    def add_filter(self, name, func):
        self._filters[name] = func

    def add_global(self, name, value):
        self._globals[name] = value

    def add_test(self, name, func):
        self._tests[name] = func

    def render(self, template_name, data=None):
        """Render a template file with the given data context."""
        source = self._load_template(template_name)
        return self.render_string(source, data)

    def render_string(self, source, data=None):
        """Render a template string with the given data context."""
        if data is None:
            data = {}
        context = dict(self._globals)
        context.update(data)
        # Inject custom tests for the expression evaluator
        if self._tests:
            context["_twig_custom_tests"] = self._tests
        tokens = _tokenize(source)
        nodes, _ = _parse(tokens)
        renderer = _Renderer(self, context, auto_escape=False)
        return renderer.render(nodes)

    def get_template(self, name):
        """Return a template object compatible with Jinja2's API."""
        source = self._load_template(name)
        return _TemplateProxy(self, source, name)

    def from_string(self, source):
        """Create a template from a string."""
        return _TemplateProxy(self, source, "<string>")

    def _load_template(self, name):
        """Load template source from search paths. Raises TemplateNotFound."""
        if name in self._cache:
            return self._cache[name]
        for path in self._search_paths:
            full = os.path.join(str(path), name)
            if os.path.isfile(full):
                with open(full, 'r', encoding='utf-8') as f:
                    source = f.read()
                self._cache[name] = source
                return source
        raise TemplateNotFound(f"Template '{name}' not found in {self._search_paths}")

    def clear_cache(self):
        """Clear the template source cache."""
        self._cache = {}


class _TemplateProxy:
    """Jinja2-compatible template object."""

    def __init__(self, engine, source, name):
        self._engine = engine
        self._source = source
        self.name = name

    def render(self, data=None, **kwargs):
        if data is None:
            data = {}
        if kwargs:
            data = dict(data, **kwargs)
        return self._engine.render_string(self._source, data)
