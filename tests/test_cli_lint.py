"""`tina4 lint` — the framework ships NO linter; the command runs the project's
own ruff and installs it as a DEV dependency on demand, with a zero-dependency
`compile()` syntax baseline as the fallback.

No mocks. The baseline tests run the real `compile()` parse over real files in a
real temp project. The install test runs a REAL `uv add --dev ruff` in a REAL
throwaway uv project (uv is the framework's own package manager, always present
in the dev environment) and reads the mutated manifest back. The registration
test reads the real COMMANDS table.
"""
import shutil
import subprocess
import sys

import pytest

from tina4_python.cli import COMMANDS, _lint, _resolve_ruff

CLEAN = "def add(a, b):\n    return a + b\n"
BROKEN = "def add(a, b)\n    return a + b\n"  # missing colon -> SyntaxError


def _run_lint(args, cwd, monkeypatch):
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit) as exc:
        _lint(args)
    return exc.value.code


class TestZeroDepBaseline:
    def test_clean_src_passes(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ok.py").write_text(CLEAN)
        assert _run_lint(["--no-install"], tmp_path, monkeypatch) == 0

    def test_syntax_error_in_src_fails(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bad.py").write_text(BROKEN)
        assert _run_lint(["--no-install"], tmp_path, monkeypatch) == 1

    def test_app_py_is_in_scope(self, tmp_path, monkeypatch):
        (tmp_path / "app.py").write_text(BROKEN)
        assert _run_lint(["--no-install"], tmp_path, monkeypatch) == 1

    def test_nothing_to_lint_is_clean(self, tmp_path, monkeypatch):
        assert _run_lint(["--no-install"], tmp_path, monkeypatch) == 0


class TestRegistration:
    def test_lint_is_a_registered_command(self):
        assert "lint" in COMMANDS
        assert COMMANDS["lint"]["handler"] is _lint


class TestOnDemandInstall:
    """The headline feature: with no ruff present and no --no-install, `tina4
    lint` adds ruff as a DEV dependency of the project, then runs it. Real uv,
    real ruff, real manifest mutation -- no mock."""

    def test_lint_installs_ruff_dev_only_then_runs_clean(self, tmp_path, monkeypatch):
        assert shutil.which("uv"), "uv is the framework's package manager and must be on PATH"
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "lintprobe"\nversion = "0.0.0"\n'
            'requires-python = ">=3.12"\n'
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ok.py").write_text("x = 1\n")
        assert _resolve_ruff(tmp_path) is None  # not present before the run

        rc = _run_lint([], tmp_path, monkeypatch)  # no --no-install -> installs

        manifest = (tmp_path / "pyproject.toml").read_text()
        assert "ruff" in manifest, f"ruff was not added to the manifest:\n{manifest}"
        assert _resolve_ruff(tmp_path) is not None  # ruff is now runnable
        assert rc == 0  # and the trivial file is clean

    def test_installed_ruff_catches_a_real_lint_issue(self, tmp_path, monkeypatch):
        assert shutil.which("uv"), "uv must be on PATH"
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "lintprobe2"\nversion = "0.0.0"\n'
            'requires-python = ">=3.12"\n'
        )
        (tmp_path / "src").mkdir()
        # An unused import is a real ruff finding (F401) but valid syntax, so the
        # zero-dep baseline would PASS it -- proving ruff (not the baseline) ran.
        (tmp_path / "src" / "smelly.py").write_text("import os\nx = 1\n")
        rc = _run_lint([], tmp_path, monkeypatch)
        assert rc == 1, "ruff should flag the unused import (F401)"
