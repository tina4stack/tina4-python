"""Real-subprocess tests for the tina4_python._import_helper meta-path finder.

ADR-0062, agent-experience contract: a wrong-guess import under the
`tina4_python.` namespace fails with a suggestion drawn from the real installed
tree; a legitimate import still works, the bare package import is not hijacked,
and — critically — a real ImportError raised INSIDE a module that already
exists is NEVER masked by our hint.

NO mocks, NO sys.modules munging. Every case shells out to a fresh Python
subprocess so the meta-path state cannot leak from one test to the next, and
the assertion is on what the real interpreter's real ImportError machinery
produced end-to-end.

The masking gate is the load-bearing test: if we ever regress and start
turning a genuine "No module named 'some_third_party'" (raised from inside a
real tina4_python submodule) into our "Did you mean ..." hint, we hide the
real cause from the developer / agent and force them to guess. Guarded here.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import tina4_python


PKG_DIR = Path(tina4_python.__file__).resolve().parent


def _run(code: str) -> subprocess.CompletedProcess:
    """Execute ``code`` in a fresh Python subprocess with a 30 s ceiling."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_import_helper_positive_happy_path():
    """A legitimate submodule import still resolves and returns the real symbol.

    Proves the finder does not intercept names that the normal finders can
    already resolve — the happy path pays zero cost because the finder is
    consulted last.
    """
    result = _run(
        "from tina4_python.core.router import get\n"
        "print(type(get).__name__)\n"
    )
    assert result.returncode == 0, (
        f"exit {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert result.stdout.strip() == "function"


def test_import_helper_positive_package_import_not_hijacked():
    """`import tina4_python` still returns the real package with its __version__.

    A finder that responded to the PACKAGE name (not only `tina4_python.<X>`)
    would break the bare import; this guards against that.
    """
    result = _run(
        "import tina4_python\n"
        "print(tina4_python.__version__)\n"
    )
    assert result.returncode == 0, (
        f"exit {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert result.stdout.strip() == tina4_python.__version__


def test_import_helper_negative_hint_names_the_real_target():
    """The wrong-guess import `tina4_python.route` fails with the standard
    ModuleNotFoundError text AND a suggestion that names the actual module
    (`tina4_python.core.router`).

    Both halves are asserted: the standard `No module named` phrase (so IDEs
    and linters that scrape that line still work) and the enrichment (the
    developer/agent sees the real target without having to grep the tree).
    """
    result = _run("from tina4_python.route import get\n")
    assert result.returncode != 0, "wrong import must not succeed"
    stderr = result.stderr
    assert "No module named 'tina4_python.route'" in stderr, stderr
    assert "tina4_python.core.router" in stderr, stderr


def test_import_helper_negative_no_close_match_still_lists_real_modules():
    """A wild guess with no near match still raises non-zero, and the message
    names at least one real top-level submodule so a developer/agent can
    browse from there instead of guessing again.
    """
    result = _run("import tina4_python.zzzzz\n")
    assert result.returncode != 0, "unknown module must not succeed"
    stderr = result.stderr
    assert "No module named 'tina4_python.zzzzz'" in stderr, stderr
    # At least one of the real, top-level submodules should be surfaced as a
    # browsing hint — the exact set depends on the fuzzy-match cutoff, but the
    # message must not be a dead end.
    known_real_modules = (
        "tina4_python.core",
        "tina4_python.orm",
        "tina4_python.database",
        "tina4_python.frond",
        "tina4_python.api",
        "tina4_python.auth",
        "tina4_python.queue",
        "tina4_python.cli",
    )
    assert any(name in stderr for name in known_real_modules), (
        f"stderr names no real tina4_python submodule; agent has nowhere to go.\n{stderr}"
    )


def test_import_helper_does_not_mask_real_error_inside_a_real_module():
    """MASKING GATE — the load-bearing test.

    Drop a REAL submodule inside tina4_python/ whose body does an
    `import definitely_missing_third_party_xxx`. When Python imports that
    submodule, the normal finder resolves it (it truly exists), then executes
    its body, which raises the ORIGINAL third-party ModuleNotFoundError. Our
    finder is registered LAST on sys.meta_path, so it is never consulted for
    `tina4_python._masking_gate_probe` (the normal path finder already
    resolved it) — proving we do not turn a genuine deeper failure into our
    "Did you mean ..." hint.

    Belt-and-braces: also assert the FROND import branch. `from
    tina4_python.frond import DefinitelyNotAClass` raises the standard
    `ImportError: cannot import name ...` from the real module's namespace —
    a second surface where the finder must not step in.
    """
    probe = PKG_DIR / "_masking_gate_probe.py"
    probe.write_text(
        '"""Deliberately broken probe used by test_import_helper.\n'
        "\n"
        "Owns a real import of a package that does not exist so the masking\n"
        "gate has something genuine to fail against. Written and removed by the\n"
        'test itself; if you see this file on disk, an unclean test run left it."""\n'
        "import definitely_missing_third_party_module_zxq123  # noqa: F401\n",
        encoding="utf-8",
    )
    try:
        result = _run("import tina4_python._masking_gate_probe\n")
        assert result.returncode != 0, (
            "the broken probe must not import successfully"
        )
        stderr = result.stderr
        # Original error preserved verbatim — our finder never wrapped it.
        assert "definitely_missing_third_party_module_zxq123" in stderr, (
            f"the original third-party ModuleNotFoundError was lost:\n{stderr}"
        )
        assert "No module named 'definitely_missing_third_party_module_zxq123'" in stderr, (
            f"expected the original error phrasing, got:\n{stderr}"
        )
        # Belt: our hint text must NOT have taken over the real error.
        assert "Did you mean" not in stderr, (
            f"our finder hijacked the deeper error:\n{stderr}"
        )
    finally:
        # Belt-and-braces: always clean up + kill the .pyc so a re-run is fresh.
        probe.unlink(missing_ok=True)
        pyc_root = PKG_DIR / "__pycache__"
        if pyc_root.is_dir():
            for pyc in pyc_root.glob("_masking_gate_probe*.pyc"):
                pyc.unlink(missing_ok=True)

    # Second surface: an `ImportError: cannot import name X from Y` on a real
    # module (tina4_python.frond) must come from Python's own machinery, not
    # from our finder. Frond is a real module, so our finder is never asked.
    result2 = _run("from tina4_python.frond import DefinitelyNotAClass\n")
    assert result2.returncode != 0
    assert "cannot import name 'DefinitelyNotAClass'" in result2.stderr, result2.stderr
    assert "from 'tina4_python.frond'" in result2.stderr, result2.stderr
    assert "Did you mean" not in result2.stderr, (
        f"our finder hijacked the ImportError on a real module:\n{result2.stderr}"
    )
