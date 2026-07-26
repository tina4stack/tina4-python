# Tina4 Frond — Ahead-of-time template compiler (ADR-0001, part 1).
"""
Compile a parsed Frond AST ONCE into a native Python callable so that
``render()`` just CALLS the compiled function and pays no per-render tree-walk.

Design (behaviour-safe by construction):

* The compiler consumes the SAME tree the interpreter does, produced by
  :mod:`tina4_python.frond.parser`. It no longer sees tokens, so it cannot
  disagree with the interpreter about structure: which nodes belong to which
  branch/body, where a loop ends, and where whitespace is trimmed are all
  decided once, by the parser. (This module used to carry ``_collect_if`` /
  ``_collect_for`` — a second, hand-synchronised copy of the engine's own token
  grouping — plus ``_apply_whitespace_control``. All three are deleted; the
  parser owns that work now.)
* The emitted function reuses the engine's OWN runtime primitives for every
  value-producing operation — ``engine._eval_var`` for ``{{ ... }}``,
  ``_eval_comparison`` for ``if`` conditions, ``_eval_expr`` for ``for``
  iterables, ``engine._handle_set`` for ``set``. Only the *structure* (which
  nodes belong to which branch/body, the whitespace-free text runs, the loop
  bookkeeping) is baked into native Python control flow. Because every value is
  produced by the identical primitive the interpreter calls, a compiled template
  renders byte-identically to the interpreted one.
* Only the common hot-path constructs are compiled: text, ``{{ var }}`` (with
  dotted paths / filters / ternary — all handled inside ``_eval_var``),
  ``if/elif/elseif/else``, ``for`` (+ loop vars + for-else), ``set``, comments,
  and ``{% raw %}`` (which the tokenizer has already turned into literal text).
* Whitespace control is compiled too, because the parser baked the structural
  trims into the text nodes. The ONE case that stays render-dependent is a
  strip-before (``{{- `` / ``{%- ``) whose left neighbour is not literal text
  (a value / block / comment output, mid-body): there the interpreter
  right-strips the live output buffer, so the parser flags that node with
  ``strip_before`` and this module falls back on it.
* ANY other construct (extends/block, include, macro, from/import, cache,
  spaceless, autoescape, live) or a malformed tag makes :func:`compile_template`
  return ``None`` so the caller falls back to the interpreter for that whole
  template. A codegen/compile error also returns ``None``. A render is therefore
  never broken by the compiler.
"""


class _Unsupported(Exception):
    """Raised internally when a node uses a construct the compiler does not
    yet emit. Caught by :func:`compile_template`, which then returns ``None``
    so the caller uses the interpreted renderer for the whole template."""


def _tostr(value) -> str:
    """Coerce a rendered value to its output string.

    THE cross-framework output contract, and it MUST stay identical to the
    interpreter's copy in ``engine.Frond._to_output`` -- the compiled path and the
    interpreted path have to render the same bytes. Change one, change both.

    A boolean renders lowercase ``true``/``false``: Frond is a template language,
    not Python, and lowercase is the form usable directly in HTML and JavaScript
    (``data-active="{{ flag }}"`` -> ``data-active="true"``, testable from JS).

    Breaking in 3.13.87: this used to emit Python's ``True``/``False``. The four
    frameworks had drifted to four different answers -- Python ``True``/``False``
    (Jinja2-faithful), PHP ``1``/``''`` (Twig-faithful, with ``false`` rendering as
    an EMPTY STRING), Ruby inconsistent between a comparison and a bare variable,
    Node ``true``/``false``. All four now agree; a 72-expression corpus locks it.

    ``is True`` / ``is False`` identity checks are deliberate: ``1 == True`` in
    Python, and an integer 1 must still render as ``1``.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _pad(indent: int) -> str:
    return "    " * indent


def compile_template(ast):
    """Compile an AST (a list of nodes) to ``_rendered(engine, ctx) -> str``.

    Returns the callable, or ``None`` when the template contains a construct
    that is not compiled yet / when codegen or ``compile()`` fails — in which
    case the caller must render the template with the interpreter.
    """
    # Lazy import breaks the engine<->compiler import cycle (each imports the
    # other only at call time, by which point both modules are loaded).
    from tina4_python.frond import engine as _engine

    try:
        lines = ["def _rendered(engine, ctx):", "    _b = []", "    _ap = _b.append"]
        _emit_body(ast, "ctx", 1, lines, {"n": 0})
        lines.append('    return "".join(_b)')
        source = "\n".join(lines)

        namespace = {
            "_LoopContext": _engine._LoopContext,
            "_eval_expr": _engine._eval_expr,
            "_eval_comparison": _engine._eval_comparison,
            "_tostr": _tostr,
            "isinstance": isinstance,
            "list": list,
            "len": len,
            "enumerate": enumerate,
        }
        code = compile(source, "<frond_compiled>", "exec")
        exec(code, namespace)  # noqa: S102 — trusted, generated from template nodes
        return namespace["_rendered"]
    except _Unsupported:
        return None
    except Exception:
        # A codegen/compile error must never break a render — fall back.
        return None


# ── Codegen ─────────────────────────────────────────────────────


def _emit_body(nodes, ctxvar, indent, out, state):
    """Emit code for a list of sibling nodes (mirrors ``_render_nodes`` dispatch
    for the compiled subset). ``ctxvar`` is the name of the context variable in
    scope (``ctx`` at top level, a loop-context name inside a ``for``)."""
    for node in nodes:
        kind = node.kind

        if kind == "text":
            out.append(_pad(indent) + "_ap(" + repr(node.text) + ")")
            continue

        if kind == "comment":
            continue

        # A strip-before the parser could not bake into a text node: the
        # interpreter right-strips the LIVE output buffer there, which depends on
        # rendered data, so the whole template falls back.
        if node.strip_before:
            raise _Unsupported

        if kind == "output":
            out.append(
                _pad(indent)
                + "_ap(_tostr(engine._eval_var(" + repr(node.expr) + ", " + ctxvar + ")))"
            )

        elif kind == "if":
            _emit_if(node, ctxvar, indent, out, state)

        elif kind == "for":
            _emit_for(node, ctxvar, indent, out, state)

        elif kind == "set":
            out.append(
                _pad(indent) + "engine._handle_set(" + repr(node.content) + ", " + ctxvar + ")"
            )

        else:
            # extends/block, include, macro, from/import, cache, spaceless,
            # autoescape, live, and any stray terminator: not compiled — fall
            # back to the interpreter for this template.
            raise _Unsupported


def _emit_if(node, ctxvar, indent, out, state):
    branches = node.branches
    if not branches:
        raise _Unsupported

    # A ``None`` condition is the ``{% else %}`` branch; native ``else:`` must be
    # last. Anything else (an else before an elseif) is malformed — fall back.
    for idx, (cond, _body) in enumerate(branches):
        if cond is None and idx != len(branches) - 1:
            raise _Unsupported

    first = True
    for cond, body in branches:
        if cond is None:
            out.append(_pad(indent) + "else:")
        else:
            keyword = "if" if first else "elif"
            out.append(
                _pad(indent)
                + keyword
                + " _eval_comparison("
                + repr(cond)
                + ", "
                + ctxvar
                + ", engine._eval_var_raw):"
            )
        body_start = len(out)
        _emit_body(body, ctxvar, indent + 1, out, state)
        if len(out) == body_start:
            out.append(_pad(indent + 1) + "pass")
        first = False


def _emit_for(node, ctxvar, indent, out, state):
    var1 = node.key_var
    var2 = node.value_var

    suffix = state["n"]
    state["n"] += 1
    it = "_it%d" % suffix
    items = "_items%d" % suffix
    total = "_total%d" % suffix
    isd = "_isd%d" % suffix
    idx = "_idx%d" % suffix
    item = "_item%d" % suffix
    lc = "_lc%d" % suffix
    k = "_k%d" % suffix
    v = "_v%d" % suffix

    out.append(_pad(indent) + it + " = _eval_expr(" + repr(node.iterable) + ", " + ctxvar + ")")
    out.append(_pad(indent) + "if not " + it + ":")
    body_start = len(out)
    if node.else_body:
        _emit_body(node.else_body, ctxvar, indent + 1, out, state)
    if len(out) == body_start:
        out.append(_pad(indent + 1) + "pass")

    out.append(_pad(indent) + "else:")
    out.append(
        _pad(indent + 1)
        + items + " = list(" + it + ".items()) if isinstance(" + it + ", dict) else list(" + it + ")"
    )
    out.append(_pad(indent + 1) + total + " = len(" + items + ")")
    out.append(_pad(indent + 1) + isd + " = isinstance(" + it + ", dict)")
    out.append(_pad(indent + 1) + "for " + idx + ", " + item + " in enumerate(" + items + "):")
    out.append(_pad(indent + 2) + lc + " = _LoopContext(" + ctxvar + ")")
    loop_dict = (
        '{"index": ' + idx + "+1, "
        '"index0": ' + idx + ", "
        '"first": ' + idx + "==0, "
        '"last": ' + idx + "==" + total + "-1, "
        '"length": ' + total + ", "
        '"revindex": ' + total + "-" + idx + ", "
        '"revindex0": ' + total + "-" + idx + "-1, "
        '"even": (' + idx + "+1)%2==0, "
        '"odd": (' + idx + "+1)%2!=0}"
    )
    out.append(_pad(indent + 2) + lc + '["loop"] = ' + loop_dict)

    out.append(_pad(indent + 2) + "if " + isd + ":")
    out.append(_pad(indent + 3) + k + ", " + v + " = " + item)
    out.append(_pad(indent + 3) + lc + "[" + repr(var1) + "] = " + k)
    if var2:
        out.append(_pad(indent + 3) + lc + "[" + repr(var2) + "] = " + v)
    out.append(_pad(indent + 2) + "else:")
    if var2:
        out.append(_pad(indent + 3) + lc + "[" + repr(var1) + "] = " + idx)
        out.append(_pad(indent + 3) + lc + "[" + repr(var2) + "] = " + item)
    else:
        out.append(_pad(indent + 3) + lc + "[" + repr(var1) + "] = " + item)

    body_start = len(out)
    _emit_body(node.body, lc, indent + 2, out, state)
    if len(out) == body_start:
        out.append(_pad(indent + 2) + "pass")
