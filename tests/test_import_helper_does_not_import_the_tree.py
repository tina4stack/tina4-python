"""The import-hint helper must build its suggestion list WITHOUT importing the
tree it lists.

`pkgutil.walk_packages` imports every package it descends into — it has to, since
recursing needs each package's `__path__`. The helper is installed from
`tina4_python/__init__.py` at import time, so using it there had two effects:

  1. every optional subsystem loaded on a bare `import tina4_python`, defeating
     the lazy loading that `test_lazy_feature_loading.py` guards; and
  2. every subpackage got bound as an attribute on `tina4_python`, which shadows
     the callables `__getattr__` exists to provide — so `tina4_python.realtime`
     resolved to the module and `realtime(...)` raised
     `TypeError: 'module' object is not callable`.

The second one is the reason this file exists: it is a public API break, and no
test named the mechanism. `test_lazy_feature_loading.py` catches (1) only, and
the realtime suites catch (2) only as a symptom, several layers away from the
cause.

Each check runs in a FRESH interpreter. The defect is about what a single
`import tina4_python` does, so it cannot be observed twice in one process.
"""
import subprocess
import sys
import textwrap

import tina4_python  # noqa: F401  — import-time behaviour is what is under test


def _in_fresh_interpreter(body: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout.strip()


def test_installing_the_helper_does_not_import_the_optional_subsystems():
    """A bare `import tina4_python` must not drag in the optional subsystems.

    Asserted here as well as in test_lazy_feature_loading.py on purpose: this
    file pins the CAUSE (how the helper enumerates), that one pins the effect.
    """
    loaded = _in_fresh_interpreter(
        """
        import sys
        import tina4_python  # noqa: F401
        optional = ("crud", "docstore", "graphql", "messenger", "mqtt",
                    "queue", "seeder", "swagger", "wsdl")
        print(",".join(sorted(
            m for m in sys.modules
            if m.startswith("tina4_python.") and any(k in m for k in optional)
        )))
        """
    )
    eager = [m for m in loaded.split(",") if m]
    assert not eager, (
        "these optional subsystems were imported just by installing the import "
        f"helper: {eager}. Enumerate the tree from disk; pkgutil.walk_packages "
        "imports every package it lists."
    )


def test_the_lazy_callables_are_not_shadowed_by_an_eagerly_imported_module():
    """`realtime` must still be the function, not the subpackage.

    `__init__.py` maps it lazily to the callable inside `tina4_python.realtime`.
    `__getattr__` only runs while no real attribute exists, so importing the
    subpackage anywhere during startup permanently shadows the callable.
    """
    kind = _in_fresh_interpreter(
        """
        import tina4_python
        attr = tina4_python.realtime
        print(f"{type(attr).__name__}:{callable(attr)}")
        """
    )
    assert kind == "function:True", (
        f"tina4_python.realtime resolved to {kind}, expected function:True — "
        "something imported tina4_python.realtime during startup and bound the "
        "module over the lazy callable, so realtime(...) raises TypeError."
    )
