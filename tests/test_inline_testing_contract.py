"""Feature 132 — inline testing conformance (INLINE-DEC-01 / INLINE-DEC-02).

Shared contract: tina4-documentation/plan/v3/fixtures/inlinetesting_contract.json.

Every case runs with NO MOCKS: it builds a real throwaway project, SPAWNS the real
`tina4python test` CLI as a child process (cwd = the project), and asserts the
child's REAL exit code and the REAL filesystem side effects. The CLI is invoked
exactly as its console-script entry maps it (`tina4python = "tina4_python.cli:main"`):
a fresh interpreter imports `main` and runs it with argv `["tina4python", "test"]`,
driving the identical `main -> COMMANDS -> _test -> inline discovery + run_all` path
as the installed command.

Invariants proven here:
  A inline-cli-real-exit-code   — `tina4 test` runs a decorated inline @tests function
                                  and exits 0 when it passes, non-zero when it fails.
  B inline-discovery-no-arbitrary-code — discovery imports only files that carry @tests,
                                  so a scanned src file WITHOUT one never runs (no
                                  arbitrary-code side effect during discovery).
  C inline-assert-surfaces-do-not-collide — the descriptor surface exposes expect_* and
                                  NOT the xUnit assert_*; the two names are distinct with
                                  distinct semantics, so importing the wrong one is loud.
"""
import subprocess
import sys
from pathlib import Path

# A fresh interpreter that runs the real CLI `main` with `test` as the command.
_RUN_CLI = (
    "import sys; "
    "from tina4_python.cli import main; "
    "sys.argv = ['tina4python', 'test']; "
    "main()"
)

_PASSING_INLINE = (
    "from tina4_python.Testing import tests, expect_equal\n"
    "\n"
    "@tests(expect_equal((5, 3), 8), expect_equal((0, 0), 0))\n"
    "def add(a, b):\n"
    "    return a + b\n"
)

_FAILING_INLINE = (
    "from tina4_python.Testing import tests, expect_equal\n"
    "\n"
    "@tests(expect_equal((5, 3), 999))\n"   # 8 != 999 -> a real failure
    "def add(a, b):\n"
    "    return a + b\n"
)

# A scanned src file with an OBSERVABLE side effect and NO @tests marker — it must
# never be imported during discovery.
_SIDE_EFFECT = (
    "import pathlib\n"
    "pathlib.Path('side_effect_ran.txt').write_text('ran')\n"
)


def _make_project(root: Path, inline_body: str, *, with_side_effect: bool = False) -> None:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "inline_math.py").write_text(inline_body, encoding="utf-8")
    if with_side_effect:
        (src / "side_effect.py").write_text(_SIDE_EFFECT, encoding="utf-8")


def _run_tina4_test(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _RUN_CLI],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )


# ── A: real exit code ────────────────────────────────────────────────

def test_tina4_test_exits_zero_when_the_inline_test_passes(tmp_path):
    _make_project(tmp_path, _PASSING_INLINE)

    result = _run_tina4_test(tmp_path)

    assert result.returncode == 0, (
        "tina4 test must exit 0 when the discovered inline @tests passes; got "
        f"{result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # The inline runner actually ran the function (proves discovery, not a no-op pass).
    assert "add" in result.stdout, f"inline test never ran; stdout:\n{result.stdout}"


def test_tina4_test_exits_non_zero_when_the_inline_test_fails(tmp_path):
    _make_project(tmp_path, _FAILING_INLINE)

    result = _run_tina4_test(tmp_path)

    assert result.returncode != 0, (
        "tina4 test must exit non-zero when a discovered inline @tests fails; got 0.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ── B: discovery does not execute arbitrary scanned code ─────────────

def test_inline_discovery_does_not_run_a_non_test_file_side_effect(tmp_path):
    _make_project(tmp_path, _PASSING_INLINE, with_side_effect=True)

    result = _run_tina4_test(tmp_path)

    assert result.returncode == 0, (
        f"passing project should exit 0; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert not (tmp_path / "side_effect_ran.txt").exists(), (
        "a src file WITHOUT @tests was imported during discovery — discovery must "
        "only import files that carry the inline marker, never arbitrary scanned code."
    )


# ── C: the two assertion surfaces do not collide ─────────────────────

def test_the_descriptor_expect_builders_and_xunit_assert_are_distinct():
    from tina4_python import Testing as descriptor
    from tina4_python import test as xunit

    # The descriptor surface builds a spec; it does not assert.
    spec = descriptor.expect_equal((1,), 1)
    assert isinstance(spec, dict) and spec["type"] == "equal"

    # The colliding name is GONE from the descriptor surface — the whole point of
    # the rename. Re-adding an assert_equal here (the old name) would fail this.
    assert not hasattr(descriptor, "assert_equal"), (
        "the descriptor surface must not expose assert_equal — it collides with the "
        "xUnit assert_equal(actual, expected, message)."
    )

    # The xUnit surface asserts immediately with the (actual, expected, message) shape.
    assert xunit.assert_equal(1, 1) is None      # passes -> returns None
    raised = False
    try:
        xunit.assert_equal(1, 2)
    except AssertionError:
        raised = True
    assert raised, "xUnit assert_equal(1, 2) must raise AssertionError"
