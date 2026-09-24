# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test-only guard: a child process must import THIS checkout's tina4_python.

tests/conftest.py puts this directory on the PYTHONPATH of every Python child
the suite starts, so the interpreter runs this file at startup (site.py imports
``sitecustomize``). It installs one meta-path finder that answers only for the
top-level ``tina4_python`` package: it resolves the package the normal way and,
if the result is not inside the repository this file lives in, aborts the
child with a message naming both copies.

Why: a venv's editable install is one .pth line pointing at one checkout. Run
the suite from any other checkout (a git worktree) and a child whose sys.path
misses the pin imports that other checkout - the test then proves nothing about
the code under test. Same idea as tina4-ruby's load_guard.

Production code is untouched: this file is never on a real app's path. A child
started with ``-S`` skips site.py and so skips this guard; such children get no
site-packages either, so no .pth can redirect them.
"""
import os
import sys
from importlib.machinery import PathFinder

_GUARD_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
_EXPECTED_ROOT = os.path.realpath(os.path.join(_GUARD_DIRECTORY, "..", ".."))
WRONG_CHECKOUT_EXIT_CODE = 70  # EX_SOFTWARE


class _CheckoutGuard:
    @staticmethod
    def find_spec(name, path=None, target=None):
        if name != "tina4_python":
            return None
        spec = PathFinder.find_spec(name, path)
        if spec is None:
            return None  # not found anywhere: the normal ModuleNotFoundError follows
        origin = os.path.realpath(spec.origin or next(iter(spec.submodule_search_locations or []), "?"))
        if origin.startswith(_EXPECTED_ROOT + os.sep):
            return spec
        sys.stderr.write(
            "tina4 test child guard: loaded the WRONG tina4_python\n"
            f"  imported from: {origin}\n"
            f"  expected under: {_EXPECTED_ROOT}\n"
            "  The child's sys.path reaches another checkout before this one (often a\n"
            "  venv editable install). Start it with PYTHONPATH from\n"
            "  tests/conftest.py child_pythonpath(), or inherit os.environ.\n"
        )
        sys.stderr.flush()
        os._exit(WRONG_CHECKOUT_EXIT_CODE)  # uncatchable: nothing may run the wrong code


sys.meta_path.insert(0, _CheckoutGuard)


def _run_the_sitecustomize_this_one_shadows():
    """Only one ``sitecustomize`` is ever imported. If the interpreter has its
    own (Debian's apport hook, for one), run it too rather than silently
    disabling it."""
    rest = [entry for entry in sys.path
            if os.path.realpath(entry or os.getcwd()) != os.path.realpath(_GUARD_DIRECTORY)]
    spec = PathFinder.find_spec("sitecustomize", rest)
    if spec is not None and spec.loader is not None:
        import importlib.util
        spec.loader.exec_module(importlib.util.module_from_spec(spec))


_run_the_sitecustomize_this_one_shadows()
