# Tina4 Frond — the parse stage: source -> tokens -> AST.
"""
The Frond front end. It turns template source into ``(type, value)`` tokens and
then turns those tokens into a STRUCTURED TREE that both consumers of a
template read:

* the interpreter — ``Frond._render_nodes`` plus the ``_handle_*`` handlers in
  :mod:`tina4_python.frond.engine`
* the ahead-of-time compiler — :mod:`tina4_python.frond.compiler`

**Why a tree.** Both consumers used to take the FLAT token list and each
RE-DERIVE the structure from it. ``engine._handle_if`` / ``_handle_for`` grouped
branches and bodies on *every render*, and ``compiler._collect_if`` /
``_collect_for`` held a second, hand-synchronised copy of that same grouping —
their docstrings said they mirror the engine handlers "EXACTLY" and named those
handlers as the source of truth, which is documentation doing load-bearing work
that a type system cannot. Change one and the other silently drifts. The parser
now owns structure outright: every grouping loop exists ONCE, here, and runs
ONCE per template instead of once per render. This is the PHP implementation's
architecture (``Frond::parse()`` -> ``renderAst()``), adopted by the Python
master per ADR-0004 ("best implementation prevails").

**Structure is decided here, values are not.** A node carries the *shape* of a
construct (which nodes are in which branch, the loop variable names) and the
raw expression *strings* it was written with. Every value is still produced at
render time by the engine's own primitives (``_eval_var``, ``_eval_comparison``,
``_eval_expr``, ``_handle_set``), so the interpreter and the compiler cannot
disagree about what an expression means.

**Whitespace control is a parse concern.** ``{{- -}}`` / ``{%- -%}`` trims are a
pure function of token POSITIONS, never of render data, so they are baked into
the TEXT nodes once here (see :func:`_apply_whitespace_control`) instead of
being re-derived on every render — and on every recursive render of every loop
body, which is what the interpreter used to do. The one trim that genuinely
depends on rendered output survives as the ``strip_before`` flag on a node; see
that field's note.

**Malformed input is preserved, not fixed.** Several collection loops below have
odd behaviour on a template with an unbalanced tag (an ``{% if %}`` with no
``{% endif %}`` drops its last branch and swallows the rest of the template; a
malformed ``{% for %}`` renders its body inline exactly once). This module
reproduces that behaviour deliberately and byte-for-byte — it is a relocation of
existing logic, not a redesign of it. Tightening those cases is a separate,
deliberate behaviour change.
"""
import re

from dataclasses import dataclass, field

# ── Token types ────────────────────────────────────────────────
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

# {% for item in items %} / {% for key, value in mapping %}. Lives here because
# whether a for tag is well-formed decides how its body is GROUPED, which is a
# parse decision.
_FOR_RE = re.compile(r"for\s+(\w+)(?:\s*,\s*(\w+))?\s+in\s+(.+)")


def _tokenize(source: str) -> list[tuple[str, str]]:
    """Split template source into (type, value) tokens.

    Before splitting on {{ }}/{% %} patterns, extract {% raw %}...{% endraw %}
    blocks and replace them with placeholder TEXT tokens so their content is
    output literally (not parsed). A raw block is therefore a plain TEXT token
    by the time the parser sees it — there is no raw node.
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


# ── AST nodes ──────────────────────────────────────────────────
#
# Every node carries a class-level ``kind`` string (a class attribute, so it
# costs nothing per instance) and the interpreter/compiler dispatch on it. The
# nodes are pure data: no rendering lives here, so the parse stage and the
# render stage stay separable.
#
# ``strip_before`` appears on every node built from a {{ }} / {% %} tag and is
# the ONE piece of whitespace control that cannot be baked into a TEXT node.
# When a strip-before marker's left neighbour is a literal TEXT token the trim
# is structural and :func:`_apply_whitespace_control` has already applied it; if
# the left neighbour is a value/block/comment output the interpreter has to
# right-strip the LIVE output buffer, which depends on rendered data. The
# parser therefore sets the flag ONLY for that render-dependent case, which
# makes it both the interpreter's "rstrip the buffer" trigger and the
# compiler's fallback signal.


@dataclass(slots=True)
class TextNode:
    """Literal output. Includes {% raw %} bodies (resolved by the tokenizer)."""
    kind = "text"
    text: str


@dataclass(slots=True)
class CommentNode:
    """{# ... #} — kept so the tree is a faithful view of the source; renders
    nothing."""
    kind = "comment"


@dataclass(slots=True)
class OutputNode:
    """{{ expr }} — expr may carry dotted paths, filters and ternaries; the
    engine's _eval_var owns all of that."""
    kind = "output"
    expr: str
    strip_before: bool = False


@dataclass(slots=True)
class IfNode:
    """{% if %}/{% elseif %}/{% elif %}/{% else %}/{% endif %}.

    ``branches`` is an ordered list of ``(condition, body_nodes)``; a condition
    of ``None`` is the {% else %} branch.
    """
    kind = "if"
    branches: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class ForNode:
    """{% for %}...{% else %}...{% endfor %} with the loop header already
    parsed. ``value_var`` is None for a single-variable loop."""
    kind = "for"
    key_var: str = ""
    value_var: str | None = None
    iterable: str = ""
    body: list = field(default_factory=list)
    else_body: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class SetNode:
    """{% set name = expr %} — the engine's _handle_set parses the assignment."""
    kind = "set"
    content: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class IncludeNode:
    """{% include "file" [with {...}] [ignore missing] %}."""
    kind = "include"
    content: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class MacroNode:
    """{% macro name(args) %}...{% endmacro %} — registers a callable."""
    kind = "macro"
    content: str = ""
    body: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class FromImportNode:
    """{% from "file" import a, b %}."""
    kind = "from_import"
    content: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class ImportAsNode:
    """{% import "file" as alias %}."""
    kind = "import_as"
    content: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class CacheNode:
    """{% cache "key" ttl %}...{% endcache %} — fragment caching."""
    kind = "cache"
    content: str = ""
    body: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class SpacelessNode:
    """{% spaceless %}...{% endspaceless %}."""
    kind = "spaceless"
    body: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class AutoescapeNode:
    """{% autoescape false %}...{% endautoescape %}."""
    kind = "autoescape"
    content: str = ""
    body: list = field(default_factory=list)
    strip_before: bool = False


@dataclass(slots=True)
class LiveNode:
    """{% live "name" ... %}...{% endlive %}.

    ``body_source`` is the body's literal template text, which the live
    endpoint re-renders on refresh. ``nested`` records that a {% live %} was
    found inside the body — the error for that is raised at render time, where
    it was raised before, so a live block inside a false branch stays as silent
    as it always was.
    """
    kind = "live"
    content: str = ""
    body: list = field(default_factory=list)
    body_source: str = ""
    nested: bool = False
    strip_before: bool = False


@dataclass(slots=True)
class ExtendsNode:
    """{% extends "parent" %} — a MARKER, not a container.

    Template inheritance runs as a SOURCE-level pass before tokenizing
    (``Frond._extract_blocks`` / ``_render_with_blocks`` substitute block bodies
    by regex), so by the time a token stream reaches the parser the extends and
    block tags are inert and the interpreter skipped them. The node exists so
    the tree names what it saw; it renders nothing.
    """
    kind = "skip"
    template: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class BlockMarkerNode:
    """{% block name %} / {% endblock %} — a marker for the same reason as
    :class:`ExtendsNode`. Its body is NOT grouped: the tags are inert here and
    the tokens between them are ordinary siblings, exactly as the interpreter
    treated them."""
    kind = "skip"
    name: str = ""
    strip_before: bool = False


@dataclass(slots=True)
class SkipNode:
    """A tag that produces no output on its own: a stray terminator
    ({% endif %} with no {% if %}), a malformed {% for %} header, or an
    unrecognised tag. Renders nothing, but still carries ``strip_before``
    because the interpreter applied whitespace control before dispatch."""
    kind = "skip"
    strip_before: bool = False


# ── Whitespace control ─────────────────────────────────────────


def _apply_whitespace_control(tokens: list) -> list:
    """Bake the STRUCTURAL whitespace trims into the TEXT tokens.

    Verbatim the pre-pass the interpreter used to run at the top of every
    ``_render_tokens`` call: for every ``{{- }}`` / ``{%- %}`` marker,
    right-strip the immediately-preceding TEXT token (strip-before) and
    left-strip the immediately-following TEXT token (strip-after).

    Running it ONCE over the whole flat token list is equivalent to the
    interpreter running it again on every nested body, because every body the
    handlers sliced out is a CONTIGUOUS run of this list whose neighbours just
    outside the slice are the block's own tags — BLOCK tokens, never TEXT — so a
    per-slice pass could only ever repeat what the full pass already did
    (``rstrip``/``lstrip`` are idempotent). It also means the markers on closing
    tags ({% endif -%}) and on branch delimiters ({% else -%}) are honoured,
    which a per-handler pass could not see because the handler consumes those
    tags itself.

    Mutates the list it is given (:func:`parse` passes a copy, so a caller's
    token list — and any source reconstructed from it — stays pristine) and
    returns it.
    """
    for idx in range(len(tokens)):
        ttype, raw = tokens[idx]
        if ttype in (VAR, BLOCK):
            _, strip_before, strip_after = _strip_tag(raw)
            if strip_before and idx > 0 and tokens[idx - 1][0] == TEXT:
                tokens[idx - 1] = (TEXT, tokens[idx - 1][1].rstrip())
            if strip_after and idx + 1 < len(tokens) and tokens[idx + 1][0] == TEXT:
                tokens[idx + 1] = (TEXT, tokens[idx + 1][1].lstrip())
    return tokens


def _bake_strip_after_end(tokens: list, strip_after: bool, end_index: int) -> None:
    """Apply a grouping tag's ``-%}`` to the TEXT token AFTER its end tag.

    An opening ``{% if ... -%}`` / ``{% for ... -%}`` trims twice: the first
    token of its body (already done by :func:`_apply_whitespace_control`) and
    the token that follows the matching end tag, because the interpreter applied
    the opening tag's strip_after once the whole block had been consumed. Purely
    structural, so it is baked here. Single-token tags need no equivalent — for
    them "the token after the tag" and "the token after the end" are the same
    token the pre-pass already trimmed.
    """
    if strip_after and end_index < len(tokens) and tokens[end_index][0] == TEXT:
        tokens[end_index] = (TEXT, tokens[end_index][1].lstrip())


def _tag_name(raw: str) -> str:
    """The keyword of a BLOCK token ('if', 'endfor', ...), or '' when empty."""
    content, _, _ = _strip_tag(raw)
    parts = content.split()
    return parts[0] if parts else ""


# ── Parse ──────────────────────────────────────────────────────


def parse(tokens: list) -> list:
    """Parse a token list into an AST — a list of sibling nodes.

    The token list is not modified: whitespace control is applied to a shallow
    copy, so a caller can still reconstruct the original source from its tokens
    (the extends path does exactly that).
    """
    return _parse_nodes(_apply_whitespace_control(list(tokens)))


def _parse_nodes(tokens: list) -> list:
    """Parse one flat run of tokens into sibling nodes, recursing into bodies."""
    nodes = []
    i = 0
    count = len(tokens)

    while i < count:
        ttype, raw = tokens[i]

        if ttype == TEXT:
            if raw:  # an empty TEXT token contributes nothing to the output
                nodes.append(TextNode(raw))
            i += 1

        elif ttype == COMMENT:
            nodes.append(CommentNode())
            i += 1

        elif ttype == VAR:
            content, strip_before, _ = _strip_tag(raw)
            nodes.append(OutputNode(content, _needs_live_strip(tokens, i, strip_before)))
            i += 1

        elif ttype == BLOCK:
            content, strip_before, strip_after = _strip_tag(raw)
            node, i = _parse_block(
                content,
                _needs_live_strip(tokens, i, strip_before),
                strip_after,
                tokens,
                i,
            )
            if node is not None:
                nodes.append(node)

        else:
            i += 1

    return nodes


def _needs_live_strip(tokens: list, index: int, strip_before: bool) -> bool:
    """Does this strip-before marker still need a RENDER-TIME trim?

    No when there is nothing to its left, and no when its left neighbour is a
    literal TEXT token — :func:`_apply_whitespace_control` already trimmed that
    text, and the interpreter's ``output[-1].rstrip()`` would be re-stripping
    the identical string. Yes when the left neighbour is a value/block/comment,
    because then the thing to trim is rendered output that only exists at render
    time. That is also precisely the case the compiler cannot bake, so the same
    flag drives its fallback.
    """
    return strip_before and index > 0 and tokens[index - 1][0] != TEXT


def _parse_block(content: str, strip_before: bool, strip_after: bool,
                 tokens: list, i: int):
    """Build the node for the BLOCK token at ``i``. Returns (node, next_index);
    a node of ``None`` means "emit nothing" (never happens today, kept so a
    future tag can be parse-only)."""
    parts = content.split()
    tag = parts[0] if parts else ""

    if tag == "if":
        return _parse_if(content, strip_before, strip_after, tokens, i)

    if tag == "for":
        return _parse_for(content, strip_before, strip_after, tokens, i)

    if tag == "set":
        return SetNode(content, strip_before), i + 1

    if tag == "include":
        return IncludeNode(content, strip_before), i + 1

    if tag == "macro":
        body, end = _collect_macro_body(tokens, i)
        _bake_strip_after_end(tokens, strip_after, end)
        return MacroNode(content, _parse_nodes(body), strip_before), end

    if tag == "from":
        return FromImportNode(content, strip_before), i + 1

    if tag == "import":
        return ImportAsNode(content, strip_before), i + 1

    if tag == "cache":
        body, end = _collect_body(tokens, i, "cache", "endcache")
        _bake_strip_after_end(tokens, strip_after, end)
        return CacheNode(content, _parse_nodes(body), strip_before), end

    if tag == "spaceless":
        body, end = _collect_body(tokens, i, "spaceless", "endspaceless")
        _bake_strip_after_end(tokens, strip_after, end)
        return SpacelessNode(_parse_nodes(body), strip_before), end

    if tag == "autoescape":
        body, end = _collect_body(tokens, i, "autoescape", "endautoescape")
        _bake_strip_after_end(tokens, strip_after, end)
        return AutoescapeNode(content, _parse_nodes(body), strip_before), end

    if tag == "live":
        body, end, nested = _collect_live_body(tokens, i)
        _bake_strip_after_end(tokens, strip_after, end)
        return LiveNode(
            content,
            _parse_nodes(body),
            "".join(raw for (_t, raw) in body),
            nested,
            strip_before,
        ), end

    if tag == "extends":
        return ExtendsNode(content, strip_before), i + 1

    if tag in ("block", "endblock"):
        return BlockMarkerNode(parts[1] if len(parts) > 1 else "", strip_before), i + 1

    # A stray terminator or an unknown tag: no output, advance one token.
    return SkipNode(strip_before), i + 1


def _parse_if(content: str, strip_before: bool, strip_after: bool,
              tokens: list, start: int):
    """Group {% if %} / {% elseif %} / {% elif %} / {% else %} / {% endif %}.

    The depth-counting scan below is now the ONLY copy of this grouping (it was
    duplicated in ``engine._handle_if`` and ``compiler._collect_if``). Its
    malformed-input behaviour is preserved exactly: with no matching
    {% endif %} the loop runs to the end of the token list and the final branch
    is never appended, so the construct renders nothing and swallows the rest of
    the template.
    """
    branches = []
    current_tokens = []
    current_cond = content[3:].strip()  # remove 'if '
    depth = 0
    i = start + 1

    while i < len(tokens):
        ttype, raw = tokens[i]
        if ttype == BLOCK:
            tag_content, _, _ = _strip_tag(raw)
            tag_parts = tag_content.split()
            tag = tag_parts[0] if tag_parts else ""

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

    _bake_strip_after_end(tokens, strip_after, i)
    return IfNode([(cond, _parse_nodes(body)) for cond, body in branches],
                  strip_before), i


def _parse_for(content: str, strip_before: bool, strip_after: bool,
               tokens: list, start: int):
    """Group {% for %} / {% else %} / {% endfor %} and parse the loop header.

    The ONLY copy of this grouping (it was duplicated in ``engine._handle_for``
    and ``compiler._collect_for``). A header that does not match ``_FOR_RE`` is
    NOT grouped — the interpreter advanced a single token in that case, leaving
    the body to render inline once and the {% endfor %} to be skipped, so the
    parser emits a bodiless :class:`SkipNode` to reproduce it.
    """
    for_match = _FOR_RE.match(content)
    if not for_match:
        return SkipNode(strip_before), start + 1

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
            tag_parts = tag_content.split()
            tag = tag_parts[0] if tag_parts else ""

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

    _bake_strip_after_end(tokens, strip_after, i)
    return ForNode(
        for_match.group(1),
        for_match.group(2),
        for_match.group(3).strip(),
        _parse_nodes(body_tokens),
        _parse_nodes(else_tokens),
        strip_before,
    ), i


def _collect_body(tokens: list, start: int, open_tag: str, end_tag: str):
    """Collect the tokens between a block tag and its matching end tag, counting
    nesting. Returns ``(body_tokens, index_past_end_tag)``.

    ONE copy of a loop ``engine.py`` had three times, character for character —
    for {% cache %}, {% spaceless %} and {% autoescape %}.
    """
    body = []
    depth = 0
    i = start + 1
    while i < len(tokens):
        if tokens[i][0] == BLOCK:
            tag = _tag_name(tokens[i][1])
            if tag == open_tag:
                depth += 1
                body.append(tokens[i])
            elif tag == end_tag:
                if depth == 0:
                    i += 1
                    break
                depth -= 1
                body.append(tokens[i])
            else:
                body.append(tokens[i])
        else:
            body.append(tokens[i])
        i += 1
    return body, i


def _collect_macro_body(tokens: list, start: int):
    """Collect a {% macro %} body up to {% endmacro %}.

    Substring match and no nesting, exactly as the three engine handlers did
    (inline {% macro %}, {% from %} import, {% import %} as). It also covers a
    MALFORMED macro header, whose old code path skipped to {% endmacro %} and
    rendered nothing — grouping the body and rendering nothing is the same
    thing, so one loop now serves both.
    """
    body = []
    i = start + 1
    while i < len(tokens):
        if tokens[i][0] == BLOCK and "endmacro" in tokens[i][1]:
            i += 1
            break
        body.append(tokens[i])
        i += 1
    return body, i


def _collect_live_body(tokens: list, start: int):
    """Collect a {% live %} body up to {% endlive %}.

    Returns ``(body_tokens, index_past_endlive, nested)``. ``nested`` flags a
    {% live %} inside the body; the parser records it rather than raising so the
    error still surfaces from the render, as it always did.
    """
    body = []
    nested = False
    i = start + 1
    while i < len(tokens):
        if tokens[i][0] == BLOCK:
            tag = _tag_name(tokens[i][1])
            if tag == "live":
                nested = True
            if tag == "endlive":
                i += 1
                break
            body.append(tokens[i])
        else:
            body.append(tokens[i])
        i += 1
    return body, i, nested


def collect_macro_nodes(nodes: list) -> list:
    """Every :class:`MacroNode` in a tree, in source order.

    {% from "f" import a %} and {% import "f" as x %} both need "the macros
    defined in file f"; walking the tree gives them one implementation instead
    of the two token scans they each carried.

    A macro's own body is NOT descended into, matching the token scans this
    replaces: they consumed a macro's body wholesale while collecting it, so a
    macro nested inside another macro was never visible to an import.
    """
    found = []
    for node in nodes:
        if node.kind == "macro":
            found.append(node)
        elif node.kind == "if":
            for _cond, body in node.branches:
                found.extend(collect_macro_nodes(body))
        elif node.kind == "for":
            found.extend(collect_macro_nodes(node.body))
            found.extend(collect_macro_nodes(node.else_body))
        elif node.kind in ("cache", "spaceless", "autoescape", "live"):
            found.extend(collect_macro_nodes(node.body))
    return found
