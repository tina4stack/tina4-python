"""Real-subprocess tests for scripts/check_version_consistency.py.

The precheck is what a release worker runs BEFORE cutting a tag, so these tests
drive the ACTUAL script the way the worker does: a real subprocess of the real
file, against real files on disk. No mocks, no stubs -- the positive case runs
against the live checkout at HEAD, and the drift cases copy the real
version-bearing files into a real temp tree, corrupt ONE, and prove the script
exits non-zero AND names the file left behind.

The script's own CHECKS list is imported (not re-hardcoded) purely to know which
files to copy, so if a fourth version-bearing file is ever added to the script
the drift fixture copies it too and cannot silently fall out of sync.
"""
import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_version_consistency.py"

# Load the script as a module to read its CHECKS list (top-level only; main() is
# guarded by __name__ == "__main__", so importing runs nothing).
_spec = importlib.util.spec_from_file_location("check_version_consistency", SCRIPT)
check_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_module)


def _current_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _run(*args: str):
    """Invoke the real script in a real subprocess, exactly as a release worker would."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
    )


def _materialise_repo_version_files(destination: Path) -> None:
    """Copy every file the script checks from the real repo into ``destination``,
    preserving layout (e.g. tina4_python/__init__.py keeps its subdir)."""
    relative_paths = sorted({relative_path for relative_path, _label, _extract in check_module.CHECKS})
    for relative_path in relative_paths:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative_path).read_text(encoding="utf-8"), encoding="utf-8")


def _rewrite_once(path: Path, old: str, new: str) -> None:
    """Replace the first occurrence of ``old`` with ``new``, asserting it was
    actually present -- a corruption that silently no-ops would make a drift test
    pass for the wrong reason (a ghost test)."""
    original = path.read_text(encoding="utf-8")
    updated = original.replace(old, new, 1)
    assert updated != original, f"corruption no-op: {old!r} not found in {path}"
    path.write_text(updated, encoding="utf-8")


def test_passes_against_current_version_at_head():
    """The script exits 0 when pointed at the real checkout with the version that
    checkout actually carries -- proving it passes at HEAD before any tag."""
    version = _current_version()
    result = _run(version)
    assert result.returncode == 0, (
        f"precheck failed at HEAD for {version}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "PASS:" in result.stdout
    assert "FAIL" not in result.stdout


def test_drift_in_pyproject_fails_and_names_the_file(tmp_path):
    """One drifted file (pyproject bumped to 9.9.9 while the rest stayed) makes
    the precheck exit non-zero AND name pyproject.toml with its wrong value."""
    version = _current_version()
    _materialise_repo_version_files(tmp_path)
    _rewrite_once(tmp_path / "pyproject.toml", f'version = "{version}"', 'version = "9.9.9"')

    result = _run(version, "--root", str(tmp_path))
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"expected non-zero exit on drift; output:\n{output}"
    assert "pyproject.toml" in output, f"drifted filename not named; output:\n{output}"
    assert "9.9.9" in output, f"wrong value not shown; output:\n{output}"
    assert version in output, f"expected version not shown; output:\n{output}"
    # The untouched files still carry the real version, so they pass -- only
    # pyproject is reported in the failure summary.
    assert "PASS" in result.stdout, f"untouched files should still PASS; output:\n{output}"


def test_drift_in_init_floor_literal_fails_and_names_that_file(tmp_path):
    """Corrupting a DIFFERENT file (the __init__.py floor literal) names THAT
    file -- proving the precheck is file-specific, not hardwired to pyproject."""
    version = _current_version()
    _materialise_repo_version_files(tmp_path)
    _rewrite_once(tmp_path / "tina4_python" / "__init__.py", f'return "{version}"', 'return "9.9.9"')

    result = _run(version, "--root", str(tmp_path))
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"expected non-zero exit on drift; output:\n{output}"
    assert "__init__.py" in output, f"drifted filename not named; output:\n{output}"
    assert "9.9.9" in output, f"wrong value not shown; output:\n{output}"


def test_wrong_expected_version_fails_at_head():
    """Pointed at the real checkout but asked for a version nothing carries, the
    precheck must fail and name every real file -- the mutation guard: a script
    that ignored its argument and always exited 0 would pass this by mistake."""
    result = _run("3.13.999")
    output = result.stdout + result.stderr

    assert result.returncode != 0, f"expected non-zero exit for a wrong version; output:\n{output}"
    assert "pyproject.toml" in output
    assert "tina4_python/__init__.py" in output
    assert "CLAUDE.md" in output
