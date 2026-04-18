"""Project index — a lightweight, persistent "where is what" map.

The AI chat, in-editor search, and any future code-navigation tools all
want the same thing: a mental model of the project that doesn't need to
be rebuilt from scratch every turn. This module maintains one.

Design:

- **Storage**: ``.tina4/project_index.json`` at the project root. Plain
  JSON, so it's diff-friendly and can be committed if the user wants it
  (by default it's git-ignored).
- **Freshness**: the index *lazy-refreshes on read*. Every public call
  first walks the file tree, compares mtimes against stored entries,
  and re-extracts any stale file. No background thread, no watcher,
  no coupling to file_write/file_patch — a single ``stat`` per file
  is fast enough for projects up to a few thousand files.
- **Extractors**: per-language symbol extraction via stdlib only.
  Python uses ``ast`` for real parsing (classes, funcs, imports,
  tina4 route decorators). Others (Twig, SQL, SCSS, TS/JS, MD) use
  lightweight regex — good enough to answer "which file has X".
- **No LLM involvement**: extraction is pure static analysis. A future
  upgrade could layer AI-generated prose summaries on top, but the
  static layer needs to be deterministic, fast, and zero-token.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from pathlib import Path

INDEX_DIRNAME = ".tina4"
INDEX_FILENAME = "project_index.json"

# Skip noisy / generated / vendored directories outright. These rarely
# contain user intent and would dominate the index otherwise.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    ".tina4", "logs", ".idea", ".vscode",
}

# Only index file types we can reason about. Binaries + noise excluded.
_INDEX_EXT = {
    ".py", ".twig", ".html", ".sql", ".scss", ".css", ".js", ".ts",
    ".mjs", ".md", ".json", ".yml", ".yaml", ".toml", ".env",
}

# Hard cap on per-file size — anything larger is probably generated
# and would bloat the JSON without helping the AI.
_MAX_FILE_BYTES = 256 * 1024


def _project_root() -> Path:
    return Path(os.getcwd()).resolve()


def _index_path() -> Path:
    p = _project_root() / INDEX_DIRNAME
    p.mkdir(exist_ok=True)
    return p / INDEX_FILENAME


# ── Per-language extractors ─────────────────────────────────────────


def _extract_python(text: str) -> dict:
    """Real AST parse — class/function names, top-level imports, tina4
    route decorators (method + path). Falls back to an empty skeleton
    if the file has a syntax error so a broken edit never stops indexing."""
    out: dict = {"symbols": [], "imports": [], "routes": [], "docstring": ""}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    doc = ast.get_docstring(tree)
    if doc:
        out["docstring"] = doc.strip().splitlines()[0][:200]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["symbols"].append(node.name)
            # Look for @get("/path"), @post("/path"), etc.
            for dec in node.decorator_list:
                method, path = _tina4_route_from_decorator(dec)
                if method and path:
                    out["routes"].append({"method": method, "path": path, "handler": node.name})
        elif isinstance(node, ast.ClassDef):
            out["symbols"].append(node.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out["imports"].append(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out["imports"].append(node.module)
    return out


_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "any_method"}


def _tina4_route_from_decorator(dec: ast.expr) -> tuple[str | None, str | None]:
    """Return (METHOD, path) if the decorator is a tina4 route, else (None, None)."""
    call = dec if isinstance(dec, ast.Call) else None
    name_node = call.func if call else dec
    # @get("/x") or @router.get("/x")
    if isinstance(name_node, ast.Name):
        name = name_node.id
    elif isinstance(name_node, ast.Attribute):
        name = name_node.attr
    else:
        return None, None
    if name not in _ROUTE_METHODS:
        return None, None
    if not call or not call.args:
        return name.upper(), ""
    first = call.args[0]
    # Python 3.8+: Constant(value="/path"). Older: Str. Tina4 also
    # supports list-of-paths, take the first.
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return name.upper(), first.value
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        el = first.elts[0]
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            return name.upper(), el.value
    return name.upper(), ""


_TWIG_EXTENDS = re.compile(r"""\{%\s*extends\s+['"]([^'"]+)['"]\s*%\}""")
_TWIG_BLOCK = re.compile(r"""\{%\s*block\s+([A-Za-z_][\w-]*)""")
_TWIG_INCLUDE = re.compile(r"""\{%\s*include\s+['"]([^'"]+)['"]""")


def _extract_twig(text: str) -> dict:
    return {
        "extends": _TWIG_EXTENDS.findall(text),
        "blocks": sorted(set(_TWIG_BLOCK.findall(text))),
        "includes": sorted(set(_TWIG_INCLUDE.findall(text))),
    }


_SQL_CREATE = re.compile(r"""create\s+(?:unique\s+)?(table|index|view|trigger|sequence|procedure|function)\s+(?:if\s+not\s+exists\s+)?([A-Za-z_][\w.]*)""", re.I)
_SQL_ALTER = re.compile(r"""alter\s+(table|index|view)\s+([A-Za-z_][\w.]*)""", re.I)


def _extract_sql(text: str) -> dict:
    out = {"creates": [], "alters": []}
    for kind, name in _SQL_CREATE.findall(text):
        out["creates"].append(f"{kind.upper()} {name}")
    for kind, name in _SQL_ALTER.findall(text):
        out["alters"].append(f"{kind.upper()} {name}")
    return out


_JS_EXPORT = re.compile(r"""^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)""", re.M)
_JS_IMPORT = re.compile(r"""^\s*import\s+[^'"]+?['"]([^'"]+)['"]""", re.M)


def _extract_js_ts(text: str) -> dict:
    return {
        "exports": sorted(set(_JS_EXPORT.findall(text))),
        "imports": sorted(set(_JS_IMPORT.findall(text))),
    }


_MD_H1 = re.compile(r"^#\s+(.+)$", re.M)
_MD_H2 = re.compile(r"^##\s+(.+)$", re.M)


def _extract_md(text: str) -> dict:
    return {
        "title": (_MD_H1.search(text) or [None, ""])[1].strip(),
        "sections": _MD_H2.findall(text)[:30],
    }


def _extract_generic(text: str) -> dict:
    """Fallback summary — first non-blank comment / content line."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("<!--"):
            continue
        return {"first_line": s[:200]}
    return {}


_EXTRACTORS = {
    ".py": _extract_python,
    ".twig": _extract_twig,
    ".html": _extract_twig,
    ".sql": _extract_sql,
    ".js": _extract_js_ts,
    ".mjs": _extract_js_ts,
    ".ts": _extract_js_ts,
    ".md": _extract_md,
}


# ── Core index ─────────────────────────────────────────────────────


def _extract(path: Path) -> dict:
    """Return a per-file entry: path, size, mtime, sha256, plus
    language-specific details. Never raises — extraction errors become
    empty slots so a single broken file can't poison the index."""
    try:
        size = path.stat().st_size
        mtime = int(path.stat().st_mtime)
    except OSError:
        return {}
    entry: dict = {
        "path": str(path.relative_to(_project_root())),
        "size": size,
        "mtime": mtime,
        "language": _language_for(path),
    }
    if size > _MAX_FILE_BYTES:
        entry["skipped"] = f"too large ({size} bytes)"
        return entry
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entry
    entry["sha256"] = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
    extractor = _EXTRACTORS.get(path.suffix, _extract_generic)
    try:
        entry.update(extractor(text))
    except Exception as exc:
        entry["extraction_error"] = str(exc)[:200]
    # Synthesise a one-liner summary — cheap and useful for search.
    entry["summary"] = _summarise(entry)
    return entry


def _language_for(path: Path) -> str:
    return {
        ".py": "python", ".twig": "twig", ".html": "html", ".sql": "sql",
        ".scss": "scss", ".css": "css", ".js": "javascript", ".mjs": "javascript",
        ".ts": "typescript", ".md": "markdown", ".json": "json", ".yml": "yaml",
        ".yaml": "yaml", ".toml": "toml", ".env": "env",
    }.get(path.suffix, "text")


def _summarise(entry: dict) -> str:
    """One-line plain-English summary suitable for a search result row."""
    if "skipped" in entry:
        return entry["skipped"]
    if entry.get("docstring"):
        return entry["docstring"]
    if entry.get("title"):
        return entry["title"]
    if entry.get("routes"):
        r = entry["routes"][0]
        extra = f" (+{len(entry['routes']) - 1} more)" if len(entry["routes"]) > 1 else ""
        return f"{r['method']} {r['path']}{extra}"
    if entry.get("symbols"):
        return "defines " + ", ".join(entry["symbols"][:4])
    if entry.get("exports"):
        return "exports " + ", ".join(entry["exports"][:4])
    if entry.get("creates"):
        return "schema: " + ", ".join(entry["creates"][:3])
    if entry.get("extends"):
        return f"template, extends {entry['extends'][0]}"
    if entry.get("first_line"):
        return entry["first_line"]
    return ""


def _walk_project() -> list[Path]:
    root = _project_root()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Mutate in place so os.walk doesn't descend into skipped dirs.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                # Allow dotfiles that are meaningful config (.env) but not editor cruft.
                if fn not in {".env"}:
                    continue
            if Path(fn).suffix not in _INDEX_EXT and fn != ".env":
                continue
            found.append(Path(dirpath) / fn)
    return found


def _load_raw() -> dict:
    p = _index_path()
    if not p.exists():
        return {"version": 1, "files": {}, "generated_at": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}, "generated_at": 0}


def _save_raw(data: dict) -> None:
    p = _index_path()
    data["generated_at"] = int(time.time())
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def refresh() -> dict:
    """Lazy incremental refresh: compare current mtimes to the stored
    index, re-extract changed/new files, drop entries for deleted ones.
    Returns {added, updated, removed, total} counts."""
    data = _load_raw()
    files: dict = data.get("files", {})
    added = updated = 0
    seen: set[str] = set()
    root = _project_root()
    for p in _walk_project():
        rel = str(p.relative_to(root))
        seen.add(rel)
        try:
            mtime = int(p.stat().st_mtime)
        except OSError:
            continue
        existing = files.get(rel)
        if existing and existing.get("mtime") == mtime:
            continue
        files[rel] = _extract(p)
        if existing:
            updated += 1
        else:
            added += 1
    removed_paths = [k for k in files if k not in seen]
    for k in removed_paths:
        del files[k]
    data["files"] = files
    _save_raw(data)
    return {
        "added": added,
        "updated": updated,
        "removed": len(removed_paths),
        "total": len(files),
        "path": str(_index_path().relative_to(root)),
    }


def search(query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive substring search over path, summary, symbols,
    routes, imports. Returns ranked matches — most specific first."""
    refresh()
    data = _load_raw()
    q = (query or "").lower().strip()
    if not q:
        return []
    hits: list[tuple[int, dict]] = []
    for rel, entry in data["files"].items():
        score = 0
        # Path hit is the strongest signal
        if q in rel.lower():
            score += 10
        # Exact symbol match next
        for s in entry.get("symbols", []):
            if q == s.lower():
                score += 8
            elif q in s.lower():
                score += 4
        for r in entry.get("routes", []):
            if q in (r.get("path", "") + " " + r.get("handler", "")).lower():
                score += 5
        if q in (entry.get("summary") or "").lower():
            score += 3
        for imp in entry.get("imports", []):
            if q in imp.lower():
                score += 1
        if score > 0:
            hits.append((score, {
                "path": rel,
                "summary": entry.get("summary", ""),
                "score": score,
                "language": entry.get("language", ""),
            }))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:max(1, limit)]]


def file_entry(rel_path: str) -> dict:
    """Full index entry for a single file (None if unknown)."""
    refresh()
    data = _load_raw()
    entry = data["files"].get(rel_path)
    return entry or {"error": f"Not in index: {rel_path}"}


def overview() -> dict:
    """High-level shape of the project: counts per language, counts of
    routes/models, the 10 most-recently changed files. Answers
    'what is this project?' in one call."""
    refresh()
    data = _load_raw()
    files = data["files"]
    langs: dict = {}
    route_count = model_count = 0
    for entry in files.values():
        lang = entry.get("language", "other")
        langs[lang] = langs.get(lang, 0) + 1
        route_count += len(entry.get("routes", []))
        # Classes in src/orm/ are models by convention
        if entry.get("path", "").startswith("src/orm/") and entry.get("symbols"):
            model_count += 1
    recent = sorted(
        ({"path": e.get("path"), "summary": e.get("summary", ""), "mtime": e.get("mtime", 0)}
         for e in files.values()),
        key=lambda e: -(e["mtime"] or 0),
    )[:10]
    return {
        "total_files": len(files),
        "by_language": langs,
        "routes_declared": route_count,
        "orm_models": model_count,
        "recently_changed": recent,
        "index_generated_at": data.get("generated_at", 0),
    }
