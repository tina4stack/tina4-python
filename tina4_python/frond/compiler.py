# Tina4 Frond — Ahead-of-time template compiler (ADR-0001, part 1).
"""
Compile a parsed Frond token list ONCE into a native Python callable so that
``render()`` just CALLS the compiled function and pays no per-render tree-walk.

Design (behaviour-safe by construction):

* The existing tokenizer/parser in :mod:`tina4_python.frond.engine` still
  produces the ``(type, value)`` token list. This module only adds a codegen
  pass over that list.
* The emitted function reuses the engine's OWN runtime primitives for every
  value-producing operation — ``engine._eval_var`` for ``{{ ... }}``,
  ``_eval_comparison`` for ``if`` conditions, ``_eval_expr`` for ``for``
  iterables, ``engine._handle_set`` for ``set``. Only the *structure* (which
  tokens belong to which branch/body, the whitespace-free text runs, the loop
  bookkeeping) is baked into native Python control flow. Because every value is
  produced by the identical primitive the interpreter calls, a compiled
  template renders byte-identically to the interpreted one.
* The tree-collection for ``if`` / ``for`` mirrors the engine handlers
  (``Frond._handle_if`` / ``Frond._handle_for``) EXACTLY, so the token grouping
  is identical — the source of truth for that grouping is those handlers.
* Only the common hot-path constructs are compiled: text, ``{{ var }}`` (with
  dotted paths / filters / ternary — all handled inside ``_eval_var``),
  ``if/elif/elseif/else``, ``for`` (+ loop vars + for-else), ``set``, comments,
  and ``{% raw %}`` (which the tokenizer has already turned into literal text).
* Whitespace control (``{{- -}}`` / ``{%- -%}``) is compiled too. The trims are
  structural (a pure function of the token positions, never of render data), so
  :func:`_apply_whitespace_control` bakes them into the neighbouring TEXT tokens
  at compile time — mirroring the interpreter's pre-pass verbatim — and codegen
  proceeds. The ONE whitespace case that stays render-dependent is a
  strip-before (``{{- `` / ``{%- ``) whose left neighbour is not a literal TEXT
  token (a value / block / comment output, mid-body): there the interpreter
  right-strips the live output buffer, so that single case still falls back
  (see the strip-before gate in :func:`_emit_body`).
* ANY other construct (extends/block, include, macro, from/import, cache,
  spaceless, autoescape, live) or a malformed tag makes
  :func:`compile_template` return ``None`` so the caller falls back to the
  interpreter for that whole template. A codegen/compile error also returns
  ``None``. A render is therefore never broken by the compiler.
"""


class _Unsupported(Exception):
    """Raised internally when a token uses a construct the compiler does not
    yet emit. Caught by :func:`compile_template`, which then returns ``None``
    so the caller uses the interpreted renderer for the whole template."""


def _tostr(value) -> str:
    """Mirror the interpreter's ``str(result) if result is not None else ""``."""
    return str(value) if value is not None else ""


def _pad(indent: int) -> str:
    return "    " * indent


def _apply_whitespace_control(tokens, eng):
    """Bake the interpreter's STRUCTURAL whitespace trims into the TEXT tokens at
    compile time so a whitespace-controlled template compiles instead of falling
    back, with compiled text literals BYTE-IDENTICAL to the interpreter's.

    This mirrors, verbatim, the pre-pass at the top of ``Frond._render_tokens``
    (``engine.py`` lines 1947-1954): for every ``{{- }}`` / ``{%- %}`` marker it
    right-strips the immediately-preceding TEXT token (strip-before) and
    left-strips the immediately-following TEXT token (strip-after). Those trims
    are a pure function of the token positions — never of render data — so
    applying them once here reproduces the interpreter exactly. Idempotent
    (``rstrip``/``lstrip``), matching the interpreter re-running this pass on
    every recursive ``_render_tokens`` call.

    Two interpreter trims are NOT baked here and are handled elsewhere so the
    compiled output stays byte-identical:

    * The opening-block ``-%}`` also left-strips the TEXT token that FOLLOWS the
      matching end tag (``engine.py`` line 2049) — baked in ``_emit_if`` /
      ``_emit_for`` where the end index is known.
    * The runtime right-strip of the live output buffer for a strip-before
      marker (``engine.py`` lines 1971-1972 / 1983-1984) — reproduced for the
      safe cases by this pass (the left neighbour is a TEXT literal, so the
      buffer tail is already trimmed) and refused for the render-dependent case
      by the strip-before gate in :func:`_emit_body`.

    Operates on the list in place (the caller passes a copy) and returns it.
    """
    strip_tag = eng._strip_tag
    TEXT, VAR, BLOCK = eng.TEXT, eng.VAR, eng.BLOCK
    for idx in range(len(tokens)):
        ttype, raw = tokens[idx]
        if ttype in (VAR, BLOCK):
            _, strip_b, strip_a = strip_tag(raw)
            if strip_b and idx > 0 and tokens[idx - 1][0] == TEXT:
                tokens[idx - 1] = (TEXT, tokens[idx - 1][1].rstrip())
            if strip_a and idx + 1 < len(tokens) and tokens[idx + 1][0] == TEXT:
                tokens[idx + 1] = (TEXT, tokens[idx + 1][1].lstrip())
    return tokens


def compile_template(tokens):
    """Compile a token list to ``_rendered(engine, ctx) -> str``.

    Returns the callable, or ``None`` when the template contains a construct
    that is not compiled yet / when codegen or ``compile()`` fails — in which
    case the caller must render the template with the interpreter.
    """
    # Lazy import breaks the engine<->compiler import cycle (each imports the
    # other only at call time, by which point both modules are loaded).
    from tina4_python.frond import engine as _engine

    try:
        # Bake the structural whitespace trims into a COPY of the token list (the
        # caller's list stays pristine for the interpreter fallback, which runs
        # its own idempotent pre-pass). Elements are immutable tuples, so the
        # shallow copy is enough — the pass replaces list entries, never mutating
        # the originals.
        tokens = _apply_whitespace_control(list(tokens), _engine)
        lines = ["def _rendered(engine, ctx):", "    _b = []", "    _ap = _b.append"]
        _emit_body(tokens, "ctx", 1, lines, {"n": 0}, _engine)
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
        exec(code, namespace)  # noqa: S102 — trusted, generated from template tokens
        return namespace["_rendered"]
    except _Unsupported:
        return None
    except Exception:
        # A codegen/compile error must never break a render — fall back.
        return None


# ── Codegen ─────────────────────────────────────────────────────


def _emit_body(tokens, ctxvar, indent, out, state, eng):
    """Emit code for a flat token sub-list (mirrors ``_render_tokens`` dispatch
    for the compiled subset). ``ctxvar`` is the name of the context variable in
    scope (``ctx`` at top level, a loop-context name inside a ``for``)."""
    strip_tag = eng._strip_tag
    TEXT, VAR, BLOCK, COMMENT = eng.TEXT, eng.VAR, eng.BLOCK, eng.COMMENT

    i = 0
    n = len(tokens)
    while i < n:
        ttype, raw = tokens[i]

        if ttype == TEXT:
            if raw:  # empty text is a no-op append; skip it
                out.append(_pad(indent) + "_ap(" + repr(raw) + ")")
            i += 1

        elif ttype == COMMENT:
            i += 1

        elif ttype == VAR:
            content, strip_b, strip_a = strip_tag(raw)
            # strip_a and the TEXT-adjacent part of strip_b are already baked into
            # the neighbouring TEXT tokens by _apply_whitespace_control. The only
            # strip_b the pre-pass cannot bake is one whose left neighbour is NOT
            # a literal TEXT token (a value/block/comment output mid-body, or a
            # body-start marker): there the interpreter right-strips the LIVE
            # output buffer, which is render-dependent — fall back for that case.
            if strip_b and not (i == 0 or tokens[i - 1][0] == TEXT):
                raise _Unsupported
            out.append(
                _pad(indent)
                + "_ap(_tostr(engine._eval_var(" + repr(content) + ", " + ctxvar + ")))"
            )
            i += 1

        elif ttype == BLOCK:
            content, strip_b, strip_a = strip_tag(raw)
            parts = content.split()
            tag = parts[0] if parts else ""

            # Same strip-before gate as VAR: the pre-pass baked the TEXT-adjacent
            # trims and _emit_if/_emit_for bake the opening-tag -%} that trims
            # past the end tag; only a strip_b whose left neighbour is not a
            # literal TEXT token stays render-dependent and must fall back.
            if strip_b and not (i == 0 or tokens[i - 1][0] == TEXT):
                raise _Unsupported

            if tag == "if":
                i = _emit_if(tokens, i, ctxvar, indent, out, state, eng)
            elif tag == "for":
                i = _emit_for(tokens, i, ctxvar, indent, out, state, eng)
            elif tag == "set":
                out.append(
                    _pad(indent) + "engine._handle_set(" + repr(content) + ", " + ctxvar + ")"
                )
                i += 1
            else:
                # extends/block/endblock/include/macro/from/import/cache/
                # spaceless/autoescape/live and any stray terminator: not
                # compiled — fall back to the interpreter for this template.
                raise _Unsupported
        else:
            i += 1


def _collect_if(tokens, start, eng):
    """Collect ``if`` branches EXACTLY as ``Frond._handle_if`` does (minus the
    rendering). Returns ``([(cond_or_None, sub_tokens), ...], end_index)``."""
    strip_tag = eng._strip_tag
    BLOCK = eng.BLOCK

    content, _, _ = strip_tag(tokens[start][1])
    condition_expr = content[3:].strip()  # remove 'if '

    branches = []
    current_tokens = []
    current_cond = condition_expr
    depth = 0
    i = start + 1

    while i < len(tokens):
        ttype, raw = tokens[i]
        if ttype == BLOCK:
            tag_content, _, _ = strip_tag(raw)
            tp = tag_content.split()
            tag = tp[0] if tp else ""

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
                current_cond = None
                current_tokens = []
            else:
                current_tokens.append(tokens[i])
        else:
            current_tokens.append(tokens[i])
        i += 1

    return branches, i


def _emit_if(tokens, start, ctxvar, indent, out, state, eng):
    branches, end_i = _collect_if(tokens, start, eng)
    if not branches:
        raise _Unsupported

    # A ``None`` condition is the ``{% else %}`` branch; native ``else:`` must be
    # last. Anything else (an else before an elseif) is malformed — fall back.
    for idx, (cond, _sub) in enumerate(branches):
        if cond is None and idx != len(branches) - 1:
            raise _Unsupported

    first = True
    for cond, sub in branches:
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
        _emit_body(sub, ctxvar, indent + 1, out, state, eng)
        if len(out) == body_start:
            out.append(_pad(indent + 1) + "pass")
        first = False

    # An opening `{% if ... -%}` also left-strips the TEXT token that FOLLOWS the
    # matching endif: engine.py line 2049 applies the OPENING tag's strip_after
    # once the block is consumed, ON TOP of the pre-pass trim of the first body
    # token. Bake it structurally (end_i is the index past endif) so compiled ==
    # interpreted.
    _, _, strip_a = eng._strip_tag(tokens[start][1])
    if strip_a and end_i < len(tokens) and tokens[end_i][0] == eng.TEXT:
        tokens[end_i] = (eng.TEXT, tokens[end_i][1].lstrip())

    return end_i


def _collect_for(tokens, start, eng):
    """Collect ``for`` body/else EXACTLY as ``Frond._handle_for`` does (minus
    the rendering). Returns ``(var1, var2, iterable_expr, body, else, end)`` or
    ``None`` when the ``for`` tag is malformed (``_FOR_RE`` does not match)."""
    strip_tag = eng._strip_tag
    BLOCK = eng.BLOCK

    content, _, _ = strip_tag(tokens[start][1])
    for_match = eng._FOR_RE.match(content)
    if not for_match:
        return None

    var1 = for_match.group(1)
    var2 = for_match.group(2)
    iterable_expr = for_match.group(3).strip()

    body_tokens = []
    else_tokens = []
    in_else = False
    for_depth = 0
    if_depth = 0
    i = start + 1

    while i < len(tokens):
        ttype, raw = tokens[i]
        if ttype == BLOCK:
            tag_content, _, _ = strip_tag(raw)
            tp = tag_content.split()
            tag = tp[0] if tp else ""

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

    return var1, var2, iterable_expr, body_tokens, else_tokens, i


def _emit_for(tokens, start, ctxvar, indent, out, state, eng):
    collected = _collect_for(tokens, start, eng)
    if collected is None:
        raise _Unsupported
    var1, var2, iterable_expr, body_tokens, else_tokens, end_i = collected

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

    out.append(_pad(indent) + it + " = _eval_expr(" + repr(iterable_expr) + ", " + ctxvar + ")")
    out.append(_pad(indent) + "if not " + it + ":")
    body_start = len(out)
    if else_tokens:
        _emit_body(else_tokens, ctxvar, indent + 1, out, state, eng)
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
    _emit_body(body_tokens, lc, indent + 2, out, state, eng)
    if len(out) == body_start:
        out.append(_pad(indent + 2) + "pass")

    # An opening `{% for ... -%}` left-strips the TEXT token after endfor too
    # (engine.py line 2049), mirroring the if case above.
    _, _, strip_a = eng._strip_tag(tokens[start][1])
    if strip_a and end_i < len(tokens) and tokens[end_i][0] == eng.TEXT:
        tokens[end_i] = (eng.TEXT, tokens[end_i][1].lstrip())

    return end_i
