"""Real lock-in tests for `tina4 test` exit-code propagation (python#96).

`tina4 test` (the `_test` CLI handler) shells out to pytest. Before the fix it
discarded pytest's return code, so `main()` always exited 0 — a red suite
silently passed a `tina4 test || exit 1` CI gate.

These tests prove the fix WITHOUT any mock/monkeypatch of subprocess: they
build a throwaway project (a real `tests/` folder with one real pytest file),
SPAWN the real CLI as a child process, and let it run REAL pytest. The child's
exit code is the actual thing under test.

The CLI is invoked exactly as its console-script entry maps it
(``tina4python = "tina4_python.cli:main"`` in pyproject.toml): a fresh
interpreter imports `main` and runs it with argv ``["tina4python", "test"]``.
The `tina4_python.cli` package has no ``__main__.py``, so ``-m
tina4_python.cli`` cannot execute it directly; importing and calling `main`
drives the identical code path (`main` -> COMMANDS dispatch -> `_test` -> real
pytest) as the installed `tina4python test` command.

Negative case (failing suite -> non-zero) FAILS against the pre-fix code, which
returned 0 regardless — that is what makes this a genuine lock-in.
"""
import subprocess
import sys

# A fresh interpreter that runs the real CLI `main` with `test` as the command.
_RUN_CLI = (
    "import sys; "
    "from tina4_python.cli import main; "
    "sys.argv = ['tina4python', 'test']; "
    "main()"
)


def _write_project(project_dir, test_body):
    """Create a minimal project with a single pytest file under tests/."""
    tests_dir = project_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(test_body, encoding="utf-8")


def _run_tina4_test(project_dir):
    """Spawn the real CLI (`tina4 test`) in project_dir and return the result."""
    return subprocess.run(
        [sys.executable, "-c", _RUN_CLI],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_failing_suite_exits_non_zero(tmp_path):
    """A failing pytest suite makes `tina4 test` exit non-zero (the bug)."""
    _write_project(tmp_path, "def test_x():\n    assert 1 == 2\n")

    result = _run_tina4_test(tmp_path)

    assert result.returncode != 0, (
        "tina4 test must propagate pytest's failure exit code; got 0.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_passing_suite_exits_zero(tmp_path):
    """A passing pytest suite makes `tina4 test` exit 0."""
    _write_project(tmp_path, "def test_ok():\n    assert 1 == 1\n")

    result = _run_tina4_test(tmp_path)

    assert result.returncode == 0, (
        "tina4 test must exit 0 on a green suite; got "
        f"{result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
