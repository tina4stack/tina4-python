#!/usr/bin/env python3
# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""
audit_doc_drift.py -- fail when the packaged CLAUDE.md or the authoritative AI
skills document an API the code does not have.

This is the machine side of the First Principle ("Documentation Matches Code
Reality"), aimed at the two files that ship INSIDE this repo and are read by AI
agents: ``tina4_python/CLAUDE.md`` and ``.claude/skills/**/references/*.md`` (the
canonical skills master lives here, so tina4-js and tina4-maintainer references
are audited here too).

Every claim below is checked against the LIVE package -- imported and
introspected, never a hand-kept list -- so the gate cannot itself drift:

  1. CLAUDE.md  -- every ``from tina4_python... import X`` in a python fence
     resolves, every ``.attr`` read on a resolved Tina4 symbol exists, and every
     ``CapWord.method(`` whose base is neither a snippet-local name, a Python
     builtin, a declared example model, nor a real Tina4 symbol is flagged.
     (Catches ``CRUD.to_crud`` -- there is no ``CRUD`` and no ``to_crud``.)

  2. tina4-developer-python skill --
     - the stated return type of ``where`` / ``all`` / ``select`` must equal the
       real return annotation (``ModelCollection``, never "plain list");
     - a ``@websocket`` handler's signature must be ``(connection, event, data)``;
     - a meta decorator (``@noauth`` / ``@secured`` / ``@description`` / ``@tags``)
       must sit ABOVE ``@get`` / ``@post`` / ..., never below it.

  3. tina4-js skill -- every name imported ``from 'tina4js'`` / ``'tina4js/<sub>'``
     must be a real export of the tina4-js source (read from the sibling
     ``../tina4-js`` checkout). (Catches ``import { mount } from 'tina4js'``.)

Usage:
    python3 scripts/audit_doc_drift.py            # report (exit 0)
    python3 scripts/audit_doc_drift.py --strict   # CI gate (exit 1 on drift)
"""
from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import inspect
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Example model names the docs use as placeholders (never Tina4 symbols). A
# CapWord method-call base that is one of these is app code, not a framework API.
EXAMPLE_MODELS = {
    "User", "Product", "Note", "Order", "Post", "Item", "Customer", "Article",
    "Task", "Event", "Comment", "Category", "Visit", "Author", "Book", "Todo",
    "Invoice", "Account", "Message", "Contact", "Page", "Tag", "Role", "MyModel",
    "Foo", "Bar", "Widget", "MyCounter", "MyWidget",
}
# Meta decorators that must sit above the HTTP-method decorator.
META_DECORATORS = {"noauth", "secured", "description", "tags", "cached", "middleware", "template"}
METHOD_DECORATORS = {"get", "post", "put", "patch", "delete", "any_method", "websocket"}


def _iter_fences(markdown: str, lang: str):
    """Yield (start_line, code) for every fenced block of the given language."""
    pattern = re.compile(r"```" + re.escape(lang) + r"\b[^\n]*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(markdown):
        start_line = markdown[: match.start()].count("\n") + 2
        yield start_line, match.group(1)


def _tina4_public_names() -> dict:
    """Public Tina4 symbols reachable for attribute checks: {name: object}."""
    names: dict = {}
    for mod_name in (
        "tina4_python", "tina4_python.orm", "tina4_python.orm.model",
        "tina4_python.auth", "tina4_python.crud", "tina4_python.core.router",
        "tina4_python.queue", "tina4_python.api", "tina4_python.graphql",
        "tina4_python.session", "tina4_python.frond", "tina4_python.container",
        "tina4_python.seeder",
    ):
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in dir(module):
            if attr.startswith("_"):
                continue
            obj = getattr(module, attr)
            if inspect.isclass(obj) or inspect.isfunction(obj):
                names.setdefault(attr, obj)
    return names


# ---------------------------------------------------------------- CLAUDE.md ---
def check_claude_md(root: Path) -> list[str]:
    path = root / "tina4_python" / "CLAUDE.md"
    problems: list[str] = []
    if not path.exists():
        return [f"{path}: packaged CLAUDE.md not found"]
    text = path.read_text(encoding="utf-8")
    public = _tina4_public_names()
    builtin_names = set(dir(builtins)) | {"self", "cls", "request", "response", "app", "db"}

    for start, code in _iter_fences(text, "python"):
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue  # illustrative fragments are not always valid modules

        # names defined inside the fence (imports, assignments, defs, args, loops)
        local: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tina4_python"):
                mod = node.module
                for alias in node.names:
                    bound = alias.asname or alias.name
                    local[bound] = ("tina4import", mod, alias.name)
                    try:
                        module = importlib.import_module(mod)
                        if alias.name != "*" and not hasattr(module, alias.name):
                            problems.append(
                                f"CLAUDE.md:{start}: `from {mod} import {alias.name}` "
                                f"-- {alias.name} is not exported by {mod}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"CLAUDE.md:{start}: cannot import {mod} ({exc})")
            elif isinstance(node, (ast.Import,)):
                for alias in node.names:
                    local[(alias.asname or alias.name).split(".")[0]] = ("import", None, None)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    for name in _assigned_names(tgt):
                        local.setdefault(name, ("local", None, None))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.setdefault(node.name, ("local", None, None))
                for arg in [*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs]:
                    local.setdefault(arg.arg, ("local", None, None))
            elif isinstance(node, ast.ClassDef):
                local.setdefault(node.name, ("local", None, None))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                for name in _assigned_names(node.target):
                    local.setdefault(name, ("local", None, None))
            elif isinstance(node, ast.comprehension):
                for name in _assigned_names(node.target):
                    local.setdefault(name, ("local", None, None))
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                for name in _assigned_names(node.optional_vars):
                    local.setdefault(name, ("local", None, None))

        # attribute-call bases: BASE.method(...)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            base = node.func.value
            if not isinstance(base, ast.Name):
                continue
            base_name = base.id
            attr = node.func.attr
            kind = local.get(base_name, (None, None, None))[0]

            if kind == "tina4import":
                _, mod, orig = local[base_name]
                try:
                    module = importlib.import_module(mod)
                    obj = getattr(module, orig, None)
                    if obj is not None and not _has_member(obj, attr):
                        problems.append(
                            f"CLAUDE.md:{start}: `{base_name}.{attr}(...)` -- "
                            f"{orig} ({mod}) has no member `{attr}`"
                        )
                except Exception:
                    pass
                continue
            if kind is not None:
                continue  # local variable / builtin import
            # base is undefined in the fence
            if base_name in public:
                obj = public[base_name]
                if not _has_member(obj, attr):
                    problems.append(
                        f"CLAUDE.md:{start}: `{base_name}.{attr}(...)` -- Tina4 "
                        f"`{base_name}` has no member `{attr}`"
                    )
            elif base_name in builtin_names or base_name in EXAMPLE_MODELS:
                continue
            elif base_name[:1].isupper():
                # CapWord API-looking base that resolves to nothing real.
                problems.append(
                    f"CLAUDE.md:{start}: `{base_name}.{attr}(...)` -- `{base_name}` is "
                    f"not a Tina4 symbol, an imported name, or a declared example model"
                )
    return problems


def _assigned_names(target) -> list[str]:
    out: list[str] = []
    if isinstance(target, ast.Name):
        out.append(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            out.extend(_assigned_names(elt))
    return out


def _has_member(obj, attr: str) -> bool:
    if hasattr(obj, attr):
        return True
    # annotation-only / class-level fields that hasattr misses on the class object
    return attr in getattr(obj, "__annotations__", {})


# ---------------------------------------------- tina4-developer-python skill ---
def check_dev_skill(root: Path) -> list[str]:
    base = root / ".claude" / "skills" / "tina4-developer-python"
    problems: list[str] = []
    problems += _check_where_return_type(base / "references" / "data-and-orm.md")
    problems += _check_ws_and_order(base / "references" / "auth-and-services.md")
    problems += _check_ws_and_order(base / "SKILL.md")
    return problems


def _check_where_return_type(path: Path) -> list[str]:
    if not path.exists():
        return []
    from tina4_python.orm.model import ORM

    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    ret = inspect.signature(ORM.where).return_annotation
    ret_name = ret if isinstance(ret, str) else getattr(ret, "__name__", str(ret))
    # The real return type is ModelCollection; the docs must not call the result
    # of where()/all()/select() a "plain list" / "return a `list`".
    for match in re.finditer(r"[^\n.]*\b(where|all|select)\(\)[^\n.]*", text):
        sentence = match.group(0)
        if re.search(r"\bplain list\b", sentence) or re.search(r"return a `list`", sentence):
            line = text[: match.start()].count("\n") + 1
            problems.append(
                f"{path.name}:{line}: doc calls {match.group(1)}() a plain list, but "
                f"the live return type is `{ret_name}`"
            )
    return problems


def _check_ws_and_order(path: Path) -> list[str]:
    if not path.exists():
        return []
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    for start, code in _iter_fences(text, "python"):
        lines = code.splitlines()
        for idx, raw in enumerate(lines):
            line = raw.strip()
            # websocket handler signature must be (connection, event, data)
            if line.startswith("@websocket("):
                sig = _next_def_params(lines, idx)
                if sig is not None and sig != ["connection", "event", "data"]:
                    problems.append(
                        f"{path.name}:{start + idx}: @websocket handler signature "
                        f"is ({', '.join(sig)}); must be (connection, event, data)"
                    )
            # meta decorator must not sit below a method decorator on the same handler
            deco = re.match(r"@(\w+)", line)
            if deco and deco.group(1) in METHOD_DECORATORS:
                for below in lines[idx + 1:]:
                    b = below.strip()
                    if not b.startswith("@"):
                        break
                    m = re.match(r"@(\w+)", b)
                    if m and m.group(1) in META_DECORATORS:
                        problems.append(
                            f"{path.name}:{start + idx}: @{m.group(1)}() appears below "
                            f"@{deco.group(1)}(); meta decorators go ABOVE @{deco.group(1)}"
                        )
    return problems


def _next_def_params(lines: list[str], start_idx: int):
    for raw in lines[start_idx + 1:]:
        line = raw.strip()
        if line.startswith("@"):
            continue
        m = re.match(r"(?:async\s+)?def\s+\w+\((.*?)\)", line)
        if m:
            params = [p.strip().split(":")[0].split("=")[0].strip()
                      for p in m.group(1).split(",") if p.strip()]
            return params
        return None
    return None


# --------------------------------------------------------- tina4-js skill ---
def check_js_skill(root: Path, tina4_js_root: Path | None) -> list[str]:
    ref_dir = root / ".claude" / "skills" / "tina4-js" / "references"
    if not ref_dir.exists():
        return []
    if tina4_js_root is None:
        tina4_js_root = root.parent / "tina4-js"
    if not (tina4_js_root / "src" / "index.ts").exists():
        return [
            f"tina4-js skill: cannot verify imports -- tina4-js source not found at "
            f"{tina4_js_root} (checkout the sibling repo so exports can be read)"
        ]
    exports = _read_ts_exports(tina4_js_root / "src" / "index.ts")
    problems: list[str] = []
    import_re = re.compile(r"import\s*\{([^}]*)\}\s*from\s*'tina4js(?:/([\w-]+))?'")
    for md in sorted(ref_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        for match in import_re.finditer(text):
            names = [n.strip().split(" as ")[0].strip()
                     for n in match.group(1).split(",") if n.strip()]
            sub = match.group(2)
            valid = exports if not sub else _read_ts_exports_for_sub(tina4_js_root, sub, exports)
            line = text[: match.start()].count("\n") + 1
            for name in names:
                if name not in valid:
                    where = "tina4js" if not sub else f"tina4js/{sub}"
                    problems.append(
                        f"{md.name}:{line}: `import {{ {name} }} from '{where}'` -- "
                        f"`{name}` is not exported by tina4-js"
                    )
    return problems


def _read_ts_exports(index_ts: Path) -> set[str]:
    text = index_ts.read_text(encoding="utf-8")
    names: set[str] = set()
    # export { a, b, c } from '...';  (skip `export type { ... }`)
    for match in re.finditer(r"export\s+\{([^}]*)\}", text):
        segment = text[max(0, match.start() - 12): match.start()]
        if "export type" in segment:
            continue
        for part in match.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            names.add(part.split(" as ")[-1].strip())
    # export function foo / export const foo
    for match in re.finditer(r"export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", text):
        names.add(match.group(1))
    return names


def _read_ts_exports_for_sub(js_root: Path, sub: str, index_exports: set[str]) -> set[str]:
    for candidate in (js_root / "src" / sub / "index.ts",
                      js_root / "src" / sub / f"{sub}.ts"):
        if candidate.exists():
            return _read_ts_exports(candidate)
    return index_exports  # fall back to the barrel


# ------------------------------------------------------------------- main ---
def check(root: Path = REPO_ROOT, tina4_js_root: Path | None = None) -> list[str]:
    problems: list[str] = []
    problems += check_claude_md(root)
    problems += check_dev_skill(root)
    problems += check_js_skill(root, tina4_js_root)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit doc/skill drift against the live package.")
    parser.add_argument("--strict", action="store_true", help="exit 1 on drift (CI gate)")
    parser.add_argument("--tina4-js", type=Path, default=None, help="path to the tina4-js checkout")
    args = parser.parse_args()

    problems = check(REPO_ROOT, args.tina4_js)
    if problems:
        print(f"Doc-drift audit: {len(problems)} problem(s) found:\n")
        for p in problems:
            print(f"  - {p}")
        print("\nFix the docs/skills to match the code (or the code to match the docs).")
        return 1 if args.strict else 0
    print("Doc-drift audit: clean -- every documented API resolves against the live code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
