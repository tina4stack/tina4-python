# Tina4Python
#
# Text folding + chunking for the Context subsystem.
#
# A thin, idiomatic port of the proven slice of neemee's tokenizer/chunkers
# (longmem-harness: pipeline.chunk_code / chunk_text, memory_systems.fold).
# Pure stdlib — ``re``/``unicodedata`` only. Nothing here touches SQLite; it
# produces the (folded body, raw text) pairs the FTS5 index stores.

import re
import unicodedata

# join comma-grouped numbers ("24,601" -> "24601") and split camelCase
# ("ForeignKeyField" -> "foreign key field") so a query token reaches a
# code identifier. snake_case already splits for free at the tokenizer.
_NUM_COMMA = re.compile(r"(?<=\d),(?=\d)")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD_RE = re.compile(r"[a-z0-9]+")

# Sentence boundary = end punctuation FOLLOWED BY whitespace/EOL, or a newline.
# NOT a bare '.', which would shred embedded code in prose ("db.fetch()" ->
# "db. fetch()"). Intra-token dots (method calls, module paths) stay intact.
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")

# Chunk boundaries across languages: python defs/classes/decorators, php/js
# functions and methods, ts exports/interfaces, php traits, and Object Pascal
# unit/type/routine headers (Delphi is case-insensitive, accept either case).
_TOPLEVEL = re.compile(
    r"^(async def |def |class |@\w"
    r"|\s*(?:public |private |protected |static |final |abstract )*function \w"
    r"|(?:export )?(?:default )?(?:abstract )?class "
    r"|interface |trait "
    r"|export (?:const|function|interface|type|async) "
    r"|[Uu]nit |[Pp]rocedure |[Ff]unction |[Cc]onstructor |[Dd]estructor "
    r"|[Tt]ype$)"
)


def fold(text: str) -> str:
    """Lowercase, strip diacritics, join comma-grouped numbers, split camelCase.

    Applied symmetrically to the indexed ``body`` and to query tokens so
    matching is consistent: a query for ``field`` reaches ``IntegerField``.
    """
    text = _CAMEL.sub(" ", _NUM_COMMA.sub("", text)).lower()
    return unicodedata.normalize("NFKD", text) \
        .encode("ascii", "ignore").decode("ascii")


def light_stem(token: str) -> str:
    """Fold simple plurals: strip one trailing 's', never from ss/us/is
    endings (class, status, axis). QUERY-side only — so ``fields`` in a
    question also reaches ``Field`` definitions."""
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def terms(text: str):
    """Accent-folded lowercase alphanumeric tokens (digits kept)."""
    return _WORD_RE.findall(fold(text))


def _pack(segments, max_lines):
    """Pack line-segments into chunks of at most ``max_lines`` lines,
    hard-splitting any single oversized segment."""
    chunks, cur = [], []
    for seg in segments:
        while len(seg) > max_lines:            # oversized segment: hard split
            if cur:
                chunks.append(cur)
                cur = []
            chunks.append(seg[:max_lines])
            seg = seg[max_lines:]
        if cur and len(cur) + len(seg) > max_lines:
            chunks.append(cur)
            cur = []
        cur += seg
    if cur:
        chunks.append(cur)
    return chunks


def chunk_code(text: str, path: str = "", max_lines: int = 60):
    """Chunk source on top-level def/class/decorator boundaries (sentence
    chunking shreds code). Segments are packed up to ``max_lines``, and every
    chunk starts with a ``# file: <path>`` line so the path's tokens are
    indexed — 'where is the router?' should match core/router.py by name.

    Returns a list of ``(index, chunk_text)`` pairs.
    """
    lines = text.splitlines()
    bounds = [i for i, ln in enumerate(lines) if _TOPLEVEL.match(ln)]
    if not bounds or bounds[0] != 0:
        bounds = [0] + bounds
    segments = [lines[a:b] for a, b in zip(bounds, bounds[1:] + [len(lines)])]

    header = f"# file: {path}" if path else None
    out = []
    for i, ch in enumerate(_pack(segments, max_lines)):
        body = "\n".join(([header] if header else []) + ch)
        out.append((i, body))
    return out


def chunk_text(text: str, max_words: int = 350):
    """Chunk prose/docs into sentence-packed windows of at most ``max_words``
    words. Returns a list of ``(index, chunk_text)`` pairs."""
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    chunks, cur, cur_words = [], [], 0
    for s in sents:
        w = len(s.split())
        if cur and cur_words + w > max_words:
            chunks.append(" ".join(cur))
            cur, cur_words = [], 0
        cur.append(s)
        cur_words += w
    if cur:
        chunks.append(" ".join(cur))
    return list(enumerate(chunks))
