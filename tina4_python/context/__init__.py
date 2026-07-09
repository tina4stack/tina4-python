# Tina4Python
#
# Context — a native, zero-dependency code/doc grounding index.
#
# Lets a Tina4 app ground its own AI assistant on its own source, offline:
# it walks the project, chunks code on def/class boundaries and docs as prose,
# and answers keyword/fuzzy queries over a SQLite FTS5 index (Python stdlib
# ``sqlite3`` — FTS5 + ``bm25()`` are built in, so NO new dependency).
#
# The retrieval core is a thin port of the proven slice of neemee
# (longmem-harness: memory_systems.SqliteFTS + pipeline.retrieve's stable
# source-over-tests / definition-first reorderings). It COMPLEMENTS the
# ``api_*`` reflection tools: ``api_*`` is exact structural lookup, Context is
# fuzzy/semantic FTS over source + docs.
#
#   from tina4_python.context import Context
#   ctx = Context(".tina4/context.db")
#   ctx.index_root("src")
#   ctx.search("where is the auth token issued?", k=5)
#   #  -> [{"path": "src/auth.py", "score": 2.31, "snippet": "..."}, ...]
#
# On-disk index defaults to ``.tina4/context.db`` (gitignored). Guards a
# sqlite build without FTS5: if absent, the Context degrades to safe no-ops
# rather than crashing the app.

import os
import re
import sqlite3
import threading
from pathlib import Path

from .chunker import (
    chunk_code,
    chunk_text,
    fold,
    light_stem,
    terms,
)

__all__ = ["Context", "default_context", "existing_context"]

# File classification — mirrors neemee's repo walk.
CODE_EXTS = {".py", ".php", ".js", ".mjs", ".ts", ".rb",
             ".pas", ".dpr", ".dpk", ".inc", ".dfm", ".fmx"}
DOC_EXTS = {".md", ".txt", ".rst", ".twig", ".html"}
# deploy/CLI/env answers live in config files, not sources — chunk as code
# (line windows), since sentence chunking shreds YAML/Dockerfiles.
CONFIG_EXTS = {".toml", ".yml", ".yaml"}
SPECIAL_FILES = {"dockerfile", "makefile", "docker-compose.yml",
                 "package.json", "composer.json",
                 ".env.example", ".env.sample"}
# Same dirs neemee skips, plus Tina4 runtime dirs that hold no source of truth
# (our own index/backups, session blobs, logs).
SKIP_DIRS = {".git", "__pycache__", "node_modules", "vendor", "dist",
             "build", "coverage", ".idea", ".venv", "venv", ".pytest_cache",
             ".tina4", "sessions", "logs"}

# generic question/code vocabulary that never NAMES a symbol — kept small.
_DEF_STOP = frozenset(
    "the and what how does can which where when who why list all available "
    "module class function functions method methods def get set new return "
    "import from with that this are is was for into use used".split())

# a chunk that DEFINES a queried symbol ('def get_token', 'class Widget')
# should out-rank one that merely USES it. Matched against the folded body.
_DEF_KW = r"(?:async def|def|class|function|fn|func|interface|trait)"


def _fts5_supported() -> bool:
    """True if this interpreter's sqlite3 was built with FTS5."""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
            return True
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return False
    except Exception:
        return False


class Context:
    """A SQLite FTS5 index over a project's source + docs.

    Methods:
        index_path(file, label=None) -> int   upsert one file (delete-by-path,
                                               re-chunk, insert); reindex-safe.
        index_root(root)             -> int   walk a tree, index every eligible
                                               file (skips vendor/build dirs).
        search(query, k=5)           -> list  [{path, score, snippet}] ranked by
                                               bm25() with source-over-tests +
                                               definition-first reordering.
    """

    def __init__(self, path="./.tina4/context.db", fts5_check=None):
        """``path`` is the on-disk index file (its parent dir is created).
        ``fts5_check`` overrides FTS5 detection (used by tests to exercise the
        graceful-degradation path); defaults to a real probe of this build.
        """
        self.path = str(path)
        self._lock = threading.Lock()
        self.conn = None
        self.root = None            # set by index_root; reindex_file relabels against it
        check = fts5_check or _fts5_supported
        self.available = bool(check())
        if not self.available:
            return
        parent = Path(self.path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        # One connection shared across threads (the dev-MCP handler may run on
        # a worker thread) with a lock serializing access — a same-thread-only
        # connection would reject those calls outright.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._ensure_table()

    # ── FTS5 availability ───────────────────────────────────────
    @classmethod
    def fts5_available(cls) -> bool:
        """Whether this Python's sqlite3 supports FTS5 (module-level probe)."""
        return _fts5_supported()

    # ── schema ──────────────────────────────────────────────────
    def _ensure_table(self):
        # `body` holds fold(text) so query/index tokenization is symmetric;
        # `raw` (UNINDEXED) keeps the original text to return as a snippet;
        # `path`/`cid` (UNINDEXED) are metadata used for upsert + citation.
        self.conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks "
            "USING fts5(cid UNINDEXED, path UNINDEXED, raw UNINDEXED, body)"
        )
        self.conn.commit()

    def reset(self):
        """Drop and recreate the index (full rebuild starting point)."""
        if not self.available:
            return
        with self._lock:
            self.conn.execute("DROP TABLE IF EXISTS chunks")
            self._ensure_table()

    # ── indexing ────────────────────────────────────────────────
    @staticmethod
    def _chunks_for(label, text):
        """(index, chunk_text) pairs — code files on def/class boundaries,
        everything else (docs) as prose."""
        ext = os.path.splitext(label)[1].lower()
        special = os.path.basename(label).lower() in SPECIAL_FILES
        if ext in CODE_EXTS or ext in CONFIG_EXTS or special:
            return chunk_code(text, path=label)
        return chunk_text(text)

    def index_path(self, file, label=None) -> int:
        """UPSERT one file into the index: delete this path's existing chunks,
        re-chunk the current contents, insert. A single file save re-indexes
        just that file (sub-100ms). ``label`` is the stored/citation path
        (defaults to ``str(file)``) and MUST be stable across calls for the
        same file so the delete targets the right rows. Returns rows inserted.
        """
        if not self.available:
            return 0
        stored = str(label) if label is not None else str(file)
        try:
            text = Path(file).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return 0
        rows = [
            (f"{stored}:{i}", stored, chunk, fold(chunk))
            for i, chunk in self._chunks_for(stored, text)
        ]
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE path = ?", (stored,))
            if rows:
                self.conn.executemany(
                    "INSERT INTO chunks(cid, path, raw, body) VALUES (?, ?, ?, ?)",
                    rows,
                )
            self.conn.commit()
        return len(rows)

    @staticmethod
    def _eligible(filename) -> bool:
        """True if a file should be indexed (the per-file filter used by both
        index_root and reindex_file). Directory skipping is handled separately."""
        fn = filename.lower()
        if fn.endswith(".min.js"):
            return False
        ext = os.path.splitext(fn)[1]
        return (ext in CODE_EXTS or ext in DOC_EXTS or ext in CONFIG_EXTS
                or fn in SPECIAL_FILES)

    def index_root(self, root) -> int:
        """Walk ``root``, indexing every eligible file (skips vendor/build/
        runtime dirs). Paths are stored RELATIVE to ``root`` for clean
        citations. Records ``root`` so reindex_file can relabel a changed file
        consistently. Returns the total number of chunks inserted."""
        if not self.available:
            return 0
        root = Path(root).resolve()
        self.root = root
        total = 0
        for dirpath, dirnames, filenames in os.walk(root):
            # prune skip-dirs and dotdirs in place
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in sorted(filenames):
                if not self._eligible(fn):
                    continue
                full = Path(dirpath) / fn
                rel = str(full.relative_to(root))
                total += self.index_path(full, label=rel)
        return total

    def reindex_file(self, changed_path) -> int:
        """Re-index a single changed file into the LIVE index — the hook the dev
        WebSocket reload trigger (POST /__dev/api/reload) calls so code_search
        tracks edits without a rebuild. Resolves ``changed_path`` against the
        indexed root, then: outside root / under a skip-or-dot dir / ineligible
        → skip (-1); deleted → drop its chunks (0); otherwise UPSERT (rows).
        No-op (-1) until index_root has run (nothing to keep fresh yet)."""
        if not self.available or self.root is None:
            return -1
        p = Path(changed_path)
        if not p.is_absolute():
            # the reload trigger reports paths relative to the project root (cwd
            # during `tina4 serve`); the index root may be a subdir like src/.
            p = Path.cwd() / changed_path
        try:
            rel = p.resolve().relative_to(self.root)
        except (ValueError, OSError):
            return -1                          # outside the indexed root
        if set(rel.parts) & SKIP_DIRS or any(part.startswith(".") for part in rel.parts[:-1]):
            return -1                          # under a skipped / dot dir
        if not self._eligible(rel.name):
            return -1
        stored = str(rel)
        if not p.exists():                     # deleted → drop its chunks
            with self._lock:
                self.conn.execute("DELETE FROM chunks WHERE path = ?", (stored,))
                self.conn.commit()
            return 0
        return self.index_path(p, label=stored)

    # ── query ───────────────────────────────────────────────────
    def _match_expr(self, query):
        """Build the FTS5 MATCH string: each folded query token (plus its
        light stem) as a quoted OR term. Quoting keeps it injection-safe."""
        toks = set()
        for t in terms(query):
            toks.add(t)
            toks.add(light_stem(t))
        toks.discard("")
        if not toks:
            return None, set()
        expr = " OR ".join('"%s"' % t for t in sorted(toks))
        return expr, toks

    @staticmethod
    def _is_testlike(path):
        s = (path or "").lower()
        return any(p in s for p in ("/test", "test/", "test_", "_test.",
                                    ".test.", "/example", "example/"))

    def _defines(self, folded_body, symbols):
        if not symbols:
            return False
        pat = re.compile(
            _DEF_KW + r"\s+(?:" + "|".join(re.escape(s) for s in symbols)
            + r")(?![a-z0-9])")
        return bool(pat.search(folded_body))

    def search(self, query, k=5):
        """Return the top-``k`` chunks as ``[{path, score, snippet}]``, ranked
        by ``bm25()`` then reordered with two stable, proven passes:
          - source-over-tests: a test that merely mentions a symbol sinks below
            the source that defines it (skipped when the query is about tests);
          - definition-first: a chunk that DEFINES a queried symbol rises above
            chunks that only use it.
        Score is a higher-is-better float (sqlite's bm25 sign flipped).
        """
        if not self.available:
            return []
        expr, _ = self._match_expr(query)
        if expr is None:
            return []
        pool_n = max(k * 3, 15)
        with self._lock:
            rows = self.conn.execute(
                "SELECT path, raw, body, bm25(chunks) AS s FROM chunks "
                "WHERE chunks MATCH ? ORDER BY s LIMIT ?",
                (expr, pool_n),
            ).fetchall()
        if not rows:
            return []

        # candidate symbol names from the query (drop generic vocab).
        symbols = {t for t in terms(query) if len(t) >= 3 and t not in _DEF_STOP}
        about_tests = "test" in query.lower()

        def sort_key(item):
            idx, (path, raw, body, s) = item
            is_test = 1 if (not about_tests and self._is_testlike(path)) else 0
            is_def = 0 if self._defines(body, symbols) else 1
            return (is_test, is_def, idx)   # bm25 order (idx) breaks ties

        ordered = sorted(enumerate(rows), key=sort_key)
        out = []
        for _, (path, raw, body, s) in ordered[:k]:
            out.append({
                "path": path,
                "score": round(-float(s), 6),   # bm25: more negative = better
                "snippet": self._snippet(raw),
            })
        return out

    @staticmethod
    def _snippet(raw, limit=280):
        text = (raw or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + " ..."

    # ── misc ────────────────────────────────────────────────────
    def count(self) -> int:
        if not self.available:
            return 0
        with self._lock:
            return self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

    def is_empty(self) -> bool:
        return self.count() == 0

    def close(self):
        if self.conn is not None:
            with self._lock:
                self.conn.close()
                self.conn = None


# ── process-wide shared index ───────────────────────────────────
# code_search (dev MCP) and the dev-reload reindex hook must share ONE index so
# a saved file is immediately searchable. Keyed by resolved db path.
_shared_contexts: dict = {}


def _db_key(db=None) -> str:
    return str((Path(db) if db else Path.cwd() / ".tina4" / "context.db").resolve())


def default_context(root=None, db=None) -> "Context":
    """Get (or create) the process-wide Context at ``db`` (default
    ``<cwd>/.tina4/context.db``). If ``root`` is given and the index is empty,
    builds it once. This is what code_search uses so the reload hook can keep
    the SAME index fresh."""
    key = _db_key(db)
    ctx = _shared_contexts.get(key)
    if ctx is None:
        ctx = Context(key)
        _shared_contexts[key] = ctx
    if root is not None and ctx.available and ctx.is_empty():
        ctx.index_root(root)
    return ctx


def existing_context(db=None):
    """Return the already-created shared Context for ``db`` (or None). Used by
    the reload hook so a file change reindexes an EXISTING index but never
    creates one on its own (nothing to keep fresh until code_search runs)."""
    return _shared_contexts.get(_db_key(db))
