# Tina4 Frond Engine — Lexer, parser, and runtime.
"""
Zero-dependency twig-like template engine.
Supports: variables, filters, if/elseif/else/endif, for/else/endfor,
extends/block, include, macro, set, comments, whitespace control, tests.
"""
import os
import re
import html
import hashlib
import json
from pathlib import Path
from datetime import datetime

from tina4_python.auth import Auth as _FrondAuth


class SafeString(str):
    """Marker subclass of str that bypasses auto-escaping in Frond."""
    pass


# ── Lexer ───────────────────────────────────────────────────────

# Token types
TEXT = "TEXT"
VAR = "VAR"          # {{ ... }}
BLOCK = "BLOCK"      # {% ... %}
COMMENT = "COMMENT"  # {# ... #}

# Regex to split template into tokens
_TOKEN_RE = re.compile(
    r"(\{%-?\s*.*?\s*-?%\})"   # Block tags
    r"|(\{\{-?\s*.*?\s*-?\}\})"  # Variable tags
    r"|(\{#.*?#\})",            # Comments
    re.DOTALL,
)

# Regex to extract {% raw %}...{% endraw %} blocks before tokenizing
_RAW_BLOCK_RE = re.compile(
    r"\{%-?\s*raw\s*-?%\}(.*?)\{%-?\s*endraw\s*-?%\}",
    re.DOTALL,
)


def _tokenize(source: str) -> list[tuple[str, str]]:
    """Split template source into (type, value) tokens.

    Before splitting on {{ }}/{% %} patterns, extract {% raw %}...{% endraw %}
    blocks and replace them with placeholder TEXT tokens so their content is
    output literally (not parsed).
    """
    # 1. Extract raw blocks and replace with placeholders
    raw_blocks: list[str] = []

    def _replace_raw(m: re.Match) -> str:
        idx = len(raw_blocks)
        raw_blocks.append(m.group(1))
        return f"\x00RAW_{idx}\x00"

    source = _RAW_BLOCK_RE.sub(_replace_raw, source)

    # 2. Normal tokenization
    tokens = []
    pos = 0
    for m in _TOKEN_RE.finditer(source):
        start = m.start()
        if start > pos:
            tokens.append((TEXT, source[pos:start]))

        raw = m.group()
        if raw.startswith("{#"):
            tokens.append((COMMENT, raw))
        elif raw.startswith("{{"):
            tokens.append((VAR, raw))
        elif raw.startswith("{%"):
            tokens.append((BLOCK, raw))
        pos = m.end()

    if pos < len(source):
        tokens.append((TEXT, source[pos:]))

    # 3. Restore raw block placeholders as literal TEXT
    if raw_blocks:
        restored = []
        for ttype, value in tokens:
            if ttype == TEXT and "\x00RAW_" in value:
                for idx, content in enumerate(raw_blocks):
                    value = value.replace(f"\x00RAW_{idx}\x00", content)
            restored.append((ttype, value))
        tokens = restored

    return tokens


def _strip_tag(raw: str) -> tuple[str, bool, bool]:
    """Extract content from a tag and detect whitespace control.

    Returns (content, strip_before, strip_after).
    """
    strip_before = False
    strip_after = False

    if raw.startswith("{{"):
        inner = raw[2:-2]
    elif raw.startswith("{%"):
        inner = raw[2:-2]
    else:
        inner = raw[2:-2]

    if inner.startswith("-"):
        strip_before = True
        inner = inner[1:]
    if inner.endswith("-"):
        strip_after = True
        inner = inner[:-1]

    return inner.strip(), strip_before, strip_after


# ── Ternary helpers ────────────────────────────────────────────


def _find_ternary(expr: str) -> int:
    """Find the index of a top-level ``?`` that is part of a ternary operator.

    Respects quoted strings, parentheses, and skips ``??`` (null coalesce).
    Returns -1 if not found.
    """
    depth = 0
    in_quote = None
    i = 0
    length = len(expr)
    while i < length:
        ch = expr[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "?" and depth == 0:
            # Skip ``??`` (null coalesce)
            if i + 1 < length and expr[i + 1] == "?":
                i += 2
                continue
            return i
        i += 1
    return -1


def _find_colon(expr: str) -> int:
    """Find the index of the top-level ``:`` that separates the true/false
    branches of a ternary.  Respects quotes and parentheses."""
    depth = 0
    in_quote = None
    for i, ch in enumerate(expr):
        if in_quote:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ":" and depth == 0:
            return i
    return -1


# ── Expression Evaluator ────────────────────────────────────────


def _split_dotted(expr: str) -> list[str]:
    """Split a dotted expression into parts, respecting quotes, parens, and brackets.

    'user.t("auth.email")' → ['user', 't("auth.email")']
    'items[0].name'        → ['items', '[0]', 'name']
    'a.b.c'                → ['a', 'b', 'c']
    """
    parts = []
    current = ""
    in_q = None
    paren_depth = 0
    bracket_depth = 0
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in ('"', "'") and paren_depth == 0 and bracket_depth == 0 and in_q is None:
            in_q = ch
            current += ch
        elif ch == in_q:
            in_q = None
            current += ch
        elif in_q:
            current += ch
        elif ch == "(":
            paren_depth += 1
            current += ch
        elif ch == ")":
            paren_depth -= 1
            current += ch
        elif ch == "[" and paren_depth == 0:
            # Start of bracket access — save current part if any
            if current:
                parts.append(current)
                current = ""
            bracket_depth += 1
            current += ch
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
            current += ch
            if bracket_depth == 0:
                parts.append(current)
                current = ""
        elif ch == "." and paren_depth == 0 and bracket_depth == 0:
            if current:
                parts.append(current)
                current = ""
        else:
            current += ch
        i += 1
    if current:
        parts.append(current)
    return parts


def _resolve(expr: str, context: dict):
    """Resolve a dotted expression against the context.

    Handles: variable, obj.attr, arr[0], obj.method()
    """
    expr = expr.strip()

    # String literal
    if (expr.startswith('"') and expr.endswith('"')) or \
       (expr.startswith("'") and expr.endswith("'")):
        return expr[1:-1]

    # Numeric literal
    try:
        if "." in expr:
            return float(expr)
        return int(expr)
    except ValueError:
        pass

    # Boolean/null literals
    if expr == "true":
        return True
    if expr == "false":
        return False
    if expr in ("null", "none", "None"):
        return None

    # Dotted path with bracket access — split respecting quotes and parens
    parts = _split_dotted(expr)

    value = context
    for part in parts:
        if part.startswith("[") and part.endswith("]"):
            idx = part[1:-1].strip("'\"")
            # Slice syntax: value[1:5], value[:10], value[3:]
            if ":" in idx:
                slice_parts = idx.split(":", 1)
                s_start = int(slice_parts[0]) if slice_parts[0].strip() else None
                s_end = int(slice_parts[1]) if slice_parts[1].strip() else None
                try:
                    value = value[s_start:s_end]
                except (TypeError, IndexError):
                    return None
            else:
                try:
                    idx = int(idx)
                except ValueError:
                    pass
                try:
                    value = value[idx]
                except (KeyError, IndexError, TypeError):
                    return None
        else:
            # Check if this part is a method call: name(args)
            call_match = re.match(r"^(\w+)\s*\((.*)?\)$", part, re.DOTALL)
            if call_match:
                method_name = call_match.group(1)
                raw_args = call_match.group(2) or ""
                # Resolve the callable from the current value
                if isinstance(value, dict):
                    fn = value.get(method_name)
                elif hasattr(value, method_name):
                    fn = getattr(value, method_name)
                else:
                    return None
                if callable(fn):
                    if raw_args.strip():
                        args = [_eval_expr(a.strip(), context) for a in _split_args(raw_args)]
                    else:
                        args = []
                    value = fn(*args)
                else:
                    return None
            elif isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                attr = getattr(value, part)
                value = attr() if callable(attr) else attr
            else:
                return None

        if value is None:
            return None

    return value


def _split_args(raw: str) -> list[str]:
    """Split comma-separated arguments respecting quotes and nested parens."""
    parts = []
    current = ""
    in_q = None
    depth = 0
    for ch in raw:
        if ch in ('"', "'") and not in_q:
            in_q = ch
            current += ch
        elif ch == in_q:
            in_q = None
            current += ch
        elif ch == "(" and not in_q:
            depth += 1
            current += ch
        elif ch == ")" and not in_q:
            depth -= 1
            current += ch
        elif ch == "," and not in_q and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _find_outside_quotes(expr: str, needle: str) -> int:
    """Find the first occurrence of *needle* that is not inside quotes or parens.

    Returns the index, or -1 if not found outside quotes.
    """
    in_q = None
    depth = 0
    i = 0
    while i <= len(expr) - len(needle):
        ch = expr[i]
        if ch in ('"', "'") and depth == 0:
            if in_q is None:
                in_q = ch
            elif ch == in_q:
                in_q = None
            i += 1
            continue
        if in_q:
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and expr[i:i + len(needle)] == needle:
            return i
        i += 1
    return -1


def _split_outside_quotes(expr: str, sep: str) -> list[str]:
    """Split *expr* on *sep* only when *sep* is outside quotes and parens."""
    parts = []
    current_start = 0
    in_q = None
    depth = 0
    i = 0
    while i <= len(expr) - len(sep):
        ch = expr[i]
        if ch in ('"', "'") and depth == 0:
            if in_q is None:
                in_q = ch
            elif ch == in_q:
                in_q = None
            i += 1
            continue
        if in_q:
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and expr[i:i + len(sep)] == sep:
            parts.append(expr[current_start:i])
            i += len(sep)
            current_start = i
            continue
        i += 1
    parts.append(expr[current_start:])
    return parts


def _eval_expr(expr: str, context: dict):
    """Evaluate a full expression (with ~, ternary, ??, comparisons)."""
    expr = expr.strip()

    # String literal — only match if the entire expression is a single quoted
    # string with no unescaped matching quotes inside (avoids catching
    # expressions like 'yes' if x else 'no').
    if len(expr) >= 2:
        q = expr[0]
        if q in ('"', "'") and expr.endswith(q) and q not in expr[1:-1]:
            return expr[1:-1]

    # Ternary: condition ? "yes" : "no"
    ternary = re.match(r"^(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$", expr)
    if ternary:
        cond = _eval_expr(ternary.group(1), context)
        if cond:
            return _eval_expr(ternary.group(2), context)
        return _eval_expr(ternary.group(3), context)

    # Jinja2-style inline if: value if condition else other_value
    inline_if = re.match(r"^(.+?)\s+if\s+(.+?)\s+else\s+(.+)$", expr)
    if inline_if:
        cond = _eval_expr(inline_if.group(2), context)
        if cond:
            return _eval_expr(inline_if.group(1), context)
        return _eval_expr(inline_if.group(3), context)

    # Null coalescing: value ?? "default"
    if _find_outside_quotes(expr, "??") >= 0:
        pos = _find_outside_quotes(expr, "??")
        left = expr[:pos]
        right = expr[pos + 2:]
        val = _eval_expr(left.strip(), context)
        if val is None:
            return _eval_expr(right.strip(), context)
        return val

    # String concatenation with ~
    if _find_outside_quotes(expr, "~") >= 0:
        parts = _split_outside_quotes(expr, "~")
        return "".join(str(_eval_expr(p, context) or "") for p in parts)

    # Comparison operators for if conditions
    for op in (" not in ", " in ", " is not ", " is ", "!=", "==", ">=", "<=", ">", "<", " and ", " or ", " not "):
        if _find_outside_quotes(expr, op) >= 0:
            return _eval_comparison(expr, context)

    # Function call: name("arg1", "arg2") or obj.method("arg1")
    fn_match = re.match(r"^([\w.]+)\s*\((.*)?\)$", expr, re.DOTALL)
    if fn_match:
        fn_name = fn_match.group(1)
        raw_args = fn_match.group(2) or ""
        # For dotted names like obj.method, resolve the object then get the method
        if "." in fn_name:
            parts = fn_name.rsplit(".", 1)
            obj = _resolve(parts[0], context)
            if obj is None:
                fn = None
            elif isinstance(obj, dict):
                fn = obj.get(parts[1])
            elif hasattr(obj, parts[1]):
                fn = getattr(obj, parts[1])
            else:
                fn = None
        else:
            fn = context.get(fn_name) or _resolve(fn_name, context)
        if callable(fn):
            if raw_args.strip():
                # Split args manually, evaluate each as expression
                parts = []
                current = ""
                in_q = None
                for ch in raw_args:
                    if ch in ('"', "'") and not in_q:
                        in_q = ch
                        current += ch
                    elif ch == in_q:
                        in_q = None
                        current += ch
                    elif ch == "," and not in_q:
                        parts.append(current.strip())
                        current = ""
                    else:
                        current += ch
                if current.strip():
                    parts.append(current.strip())
                eval_args = [_eval_expr(a, context) for a in parts]
            else:
                eval_args = []
            return fn(*eval_args)

    return _resolve(expr, context)


def _eval_comparison(expr: str, context: dict):
    """Evaluate comparison/logical expressions."""
    expr = expr.strip()

    # Handle 'not' prefix
    if expr.startswith("not "):
        return not _eval_comparison(expr[4:], context)

    # 'and' / 'or' (lowest precedence)
    # Split on ' or ' first (lower precedence)
    or_parts = re.split(r"\s+or\s+", expr)
    if len(or_parts) > 1:
        return any(_eval_comparison(p, context) for p in or_parts)

    and_parts = re.split(r"\s+and\s+", expr)
    if len(and_parts) > 1:
        return all(_eval_comparison(p, context) for p in and_parts)

    # 'is not' test
    m = re.match(r"^(.+?)\s+is\s+not\s+(\w+)(.*)$", expr)
    if m:
        return not _eval_test(m.group(1).strip(), m.group(2), m.group(3).strip(), context)

    # 'is' test
    m = re.match(r"^(.+?)\s+is\s+(\w+)(.*)$", expr)
    if m:
        return _eval_test(m.group(1).strip(), m.group(2), m.group(3).strip(), context)

    # 'not in'
    m = re.match(r"^(.+?)\s+not\s+in\s+(.+)$", expr)
    if m:
        val = _eval_expr(m.group(1).strip(), context)
        collection = _eval_expr(m.group(2).strip(), context)
        return val not in (collection or [])

    # 'in'
    m = re.match(r"^(.+?)\s+in\s+(.+)$", expr)
    if m:
        val = _eval_expr(m.group(1).strip(), context)
        collection = _eval_expr(m.group(2).strip(), context)
        return val in (collection or [])

    # Binary operators
    for op, fn in [("!=", lambda a, b: a != b), ("==", lambda a, b: a == b),
                    (">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b),
                    (">", lambda a, b: a > b), ("<", lambda a, b: a < b)]:
        if op in expr:
            left, _, right = expr.partition(op)
            l = _eval_expr(left.strip(), context)
            r = _eval_expr(right.strip(), context)
            try:
                return fn(l, r)
            except TypeError:
                return False

    # Fall through to simple eval
    val = _eval_expr(expr, context)
    return bool(val) if val is not None else False


def _eval_test(value_expr: str, test_name: str, args: str, context: dict) -> bool:
    """Evaluate an 'is' test."""
    val = _eval_expr(value_expr, context)

    tests = {
        "defined": lambda v: v is not None,
        "empty": lambda v: not v,
        "null": lambda v: v is None,
        "none": lambda v: v is None,
        "even": lambda v: isinstance(v, int) and v % 2 == 0,
        "odd": lambda v: isinstance(v, int) and v % 2 != 0,
        "iterable": lambda v: hasattr(v, "__iter__") and not isinstance(v, str),
        "string": lambda v: isinstance(v, str),
        "number": lambda v: isinstance(v, (int, float)),
        "boolean": lambda v: isinstance(v, bool),
    }

    # 'divisible by(n)'
    if test_name == "divisible":
        m = re.match(r"\s*by\s*\(\s*(\d+)\s*\)", args)
        if m:
            n = int(m.group(1))
            return isinstance(val, int) and val % n == 0
        return False

    if test_name in tests:
        return tests[test_name](val)

    return False


# ── Filters ─────────────────────────────────────────────────────

def _split_on_pipe(expr: str) -> list[str]:
    """Split expression on | respecting quotes and parentheses."""
    parts = []
    current = ""
    in_quote = None
    depth = 0

    for ch in expr:
        if in_quote:
            current += ch
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current += ch
        elif ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch

    if current:
        parts.append(current)

    return parts


def _parse_filter_chain(expr: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Parse 'variable | filter1 | filter2(arg)' into (variable, [(name, args)])."""
    parts = _split_on_pipe(expr)
    variable = parts[0].strip()
    filters = []

    for f in parts[1:]:
        f = f.strip()
        m = re.match(r"(\w+)\s*\((.*)\)$", f, re.DOTALL)
        if m:
            name = m.group(1)
            raw_args = m.group(2).strip()
            # Simple arg parsing (handles strings and numbers)
            args = _parse_args(raw_args) if raw_args else []
            filters.append((name, args))
        else:
            filters.append((f.strip(), []))

    return variable, filters


def _parse_args(raw: str) -> list[str]:
    """Parse filter arguments, respecting quoted strings."""
    args = []
    current = ""
    in_quote = None
    depth = 0

    for ch in raw:
        if ch in ('"', "'") and not in_quote:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch == "(" and not in_quote:
            depth += 1
        elif ch == ")" and not in_quote:
            depth -= 1
        elif ch == "," and not in_quote and depth == 0:
            args.append(current.strip().strip("'\""))
            current = ""
            continue
        current += ch

    if current.strip():
        args.append(current.strip().strip("'\""))

    return args


# Built-in filters
_BUILTIN_FILTERS = {
    "upper": lambda v, *a: str(v).upper(),
    "lower": lambda v, *a: str(v).lower(),
    "capitalize": lambda v, *a: str(v).capitalize(),
    "title": lambda v, *a: str(v).title(),
    "trim": lambda v, *a: str(v).strip(),
    "ltrim": lambda v, *a: str(v).lstrip(),
    "rtrim": lambda v, *a: str(v).rstrip(),
    "length": lambda v, *a: len(v) if v else 0,
    "reverse": lambda v, *a: list(reversed(v)) if isinstance(v, list) else str(v)[::-1],
    "sort": lambda v, *a: sorted(v) if isinstance(v, list) else v,
    "shuffle": lambda v, *a: __import__("random").sample(v, len(v)) if isinstance(v, list) else v,
    "first": lambda v, *a: v[0] if v else None,
    "last": lambda v, *a: v[-1] if v else None,
    "join": lambda v, *a: (a[0] if a else ", ").join(str(i) for i in v) if isinstance(v, list) else str(v),
    "split": lambda v, *a: str(v).split(a[0] if a else " "),
    "replace": lambda v, *a: str(v).replace(a[0], a[1]) if len(a) >= 2 else str(v),
    "default": lambda v, *a: v if v is not None and v != "" else (a[0] if a else ""),
    "raw": lambda v, *a: v,  # Mark as safe (no escaping)
    "safe": lambda v, *a: v,
    "escape": lambda v, *a: html.escape(str(v)),
    "e": lambda v, *a: html.escape(str(v)),
    "striptags": lambda v, *a: re.sub(r"<[^>]+>", "", str(v)),
    "nl2br": lambda v, *a: str(v).replace("\n", "<br>\n"),
    "abs": lambda v, *a: abs(v) if isinstance(v, (int, float)) else v,
    "round": lambda v, *a: round(float(v), int(a[0]) if a else 0),
    "int": lambda v, *a: int(v) if v else 0,
    "float": lambda v, *a: float(v) if v else 0.0,
    "string": lambda v, *a: str(v),
    "json_encode": lambda v, *a: json.dumps(v),
    "json_decode": lambda v, *a: json.loads(v) if isinstance(v, str) else v,
    "keys": lambda v, *a: list(v.keys()) if isinstance(v, dict) else [],
    "values": lambda v, *a: list(v.values()) if isinstance(v, dict) else [],
    "merge": lambda v, *a: {**v, **(a[0] if a and isinstance(a[0], dict) else {})} if isinstance(v, dict) else v,
    "slice": lambda v, *a: v[int(a[0]):int(a[1])] if len(a) >= 2 else v,
    "batch": lambda v, *a: [v[i:i+int(a[0])] for i in range(0, len(v), int(a[0]))] if a else [v],
    "unique": lambda v, *a: list(dict.fromkeys(v)) if isinstance(v, list) else v,
    "map": lambda v, *a: [i.get(a[0]) if isinstance(i, dict) else getattr(i, a[0], None) for i in v] if a and isinstance(v, list) else v,
    "filter": lambda v, *a: [i for i in v if i] if isinstance(v, list) else v,
    "column": lambda v, *a: [row.get(a[0]) for row in v if isinstance(row, dict)] if a and isinstance(v, list) else v,
    "number_format": lambda v, *a: f"{float(v):,.{int(a[0]) if a else 0}f}",
    "date": lambda v, *a: _date_filter(v, a[0] if a else "%Y-%m-%d"),
    "truncate": lambda v, *a: (str(v)[:int(a[0])] + "...") if a and len(str(v)) > int(a[0]) else str(v),
    "wordwrap": lambda v, *a: _wordwrap(str(v), int(a[0]) if a else 75),
    "slug": lambda v, *a: re.sub(r"[^a-z0-9]+", "-", str(v).lower()).strip("-"),
    "md5": lambda v, *a: hashlib.md5(str(v).encode()).hexdigest(),
    "sha256": lambda v, *a: hashlib.sha256(str(v).encode()).hexdigest(),
    "base64_encode": lambda v, *a: __import__("base64").b64encode(v if isinstance(v, bytes) else str(v).encode()).decode(),
    "base64encode": lambda v, *a: __import__("base64").b64encode(v if isinstance(v, bytes) else str(v).encode()).decode(),
    "base64_decode": lambda v, *a: __import__("base64").b64decode(str(v)).decode(),
    "base64decode": lambda v, *a: __import__("base64").b64decode(str(v)).decode(),
    "data_uri": lambda v, *a: f"data:{v.get('type', 'application/octet-stream')};base64,{__import__('base64').b64encode(v['content'] if isinstance(v['content'], bytes) else v['content'].encode()).decode()}" if isinstance(v, dict) else str(v),
    "url_encode": lambda v, *a: __import__("urllib.parse", fromlist=["quote"]).quote(str(v)),
    "format": lambda v, *a: str(v) % tuple(a) if a else str(v),
    "dump": lambda v, *a: repr(v),
    "form_token": lambda v, *a: _form_token(str(v) if v else ""),
}


def _date_filter(value, fmt: str) -> str:
    """Format a date/datetime value."""
    if isinstance(value, datetime):
        return value.strftime(fmt)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime(fmt)
        except ValueError:
            return value
    return str(value)


def _wordwrap(text: str, width: int) -> str:
    """Wrap text at word boundaries."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return "\n".join(lines)


# ── Form Token ─────────────────────────────────────────────────


def _form_token(descriptor: str = "", session_id: str = "") -> str:
    """Generate a JWT form token and return a hidden input element.

    Args:
        descriptor: Optional string to enrich the token payload.
            - Empty or omitted: payload is ``{"type": "form"}``
            - ``"admin_panel"``: payload is ``{"type": "form", "context": "admin_panel"}``
            - ``"checkout|order_123"``: payload is ``{"type": "form", "context": "checkout", "ref": "order_123"}``
        session_id: Optional session ID to bind the token to a specific session.
            When provided, the CSRF middleware will verify the token belongs to
            the same session. If empty, checks ``_form_token_session_id`` global.

    Returns:
        ``<input type="hidden" name="formToken" value="TOKEN">``
    """
    payload = {"type": "form"}
    if descriptor:
        descriptor = str(descriptor)
        if "|" in descriptor:
            parts = descriptor.split("|", 1)
            payload["context"] = parts[0]
            payload["ref"] = parts[1]
        else:
            payload["context"] = descriptor

    # Include session_id in payload for CSRF session binding
    sid = session_id or _form_token_session_id
    if sid:
        payload["session_id"] = sid

    secret = os.environ.get("SECRET", "tina4-default-secret")
    ttl = int(os.environ.get("TINA4_TOKEN_EXPIRES_IN", "60"))
    auth = _FrondAuth(secret=secret, expires_in=ttl)
    token = auth.get_token(payload)
    return SafeString(f'<input type="hidden" name="formToken" value="{token}">')


# Module-level session ID holder — set by the server before rendering templates
# so that form_token() can bind tokens to the current session.
_form_token_session_id: str = ""


def set_form_token_session_id(session_id: str) -> None:
    """Set the session ID used by form_token() for CSRF session binding."""
    global _form_token_session_id
    _form_token_session_id = session_id or ""


# ── Frond Engine ────────────────────────────────────────────────


class Frond:
    """Twig-like template engine with sandboxing and fragment caching."""

    def __init__(self, template_dir: str = "src/templates"):
        self.template_dir = Path(template_dir)
        self._filters = dict(_BUILTIN_FILTERS)
        self._globals = {}
        self._tests = {}
        self._cache: dict[str, str] = {}
        # Sandboxing
        self._sandbox = False
        self._allowed_filters: set[str] | None = None
        self._allowed_tags: set[str] | None = None
        self._allowed_vars: set[str] | None = None
        # Fragment cache (key → (html, expires_at))
        self._fragment_cache: dict[str, tuple[str, float]] = {}
        # Token pre-compilation cache
        self._compiled: dict[str, tuple[list, float]] = {}  # {template_name: (tokens, mtime)}
        self._compiled_strings: dict[str, list] = {}  # {md5_hash: tokens}

        # Built-in global functions
        self._globals["form_token"] = _form_token

    def sandbox(self, allowed_filters: list[str] = None,
                allowed_tags: list[str] = None,
                allowed_vars: list[str] = None):
        """Enable sandbox mode — restrict what templates can access.

        Args:
            allowed_filters: Whitelist of filter names. None = all allowed.
            allowed_tags: Whitelist of tag names (if, for, set, include, etc.). None = all.
            allowed_vars: Whitelist of variable names accessible in context. None = all.

        Usage:
            engine.sandbox(
                allowed_filters=["upper", "lower", "default", "e"],
                allowed_tags=["if", "for", "set"],
                allowed_vars=["title", "items", "user"],
            )
        """
        self._sandbox = True
        self._allowed_filters = set(allowed_filters) if allowed_filters else None
        self._allowed_tags = set(allowed_tags) if allowed_tags else None
        self._allowed_vars = set(allowed_vars) if allowed_vars else None
        return self

    def unsandbox(self):
        """Disable sandbox mode."""
        self._sandbox = False
        self._allowed_filters = None
        self._allowed_tags = None
        self._allowed_vars = None
        return self

    def add_filter(self, name: str, fn):
        """Register a custom filter."""
        self._filters[name] = fn

    def add_global(self, name: str, value):
        """Register a global variable available in all templates."""
        self._globals[name] = value

    def add_test(self, name: str, fn):
        """Register a custom test."""
        self._tests[name] = fn

    def render(self, template: str, data: dict = None) -> str:
        """Render a template with data. Uses token caching for performance."""
        context = {**self._globals, **(data or {})}

        # Resolve file path and check mtime for cache validity
        path = self.template_dir / template
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")

        debug_mode = os.environ.get("TINA4_DEBUG", "").lower() == "true"
        cached = self._compiled.get(template)

        if cached is not None:
            if debug_mode:
                # Dev mode: check if file changed
                mtime = path.stat().st_mtime
                if cached[1] == mtime:
                    return self._execute_cached(cached[0], context, template)
            else:
                # Production: skip mtime check, cache is permanent
                return self._execute_cached(cached[0], context, template)

        # Cache miss — load, tokenize, cache
        source = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
        tokens = _tokenize(source)
        self._compiled[template] = (tokens, mtime)
        return self._execute_with_source(source, tokens, context, template)

    def render_string(self, source: str, data: dict = None) -> str:
        """Render a template string directly. Uses token caching for performance."""
        context = {**self._globals, **(data or {})}

        key = hashlib.md5(source.encode()).hexdigest()
        cached_tokens = self._compiled_strings.get(key)
        if cached_tokens is not None:
            return self._execute_cached(cached_tokens, context)

        tokens = _tokenize(source)
        self._compiled_strings[key] = tokens
        return self._execute_cached(tokens, context)

    def clear_cache(self):
        """Clear all compiled template caches."""
        self._compiled.clear()
        self._compiled_strings.clear()

    def _load(self, name: str) -> str:
        """Load template source from file."""
        path = self.template_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _execute_cached(self, tokens: list, context: dict, template: str = None) -> str:
        """Execute pre-tokenized template against context.

        Checks for extends in tokens; if found, falls back to source-based
        execution (extends requires re-reading parent template).
        """
        # Check if first non-text token is an extends block
        for ttype, raw in tokens:
            if ttype == TEXT:
                if raw.strip():
                    break
                continue
            if ttype == BLOCK:
                content, _, _ = _strip_tag(raw)
                if content.startswith("extends "):
                    # Extends requires source-based execution for block extraction
                    # Reconstruct source from tokens
                    source = "".join(val for _, val in tokens)
                    return self._execute(source, context)
            break
        return self._render_tokens(tokens, context)

    def _execute_with_source(self, source: str, tokens: list, context: dict, template: str = None) -> str:
        """Execute with both source and pre-tokenized tokens available."""
        # Handle extends first
        extends_match = re.match(r"\{%[-\s]*extends\s+[\"'](.+?)[\"']\s*[-]?%\}", source.lstrip())
        if extends_match:
            parent_name = extends_match.group(1)
            parent_source = self._load(parent_name)
            child_blocks = self._extract_blocks(source)
            return self._render_with_blocks(parent_source, context, child_blocks)

        return self._render_tokens(tokens, context)

    def _execute(self, source: str, context: dict) -> str:
        """Execute template source against context."""
        # Handle extends first
        extends_match = re.match(r"\{%[-\s]*extends\s+[\"'](.+?)[\"']\s*[-]?%\}", source.lstrip())
        if extends_match:
            parent_name = extends_match.group(1)
            parent_source = self._load(parent_name)

            # Extract blocks from child
            child_blocks = self._extract_blocks(source)

            # Render parent with child blocks
            return self._render_with_blocks(parent_source, context, child_blocks)

        return self._render_tokens(_tokenize(source), context)

    def _extract_blocks(self, source: str) -> dict[str, str]:
        """Extract {% block name %}...{% endblock %} from source."""
        blocks = {}
        pattern = re.compile(
            r"\{%[-\s]*block\s+(\w+)\s*[-]?%\}(.*?)\{%[-\s]*endblock\s*[-]?%\}",
            re.DOTALL,
        )
        for m in pattern.finditer(source):
            blocks[m.group(1)] = m.group(2)
        return blocks

    def _render_with_blocks(self, parent_source: str, context: dict, child_blocks: dict) -> str:
        """Render parent template, replacing blocks with child content."""
        def replace_block(m):
            name = m.group(1)
            default_content = m.group(2)
            block_source = child_blocks.get(name, default_content)
            return self._render_tokens(_tokenize(block_source), context)

        pattern = re.compile(
            r"\{%[-\s]*block\s+(\w+)\s*[-]?%\}(.*?)\{%[-\s]*endblock\s*[-]?%\}",
            re.DOTALL,
        )

        # First pass: replace blocks
        result = pattern.sub(replace_block, parent_source)
        # Second pass: render remaining tokens (text, vars outside blocks)
        return self._render_tokens(_tokenize(result), context)

    def _render_tokens(self, tokens: list, context: dict) -> str:
        """Render a list of tokens to string."""
        output = []
        i = 0

        while i < len(tokens):
            ttype, raw = tokens[i]

            if ttype == TEXT:
                output.append(raw)
                i += 1

            elif ttype == COMMENT:
                i += 1

            elif ttype == VAR:
                content, strip_b, strip_a = _strip_tag(raw)
                if strip_b and output:
                    output[-1] = output[-1].rstrip()

                result = self._eval_var(content, context)
                output.append(str(result) if result is not None else "")

                if strip_a and i + 1 < len(tokens) and tokens[i + 1][0] == TEXT:
                    tokens[i + 1] = (TEXT, tokens[i + 1][1].lstrip())
                i += 1

            elif ttype == BLOCK:
                content, strip_b, strip_a = _strip_tag(raw)
                if strip_b and output:
                    output[-1] = output[-1].rstrip()

                tag = content.split()[0] if content.split() else ""

                if tag == "if":
                    result, skip = self._handle_if(tokens, i, context)
                    output.append(result)
                    i = skip

                elif tag == "for":
                    result, skip = self._handle_for(tokens, i, context)
                    output.append(result)
                    i = skip

                elif tag == "set":
                    self._handle_set(content, context)
                    i += 1

                elif tag == "include":
                    # Sandbox: check tag
                    if self._sandbox and self._allowed_tags is not None and "include" not in self._allowed_tags:
                        i += 1
                    else:
                        result = self._handle_include(content, context)
                        output.append(result)
                        i += 1

                elif tag == "macro":
                    skip = self._handle_macro(tokens, i, context)
                    i = skip

                elif tag == "from":
                    self._handle_from_import(content, context)
                    i += 1

                elif tag == "cache":
                    result, skip = self._handle_cache(tokens, i, context)
                    output.append(result)
                    i = skip

                elif tag == "spaceless":
                    result, skip = self._handle_spaceless(tokens, i, context)
                    output.append(result)
                    i = skip

                elif tag == "autoescape":
                    result, skip = self._handle_autoescape(tokens, i, context)
                    output.append(result)
                    i = skip

                elif tag in ("block", "endblock", "extends"):
                    i += 1  # Already handled

                else:
                    i += 1

                if strip_a and i < len(tokens) and tokens[i][0] == TEXT:
                    tokens[i] = (TEXT, tokens[i][1].lstrip())
            else:
                i += 1

        return "".join(output)

    def _eval_var(self, expr: str, context: dict):
        """Evaluate a variable expression with filters."""
        # Check for top-level ternary BEFORE splitting filters, so that
        # expressions like ``products|length != 1 ? "s" : ""`` are handled
        # correctly.  The ``?`` belongs to the ternary, not to a filter.
        ternary_pos = _find_ternary(expr)
        if ternary_pos != -1:
            cond_part = expr[:ternary_pos].strip()
            rest = expr[ternary_pos + 1:]
            colon_pos = _find_colon(rest)
            if colon_pos != -1:
                true_part = rest[:colon_pos].strip()
                false_part = rest[colon_pos + 1:].strip()
                cond = self._eval_var_raw(cond_part, context)
                if cond:
                    return self._eval_var(true_part, context)
                return self._eval_var(false_part, context)

        return self._eval_var_inner(expr, context)

    def _eval_var_raw(self, expr: str, context: dict):
        """Evaluate a variable expression with filters, returning the raw
        (unescaped) value for use in boolean/comparison tests.

        Handles the case where a filter segment contains a trailing comparison
        operator, e.g. ``products|length != 1`` is split by the filter parser
        into variable ``products`` and filter ``length != 1``.  We detect that
        ``length`` is a real filter but ``!= 1`` is a comparison, so we apply
        the filter first and then evaluate the comparison.
        """
        var_name, filters = _parse_filter_chain(expr)
        value = _eval_expr(var_name, context)

        for fname, args in filters:
            if fname in ("raw", "safe"):
                continue
            fn = self._filters.get(fname)
            if fn:
                value = fn(value, *args)
            else:
                # The filter name may include a trailing comparison operator,
                # e.g. "length != 1".  Extract the real filter name and the
                # comparison suffix, apply the filter, then evaluate the
                # comparison against the result.
                m = re.match(r"(\w+)\s*(!=|==|>=|<=|>|<)\s*(.+)", fname)
                if m:
                    real_filter = m.group(1)
                    op = m.group(2)
                    right_expr = m.group(3).strip()
                    fn2 = self._filters.get(real_filter)
                    if fn2:
                        value = fn2(value, *args)
                    right = _eval_expr(right_expr, context)
                    ops = {"!=": lambda a, b: a != b, "==": lambda a, b: a == b,
                           ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
                           ">": lambda a, b: a > b, "<": lambda a, b: a < b}
                    try:
                        value = ops[op](value, right)
                    except TypeError:
                        value = False
                else:
                    # Unrecognised filter with no comparison — evaluate as a
                    # full expression (handles cases like bare comparisons).
                    value = _eval_expr(fname, context)
        return value

    def _eval_var_inner(self, expr: str, context: dict):
        """Core variable evaluation: resolve expression, apply filters, escape."""
        var_name, filters = _parse_filter_chain(expr)

        # Sandbox: check variable access
        if self._sandbox and self._allowed_vars is not None:
            root_var = var_name.split(".")[0].split("[")[0].strip()
            if root_var and root_var not in self._allowed_vars and root_var != "loop":
                return ""  # Silently block

        value = _eval_expr(var_name, context)

        is_safe = False
        for fname, args in filters:
            if fname in ("raw", "safe"):
                is_safe = True
                continue

            # Sandbox: check filter access
            if self._sandbox and self._allowed_filters is not None:
                if fname not in self._allowed_filters:
                    continue  # Silently skip blocked filter

            fn = self._filters.get(fname)
            if fn:
                value = fn(value, *args)

        # Auto-escape HTML unless marked safe or SafeString
        if not is_safe and isinstance(value, str) and not isinstance(value, SafeString):
            value = html.escape(value)

        return value

    def _handle_if(self, tokens: list, start: int, context: dict) -> tuple[str, int]:
        """Handle {% if %}...{% elseif %}...{% else %}...{% endif %}."""
        content, _, _ = _strip_tag(tokens[start][1])
        condition_expr = content[3:].strip()  # Remove 'if '

        # Collect branches: [(condition, tokens), ...]
        branches = []
        current_tokens = []
        current_cond = condition_expr
        depth = 0
        i = start + 1

        while i < len(tokens):
            ttype, raw = tokens[i]
            if ttype == BLOCK:
                tag_content, _, _ = _strip_tag(raw)
                tag = tag_content.split()[0] if tag_content.split() else ""

                if tag == "if":
                    depth += 1
                    current_tokens.append(tokens[i])
                elif tag == "endif" and depth > 0:
                    depth -= 1
                    current_tokens.append(tokens[i])
                elif tag == "endif" and depth == 0:
                    branches.append((current_cond, current_tokens))
                    i += 1
                    break
                elif tag in ("elseif", "elif") and depth == 0:
                    branches.append((current_cond, current_tokens))
                    current_cond = tag_content[len(tag):].strip()
                    current_tokens = []
                elif tag == "else" and depth == 0:
                    branches.append((current_cond, current_tokens))
                    current_cond = None  # else branch
                    current_tokens = []
                else:
                    current_tokens.append(tokens[i])
            else:
                current_tokens.append(tokens[i])
            i += 1

        # Evaluate branches
        for cond, branch_tokens in branches:
            if cond is None or _eval_comparison(cond, context):
                return self._render_tokens(list(branch_tokens), context), i

        return "", i

    def _handle_for(self, tokens: list, start: int, context: dict) -> tuple[str, int]:
        """Handle {% for item in items %}...{% else %}...{% endfor %}."""
        content, _, _ = _strip_tag(tokens[start][1])
        # Parse: for key, value in expr  OR  for item in expr
        for_match = re.match(
            r"for\s+(\w+)(?:\s*,\s*(\w+))?\s+in\s+(.+)",
            content,
        )
        if not for_match:
            return "", start + 1

        var1 = for_match.group(1)
        var2 = for_match.group(2)
        iterable_expr = for_match.group(3).strip()

        # Collect body and else tokens
        body_tokens = []
        else_tokens = []
        in_else = False
        for_depth = 0
        if_depth = 0
        i = start + 1

        while i < len(tokens):
            ttype, raw = tokens[i]
            if ttype == BLOCK:
                tag_content, _, _ = _strip_tag(raw)
                tag = tag_content.split()[0] if tag_content.split() else ""

                if tag == "for":
                    for_depth += 1
                    (else_tokens if in_else else body_tokens).append(tokens[i])
                elif tag == "endfor" and for_depth > 0:
                    for_depth -= 1
                    (else_tokens if in_else else body_tokens).append(tokens[i])
                elif tag == "endfor" and for_depth == 0:
                    i += 1
                    break
                elif tag == "if":
                    if_depth += 1
                    (else_tokens if in_else else body_tokens).append(tokens[i])
                elif tag == "endif":
                    if_depth -= 1
                    (else_tokens if in_else else body_tokens).append(tokens[i])
                elif tag == "else" and for_depth == 0 and if_depth == 0:
                    in_else = True
                else:
                    (else_tokens if in_else else body_tokens).append(tokens[i])
            else:
                (else_tokens if in_else else body_tokens).append(tokens[i])
            i += 1

        # Evaluate iterable
        iterable = _eval_expr(iterable_expr, context)

        if not iterable:
            if else_tokens:
                return self._render_tokens(list(else_tokens), context), i
            return "", i

        # Iterate
        output = []
        items = list(iterable.items()) if isinstance(iterable, dict) else list(iterable)
        total = len(items)

        for idx, item in enumerate(items):
            loop_ctx = dict(context)
            loop_ctx["loop"] = {
                "index": idx + 1,
                "index0": idx,
                "first": idx == 0,
                "last": idx == total - 1,
                "length": total,
                "revindex": total - idx,
                "revindex0": total - idx - 1,
                "even": (idx + 1) % 2 == 0,
                "odd": (idx + 1) % 2 != 0,
            }

            if isinstance(iterable, dict):
                key, value = item
                if var2:
                    loop_ctx[var1] = key
                    loop_ctx[var2] = value
                else:
                    loop_ctx[var1] = key
            else:
                if var2:
                    loop_ctx[var1] = idx
                    loop_ctx[var2] = item
                else:
                    loop_ctx[var1] = item

            output.append(self._render_tokens(list(body_tokens), loop_ctx))

        return "".join(output), i

    def _handle_set(self, content: str, context: dict):
        """Handle {% set name = expr %}."""
        m = re.match(r"set\s+(\w+)\s*=\s*(.+)", content)
        if m:
            name = m.group(1)
            expr = m.group(2).strip()
            context[name] = _eval_expr(expr, context)

    def _handle_include(self, content: str, context: dict) -> str:
        """Handle {% include "file.html" %} with optional 'with' and 'ignore missing'."""
        ignore_missing = "ignore missing" in content
        content = content.replace("ignore missing", "").strip()

        # Parse: include "file" with { ... }
        m = re.match(r'include\s+["\'](.+?)["\'](?:\s+with\s+(.+))?', content)
        if not m:
            return ""

        filename = m.group(1)
        with_expr = m.group(2)

        try:
            source = self._load(filename)
        except FileNotFoundError:
            if ignore_missing:
                return ""
            raise

        inc_context = dict(context)
        if with_expr:
            extra = _eval_expr(with_expr, context)
            if isinstance(extra, dict):
                inc_context.update(extra)

        return self._execute(source, inc_context)

    def _handle_macro(self, tokens: list, start: int, context: dict) -> int:
        """Handle {% macro name(args) %}...{% endmacro %}. Registers as context callable."""
        content, _, _ = _strip_tag(tokens[start][1])
        m = re.match(r"macro\s+(\w+)\s*\(([^)]*)\)", content)
        if not m:
            # Skip to endmacro
            i = start + 1
            while i < len(tokens):
                if tokens[i][0] == BLOCK and "endmacro" in tokens[i][1]:
                    return i + 1
                i += 1
            return i

        macro_name = m.group(1)
        param_names = [p.strip() for p in m.group(2).split(",") if p.strip()]

        # Collect body tokens
        body_tokens = []
        i = start + 1
        while i < len(tokens):
            if tokens[i][0] == BLOCK and "endmacro" in tokens[i][1]:
                i += 1
                break
            body_tokens.append(tokens[i])
            i += 1

        # Register macro as a callable in context
        engine = self

        def macro_fn(*args):
            macro_ctx = dict(context)
            for pi, pname in enumerate(param_names):
                macro_ctx[pname] = args[pi] if pi < len(args) else None
            return engine._render_tokens(list(body_tokens), macro_ctx)

        context[macro_name] = macro_fn
        return i

    def _handle_from_import(self, content: str, context: dict):
        """Handle {% from "file" import macro1, macro2 %}.

        Loads the given template file, parses it for macro definitions,
        and registers the named macros as callables in the current context.
        """
        m = re.match(r'from\s+["\'](.+?)["\']\s+import\s+(.+)', content)
        if not m:
            return

        filename = m.group(1)
        names = [n.strip() for n in m.group(2).split(",") if n.strip()]

        # Load and tokenize the macro file
        source = self._load(filename)
        tokens = _tokenize(source)

        # Walk tokens to find macro definitions
        i = 0
        while i < len(tokens):
            ttype, raw = tokens[i]
            if ttype == BLOCK:
                tag_content, _, _ = _strip_tag(raw)
                tag = tag_content.split()[0] if tag_content.split() else ""
                if tag == "macro":
                    macro_m = re.match(r"macro\s+(\w+)\s*\(([^)]*)\)", tag_content)
                    if macro_m and macro_m.group(1) in names:
                        macro_name = macro_m.group(1)
                        param_names = [p.strip() for p in macro_m.group(2).split(",") if p.strip()]

                        # Collect body tokens until endmacro
                        body_tokens = []
                        i += 1
                        while i < len(tokens):
                            if tokens[i][0] == BLOCK and "endmacro" in tokens[i][1]:
                                i += 1
                                break
                            body_tokens.append(tokens[i])
                            i += 1

                        # Register as callable
                        engine = self
                        captured_body = list(body_tokens)
                        captured_params = list(param_names)
                        captured_context = dict(context)

                        def macro_fn(*args, _params=captured_params, _body=captured_body, _ctx=captured_context):
                            macro_ctx = dict(_ctx)
                            for pi, pname in enumerate(_params):
                                macro_ctx[pname] = args[pi] if pi < len(args) else None
                            return engine._render_tokens(list(_body), macro_ctx)

                        context[macro_name] = macro_fn
                        continue
            i += 1

    def _handle_cache(self, tokens: list, start: int, context: dict) -> tuple[str, int]:
        """Handle {% cache "key" ttl %}...{% endcache %}.

        Fragment caching — caches the rendered block content.

        Usage:
            {% cache "sidebar" 300 %}
                <div>Expensive content here</div>
            {% endcache %}
        """
        import time

        content, _, _ = _strip_tag(tokens[start][1])
        # Parse: cache "key" ttl  OR  cache "key"
        m = re.match(r'cache\s+["\'](.+?)["\']\s*(\d+)?', content)
        cache_key = m.group(1) if m else "default"
        ttl = int(m.group(2)) if m and m.group(2) else 60

        # Check cache
        cached = self._fragment_cache.get(cache_key)
        if cached:
            html_content, expires_at = cached
            if time.time() < expires_at:
                # Skip to endcache
                i = start + 1
                depth = 0
                while i < len(tokens):
                    if tokens[i][0] == BLOCK:
                        tag_content, _, _ = _strip_tag(tokens[i][1])
                        tag = tag_content.split()[0] if tag_content.split() else ""
                        if tag == "cache":
                            depth += 1
                        elif tag == "endcache":
                            if depth == 0:
                                return html_content, i + 1
                            depth -= 1
                    i += 1
                return html_content, i

        # Collect body tokens
        body_tokens = []
        i = start + 1
        depth = 0
        while i < len(tokens):
            if tokens[i][0] == BLOCK:
                tag_content, _, _ = _strip_tag(tokens[i][1])
                tag = tag_content.split()[0] if tag_content.split() else ""
                if tag == "cache":
                    depth += 1
                    body_tokens.append(tokens[i])
                elif tag == "endcache":
                    if depth == 0:
                        i += 1
                        break
                    depth -= 1
                    body_tokens.append(tokens[i])
                else:
                    body_tokens.append(tokens[i])
            else:
                body_tokens.append(tokens[i])
            i += 1

        # Render and cache
        rendered = self._render_tokens(list(body_tokens), context)
        self._fragment_cache[cache_key] = (rendered, time.time() + ttl)
        return rendered, i

    def _handle_spaceless(self, tokens: list, start: int, context: dict) -> tuple[str, int]:
        """Handle {% spaceless %}...{% endspaceless %}.

        Removes whitespace between HTML tags in the rendered content.
        """
        body_tokens = []
        i = start + 1
        depth = 0
        while i < len(tokens):
            if tokens[i][0] == BLOCK:
                tag_content, _, _ = _strip_tag(tokens[i][1])
                tag = tag_content.split()[0] if tag_content.split() else ""
                if tag == "spaceless":
                    depth += 1
                    body_tokens.append(tokens[i])
                elif tag == "endspaceless":
                    if depth == 0:
                        i += 1
                        break
                    depth -= 1
                    body_tokens.append(tokens[i])
                else:
                    body_tokens.append(tokens[i])
            else:
                body_tokens.append(tokens[i])
            i += 1

        rendered = self._render_tokens(list(body_tokens), context)
        # Collapse whitespace between > and <
        rendered = re.sub(r">\s+<", "><", rendered)
        return rendered, i

    def _handle_autoescape(self, tokens: list, start: int, context: dict) -> tuple[str, int]:
        """Handle {% autoescape false %}...{% endautoescape %}.

        When autoescape is false, variables inside the block skip HTML escaping.
        """
        content, _, _ = _strip_tag(tokens[start][1])
        # Parse: autoescape false|true
        mode_match = re.match(r"autoescape\s+(false|true)", content)
        auto_escape_on = True
        if mode_match and mode_match.group(1) == "false":
            auto_escape_on = False

        body_tokens = []
        i = start + 1
        depth = 0
        while i < len(tokens):
            if tokens[i][0] == BLOCK:
                tag_content, _, _ = _strip_tag(tokens[i][1])
                tag = tag_content.split()[0] if tag_content.split() else ""
                if tag == "autoescape":
                    depth += 1
                    body_tokens.append(tokens[i])
                elif tag == "endautoescape":
                    if depth == 0:
                        i += 1
                        break
                    depth -= 1
                    body_tokens.append(tokens[i])
                else:
                    body_tokens.append(tokens[i])
            else:
                body_tokens.append(tokens[i])
            i += 1

        if not auto_escape_on:
            # Render with a temporary engine that has auto-escape disabled
            # We wrap _eval_var to skip escaping
            original_eval_var = self._eval_var

            def _no_escape_eval_var(expr, ctx):
                var_name, filters = _parse_filter_chain(expr)
                if self._sandbox and self._allowed_vars is not None:
                    root_var = var_name.split(".")[0].split("[")[0].strip()
                    if root_var and root_var not in self._allowed_vars and root_var != "loop":
                        return ""
                value = _eval_expr(var_name, ctx)
                for fname, args in filters:
                    if fname in ("raw", "safe"):
                        continue
                    if self._sandbox and self._allowed_filters is not None:
                        if fname not in self._allowed_filters:
                            continue
                    fn = self._filters.get(fname)
                    if fn:
                        value = fn(value, *args)
                # Skip auto-escape
                return value

            self._eval_var = _no_escape_eval_var
            rendered = self._render_tokens(list(body_tokens), context)
            self._eval_var = original_eval_var
        else:
            rendered = self._render_tokens(list(body_tokens), context)

        return rendered, i
