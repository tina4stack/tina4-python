"""
tina4_python._import_helper — turn a wrong `tina4_python.<X>` import into a
helpful ModuleNotFoundError that names the closest real module in the tree.

The finder registers LAST on sys.meta_path, so Python's normal resolution runs
first. We're only consulted for names that all other finders already gave up
on — which means we never mask a legitimate ImportError raised deeper inside
a module that DOES exist. If we're being asked, the module truly does not
exist under this name.

The suggestion is derived from the REAL installed tree, read from DISK, so a
rename in the framework updates the hint automatically. There is no
hand-maintained wrong-guess list.

The tree is enumerated with the filesystem rather than pkgutil.walk_packages()
on purpose: walk_packages IMPORTS every package it descends into, because
recursing needs each package's __path__. Doing that here — from
tina4_python/__init__.py at import time — has two effects, and both are bugs:
it defeats the lazy subsystem loading, and it binds every subpackage as an
attribute on tina4_python, which shadows the callables __getattr__ exists to
provide. That second one is why `realtime` resolved to a module and stopped
being callable. See tests/test_import_helper_does_not_import_the_tree.py.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from difflib import get_close_matches
from importlib.abc import MetaPathFinder
from typing import Sequence


_PREFIX = "tina4_python."


class _Tina4ModuleFinder(MetaPathFinder):
    """Last-resort finder that turns tina4_python.X misses into hints."""

    def __init__(self) -> None:
        # Snapshot the tree once at install time. If a plugin registers a new
        # submodule after install, that plugin's own module load succeeds via
        # the normal finders BEFORE we're consulted, so the snapshot only
        # matters for the "did-you-mean" list. A missing plugin module still
        # produces a helpful hint, just without the plugin's name in it.
        self._known: tuple[str, ...] = tuple(self._walk())

    @staticmethod
    def _walk() -> Sequence[str]:
        try:
            pkg = importlib.import_module("tina4_python")
            names: list[str] = []
            for root in pkg.__path__:
                base = Path(root)
                for path in base.rglob("*"):
                    if path.name.startswith((".", "_")) and path.name != "__init__.py":
                        continue
                    if path.is_dir():
                        if (path / "__init__.py").is_file():
                            names.append(_PREFIX + ".".join(path.relative_to(base).parts))
                    elif path.suffix == ".py" and path.name != "__init__.py":
                        rel = path.relative_to(base).with_suffix("")
                        names.append(_PREFIX + ".".join(rel.parts))
            if names:
                return sorted(set(names))
            # Not a plain directory tree (zipimport, a namespace package): fall
            # back to the non-importing pkgutil call. Top level only, but
            # correct. Never walk_packages, which would import.
            return sorted(
                name for _, name, _ in pkgutil.iter_modules(pkg.__path__, prefix=_PREFIX)
            )
        except Exception:  # noqa: BLE001 — never let the helper break import
            return ()

    def find_spec(self, fullname, path, target=None):  # noqa: D401
        # Only intervene for tina4_python.<X> — everything else defers to
        # whatever finder comes next, but since we appended ourselves last
        # and this call reached us, no next finder exists.
        if not fullname.startswith(_PREFIX):
            return None

        # Compute the hint. Any failure here degrades to a plain
        # ModuleNotFoundError rather than raising the helper's own bug.
        try:
            hint = self._hint(fullname)
        except Exception:  # noqa: BLE001
            hint = ""

        message = f"No module named {fullname!r}"
        if hint:
            message = f"{message}. {hint}"
        raise ModuleNotFoundError(message, name=fullname)

    def _hint(self, fullname: str) -> str:
        tail = fullname[len(_PREFIX):]
        last = tail.rsplit(".", 1)[-1]

        # 1) Exact-suffix match — e.g. miss "route" surfaces every real
        #    module whose last component contains "route" ("core.router",
        #    "routing_x", "route_helper"). Cheap and reads well.
        suffix_matches = [
            m for m in self._known
            if m != fullname and last in m.rsplit(".", 1)[-1]
        ]

        # 2) Fuzzy fallback — Levenshtein-style close matches on the
        #    FULL dotted name, so "tina4_python.route" surfaces
        #    "tina4_python.core.router" even though "route" is not a
        #    substring of "router".
        fuzzy = get_close_matches(fullname, list(self._known), n=5, cutoff=0.55)

        # Merge preserving order, cap at 5.
        seen: set[str] = set()
        merged: list[str] = []
        for name in (*suffix_matches, *fuzzy):
            if name in seen:
                continue
            seen.add(name)
            merged.append(name)
            if len(merged) >= 5:
                break

        if not merged:
            return ""
        if len(merged) == 1:
            return f"Did you mean {merged[0]!r}?"
        return "Did you mean one of: " + ", ".join(repr(m) for m in merged) + "?"


_installed: bool = False


def install() -> None:
    """Idempotent: append the finder to sys.meta_path exactly once."""
    global _installed
    if _installed:
        return
    sys.meta_path.append(_Tina4ModuleFinder())
    _installed = True
