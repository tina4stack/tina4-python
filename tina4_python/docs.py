"""Live API RAG — `Docs` module.

Walks framework packages (`tina4_python/*`) via stdlib `inspect` and
reflects the user project's `src/` tree via `ast` (no import — user
files may have unresolved imports in a fresh process).

Exposes ranked search, class/method specs, a flat index, MCP-style
static mirrors, and a Markdown drift/sync helper. Zero third-party
deps — stdlib only.

Spec: plan/v3/22-LIVE-API-RAG.md
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import pkgutil
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Constants ────────────────────────────────────────────────────────

_FRAMEWORK_PKG = "tina4_python"
_USER_DIRS = ("orm", "routes", "app", "services")
_STDLIB_ALLOWLIST = {
    "print", "len", "range", "str", "int", "float", "list", "dict",
    "tuple", "set", "sum", "min", "max", "abs", "round", "open",
    "isinstance", "type", "hasattr", "getattr", "setattr", "repr",
    "sorted", "reversed", "enumerate", "zip", "map", "filter", "any",
    "all", "format", "bool", "bytes", "hex", "oct", "bin", "chr", "ord",
    "dumps", "loads", "join", "split", "strip", "replace", "find",
    "append", "extend", "get", "keys", "values", "items", "pop", "sort",
    "update", "copy", "clear", "remove", "count", "index",
    "lower", "upper", "title", "startswith", "endswith", "encode", "decode",
    "decode", "read", "write", "close", "flush", "seek", "tell",
    # Common tina4 methods that appear in docs which we know are fine
    # (the real entity lookup handles them anyway)
    "utcnow", "now",
}

# Module-level caches keyed by (project_root_str,)
_DOCS_CACHE: dict[str, "Docs"] = {}


# ── Data shapes ──────────────────────────────────────────────────────


@dataclass
class _Entity:
    fqn: str
    kind: str               # class | method | function
    name: str
    signature: str
    summary: str
    docstring: str
    file: str
    line: int
    version: str
    source: str              # framework | user | vendor
    visibility: str = "public"
    class_fqn: str | None = None   # only set for methods
    parent_class: str | None = None
    static: bool = False

    def as_hit(self, score: float) -> dict[str, Any]:
        return {
            "fqn": self.fqn,
            "kind": self.kind,
            "name": self.name,
            "signature": self.signature,
            "summary": self.summary,
            "file": self.file,
            "line": self.line,
            "version": self.version,
            "source": self.source,
            "score": round(score, 4),
            "visibility": self.visibility,
        }


# ── Tokenisation + ranking helpers ───────────────────────────────────


_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenise(text: str) -> list[str]:
    if not text:
        return []
    # Split camelCase first, then fallback to underscores / whitespace / punctuation.
    text = _CAMEL_SPLIT.sub(" ", text)
    parts = re.split(r"[\s_\-./:,;()\[\]{}]+", text.lower())
    return [p for p in parts if p]


def _summary_from_doc(doc: str) -> str:
    if not doc:
        return ""
    # First non-empty line.
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


# ── Framework reflection (inspect-based) ─────────────────────────────


def _iter_framework_modules():
    """Yield fully-qualified module names under `tina4_python`."""
    try:
        pkg = importlib.import_module(_FRAMEWORK_PKG)
    except Exception:
        return
    yield pkg.__name__
    if not hasattr(pkg, "__path__"):
        return
    for _finder, name, _is_pkg in pkgutil.walk_packages(
        pkg.__path__, prefix=pkg.__name__ + "."
    ):
        yield name


def _safe_signature(obj) -> str:
    try:
        sig = inspect.signature(obj)
        return f"{obj.__name__}{sig}"
    except (TypeError, ValueError):
        try:
            return f"{obj.__name__}(...)"
        except Exception:
            return "(...)"


def _is_private_name(name: str) -> bool:
    """Dunder stays hidden always. Single-underscore is private (opt-in)."""
    if name.startswith("__") and name.endswith("__"):
        return True
    return name.startswith("_")


def _path_source_tag(path: str, project_root: Path) -> str:
    """Classify a file path as framework | user | vendor."""
    if not path:
        return "vendor"
    # Normalise
    abs_path = os.path.abspath(path)
    fw_root = os.path.dirname(
        os.path.abspath(importlib.util.find_spec(_FRAMEWORK_PKG).origin)
    ) if importlib.util.find_spec(_FRAMEWORK_PKG) else ""

    user_src = str(project_root / "src")

    if fw_root and abs_path.startswith(fw_root + os.sep):
        return "framework"
    if abs_path.startswith(user_src + os.sep) or abs_path == user_src:
        return "user"
    # Anything else (site-packages, .venv, stdlib) — vendor
    return "vendor"


def _framework_relative_file(path: str) -> str:
    """Return the framework-relative file (tina4_python/...) when possible."""
    if not path:
        return ""
    try:
        spec = importlib.util.find_spec(_FRAMEWORK_PKG)
        if spec and spec.origin:
            fw_root = os.path.dirname(os.path.dirname(os.path.abspath(spec.origin)))
            rel = os.path.relpath(os.path.abspath(path), fw_root)
            if not rel.startswith(".."):
                return rel
    except Exception:
        pass
    return path


def _reflect_framework(version: str) -> list[_Entity]:
    """Walk tina4_python/, reflect public classes and their public methods."""
    out: list[_Entity] = []
    seen_classes: set[str] = set()

    for modname in _iter_framework_modules():
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        # Skip third-party re-exports — only classes defined in tina4_python itself.
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if _is_private_name(name):
                continue
            if not getattr(obj, "__module__", "").startswith(_FRAMEWORK_PKG):
                continue
            fqn_class = f"{obj.__module__}.{obj.__qualname__}"
            if fqn_class in seen_classes:
                continue
            seen_classes.add(fqn_class)

            try:
                src_file = inspect.getsourcefile(obj) or ""
                src_lines = inspect.getsourcelines(obj)
                class_line = src_lines[1]
            except (OSError, TypeError):
                src_file, class_line = "", 0

            class_doc = inspect.getdoc(obj) or ""
            class_summary = _summary_from_doc(class_doc)

            out.append(_Entity(
                fqn=fqn_class,
                kind="class",
                name=obj.__name__,
                signature=f"class {obj.__name__}",
                summary=class_summary,
                docstring=class_doc,
                file=_framework_relative_file(src_file),
                line=class_line,
                version=version,
                source="framework",
            ))

            # Methods — both regular functions and @classmethod/@staticmethod wrappers.
            for mname, mobj in inspect.getmembers(obj):
                if _is_private_name(mname):
                    continue
                is_static = False
                is_class = False
                # Pick real callable
                raw = obj.__dict__.get(mname, None)
                if isinstance(raw, staticmethod):
                    is_static = True
                    func = raw.__func__
                elif isinstance(raw, classmethod):
                    is_class = True
                    func = raw.__func__
                elif inspect.isfunction(mobj) or inspect.ismethod(mobj):
                    func = mobj
                else:
                    continue

                # Only include methods actually defined on this class (not inherited).
                if func.__qualname__.split(".")[0] != obj.__qualname__.split(".")[-1]:
                    # Heuristic: compare the first qualname segment to class name.
                    # If the method's __qualname__ doesn't start with this class, skip.
                    owner = func.__qualname__.rsplit(".", 1)[0]
                    if owner != obj.__qualname__:
                        continue

                try:
                    mfile = inspect.getsourcefile(func) or src_file
                    mlines = inspect.getsourcelines(func)
                    mline = mlines[1]
                except (OSError, TypeError):
                    mfile, mline = src_file, 0

                mdoc = inspect.getdoc(func) or ""
                msummary = _summary_from_doc(mdoc)
                sig = _safe_signature(func)

                out.append(_Entity(
                    fqn=f"{fqn_class}.{mname}",
                    kind="method",
                    name=mname,
                    signature=sig,
                    summary=msummary,
                    docstring=mdoc,
                    file=_framework_relative_file(mfile),
                    line=mline,
                    version=version,
                    source="framework",
                    class_fqn=fqn_class,
                    parent_class=obj.__name__,
                    static=is_static or is_class,
                ))
    return out


# ── User reflection (AST-based) ──────────────────────────────────────


def _ast_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a Python-ish signature for a FunctionDef AST node."""
    args = node.args
    parts: list[str] = []

    def _annot(ann):
        if ann is None:
            return None
        try:
            return ast.unparse(ann)
        except Exception:
            return None

    pos_defaults = list(args.defaults)
    num_pos = len(args.args)
    num_defaults = len(pos_defaults)
    default_offset = num_pos - num_defaults

    for i, a in enumerate(args.args):
        piece = a.arg
        ann = _annot(a.annotation)
        if ann:
            piece += f": {ann}"
        if i >= default_offset:
            try:
                dv = ast.unparse(pos_defaults[i - default_offset])
            except Exception:
                dv = "..."
            piece += f" = {dv}"
        parts.append(piece)

    if args.vararg:
        piece = "*" + args.vararg.arg
        ann = _annot(args.vararg.annotation)
        if ann:
            piece += f": {ann}"
        parts.append(piece)
    elif args.kwonlyargs:
        parts.append("*")

    for i, a in enumerate(args.kwonlyargs):
        piece = a.arg
        ann = _annot(a.annotation)
        if ann:
            piece += f": {ann}"
        dv = args.kw_defaults[i]
        if dv is not None:
            try:
                piece += f" = {ast.unparse(dv)}"
            except Exception:
                pass
        parts.append(piece)

    if args.kwarg:
        piece = "**" + args.kwarg.arg
        ann = _annot(args.kwarg.annotation)
        if ann:
            piece += f": {ann}"
        parts.append(piece)

    ret = _annot(node.returns)
    sig = f"{node.name}({', '.join(parts)})"
    if ret:
        sig += f" -> {ret}"
    return sig


def _module_dotted_from_file(root: Path, file: Path) -> str:
    """Return 'src.orm.User' for '<root>/src/orm/User.py'."""
    rel = file.relative_to(root).with_suffix("")
    return ".".join(rel.parts)


def _reflect_user(project_root: Path, version: str) -> list[_Entity]:
    out: list[_Entity] = []
    for sub in _USER_DIRS:
        root = project_root / "src" / sub
        if not root.is_dir():
            continue
        for pyfile in root.rglob("*.py"):
            try:
                src = pyfile.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except (OSError, SyntaxError):
                continue
            module_fqn = _module_dotted_from_file(project_root, pyfile)
            rel_file = str(pyfile.relative_to(project_root))
            out.extend(_walk_user_module(tree, module_fqn, rel_file, version))
    return out


def _walk_user_module(
    tree: ast.AST,
    module_fqn: str,
    rel_file: str,
    version: str,
) -> list[_Entity]:
    """Extract classes, methods, module-level functions from a user AST."""
    out: list[_Entity] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_fqn = f"{module_fqn}.{node.name}"
            cdoc = ast.get_docstring(node) or ""
            out.append(_Entity(
                fqn=class_fqn,
                kind="class",
                name=node.name,
                signature=f"class {node.name}",
                summary=_summary_from_doc(cdoc),
                docstring=cdoc,
                file=rel_file,
                line=node.lineno,
                version=version,
                source="user",
            ))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    vis = "public"
                    if item.name.startswith("__") and item.name.endswith("__"):
                        vis = "magic"
                    elif item.name.startswith("_"):
                        vis = "private"
                    mdoc = ast.get_docstring(item) or ""
                    out.append(_Entity(
                        fqn=f"{class_fqn}.{item.name}",
                        kind="method",
                        name=item.name,
                        signature=_ast_signature(item),
                        summary=_summary_from_doc(mdoc),
                        docstring=mdoc,
                        file=rel_file,
                        line=item.lineno,
                        version=version,
                        source="user",
                        visibility=vis,
                        class_fqn=class_fqn,
                        parent_class=node.name,
                    ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            vis = "public"
            if node.name.startswith("__") and node.name.endswith("__"):
                vis = "magic"
            elif node.name.startswith("_"):
                vis = "private"
            mdoc = ast.get_docstring(node) or ""
            out.append(_Entity(
                fqn=f"{module_fqn}.{node.name}",
                kind="function",
                name=node.name,
                signature=_ast_signature(node),
                summary=_summary_from_doc(mdoc),
                docstring=mdoc,
                file=rel_file,
                line=node.lineno,
                version=version,
                source="user",
                visibility=vis,
            ))
    return out


# ── Ranking ──────────────────────────────────────────────────────────


def _score(entity: _Entity, tokens: list[str], raw_query: str) -> float:
    if not tokens:
        return 0.0
    score = 0.0
    name_lower = entity.name.lower()
    # 5: exact (case-insensitive) name match on full query.
    if raw_query.strip().lower() == name_lower:
        score += 5.0
    # 3: any token is a prefix of name.
    for tok in tokens:
        if name_lower.startswith(tok):
            score += 3.0
            break
    # 2: per token in summary.
    summary_lower = entity.summary.lower()
    for tok in tokens:
        if tok in summary_lower:
            score += 2.0
    # 1: per token in docstring body.
    doc_lower = entity.docstring.lower()
    for tok in tokens:
        if tok in doc_lower:
            score += 1.0
    # Fallback: token in name (substring, not prefix) — small boost so "render"
    # still ranks "render_template"-style methods.
    for tok in tokens:
        if tok in name_lower:
            score += 0.5
    if entity.source == "user":
        score *= 1.2
    return score


# ── Drift helpers ────────────────────────────────────────────────────


_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)\n```", re.DOTALL)
_CALL_RE = re.compile(
    r"(?:[a-zA-Z_][\w]*)"
    r"(?:->|::|\.)"
    r"([a-zA-Z_][\w]*)"
    r"\s*\("
)


# ── Main class ───────────────────────────────────────────────────────


class Docs:
    """Live API RAG index + drift helpers.

    Usage:
        docs = Docs(project_root="/path/to/project")
        hits = docs.search("render template", k=5)
        spec = docs.class_spec("tina4_python.core.response.Response")
    """

    __slots__ = (
        "project_root",
        "_framework",
        "_user",
        "_user_mtime",
        "_version",
    )

    def __init__(self, project_root: str) -> None:
        self.project_root: Path = Path(project_root)
        self._framework: list[_Entity] | None = None
        self._user: list[_Entity] | None = None
        self._user_mtime: float = 0.0
        self._version: str = self._detect_version()

    def _detect_version(self) -> str:
        try:
            mod = importlib.import_module(_FRAMEWORK_PKG)
            return getattr(mod, "__version__", "") or "0.0.0"
        except Exception:
            return "0.0.0"

    # ── Index build / refresh ──────────────────────────────────────

    def _current_user_mtime(self) -> float:
        max_mt = 0.0
        for sub in _USER_DIRS:
            root = self.project_root / "src" / sub
            if not root.is_dir():
                continue
            for pyfile in root.rglob("*.py"):
                try:
                    mt = pyfile.stat().st_mtime
                    if mt > max_mt:
                        max_mt = mt
                except OSError:
                    continue
        return max_mt

    def _ensure_index(self) -> None:
        if self._framework is None:
            self._framework = _reflect_framework(self._version)
        current = self._current_user_mtime()
        if self._user is None or current > self._user_mtime:
            self._user = _reflect_user(self.project_root, self._version)
            self._user_mtime = current

    # ── Public API ─────────────────────────────────────────────────

    def index(self) -> list[dict[str, Any]]:
        """Flat list of every known entity (framework + user)."""
        self._ensure_index()
        return [e.as_hit(score=0.0) for e in (self._framework + self._user)]

    def search(
        self,
        query: str,
        k: int = 5,
        source: str = "all",
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        self._ensure_index()
        tokens = _tokenise(query)
        pool: list[_Entity] = []
        for e in self._framework + self._user:
            if e.source == "vendor":
                continue
            if source != "all" and e.source != source:
                continue
            if not include_private and (
                e.visibility == "private" or _is_private_name(e.name)
            ):
                continue
            pool.append(e)

        scored = [(e, _score(e, tokens, query)) for e in pool]
        scored = [p for p in scored if p[1] > 0]
        scored.sort(key=lambda p: (-p[1], p[0].fqn))
        return [e.as_hit(s) for (e, s) in scored[:k]]

    def class_spec(self, fqn: str) -> dict[str, Any] | None:
        """Full reflection of a class — `None` if not found."""
        self._ensure_index()
        all_entities = self._framework + self._user
        klass = next(
            (e for e in all_entities if e.kind == "class" and e.fqn == fqn),
            None,
        )
        if klass is None:
            return None
        methods = [
            {
                "name": m.name,
                "signature": m.signature,
                "summary": m.summary,
                "docstring": m.docstring,
                "file": m.file,
                "line": m.line,
                "visibility": m.visibility,
                "static": m.static,
                "source": m.source,
            }
            for m in all_entities
            if m.kind == "method" and m.class_fqn == fqn
        ]
        return {
            "fqn": klass.fqn,
            "kind": "class",
            "name": klass.name,
            "file": klass.file,
            "line": klass.line,
            "summary": klass.summary,
            "docstring": klass.docstring,
            "source": klass.source,
            "version": klass.version,
            "methods": methods,
        }

    def method_spec(
        self, class_fqn: str, method_name: str,
    ) -> dict[str, Any] | None:
        self._ensure_index()
        for e in self._framework + self._user:
            if e.kind == "method" and e.class_fqn == class_fqn and e.name == method_name:
                return {
                    "fqn": e.fqn,
                    "name": e.name,
                    "kind": "method",
                    "signature": e.signature,
                    "summary": e.summary,
                    "docstring": e.docstring,
                    "file": e.file,
                    "line": e.line,
                    "visibility": e.visibility,
                    "static": e.static,
                    "source": e.source,
                    "version": e.version,
                }
        return None

    # ── MCP-style static mirrors (shared cache per project_root) ──

    @staticmethod
    def _cached(project_root: str | None) -> "Docs":
        if project_root is None:
            project_root = os.getcwd()
        key = str(Path(project_root).resolve())
        inst = _DOCS_CACHE.get(key)
        if inst is None:
            inst = Docs(project_root)
            _DOCS_CACHE[key] = inst
        return inst

    @staticmethod
    def mcp_search(
        query: str,
        k: int = 5,
        project_root: str | None = None,
        source: str = "all",
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        return Docs._cached(project_root).search(
            query, k=k, source=source, include_private=include_private,
        )

    @staticmethod
    def mcp_method(
        class_fqn: str,
        name: str,
        project_root: str | None = None,
    ) -> dict[str, Any] | None:
        return Docs._cached(project_root).method_spec(class_fqn, name)

    @staticmethod
    def mcp_class(
        fqn: str,
        project_root: str | None = None,
    ) -> dict[str, Any] | None:
        return Docs._cached(project_root).class_spec(fqn)

    # ── Drift detector ─────────────────────────────────────────────

    @staticmethod
    def check_docs(md_path: str, project_root: str | None = None) -> dict[str, Any]:
        """Scan a markdown file for method calls that don't exist in the index."""
        path = Path(md_path)
        if not path.is_file():
            return {"drift": [], "error": f"file not found: {md_path}"}

        if project_root is None:
            project_root = str(path.parent)
        docs = Docs._cached(project_root)
        idx = docs.index()
        known = {e["name"] for e in idx}

        drift: list[dict[str, Any]] = []
        text = path.read_text(encoding="utf-8")
        line_of_offset = _build_line_index(text)

        for match in _FENCE_RE.finditer(text):
            block = match.group(1)
            block_start = match.start(1)
            for call in _CALL_RE.finditer(block):
                name = call.group(1)
                if name in known or name in _STDLIB_ALLOWLIST:
                    continue
                offset = block_start + call.start(1)
                line = line_of_offset(offset)
                drift.append({
                    "method": name,
                    "line": line,
                    "block": block.strip().splitlines()[0] if block.strip() else "",
                })
        return {"drift": drift}

    # ── Sync writer ────────────────────────────────────────────────

    @staticmethod
    def sync_docs(md_path: str, project_root: str | None = None) -> None:
        """Rewrite the `<!-- BEGIN GENERATED API -->` block in `md_path`."""
        path = Path(md_path)
        if not path.is_file():
            return
        if project_root is None:
            project_root = str(path.parent)
        docs = Docs._cached(project_root)
        generated = docs._render_generated_block()

        text = path.read_text(encoding="utf-8")
        begin = "<!-- BEGIN GENERATED API -->"
        end = "<!-- END GENERATED API -->"
        b = text.find(begin)
        e = text.find(end)
        if b == -1 or e == -1 or e < b:
            # Append a fresh block if markers aren't present.
            block = f"\n\n{begin}\n{generated}\n{end}\n"
            path.write_text(text.rstrip() + block, encoding="utf-8")
            return
        before = text[: b + len(begin)]
        after = text[e:]
        path.write_text(
            f"{before}\n{generated}\n{after}",
            encoding="utf-8",
        )

    def _render_generated_block(self) -> str:
        """Produce a small Markdown summary of classes and surface."""
        self._ensure_index()
        lines: list[str] = []
        lines.append(f"_Generated by `tina4_python.docs` — version {self._version}._")
        lines.append("")
        lines.append("## Framework classes")
        lines.append("")
        fw_classes = sorted(
            (e for e in self._framework if e.kind == "class"),
            key=lambda x: x.fqn,
        )
        method_counts: dict[str, int] = {}
        for m in self._framework:
            if m.kind == "method" and m.class_fqn:
                method_counts[m.class_fqn] = method_counts.get(m.class_fqn, 0) + 1
        for c in fw_classes:
            summary = f" — {c.summary}" if c.summary else ""
            lines.append(
                f"- `{c.fqn}` ({method_counts.get(c.fqn, 0)} methods){summary}"
            )
        if self._user:
            lines.append("")
            lines.append("## User code")
            lines.append("")
            user_classes = sorted(
                (e for e in self._user if e.kind == "class"),
                key=lambda x: x.fqn,
            )
            for c in user_classes:
                summary = f" — {c.summary}" if c.summary else ""
                lines.append(f"- `{c.fqn}`{summary}")
            user_fns = sorted(
                (e for e in self._user if e.kind == "function"),
                key=lambda x: x.fqn,
            )
            if user_fns:
                lines.append("")
                lines.append("### Functions")
                lines.append("")
                for f in user_fns:
                    lines.append(f"- `{f.fqn}`")
        return "\n".join(lines)


# ── Internal helpers ─────────────────────────────────────────────────


def _build_line_index(text: str):
    """Return a fn that maps a char offset in `text` to a 1-based line."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)

    def lookup(offset: int) -> int:
        # Binary search for the largest start <= offset.
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    return lookup
