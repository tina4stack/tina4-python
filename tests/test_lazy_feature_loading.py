"""Lock-in: a never-referenced subsystem is never imported.

A batteries-included framework should not pay to import ~98 features on every
boot. `tina4_python/__init__.py` imports only the CORE surface eagerly and
registers every optional subsystem in `_LAZY`, resolving it on first reference
through a PEP 562 module `__getattr__`.

Measured on this change (macOS, Python 3.13):

    import time      79.0ms -> 40.9ms
    tina4 modules    48     -> 17
    total modules    362    -> 206
    optional eager   13     -> 1

The one remaining eager optional is `tina4_python.websocket`: `core/server.py`
owns the `/__dev_reload` channel and instantiates a module-level
`WebSocketManager`, so websocket is genuinely part of the core server rather
than an optional feature. It is asserted explicitly below so the exception stays
deliberate rather than drifting.

These are pure-import assertions in a subprocess: no dependency, no double.

Parity: this contract holds in all four frameworks via each language's own
mechanism -- PHP through PSR-4 autoload (native), Ruby through `Module#autoload`,
Node through its package split (static ESM re-exports are eager by spec, so a
transparent lazy barrel is not expressible there). See
tests/DevAdminBundleDedupTest.php's sibling test in each repo.
"""

import subprocess
import sys

# Subsystems that MUST NOT load unless the app references them.
LAZY_SUBSYSTEMS = [
    "graphql",
    "wsdl",
    "mqtt",
    "messenger",
    "queue",
    "crud",
    "seeder",
    "docstore",
    "swagger",
]

# Deliberate exception: the core server owns /__dev_reload and holds a
# module-level WebSocketManager, so websocket rides with the core.
CORE_OWNED = ["websocket"]


def _run(code: str) -> str:
    """Run a snippet in a FRESH interpreter and return stdout.

    A fresh process is required: this test module itself imports plenty, so
    checking sys.modules in-process would prove nothing.
    """
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"snippet failed: {result.stderr}"
    return result.stdout.strip()


def test_importing_the_package_does_not_load_optional_subsystems():
    out = _run(
        "import sys, tina4_python;"
        "print(','.join(sorted(m for m in sys.modules if m.startswith('tina4_python'))))"
    )
    loaded = set(out.split(","))
    leaked = sorted(
        m for m in loaded
        if any(f"tina4_python.{s}" == m or m.startswith(f"tina4_python.{s}.")
               for s in LAZY_SUBSYSTEMS)
    )
    assert leaked == [], (
        f"these optional subsystems loaded on a bare `import tina4_python`: {leaked}. "
        "Either they were added to the eager core by mistake, or something in the "
        "eager path imports them at module level -- move that import inside the "
        "function that uses it."
    )


def test_websocket_stays_the_one_documented_exception():
    """Pin the exception so it cannot silently grow into two."""
    out = _run(
        "import sys, tina4_python;"
        "print(','.join(sorted(m for m in sys.modules if m.startswith('tina4_python'))))"
    )
    loaded = set(out.split(","))
    assert "tina4_python.websocket" in loaded, (
        "websocket is no longer eager -- if that was deliberate, move it into "
        "LAZY_SUBSYSTEMS here and delete this test."
    )


def test_a_lazy_name_resolves_and_imports_its_module_on_first_reference():
    out = _run(
        "import sys, tina4_python;"
        "before = 'tina4_python.graphql' in sys.modules;"
        "obj = tina4_python.GraphQL;"
        "after = 'tina4_python.graphql' in sys.modules;"
        "print(f'{before}|{after}|{obj.__name__}')"
    )
    before, after, name = out.split("|")
    assert before == "False", "graphql was already loaded -- laziness is broken"
    assert after == "True", "referencing GraphQL did not import tina4_python.graphql"
    assert name == "GraphQL"


def test_the_from_import_form_still_works():
    """`from tina4_python import GraphQL` must route through __getattr__."""
    out = _run("from tina4_python import GraphQL, Mqtt, Queue; print('ok')")
    assert out == "ok"


def test_first_reference_caches_the_name_so_later_access_skips_the_hook():
    out = _run(
        "import tina4_python;"
        "tina4_python.GraphQL;"
        "print('GraphQL' in vars(tina4_python))"
    )
    assert out == "True", (
        "__getattr__ must cache the resolved name in globals(), otherwise every "
        "attribute access re-enters the hook"
    )


def test_dir_lists_lazy_names_so_introspection_and_tab_completion_work():
    out = _run("import tina4_python; print('GraphQL' in dir(tina4_python))")
    assert out == "True"


def test_an_unknown_attribute_still_raises_attribute_error():
    """The hook must not swallow genuine typos into something truthy."""
    out = _run(
        "import tina4_python\n"
        "try:\n"
        "    tina4_python.NoSuchFeature\n"
        "    print('NO RAISE')\n"
        "except AttributeError:\n"
        "    print('raised')\n"
    )
    assert out == "raised"


def test_the_eager_core_surface_is_importable_without_touching_lazy_names():
    """Routing, constants, server and events must work with nothing else loaded."""
    out = _run(
        "import tina4_python as t;"
        "assert callable(t.get) and callable(t.post);"
        "assert t.HTTP_OK == 200;"
        "assert callable(t.run) and callable(t.background);"
        "assert callable(t.on) and callable(t.emit);"
        "print('core ok')"
    )
    assert out == "core ok"
