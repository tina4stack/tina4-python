# Tina4 Frond Engine — the runtime (expression evaluation, filters, rendering).
"""
Zero-dependency twig-like template engine.
Supports: variables, filters, if/elseif/else/endif, for/else/endfor,
extends/block, include, macro, set, comments, whitespace control, tests.

The lexer and the parser live in :mod:`tina4_python.frond.parser`, which turns
source into tokens and tokens into an AST. This module consumes that AST: it
owns expression evaluation, the filter set, and rendering. Structure is never
re-derived here — see the parser's module docstring for why.
"""
import os
import re
import html
import hashlib
import json
import secrets
import time
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

from tina4_python.auth import Auth as _FrondAuth, _resolve_secret
# Lexer + parser primitives, re-exported because this module is their historic
# home and callers still reach for them here (``engine._tokenize``,
# ``engine.TEXT``). The four token types are kept as a COMPLETE set even though
# this module only reads TEXT and BLOCK: half a set is a worse surface than a
# whole one, so do not prune VAR/COMMENT as dead code.
from tina4_python.frond.parser import (  # noqa: F401
    TEXT, VAR, BLOCK, COMMENT,
    _tokenize, _strip_tag, parse, collect_macro_nodes,
)


class SafeString(str):
    """Marker subclass of str that bypasses auto-escaping in Frond."""
    pass


# ── Lazy Context Wrapper ──────────────────────────────────────


class _LoopContext(dict):
    """Copy-on-write context overlay for loop iterations.

    Reads fall through to the parent dict; writes go to a local overlay.
    Avoids copying the entire parent context on every loop iteration.
    """
    __slots__ = ("_parent", "_local")

    def __init__(self, parent: dict):
        # Do NOT call super().__init__() — we never populate the base dict
        self._parent = parent
        self._local = {}

    def __getitem__(self, key):
        try:
            return self._local[key]
        except KeyError:
            return self._parent[key]

    def __setitem__(self, key, value):
        self._local[key] = value

    def __contains__(self, key):
        return key in self._local or key in self._parent

    def get(self, key, default=None):
        try:
            return self._local[key]
        except KeyError:
            return self._parent.get(key, default)

    def __iter__(self):
        seen = set(self._local)
        yield from self._local
        for k in self._parent:
            if k not in seen:
                yield k

    def keys(self):
        return list(self)

    def values(self):
        return [self[k] for k in self]

    def items(self):
        return [(k, self[k]) for k in self]

    def __len__(self):
        return len(set(self._local) | set(self._parent))

    def __repr__(self):
        return f"_LoopContext({dict(self.items())})"


# ── Lexer ───────────────────────────────────────────────────────

# Token types
# Sentinel distinguishing "not yet compiled" from a cached None (= compiled and
# found unsupported, use the interpreter) in Frond._compiled_fn.
_COMPILE_UNSET = object()

# ── Pre-compiled regexes for hot-path operations ───────────────
_METHOD_CALL_RE = re.compile(r"^(\w+)\s*\((.*)?\)$", re.DOTALL)
_FUNC_CALL_RE = re.compile(r"^([\w.]+)\s*\((.*)?\)$", re.DOTALL)
_OR_RE = re.compile(r"\s+or\s+")
_AND_RE = re.compile(r"\s+and\s+")
_IS_NOT_RE = re.compile(r"^(.+?)\s+is\s+not\s+(\w+)(.*)$")
_IS_RE = re.compile(r"^(.+?)\s+is\s+(\w+)(.*)$")
_NOT_IN_RE = re.compile(r"^(.+?)\s+not\s+in\s+(.+)$")
_IN_RE = re.compile(r"^(.+?)\s+in\s+(.+)$")
_DIVISIBLE_BY_RE = re.compile(r"\s*by\s*\(\s*(\d+)\s*\)")
_FILTER_ARGS_RE = re.compile(r"(\w+)\s*\((.*)\)$", re.DOTALL)
_FILTER_CMP_RE = re.compile(r"(\w+)\s*(!=|==|>=|<=|>|<)\s*(.+)")
_SET_RE = re.compile(r"set\s+(\w+)\s*=\s*(.+)", re.DOTALL)
_INCLUDE_RE = re.compile(r'include\s+["\'](.+?)["\'](?:\s+with\s+(.+))?')
_LIVE_RE = re.compile(r'live\s+["\'](?P<name>[^"\']+)["\'](?P<rest>.*)$', re.DOTALL)
_LIVE_WS_RE = re.compile(r'ws\s+["\']([^"\']+)["\']')
_LIVE_SRC_RE = re.compile(r'src\s+["\']([^"\']+)["\']')


def _live_attr(value) -> str:
    """Escape a value for use inside an HTML attribute on a live marker."""
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))
_MACRO_RE = re.compile(r"macro\s+(\w+)\s*\(([^)]*)\)")
_FROM_IMPORT_RE = re.compile(r'from\s+["\'](.+?)["\']\s+import\s+(.+)')
_IMPORT_AS_RE = re.compile(r'import\s+["\'](.+?)["\']\s+as\s+(\w+)')
_CACHE_RE = re.compile(r'cache\s+["\'](.+?)["\']\s*(\d+)?')
_AUTOESCAPE_RE = re.compile(r"autoescape\s+(false|true)")
_SPACELESS_RE = re.compile(r">\s+<")
_STRIPTAGS_RE = re.compile(r"<[^>]+>")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXTENDS_RE = re.compile(r"\{%[-\s]*extends\s+[\"'](.+?)[\"']\s*[-]?%\}")
_BLOCK_RE = re.compile(
    r"\{%[-\s]*block\s+(\w+)\s*[-]?%\}(.*?)\{%[-\s]*endblock\s*[-]?%\}",
    re.DOTALL,
)


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


@lru_cache(maxsize=1024)
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
            raw_idx = part[1:-1].strip()
            # Slice syntax: value[1:5], value[:10], value[3:]
            if ":" in raw_idx and not ((raw_idx.startswith('"') and raw_idx.endswith('"')) or (raw_idx.startswith("'") and raw_idx.endswith("'"))):
                idx_clean = raw_idx.strip("'\"")
                slice_parts = idx_clean.split(":", 1)
                s_start = _eval_expr(slice_parts[0].strip(), context) if slice_parts[0].strip() else None
                s_end = _eval_expr(slice_parts[1].strip(), context) if slice_parts[1].strip() else None
                # Convert to int for slicing
                if s_start is not None: s_start = int(s_start)
                if s_end is not None: s_end = int(s_end)
                try:
                    value = value[s_start:s_end]
                except (TypeError, IndexError):
                    return None
            else:
                # Resolve the key: string literal, int literal, or variable
                if (raw_idx.startswith('"') and raw_idx.endswith('"')) or \
                   (raw_idx.startswith("'") and raw_idx.endswith("'")):
                    # String literal: balances["9600.000"]
                    idx = raw_idx[1:-1]
                else:
                    try:
                        # Integer literal: items[0]
                        idx = int(raw_idx)
                    except ValueError:
                        # Expression key: loop.index0 % 2, variable, etc.
                        idx = _eval_expr(raw_idx, context)
                        if idx is None:
                            return None
                try:
                    value = value[idx]
                except (KeyError, IndexError, TypeError):
                    return None
        else:
            # Check if this part is a method call: name(args)
            call_match = _METHOD_CALL_RE.match(part)
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
            elif isinstance(value, (list, tuple)) and part.isdigit():
                # Numeric dot-index into a list/tuple: items.0.name
                idx = int(part)
                try:
                    value = value[idx]
                except IndexError:
                    return None
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
    """Find the first occurrence of *needle* that is not inside quotes, parens, or brackets.

    Returns the index, or -1 if not found outside quotes.
    """
    # Fast path. This function is the hottest thing in a render -- profiling a
    # 20-row loop template showed 415,200 calls to it, 53% of total render time,
    # and the vast majority return -1 because the needle simply is not in the
    # expression. `needle not in expr` is a C-speed scan, so bailing here skips
    # the whole Python character loop below. If the needle is absent entirely it
    # cannot be present outside quotes either, so this is exact, not a heuristic.
    if needle not in expr:
        return -1

    in_q = None
    depth = 0
    bracket_depth = 0
    i = 0
    # Hoisted out of the loop condition: these were re-evaluated on EVERY
    # iteration, which is where 12.4 million len() calls per 300 renders came
    # from (roughly 41,000 per single render).
    needle_len = len(needle)
    last_start = len(expr) - needle_len
    while i <= last_start:
        ch = expr[i]
        if ch in ('"', "'") and depth == 0 and bracket_depth == 0:
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
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
        # startswith(needle, i) rather than expr[i:i + needle_len] == needle:
        # the slice allocated a throwaway string at every character position.
        if depth == 0 and bracket_depth == 0 and expr.startswith(needle, i):
            return i
        i += 1
    return -1


def _split_outside_quotes(expr: str, sep: str) -> list[str]:
    """Split *expr* on *sep* only when *sep* is outside quotes, parens, and brackets."""
    # Fast path, same reasoning as _find_outside_quotes: no separator anywhere
    # means no split, and `in` is a C-speed scan versus a Python character loop.
    if sep not in expr:
        return [expr]

    parts = []
    current_start = 0
    in_q = None
    depth = 0
    bracket_depth = 0
    i = 0
    # Hoisted out of the loop condition -- these were recomputed every iteration.
    sep_len = len(sep)
    last_start = len(expr) - sep_len
    while i <= last_start:
        ch = expr[i]
        if ch in ('"', "'") and depth == 0 and bracket_depth == 0:
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
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
        # startswith avoids allocating a throwaway slice at every position.
        if depth == 0 and bracket_depth == 0 and expr.startswith(sep, i):
            parts.append(expr[current_start:i])
            i += sep_len
            current_start = i
            continue
        i += 1
    parts.append(expr[current_start:])
    return parts


# Operators that bind LOOSER than a filter pipe (Twig: | is nearly the
# tightest operator). Ordered longest-token-first so a two-char op isn't
# masked. Ternary/inline-if are peeled off before this is consulted, but they
# stay in the list so the check is correct if called on a raw expression.
_LOW_PRECEDENCE_OPS = (
    "~", "??", " if ", " and ", " or ", " not in ", " in ", " is not ", " is ",
    "!=", "==", ">=", "<=", " + ", " - ", " * ", " // ", " / ", " % ", " ** ",
)


@lru_cache(maxsize=1024)
def _has_low_precedence_op(expr: str) -> bool:
    """True when *expr* has a top-level operator that binds LOOSER than a
    filter pipe. When present, a naive top-level split on ``|`` is wrong (the
    pipe binds to a sub-term, not the whole expression), so the expression must
    be routed through :func:`_eval_expr`, which resolves the pipe at the
    correct (primary) precedence at any depth (issue #171).

    The answer depends only on the expression string (a top-level operator scan),
    so it is memoized — the same bounded LRU pattern as ``_split_dotted`` — to
    stop re-scanning the same invariant expression on every render/loop iteration
    from :meth:`Frond._eval_var_inner`."""
    return any(_find_outside_quotes(expr, op) >= 0 for op in _LOW_PRECEDENCE_OPS)


@lru_cache(maxsize=1024)
def _expr_descriptor(expr: str, has_filters: bool):
    """Compute the render-independent STRUCTURAL descriptor for an expression.

    Mirrors the branch-detection order of :func:`_eval_expr` exactly, but records
    the decision + split points instead of resolving any values, so that repeat
    renders of the same expression string (every loop iteration, every request)
    skip the string scanning — operator detection via ``_find_outside_quotes``,
    the ternary/inline-if split, the ``~`` concat split, the filter-chain split —
    and go straight to value resolution against the live context.

    The descriptor contains NO context value; it is a pure function of the
    (already-stripped) expression string and ``has_filters`` (whether a filter
    applier is threaded, which is the one thing that gates the pipe step). That
    render-independence is the correctness invariant — value lookups and filter
    application still run on every :func:`_eval_expr` call. Bounded by ``lru_cache``
    (same 1024-entry cap as ``_split_dotted``/``_split_on_pipe``) so dynamically
    built expression strings cannot grow it without limit.

    Returns a ``(kind, *payload)`` tuple; ``("tail",)`` means "no top-level
    operator" — fall through to the function-call / ``_resolve`` path, which stays
    inline in :func:`_eval_expr` because its callable check is context-dependent.
    """
    # Array literal: ["a", "b", "c"] or [1, 2, 3]
    if expr.startswith("[") and expr.endswith("]"):
        inner = expr[1:-1].strip()
        if not inner:
            return ("array", [])
        # Split on commas, respecting quotes
        items = []
        current = ""
        in_q = None
        depth = 0
        for ch in inner:
            if ch in ('"', "'") and in_q is None:
                in_q = ch
                current += ch
            elif ch == in_q:
                in_q = None
                current += ch
            elif ch == "[" and in_q is None:
                depth += 1
                current += ch
            elif ch == "]" and in_q is None:
                depth -= 1
                current += ch
            elif ch == "," and in_q is None and depth == 0:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(current.strip())
        return ("array", items)

    # Dict literal: {"key": "value", ...}
    if expr.startswith("{") and expr.endswith("}"):
        inner = expr[1:-1].strip()
        if not inner:
            return ("dict", [])
        # Split on commas, respecting quotes and nesting
        pairs = []
        current = ""
        in_q = None
        depth = 0
        for ch in inner:
            if ch in ('"', "'") and in_q is None:
                in_q = ch
                current += ch
            elif ch == in_q:
                in_q = None
                current += ch
            elif ch in ("{", "[") and in_q is None:
                depth += 1
                current += ch
            elif ch in ("}", "]") and in_q is None:
                depth -= 1
                current += ch
            elif ch == "," and in_q is None and depth == 0:
                pairs.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            pairs.append(current.strip())
        kv = []
        for pair in pairs:
            colon_pos = _find_outside_quotes(pair, ":")
            if colon_pos > 0:
                kv.append((pair[:colon_pos].strip(), pair[colon_pos + 1:].strip()))
        return ("dict", kv)

    # String literal — only match if the entire expression is a single quoted
    # string with no unescaped matching quotes inside (avoids catching
    # expressions like 'yes' if x else 'no').
    if len(expr) >= 2:
        q = expr[0]
        if q in ('"', "'") and expr.endswith(q) and q not in expr[1:-1]:
            return ("str", expr[1:-1])

    # Parenthesized sub-expression: (expr) — strip parens and evaluate inner
    if expr.startswith("(") and expr.endswith(")"):
        # Verify matching parens (not just any parens)
        depth = 0
        matched = True
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i < len(expr) - 1:
                matched = False
                break
        if matched:
            return ("paren", expr[1:-1])

    # Ternary: condition ? "yes" : "no" — quote-aware
    q_pos = _find_outside_quotes(expr, "?")
    if q_pos > 0:
        rest = expr[q_pos + 1:]
        c_pos = _find_outside_quotes(rest, ":")
        if c_pos >= 0:
            return ("ternary", expr[:q_pos].strip(),
                    rest[:c_pos].strip(), rest[c_pos + 1:].strip())

    # Jinja2-style inline if: value if condition else other_value — quote-aware
    if_pos = _find_outside_quotes(expr, " if ")
    if if_pos >= 0:
        else_pos = _find_outside_quotes(expr, " else ")
        if else_pos > if_pos:
            return ("inline_if", expr[:if_pos].strip(),
                    expr[if_pos + 4:else_pos].strip(), expr[else_pos + 6:].strip())

    # Null coalescing: value ?? "default"
    nc_pos = _find_outside_quotes(expr, "??")
    if nc_pos >= 0:
        return ("coalesce", expr[:nc_pos].strip(), expr[nc_pos + 2:].strip())

    # String concatenation with ~
    tilde_pos = _find_outside_quotes(expr, "~")
    if tilde_pos >= 0:
        return ("concat", _split_outside_quotes(expr, "~"))

    # Comparison operators for if conditions
    for op in (" not in ", " in ", " is not ", " is ", "!=", "==", ">=", "<=", ">", "<", " and ", " or ", " not "):
        if _find_outside_quotes(expr, op) >= 0:
            return ("comparison",)

    # Arithmetic operators: +, -, *, /, //, %, ** (lowest to highest precedence)
    # Check for +/- first (lower precedence), then *//, then %, then **
    for op in (" + ", " - ", " * ", " // ", " / ", " % ", " ** "):
        pos = _find_outside_quotes(expr, op)
        if pos >= 0:
            return ("arith", op.strip(),
                    expr[:pos].strip(), expr[pos + len(op):].strip())

    # Filter pipe (Twig ``|``): the highest-precedence binary operator, so it
    # is resolved LAST here — after ~, comparisons and arithmetic have already
    # been split off — which makes ``|`` bind TIGHTER than all of them at any
    # nesting depth (issue #171). Only fires when the engine threaded its bound
    # applier in; the many internal callers pass None and skip it. A pipe inside
    # quotes/parens is not top-level (``_parse_filter_chain`` respects both), so
    # ``{{ (x|f) ~ y }}`` and ``{{ items|join(' ~ ') }}`` resolve correctly.
    if has_filters:
        var_name, pipe_filters = _parse_filter_chain(expr)
        if pipe_filters:
            return ("pipe", var_name, pipe_filters)

    # No top-level operator — function call / _resolve tail (kept inline in
    # _eval_expr because its callable check is context-dependent).
    return ("tail",)


def _eval_expr(expr: str, context: dict, apply_filters=None):
    """Evaluate a full expression (with ~, ternary, ??, comparisons).

    ``apply_filters`` is the engine's bound filter applier
    (``Frond._apply_filters``). When supplied, a filter pipe (``x|filter``) is
    resolved HERE — after the lower-precedence operators (``~``, comparisons,
    arithmetic, ternary) have been split off — so ``|`` binds tighter than them
    at any nesting depth (issue #171, Twig precedence). It is threaded through
    every recursive call so pipes resolve inside concat operands, ternary
    branches, parentheses, arithmetic, and function-call args. When ``None``
    (the many internal callers that never contain a pipe) the pipe step is a
    no-op and behaviour is exactly as before.
    """
    expr = expr.strip()

    # Structural analysis (which top-level operator this expression splits on
    # and where) is invariant across renders, so it is computed once and cached
    # by _expr_descriptor keyed on (expr, has_filters). Only the value
    # resolution below runs every call. The dispatch order below is IDENTICAL to
    # the linear branch order it replaced — same precedence, same behaviour.
    desc = _expr_descriptor(expr, apply_filters is not None)
    kind = desc[0]

    # Array literal: ["a", "b", "c"] or [1, 2, 3]
    if kind == "array":
        return [_eval_expr(item, context, apply_filters) for item in desc[1]]

    # Dict literal: {"key": "value", ...}
    if kind == "dict":
        result = {}
        for key_expr, val_expr in desc[1]:
            key = _eval_expr(key_expr, context, apply_filters)
            val = _eval_expr(val_expr, context, apply_filters)
            result[key] = val
        return result

    # String literal
    if kind == "str":
        return desc[1]

    # Parenthesized sub-expression: (expr) — evaluate inner
    if kind == "paren":
        return _eval_expr(desc[1], context, apply_filters)

    # Ternary: condition ? "yes" : "no"
    if kind == "ternary":
        _, cond_part, true_part, false_part = desc
        cond = _eval_expr(cond_part, context, apply_filters)
        if cond:
            return _eval_expr(true_part, context, apply_filters)
        return _eval_expr(false_part, context, apply_filters)

    # Jinja2-style inline if: value if condition else other_value
    if kind == "inline_if":
        _, value_part, cond_part, else_part = desc
        cond = _eval_expr(cond_part, context, apply_filters)
        if cond:
            return _eval_expr(value_part, context, apply_filters)
        return _eval_expr(else_part, context, apply_filters)

    # Null coalescing: value ?? "default"
    if kind == "coalesce":
        _, left, right = desc
        val = _eval_expr(left, context, apply_filters)
        if val is None:
            return _eval_expr(right, context, apply_filters)
        return val

    # String concatenation with ~
    if kind == "concat":
        return "".join(str(_eval_expr(p, context, apply_filters) or "") for p in desc[1])

    # Comparison operators for if conditions
    if kind == "comparison":
        return _eval_comparison(expr, context)

    # Arithmetic operators: +, -, *, /, //, %, **
    if kind == "arith":
        _, op_s, left, right = desc
        l_val = _eval_expr(left, context, apply_filters)
        r_val = _eval_expr(right, context, apply_filters)
        try:
            l_num = float(l_val) if l_val is not None else 0
            r_num = float(r_val) if r_val is not None else 0
            # Preserve int type when both operands are int-like
            if l_num == int(l_num) and r_num == int(r_num) and op_s not in ("/",):
                l_num, r_num = int(l_num), int(r_num)
            if op_s == "+":
                return l_num + r_num
            elif op_s == "-":
                return l_num - r_num
            elif op_s == "*":
                return l_num * r_num
            elif op_s == "//":
                return l_num // r_num if r_num != 0 else 0
            elif op_s == "/":
                return l_num / r_num if r_num != 0 else 0
            elif op_s == "%":
                return l_num % r_num if r_num != 0 else 0
            elif op_s == "**":
                return l_num ** r_num
        except (ValueError, TypeError):
            return None

    # Filter pipe (Twig ``|``): the highest-precedence binary operator, resolved
    # only when the engine threaded its bound applier in (has_filters). See
    # _expr_descriptor / issue #171 for the precedence rationale.
    if kind == "pipe":
        _, var_name, pipe_filters = desc
        base = _eval_expr(var_name, context, apply_filters)
        return apply_filters(base, pipe_filters, context)

    # kind == "tail": no top-level operator — fall through to the
    # function-call / _resolve path below.

    # Function call: name("arg1", "arg2") or obj.method("arg1")
    fn_match = _FUNC_CALL_RE.match(expr)
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
                eval_args = [_eval_expr(a, context, apply_filters) for a in parts]
            else:
                eval_args = []
            return fn(*eval_args)

    return _resolve(expr, context)


def _eval_comparison(expr: str, context: dict, eval_fn=None):
    """Evaluate comparison/logical expressions.

    Args:
        eval_fn: Optional evaluator function for sub-expressions.  When
                 provided by the Frond engine this will be ``_eval_var_raw``
                 which understands filter pipes (``items|length``).  When
                 ``None``, falls back to ``_eval_expr`` (no pipe support).
    """
    if eval_fn is None:
        eval_fn = _eval_expr
    expr = expr.strip()

    # Handle 'not' prefix
    if expr.startswith("not "):
        return not _eval_comparison(expr[4:], context, eval_fn)

    # 'and' / 'or' (lowest precedence)
    # Split on ' or ' first (lower precedence)
    or_parts = _OR_RE.split(expr)
    if len(or_parts) > 1:
        return any(_eval_comparison(p, context, eval_fn) for p in or_parts)

    and_parts = _AND_RE.split(expr)
    if len(and_parts) > 1:
        return all(_eval_comparison(p, context, eval_fn) for p in and_parts)

    # 'is not' test
    m = _IS_NOT_RE.match(expr)
    if m:
        return not _eval_test(m.group(1).strip(), m.group(2), m.group(3).strip(), context, eval_fn)

    # 'is' test
    m = _IS_RE.match(expr)
    if m:
        return _eval_test(m.group(1).strip(), m.group(2), m.group(3).strip(), context, eval_fn)

    # 'not in'
    m = _NOT_IN_RE.match(expr)
    if m:
        val = eval_fn(m.group(1).strip(), context)
        collection = eval_fn(m.group(2).strip(), context)
        return val not in (collection or [])

    # 'in'
    m = _IN_RE.match(expr)
    if m:
        val = eval_fn(m.group(1).strip(), context)
        collection = eval_fn(m.group(2).strip(), context)
        return val in (collection or [])

    # Binary operators
    for op, fn in [("!=", lambda a, b: a != b), ("==", lambda a, b: a == b),
                    (">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b),
                    (">", lambda a, b: a > b), ("<", lambda a, b: a < b)]:
        if op in expr:
            left, _, right = expr.partition(op)
            l = eval_fn(left.strip(), context)
            r = eval_fn(right.strip(), context)
            try:
                return fn(l, r)
            except TypeError:
                return False

    # Fall through to simple eval
    val = eval_fn(expr, context)
    return bool(val) if val is not None else False


def _eval_test(value_expr: str, test_name: str, args: str, context: dict, eval_fn=None) -> bool:
    """Evaluate an 'is' test."""
    if eval_fn is None:
        eval_fn = _eval_expr
    val = eval_fn(value_expr, context)

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

    # Merge in custom tests registered via add_test(). They live on the Frond
    # instance, reachable through the bound eval_fn (eval_fn.__self__._tests).
    # Custom registrations override built-ins, matching PHP/Ruby/Node.
    custom = getattr(getattr(eval_fn, "__self__", None), "_tests", None)
    if custom:
        tests = {**tests, **custom}

    # 'divisible by(n)'
    if test_name == "divisible":
        m = _DIVISIBLE_BY_RE.match(args)
        if m:
            n = int(m.group(1))
            return isinstance(val, int) and val % n == 0
        return False

    if test_name in tests:
        return tests[test_name](val)

    return False


# ── Filters ─────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
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


def _split_filter_name_and_path(fname: str) -> tuple[str, str]:
    """Split `first.groupSummary` into (`first`, `groupSummary`).

    Returns (fname, "") when no structural `.` is present. The split
    point must be outside parens, brackets, braces, and quotes so
    filter args like ``number_format(1.5)`` or ``date("Y.m.d")`` don't
    trip false splits.

    Used by the filter-application loops to support `{{ x | first.foo }}`
    syntax — apply the filter, then traverse the property path on the
    filter's result. Parity with tina4-php's findDotOutsideParens().
    """
    depth = 0
    in_q = None
    i = 0
    n = len(fname)
    while i < n:
        ch = fname[i]
        if in_q is not None:
            if ch == in_q and (i == 0 or fname[i - 1] != "\\"):
                in_q = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_q = ch
        elif ch in ("(", "[", "{"):
            depth += 1
        elif ch in (")", "]", "}"):
            depth -= 1
        elif ch == "." and depth == 0:
            return fname[:i], fname[i + 1:]
        i += 1
    return fname, ""


def _parse_filter_chain(expr: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Parse 'variable | filter1 | filter2(arg)' into (variable, [(name, args)])."""
    parts = _split_on_pipe(expr)
    variable = parts[0].strip()
    filters = []

    for f in parts[1:]:
        f = f.strip()
        m = _FILTER_ARGS_RE.match(f)
        if m:
            name = m.group(1)
            raw_args = m.group(2).strip()
            # Simple arg parsing (handles strings and numbers)
            args = _parse_args(raw_args) if raw_args else []
            filters.append((name, args))
        else:
            filters.append((f.strip(), []))

    return variable, filters


def _coerce_arg(s: str):
    """Try to convert a string argument to a Python object (dict, list, number, bool).

    Returns the original string unchanged if no conversion applies.
    """
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception:
            pass
    if s.startswith("[") and s.endswith("]"):
        try:
            return json.loads(s)
        except Exception:
            pass
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "None", "none"):
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    return s


class _Ref:
    """A filter argument that was an UNQUOTED bareword — i.e. a variable
    reference (or dotted/bracket path), not a literal. Resolved against the
    render context at apply-time so e.g. `{{ '%.2f' | format(price) }}` binds
    `price` to its value. Quoted literals (`default('fb')`) are kept as plain
    strings and never resolved."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name


def _parse_args(raw: str) -> list:
    """Parse filter arguments, respecting quoted strings, braces, and backslash escapes.

    Quoted args become literal strings; numbers/bools/null/JSON are coerced to
    their Python types; an unquoted bareword becomes a `_Ref` (a variable
    reference resolved against the context when the filter runs)."""
    tokens = []
    current = ""
    in_quote = None
    depth = 0

    for ch in raw:
        if ch in ('"', "'") and not in_quote:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch in ("(", "{", "[") and not in_quote:
            depth += 1
        elif ch in (")", "}", "]") and not in_quote:
            depth -= 1
        elif ch == "," and not in_quote and depth == 0:
            tokens.append(current.strip())
            current = ""
            continue
        current += ch

    if current.strip():
        tokens.append(current.strip())

    out = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ('"', "'"):
            out.append(_strip_outer_quotes(tok))  # quoted literal → string
        else:
            coerced = _coerce_arg(tok)
            # A bareword that stayed a string is a variable/expression
            # reference (e.g. `n`, `user.age`) — resolve it at apply-time.
            if isinstance(coerced, str) and tok:
                out.append(_Ref(tok))
            else:
                out.append(coerced)
    return out


def _strip_outer_quotes(s: str) -> str:
    """Remove only the outermost matching quotes from a string.

    'hello' → hello, "world" → world, \\'  → \\' (no matching quotes).
    Handles backslash escapes inside: "\\'" → \\' (preserves backslash).
    """
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        inner = s[1:-1]
        # Process backslash escapes: \' → ', \\" → ", \\\\ → \\
        result = []
        i = 0
        while i < len(inner):
            if inner[i] == '\\' and i + 1 < len(inner):
                result.append(inner[i + 1])
                i += 2
            else:
                result.append(inner[i])
                i += 1
        return "".join(result)
    return s


def _dict_replace(s: str, mapping: dict) -> str:
    """Apply multiple replacements from a dict (Twig-style replace filter)."""
    for old, new in mapping.items():
        s = s.replace(str(old), str(new))
    return s


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
    "replace": lambda v, *a: (
        _dict_replace(str(v), a[0]) if len(a) == 1 and isinstance(a[0], dict)
        else str(v).replace(a[0], a[1]) if len(a) >= 2
        else str(v)
    ),
    "default": lambda v, *a: v if v is not None and v != "" else (a[0] if a else ""),
    "raw": lambda v, *a: v,  # Mark as safe (no escaping)
    "safe": lambda v, *a: v,
    "escape": lambda v, *a: SafeString(html.escape(str(v))),
    "e": lambda v, *a: SafeString(html.escape(str(v))),
    "striptags": lambda v, *a: _STRIPTAGS_RE.sub("", str(v)),
    "nl2br": lambda v, *a: SafeString(html.escape(str(v)).replace("\n", "<br />\n")),
    "abs": lambda v, *a: abs(v) if isinstance(v, (int, float)) else v,
    "round": lambda v, *a: round(float(v), int(a[0])) if a else int(round(float(v))),
    "int": lambda v, *a: int(v) if v else 0,
    "float": lambda v, *a: float(v) if v else 0.0,
    "string": lambda v, *a: str(v),
    "json_encode": lambda v, *a: json.dumps(v, separators=(",", ":")),
    "to_json": lambda v, *a: SafeString(json.dumps(v, default=str, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")),
    "tojson": lambda v, *a: SafeString(json.dumps(v, default=str, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")),
    "js_escape": lambda v, *a: SafeString(str(v).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")),
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
    "number_format": lambda v, *a: _number_format(v, *a),
    "date": lambda v, *a: _date_filter(v, a[0] if a else "%Y-%m-%d"),
    "truncate": lambda v, *a: (str(v)[:int(a[0])] + "...") if a and len(str(v)) > int(a[0]) else str(v),
    "wordwrap": lambda v, *a: _wordwrap(str(v), int(a[0]) if a else 75),
    "slug": lambda v, *a: _SLUG_RE.sub("-", str(v).lower()).strip("-"),
    "md5": lambda v, *a: hashlib.md5(str(v).encode()).hexdigest(),
    "sha256": lambda v, *a: hashlib.sha256(str(v).encode()).hexdigest(),
    "base64_encode": lambda v, *a: __import__("base64").b64encode(v if isinstance(v, bytes) else str(v).encode()).decode(),
    "base64encode": lambda v, *a: __import__("base64").b64encode(v if isinstance(v, bytes) else str(v).encode()).decode(),
    "base64_decode": lambda v, *a: __import__("base64").b64decode(str(v)).decode(),
    "base64decode": lambda v, *a: __import__("base64").b64decode(str(v)).decode(),
    "data_uri": lambda v, *a: f"data:{v.get('type', 'application/octet-stream')};base64,{__import__('base64').b64encode(v['content'] if isinstance(v['content'], bytes) else v['content'].encode()).decode()}" if isinstance(v, dict) else str(v),
    "url_encode": lambda v, *a: __import__("urllib.parse", fromlist=["quote"]).quote(str(v)),
    "format": lambda v, *a: str(v) % tuple(a) if a else str(v),
    "dump": lambda v, *a: _render_dump(v),
    "form_token": lambda v, *a: _form_token(str(v) if v else ""),
}


def _number_format(value, decimals=0, decimal_point=".", thousands_sep=","):
    """Twig ``number_format(decimals, decimalPoint, thousandsSep)`` (issue #170).

    Formats a number with ``decimals`` fractional digits, ``decimal_point`` as
    the decimal separator, and ``thousands_sep`` grouping the integer part in
    threes. The defaults reproduce the pre-3.13.72 output exactly
    (``number_format(2)`` -> ``"1,234.50"``) so one-arg templates are
    unchanged; passing all three enables localized formats
    (``number_format(2, ',', '.')`` -> ``"1.234,50"``).

    Python is the master implementation — PHP/Ruby/Node mirror this signature,
    these defaults, and these outputs.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    try:
        places = int(decimals)
    except (TypeError, ValueError):
        places = 0

    fixed = f"{abs(number):.{places}f}"
    int_part, _, frac_part = fixed.partition(".")

    # Group the integer part into threes with the requested separator. Building
    # it from scratch (rather than reformatting Python's ``,`` grouping) means
    # the decimal and thousands separators never collide during a swap.
    grouped = ""
    for offset, digit in enumerate(reversed(int_part)):
        if offset and offset % 3 == 0:
            grouped = str(thousands_sep) + grouped
        grouped = digit + grouped

    sign = "-" if number < 0 else ""
    if places > 0:
        return f"{sign}{grouped}{decimal_point}{frac_part}"
    return f"{sign}{grouped}"


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


def _generate_form_jwt(descriptor: str = "", session_id: str = "") -> str:
    """Generate a JWT form token string.

    Args:
        descriptor: Optional string to enrich the token payload.
            - Empty or omitted: payload is ``{"type": "form"}``
            - ``"admin_panel"``: payload is ``{"type": "form", "context": "admin_panel"}``
            - ``"checkout|order_123"``: payload is ``{"type": "form", "context": "checkout", "ref": "order_123"}``
        session_id: Optional session ID to bind the token to a specific session.

    Returns:
        The raw JWT string.
    """
    payload = {"type": "form", "nonce": secrets.token_hex(8)}
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

    secret = _resolve_secret()
    ttl = int(os.environ.get("TINA4_TOKEN_EXPIRES_IN", "60"))
    auth = _FrondAuth(secret=secret, expires_in=ttl)
    return auth.get_token(payload)


def _render_dump(value) -> str:
    """Render a value as a pre-formatted repr() wrapped in <pre> tags.

    Gated on ``TINA4_DEBUG=true``. In production (``TINA4_DEBUG`` unset or
    false) this returns an empty ``SafeString`` to avoid leaking internal
    state, object shapes, or sensitive values into rendered HTML.

    Shared by the ``{{ value|dump }}`` filter and the ``{{ dump(value) }}``
    global function so both produce identical output and obey the same
    gating.
    """
    if os.environ.get("TINA4_DEBUG", "").lower() != "true":
        return SafeString("")
    dumped = repr(value)
    escaped = html.escape(dumped, quote=True)
    return SafeString(f"<pre>{escaped}</pre>")


def _form_token(descriptor: str = "", session_id: str = "") -> str:
    """Generate a JWT form token and return a hidden input element.

    Usage in templates: ``{{ form_token() }}`` or ``{{ "context" | form_token }}``

    Returns:
        ``<input type="hidden" name="formToken" value="TOKEN">``
    """
    token = _generate_form_jwt(descriptor, session_id)
    return SafeString(f'<input type="hidden" name="formToken" value="{token}">')


def _form_token_value(descriptor: str = "", session_id: str = "") -> str:
    """Generate a JWT form token and return just the raw token string.

    Usage in templates: ``{{ formTokenValue("Sleek") }}``

    Returns:
        The raw JWT string (no HTML wrapper).
    """
    return SafeString(_generate_form_jwt(descriptor, session_id))


# Module-level session ID holder — set by the server before rendering templates
# so that form_token() can bind tokens to the current session.
_form_token_session_id: str = ""


def set_form_token_session_id(session_id: str) -> None:
    """Set the session ID used by form_token() for CSRF session binding."""
    global _form_token_session_id
    _form_token_session_id = session_id or ""


# ── Frond Engine ────────────────────────────────────────────────


# ── ClassOrInstance method descriptor ──────────────────────────────────────
#
# Frond.add_filter / Frond.add_global / Frond.add_test must work BOTH as
# a classmethod (``Frond.add_filter("money", fn)`` — the documented form,
# convenient at app-startup before any instance exists) AND as an instance
# method (``engine.add_filter("money", fn)`` — the existing form, which
# also updates the live instance's local registry).
#
# A plain @classmethod loses the live-instance update; a plain instance
# method blocks the class-level call. This descriptor wraps a function so
# it receives BOTH ``cls`` and ``instance`` (instance is None when called
# on the class) — the function can update class state always and instance
# state when applicable.

class _ClassOrInstanceMethod:
    def __init__(self, func):
        self.func = func
        self.__doc__ = func.__doc__
        self.__name__ = func.__name__

    def __get__(self, instance, owner):
        def wrapper(*args, **kwargs):
            return self.func(owner, instance, *args, **kwargs)
        wrapper.__doc__ = self.__doc__
        wrapper.__name__ = self.__name__
        return wrapper


class Frond:
    """Twig-like template engine with sandboxing and fragment caching."""

    # ── Class-level registries ──────────────────────────────────
    # Persist globals, filters, and tests across hot-reloads.
    # When a module creates ``frond = Frond()`` and a hot-reload
    # re-executes that line, the NEW instance inherits everything
    # previously registered via add_global / add_filter / add_test.
    _class_globals: dict = {}
    _class_filters: dict = {}
    _class_tests: dict = {}
    # Live blocks: name -> body template source (registered when a {% live %}
    # block renders); name -> data provider (registered via @live_source).
    _class_live_fragments: dict = {}
    _class_live_sources: dict = {}
    _class_live_ws_paths: dict = {}

    @classmethod
    def clear_registry(cls):
        """Clear the class-level globals/filters/tests registries.

        Useful in test fixtures to prevent leaking state between tests.
        Does NOT affect built-in filters or globals — only user-registered ones.
        """
        cls._class_globals.clear()
        cls._class_filters.clear()
        cls._class_tests.clear()
        cls._class_live_fragments.clear()
        cls._class_live_sources.clear()
        cls._class_live_ws_paths.clear()

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
        # Token + AST pre-compilation cache. The AST is cached ALONGSIDE the
        # tokens (mirroring PHP's {'tokens', 'ast'}) so a template is tokenized
        # and parsed once: the tokens stay for the extends path, which
        # reconstructs source from them, and the AST is what actually renders.
        self._compiled: dict[str, tuple[list, list, float]] = {}  # {name: (tokens, ast, expires_at)}
        self._compiled_strings: dict[str, tuple[list, list]] = {}  # {md5_hash: (tokens, ast)}
        # AOT-compiled render functions (ADR-0001): {compile_key: callable | None}.
        # The value is the compiled ``_rendered(engine, ctx)`` callable, or None
        # when the template used a construct the compiler falls back on (cached
        # so we do not re-attempt a compile that already returned None). Keyed
        # the same way the token cache is (template name in prod, md5 for
        # strings, a source hash in dev so an edit recompiles).
        self._compiled_fn: dict[str, object] = {}
        # Filter chain cache: expr → (var_name, [(filter_name, [args])])
        self._filter_chain_cache: dict[str, tuple[str, list]] = {}
        # Compile-cache TTL — TINA4_TEMPLATE_CACHE_TTL in seconds.
        # 0 (default) means "no expiry" so the existing permanent-cache
        # behaviour is preserved. Anything >0 forces re-tokenisation
        # after that many seconds, which is handy for long-running
        # workers that want to pick up template edits without a full
        # restart but without paying the dev-mode "always re-read" tax.
        try:
            self._cache_ttl: int = int(os.environ.get("TINA4_TEMPLATE_CACHE_TTL", "0"))
        except (TypeError, ValueError):
            self._cache_ttl = 0

        # Built-in global functions
        self._globals["form_token"] = _form_token
        self._globals["formTokenValue"] = _form_token_value
        self._globals["form_token_value"] = _form_token_value

        # Debug helper: {{ dump(x) }} — gated on TINA4_DEBUG=true.
        # Both this global and the |dump filter call _render_dump() which
        # returns an empty string in production so dump never leaks state.
        self._globals["dump"] = _render_dump

        # Restore any globals/filters/tests registered on prior instances.
        # This is the key to surviving hot-reloads: app.py calls
        # frond.add_global("t", _t) once, the class remembers it, and
        # every future Frond() instance gets it automatically.
        self._globals.update(Frond._class_globals)
        self._filters.update(Frond._class_filters)
        self._tests.update(Frond._class_tests)

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

    @_ClassOrInstanceMethod
    def add_filter(cls, instance, name: str, fn):
        """Register a custom filter.

        Callable as a classmethod (``Frond.add_filter("money", fn)``) or
        as an instance method (``engine.add_filter("money", fn)``). The
        filter is persisted at class level so new instances created by
        hot-reload inherit it automatically; when called on an existing
        instance, that instance's local filter map also receives the
        addition immediately.
        """
        cls._class_filters[name] = fn
        if instance is not None:
            instance._filters[name] = fn

    @_ClassOrInstanceMethod
    def add_global(cls, instance, name: str, value):
        """Register a global variable available in all templates.

        Callable as classmethod or instance method. See ``add_filter`` for the
        dual-call semantics.
        """
        cls._class_globals[name] = value
        if instance is not None:
            instance._globals[name] = value

    @_ClassOrInstanceMethod
    def add_test(cls, instance, name: str, fn):
        """Register a custom test (``{% if x is positive %}``).

        Callable as classmethod or instance method. See ``add_filter`` for the
        dual-call semantics.
        """
        cls._class_tests[name] = fn
        if instance is not None:
            instance._tests[name] = fn

    def render(self, template: str, data: dict = None) -> str:
        """Render a template with data. Uses token caching for performance."""
        context = {**self._globals, **(data or {})}

        # Resolve file path and check mtime for cache validity
        path = self.template_dir / template
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")

        debug_mode = os.environ.get("TINA4_DEBUG", "").lower() == "true"

        if not debug_mode:
            # Production: cached. If TINA4_TEMPLATE_CACHE_TTL > 0 we honour
            # the expiry; otherwise the cache is permanent (legacy behaviour).
            cached = self._compiled.get(template)
            if cached is not None:
                tokens_cached, ast_cached, expires_at = cached
                if self._cache_ttl <= 0 or time.time() < expires_at:
                    return self._execute_cached(tokens_cached, ast_cached, context,
                                                template, compile_key=template)

        # Dev mode (or expired entry): re-read, re-tokenize and re-parse.
        # mtime-based invalidation doesn't catch changes to included/extended
        # templates (parent or partial changes don't update the caller's mtime).
        source = path.read_text(encoding="utf-8")
        tokens = _tokenize(source)
        ast = parse(tokens)
        if not debug_mode:
            expires_at = (time.time() + self._cache_ttl) if self._cache_ttl > 0 else 0
            self._compiled[template] = (tokens, ast, expires_at)
            # Prod: the compiled fn is stable per template name (files don't
            # change under a running prod worker), so key it by name.
            return self._execute_with_source(source, tokens, ast, context, template,
                                             compile_key=template)
        # Dev: the source is re-read every render, so key the compiled fn by a
        # hash of THIS source. An edit produces a new hash and recompiles —
        # dev visibility (hot-reload) stays intact, and the compiled path is
        # still exercised so it never silently drifts from the interpreter.
        dev_key = "dev:" + hashlib.md5(source.encode()).hexdigest()
        return self._execute_with_source(source, tokens, ast, context, template,
                                         compile_key=dev_key)

    def render_string(self, source: str, data: dict = None) -> str:
        """Render a template string directly. Uses token+AST caching."""
        context = {**self._globals, **(data or {})}

        key = hashlib.md5(source.encode()).hexdigest()
        cached = self._compiled_strings.get(key)
        if cached is None:
            tokens = _tokenize(source)
            cached = (tokens, parse(tokens))
            self._compiled_strings[key] = cached
        return self._execute_cached(cached[0], cached[1], context, compile_key=key)

    def clear_cache(self):
        """Clear all compiled template caches."""
        self._compiled.clear()
        self._compiled_strings.clear()
        self._compiled_fn.clear()
        self._filter_chain_cache.clear()

    def render_dump(self, v) -> str:
        """Render a debug dump of a value as HTML — parity with PHP/Ruby.

        Gated on TINA4_DEBUG=true. Returns empty string in production.
        """
        return _render_dump(v)

    def _load(self, name: str) -> str:
        """Load template source from file."""
        path = self.template_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _get_compiled(self, compile_key: str, ast: list):
        """Return the AOT-compiled ``_rendered(engine, ctx)`` for this template,
        or ``None`` to signal the caller should use the interpreter.

        Compiles the AST once per key and caches the result (a ``None`` fallback
        too, so an unsupported template is not re-analysed on every render).
        Never returns a compiled fn in sandbox mode — the sandbox
        tag/filter/var gates are enforced on the interpreter path, so a
        sandboxed engine always interprets. ``compile_template`` itself never
        raises (it returns ``None`` on any unsupported construct or
        codegen/compile error), so a render is never broken by the compiler.
        """
        if compile_key is None or self._sandbox:
            return None
        cached = self._compiled_fn.get(compile_key, _COMPILE_UNSET)
        if cached is not _COMPILE_UNSET:
            return cached
        from tina4_python.frond.compiler import compile_template
        fn = compile_template(ast)
        self._compiled_fn[compile_key] = fn
        return fn

    def _execute_cached(self, tokens: list, ast: list, context: dict,
                        template: str = None, compile_key: str = None) -> str:
        """Execute a pre-parsed template against context.

        Checks for extends in tokens; if found, falls back to source-based
        execution (extends requires re-reading parent template — the tokens are
        pristine, so the source reconstruction below is exact). Otherwise
        prefers the AOT-compiled render fn when the template compiled.
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
        compiled = self._get_compiled(compile_key, ast)
        if compiled is not None:
            return compiled(self, context)
        return self._render_nodes(ast, context)

    def _execute_with_source(self, source: str, tokens: list, ast: list, context: dict,
                             template: str = None, compile_key: str = None) -> str:
        """Execute with the source, its tokens and its AST all available."""
        # Handle extends first
        extends_match = _EXTENDS_RE.match(source.lstrip())
        if extends_match:
            parent_name = extends_match.group(1)
            parent_source = self._load(parent_name)
            child_blocks = self._extract_blocks(source)
            return self._render_with_blocks(parent_source, context, child_blocks)

        compiled = self._get_compiled(compile_key, ast)
        if compiled is not None:
            return compiled(self, context)
        return self._render_nodes(ast, context)

    def _execute(self, source: str, context: dict) -> str:
        """Execute template source against context."""
        # Handle extends first
        extends_match = _EXTENDS_RE.match(source.lstrip())
        if extends_match:
            parent_name = extends_match.group(1)
            parent_source = self._load(parent_name)

            # Extract blocks from child
            child_blocks = self._extract_blocks(source)

            # Render parent with child blocks
            return self._render_with_blocks(parent_source, context, child_blocks)

        return self._render_tokens(_tokenize(source), context)

    def _extract_blocks(self, source: str) -> dict[str, str]:
        """Extract {% block name %}...{% endblock %} from source.

        Handles nested blocks correctly by counting depth rather than using
        a single non-greedy regex (which fails on nested block tags).
        """
        blocks = {}
        block_open = re.compile(r"\{%[-\s]*block\s+(\w+)\s*[-]?%\}")
        block_close = re.compile(r"\{%[-\s]*endblock\s*[-]?%\}")

        pos = 0
        while pos < len(source):
            m_open = block_open.search(source, pos)
            if not m_open:
                break

            name = m_open.group(1)
            content_start = m_open.end()
            depth = 1
            scan = content_start

            while depth > 0 and scan < len(source):
                next_open = block_open.search(source, scan)
                next_close = block_close.search(source, scan)

                if next_close is None:
                    break  # malformed — no matching endblock

                if next_open and next_open.start() < next_close.start():
                    depth += 1
                    scan = next_open.end()
                else:
                    depth -= 1
                    if depth == 0:
                        blocks[name] = source[content_start:next_close.start()]
                        pos = next_close.end()
                        break
                    scan = next_close.end()
            else:
                pos = content_start  # malformed, skip forward

        return blocks

    def _render_with_blocks(self, parent_source: str, context: dict, child_blocks: dict) -> str:
        """Render parent template, replacing blocks with child content.

        Supports multi-level inheritance: if the parent itself extends another
        template, blocks are merged (child overrides parent) and the chain is
        followed recursively until a root template with no {% extends %} is
        reached.

        Supports {{ parent() }} / {{ super() }} inside child blocks to include
        the parent block's content (standard Twig/Jinja2 behavior).
        """
        # --- Multi-level extends: check if parent itself extends a grandparent ---
        extends_match = _EXTENDS_RE.match(parent_source.lstrip())
        if extends_match:
            grandparent_name = extends_match.group(1)
            grandparent_source = self._load(grandparent_name)

            # Extract block defaults defined in the parent template
            parent_blocks = self._extract_blocks(parent_source)

            # Child blocks override parent blocks at the same name
            merged_blocks = {**parent_blocks, **child_blocks}

            # Resolve nested blocks: if a block value contains {% block inner %}
            # tags, replace them with child_blocks values too
            changed = True
            while changed:
                changed = False
                for name, source in list(merged_blocks.items()):
                    def _resolve_nested(m, _blocks=merged_blocks):
                        inner_name = m.group(1)
                        inner_default = m.group(2)
                        return _blocks.get(inner_name, inner_default)
                    resolved = _BLOCK_RE.sub(_resolve_nested, source)
                    if resolved != source:
                        merged_blocks[name] = resolved
                        changed = True

            # Recurse up the chain (handles 3+, 4+, ... levels)
            return self._render_with_blocks(grandparent_source, context, merged_blocks)

        # --- Leaf parent (no extends) — resolve blocks and render ---
        engine = self

        def replace_block(m):
            name = m.group(1)
            parent_content = m.group(2)
            block_source = child_blocks.get(name, parent_content)

            # Make parent() and super() available inside child blocks
            # They return the rendered parent block content
            rendered_parent = None

            def get_parent():
                nonlocal rendered_parent
                if rendered_parent is None:
                    rendered_parent = SafeString(
                        engine._render_tokens(_tokenize(parent_content), context)
                    )
                return rendered_parent

            # Inject parent/super into a block-local context
            block_ctx = dict(context)
            block_ctx["parent"] = get_parent
            block_ctx["super"] = get_parent

            return engine._render_tokens(_tokenize(block_source), block_ctx)

        pattern = _BLOCK_RE

        # First pass: replace blocks
        result = pattern.sub(replace_block, parent_source)
        # Second pass: render remaining tokens (text, vars outside blocks)
        return self._render_tokens(_tokenize(result), context)

    def _render_tokens(self, tokens: list, context: dict) -> str:
        """Parse a token list and render it — the entry point for the paths that
        only have tokens in hand (include, template inheritance)."""
        return self._render_nodes(parse(tokens), context)

    def _render_nodes(self, nodes: list, context: dict) -> str:
        """Render a list of AST nodes to a string.

        The interpreter half of the parse/render split. It walks a tree the
        parser already grouped, so there is no structure to re-derive here: no
        whitespace pre-pass (baked into the TEXT nodes), no branch or body
        collection (owned by ``parser._parse_if`` / ``_parse_for``), no tag
        keyword re-splitting per render.

        ``strip_before`` is the one whitespace case that survives to render
        time: the parser sets it only when the thing to right-strip is rendered
        output rather than a literal TEXT node. Each block's body renders into
        its OWN buffer and lands in the parent as a single element, so a
        strip-before after a block trims that block's whole output — as it
        always did.
        """
        output = []

        for node in nodes:
            kind = node.kind

            # Literal text and comments carry no whitespace markers of their
            # own, so they short-circuit ahead of the single strip site below.
            if kind == "text":
                output.append(node.text)
                continue
            if kind == "comment":
                continue

            if node.strip_before and output:
                output[-1] = output[-1].rstrip()

            if kind == "output":
                result = self._eval_var(node.expr, context)
                output.append(str(result) if result is not None else "")

            elif kind == "if":
                output.append(self._handle_if(node, context))

            elif kind == "for":
                output.append(self._handle_for(node, context))

            elif kind == "set":
                self._handle_set(node.content, context)

            elif kind == "include":
                # Sandbox: check tag
                if not (self._sandbox and self._allowed_tags is not None
                        and "include" not in self._allowed_tags):
                    output.append(self._handle_include(node.content, context))

            elif kind == "macro":
                self._handle_macro(node, context)

            elif kind == "from_import":
                self._handle_from_import(node.content, context)

            elif kind == "import_as":
                self._handle_import_as(node.content, context)

            elif kind == "cache":
                output.append(self._handle_cache(node, context))

            elif kind == "spaceless":
                output.append(self._handle_spaceless(node, context))

            elif kind == "autoescape":
                output.append(self._handle_autoescape(node, context))

            elif kind == "live":
                output.append(self._handle_live(node, context))

            # else: an extends / block / endblock marker or a stray terminator —
            # no output of its own, and its strip is already applied above.

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

    def _cached_filter_chain(self, expr: str):
        """Return parsed filter chain from cache, or parse and cache."""
        cached = self._filter_chain_cache.get(expr)
        if cached is not None:
            return cached
        result = _parse_filter_chain(expr)
        self._filter_chain_cache[expr] = result
        return result

    def _eval_var_raw(self, expr: str, context: dict):
        """Evaluate a variable expression with filters, returning the raw
        (unescaped) value for use in boolean/comparison tests.

        Handles the case where a filter segment contains a trailing comparison
        operator, e.g. ``products|length != 1`` is split by the filter parser
        into variable ``products`` and filter ``length != 1``.  We detect that
        ``length`` is a real filter but ``!= 1`` is a comparison, so we apply
        the filter first and then evaluate the comparison.
        """
        var_name, filters = self._cached_filter_chain(expr)
        value = _eval_expr(var_name, context)

        for fname, args in filters:
            if fname in ("raw", "safe"):
                continue

            # Sandbox: a blocked filter is silently skipped (value passes
            # through unchanged) — same gate as _apply_filters. _eval_var_raw
            # is reached by a ternary condition (`x|f ? a : b`) and comparison
            # tests, which otherwise would run a non-allow-listed filter in
            # sandbox mode.
            if self._sandbox and self._allowed_filters is not None:
                if fname not in self._allowed_filters:
                    continue

            # Support `{{ x | first.foo.bar }}` — filter followed by
            # property access. Split on the first structural `.`; apply
            # the filter, then traverse the path on the result via a
            # synthetic context so we reuse _eval_expr's dotted/bracket
            # resolution.
            real_fname, tail_path = _split_filter_name_and_path(fname)
            fn = self._filters.get(real_fname) if tail_path else None
            if tail_path and fn is not None:
                value = fn(value, *args)
                value = _eval_expr("__frond_filter_tmp." + tail_path,
                                   {"__frond_filter_tmp": value})
                continue

            fn = self._filters.get(fname)
            if fn:
                value = fn(value, *args)
            else:
                # The filter name may include a trailing comparison operator,
                # e.g. "length != 1".  Extract the real filter name and the
                # comparison suffix, apply the filter, then evaluate the
                # comparison against the result.
                m = _FILTER_CMP_RE.match(fname)
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

    def _apply_filters(self, value, filters, context: dict):
        """Apply a parsed filter list ``[(name, args), ...]`` to *value*.

        Extracted from :meth:`_eval_var_inner` so the exact same filter logic
        (``_Ref`` arg resolution, sandbox gate, ``first.foo`` tail paths, the
        no-arg fast paths, registered filters) runs whether the pipe was the
        top-level output chain OR nested inside an expression that
        :func:`_eval_expr` resolves (issue #171). ``raw``/``safe`` are no-ops
        here — escaping is decided once, at the output layer. Never escapes."""
        for fname, args in filters:
            if fname in ("raw", "safe"):
                continue

            # Resolve any unquoted-bareword args against the context (a quoted
            # literal stays a plain string). Lets `{{ '%.2f' | format(n) }}`
            # bind `n` to its value instead of the literal text "n".
            if args and any(isinstance(a, _Ref) for a in args):
                args = [_eval_expr(a.name, context) if isinstance(a, _Ref) else a
                        for a in args]

            # Sandbox: check filter access
            if self._sandbox and self._allowed_filters is not None:
                if fname not in self._allowed_filters:
                    continue  # Silently skip blocked filter

            # Support `{{ x | first.foo.bar }}` — filter followed by
            # property access. Split on the first structural `.`; apply
            # the filter, then traverse the path on the result via a
            # synthetic context so we reuse _eval_expr's dotted/bracket
            # resolution. Done BEFORE the fast-path switch so chained
            # cases like `items|first.name` are always handled.
            real_fname, tail_path = _split_filter_name_and_path(fname)
            if tail_path:
                fn = self._filters.get(real_fname)
                if fn is not None:
                    value = fn(value, *args)
                    value = _eval_expr("__frond_filter_tmp." + tail_path,
                                       {"__frond_filter_tmp": value})
                    continue
                # Fall through if the leading segment isn't a known
                # filter — lets legacy filter names with dots (unusual)
                # still hit the registered-filter lookup below.

            # Fast path for common no-arg filters
            if not args:
                if fname == "upper":
                    value = str(value).upper()
                    continue
                if fname == "lower":
                    value = str(value).lower()
                    continue
                if fname == "length":
                    value = len(value) if value else 0
                    continue
                if fname == "trim":
                    value = str(value).strip()
                    continue
                if fname == "capitalize":
                    value = str(value).capitalize()
                    continue
                if fname == "title":
                    value = str(value).title()
                    continue
                if fname == "string":
                    value = str(value)
                    continue
                if fname == "int":
                    value = int(value) if value else 0
                    continue
                if fname in ("e", "escape"):
                    value = SafeString(html.escape(str(value)))
                    continue

            fn = self._filters.get(fname)
            if fn:
                value = fn(value, *args)

        return value

    def _eval_var_inner(self, expr: str, context: dict):
        """Core variable evaluation: resolve expression, apply filters, escape."""
        var_name, filters = self._cached_filter_chain(expr)

        # Sandbox: check variable access
        if self._sandbox and self._allowed_vars is not None:
            root_var = var_name.split(".")[0].split("[")[0].strip()
            if root_var and root_var not in self._allowed_vars and root_var != "loop":
                return ""  # Silently block

        # Compound expression (a top-level ~, comparison, arithmetic or ?? sits
        # BELOW the pipe): the naive top-level split above is wrong because the
        # pipe binds tighter (issue #171). Re-evaluate the whole expression
        # through _eval_expr — which resolves pipes at the correct precedence at
        # any depth — then escape here at the output layer.
        if filters and _has_low_precedence_op(expr):
            value = _eval_expr(expr, context, self._apply_filters)
            if isinstance(value, str) and not isinstance(value, SafeString):
                return html.escape(value)
            return value

        # Pure filter chain (or a plain variable). Threading _apply_filters into
        # the var_name eval lets a parenthesised pipe like `{{ (a|f) }}` resolve
        # too — the old code returned empty for that.
        value = _eval_expr(var_name, context, self._apply_filters)
        is_safe = any(name in ("raw", "safe") for name, _ in filters)
        value = self._apply_filters(value, filters, context)

        # Auto-escape HTML unless marked safe or SafeString
        if not is_safe and isinstance(value, str) and not isinstance(value, SafeString):
            value = html.escape(value)

        return value

    def _handle_if(self, node, context: dict) -> str:
        """Render an :class:`~tina4_python.frond.parser.IfNode`.

        The branches arrive already grouped by the parser, so all this does is
        pick the first one whose condition holds. ``_eval_var_raw`` is passed in
        so filters work inside a condition, e.g. {% if items|length > 0 %}.
        """
        for cond, body in node.branches:
            if cond is None or _eval_comparison(cond, context, self._eval_var_raw):
                return self._render_nodes(body, context)
        return ""

    def _handle_for(self, node, context: dict) -> str:
        """Render a :class:`~tina4_python.frond.parser.ForNode`.

        Header, body and else-body all come from the parser; this is the loop
        bookkeeping only.
        """
        var1 = node.key_var
        var2 = node.value_var
        iterable = _eval_expr(node.iterable, context)

        if not iterable:
            if node.else_body:
                return self._render_nodes(node.else_body, context)
            return ""

        # Iterate
        output = []
        body = node.body
        items = list(iterable.items()) if isinstance(iterable, dict) else list(iterable)
        total = len(items)
        is_dict = isinstance(iterable, dict)

        for idx, item in enumerate(items):
            loop_ctx = _LoopContext(context)
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

            if is_dict:
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

            output.append(self._render_nodes(body, loop_ctx))

        return "".join(output)

    def _handle_set(self, content: str, context: dict):
        """Handle {% set name = expr %}.

        Uses _eval_var_raw so filter pipes work (e.g. a.dr|default(0)).
        """
        m = _SET_RE.match(content)
        if m:
            name = m.group(1)
            expr = m.group(2).strip()
            context[name] = self._eval_var_raw(expr, context)

    def _handle_include(self, content: str, context: dict) -> str:
        """Handle {% include "file.html" %} with optional 'with' and 'ignore missing'."""
        ignore_missing = "ignore missing" in content
        content = content.replace("ignore missing", "").strip()

        # Parse: include "file" with { ... }
        m = _INCLUDE_RE.match(content)
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

    @staticmethod
    def _parse_macro_params(raw_params):
        """Parse macro parameter list, extracting names and default values.

        Handles: name, name="default", name='default'
        Returns list of (name, default_value) tuples.
        default_value is None when no default is specified.
        """
        params = []
        for p in raw_params.split(","):
            p = p.strip()
            if not p:
                continue
            if "=" in p:
                name, default = p.split("=", 1)
                name = name.strip()
                default = default.strip()
                # Strip surrounding quotes from default value
                if (default.startswith('"') and default.endswith('"')) or \
                   (default.startswith("'") and default.endswith("'")):
                    default = default[1:-1]
                params.append((name, default))
            else:
                params.append((p, None))
        return params

    def _macro_callable(self, params: list, body: list, context: dict):
        """Build the callable a macro registers.

        ``context`` is the dict the macro body renders against: the LIVE render
        context for an inline {% macro %} (so a later {% set %} is visible), or a
        snapshot for an imported one (an imported macro must not see the
        importer's later state). One implementation for all three registration
        sites — inline, {% from %} import, {% import %} as.
        """
        engine = self

        def macro_fn(*args):
            macro_ctx = dict(context)
            for pi, (pname, pdefault) in enumerate(params):
                if pi < len(args):
                    macro_ctx[pname] = args[pi]
                else:
                    macro_ctx[pname] = pdefault
            return SafeString(engine._render_nodes(body, macro_ctx))

        return macro_fn

    def _handle_macro(self, node, context: dict) -> None:
        """Register a {% macro name(args) %} body as a callable in the context.

        A header the regex rejects registers nothing: the parser grouped the body
        regardless, so a malformed macro stays as silent as it always was.
        """
        m = _MACRO_RE.match(node.content)
        if not m:
            return
        context[m.group(1)] = self._macro_callable(
            self._parse_macro_params(m.group(2)), node.body, context)

    def _macros_in_file(self, filename: str) -> list:
        """Every macro node defined in another template file, in source order."""
        return collect_macro_nodes(parse(_tokenize(self._load(filename))))

    def _handle_from_import(self, content: str, context: dict):
        """Handle {% from "file" import macro1, macro2 %}.

        Loads the given template file, parses it for macro definitions,
        and registers the named macros as callables in the current context.
        Each macro captures the context as it stands when IT is registered, so
        a later macro in the file can call an earlier one.
        """
        m = _FROM_IMPORT_RE.match(content)
        if not m:
            return

        names = [n.strip() for n in m.group(2).split(",") if n.strip()]

        for macro_node in self._macros_in_file(m.group(1)):
            macro_m = _MACRO_RE.match(macro_node.content)
            if macro_m and macro_m.group(1) in names:
                context[macro_m.group(1)] = self._macro_callable(
                    self._parse_macro_params(macro_m.group(2)),
                    macro_node.body,
                    dict(context),
                )

    def _handle_import_as(self, content: str, context: dict):
        """Handle {% import "file" as alias %}.

        Loads ALL macros from the file and registers them as an object
        with methods, so {{ alias.macro_name(args) }} works.
        """
        m = _IMPORT_AS_RE.match(content)
        if not m:
            return

        macros = {}
        for macro_node in self._macros_in_file(m.group(1)):
            macro_m = _MACRO_RE.match(macro_node.content)
            if macro_m:
                macros[macro_m.group(1)] = self._macro_callable(
                    self._parse_macro_params(macro_m.group(2)),
                    macro_node.body,
                    dict(context),
                )

        # A namespace object so alias.macro_name(args) works.
        #
        # MUST NOT be a class built with type("...", (), macros): a plain function
        # stored as a CLASS attribute is a descriptor, so alias.macro_name returns a
        # BOUND method and the namespace instance is injected as the first positional
        # argument -- shifting every real argument one place right and dropping the
        # last one. SimpleNamespace holds the functions as INSTANCE attributes, so
        # attribute access hands back the function itself, unbound. This keeps
        # {% import as %} byte-identical to {% from import %}, which never had the
        # bug because it registers the callables straight into the context.
        context[m.group(2)] = SimpleNamespace(**macros)

    def _handle_cache(self, node, context: dict) -> str:
        """Handle {% cache "key" ttl %}...{% endcache %}.

        Fragment caching — caches the rendered block content.

        Usage:
            {% cache "sidebar" 300 %}
                <div>Expensive content here</div>
            {% endcache %}
        """
        # Parse: cache "key" ttl  OR  cache "key"
        m = _CACHE_RE.match(node.content)
        cache_key = m.group(1) if m else "default"
        ttl = int(m.group(2)) if m and m.group(2) else 60

        # Check cache — a live entry means the body is never rendered
        cached = self._fragment_cache.get(cache_key)
        if cached:
            html_content, expires_at = cached
            if time.time() < expires_at:
                return html_content

        # Render and cache
        rendered = self._render_nodes(node.body, context)
        self._fragment_cache[cache_key] = (rendered, time.time() + ttl)
        return rendered

    def _handle_live(self, node, context: dict) -> str:
        """Handle {% live "name" poll N | sse | ws "path" [src "url"] %}...{% endlive %}.

        Server-rendered live region. The body renders once for first paint, is
        registered under <name> so the /__frond/live/<name> endpoint (or a
        @live_source provider) can re-render it, and is wrapped in a marker
        element that frond.js wires to the chosen transport (poll / sse / ws).
        """
        content = node.content
        m = _LIVE_RE.match(content)
        if not m:
            raise ValueError('live: expected {% live "name" poll N | sse | ws "path" %}')
        name = m.group("name")
        rest = (m.group("rest") or "").strip()
        parts = rest.split()
        mode = parts[0] if parts else ""

        src = None
        sm = _LIVE_SRC_RE.search(rest)
        if sm:
            src = sm.group(1)
        if src and (src.startswith("http://") or src.startswith("https://") or src.startswith("//")):
            raise ValueError("live: src must be a same-origin path, not an absolute URL")

        interval = None
        ws_path = None
        if mode == "poll":
            if len(parts) < 2 or not parts[1].isdigit():
                raise ValueError('live: poll requires seconds, e.g. {% live "x" poll 5 %}')
            interval = int(parts[1])
        elif mode == "sse":
            pass
        elif mode == "ws":
            wm = _LIVE_WS_RE.search(rest)
            if not wm:
                raise ValueError('live: ws requires a path, e.g. {% live "x" ws "/ws/x" %}')
            ws_path = wm.group(1)
        else:
            raise ValueError(f'live: unknown transport "{mode}" (use poll N, sse, or ws "path")')

        # Nested live is unsupported. The parser recorded it rather than raising,
        # so the error still surfaces here at render time — a live block inside a
        # branch that never renders stays as silent as it always was.
        if node.nested:
            raise ValueError("live: nested live blocks are not supported")

        # Register the body source so the auto endpoint can re-render it.
        Frond._class_live_fragments[name] = node.body_source

        endpoint = src or ("/__frond/live/" + name)
        attrs = [f'data-frond-live="{_live_attr(name)}"', f'id="live-{_live_attr(name)}"']
        if mode == "poll":
            attrs += ['data-mode="poll"', f'data-interval="{interval}"',
                      f'data-src="{_live_attr(endpoint)}"']
        elif mode == "sse":
            attrs += ['data-mode="sse"', f'data-src="{_live_attr(endpoint)}"']
        elif mode == "ws":
            Frond._class_live_ws_paths[name] = ws_path
            attrs += ['data-mode="ws"', f'data-ws="{_live_attr(ws_path)}"']

        first_paint = self._render_nodes(node.body, context)
        return f'<div {" ".join(attrs)}>{first_paint}</div>'

    @classmethod
    def render_live(cls, name: str, data: dict = None):
        """Re-render a registered {% live %} fragment by name.

        Returns the rendered HTML fragment, or None if no fragment is registered
        under that name yet (the page carrying the block has not rendered). The
        /__frond/live/<name> endpoint calls this after resolving the provider data.
        """
        source = cls._class_live_fragments.get(name)
        if source is None:
            return None
        return cls().render_string(source, data or {})

    def _handle_spaceless(self, node, context: dict) -> str:
        """Handle {% spaceless %}...{% endspaceless %}.

        Removes whitespace between HTML tags in the rendered content.
        """
        rendered = self._render_nodes(node.body, context)
        # Collapse whitespace between > and <
        return _SPACELESS_RE.sub("><", rendered)

    def _handle_autoescape(self, node, context: dict) -> str:
        """Handle {% autoescape false %}...{% endautoescape %}.

        When autoescape is false, variables inside the block skip HTML escaping.
        """
        # Parse: autoescape false|true
        mode_match = _AUTOESCAPE_RE.match(node.content)
        auto_escape_on = True
        if mode_match and mode_match.group(1) == "false":
            auto_escape_on = False

        if not auto_escape_on:
            # Render with a temporary engine that has auto-escape disabled
            # We wrap _eval_var to skip escaping
            original_eval_var = self._eval_var

            def _no_escape_eval_var(expr, ctx):
                var_name, filters = self._cached_filter_chain(expr)
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
                    # Filter + property access: e.g. `items|first.name`.
                    real_fname, tail_path = _split_filter_name_and_path(fname)
                    if tail_path:
                        fn = self._filters.get(real_fname)
                        if fn is not None:
                            value = fn(value, *args)
                            value = _eval_expr("__frond_filter_tmp." + tail_path,
                                               {"__frond_filter_tmp": value})
                            continue
                    fn = self._filters.get(fname)
                    if fn:
                        value = fn(value, *args)
                # Skip auto-escape
                return value

            self._eval_var = _no_escape_eval_var
            rendered = self._render_nodes(node.body, context)
            self._eval_var = original_eval_var
        else:
            rendered = self._render_nodes(node.body, context)

        return rendered
