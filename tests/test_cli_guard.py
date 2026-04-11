# Tests for the tina4 CLI guard — ensures `run()` refuses to start
# without `TINA4_CLI=true` unless `TINA4_OVERRIDE_CLIENT=true` is set.
import os
import subprocess
import sys
import tempfile

import pytest

# Helper script that tests just the guard logic (same as in server.py run())
_GUARD_SCRIPT = """\
import sys, os
sys.path.insert(0, os.getcwd())
cli = os.environ.get("TINA4_CLI")
override = os.environ.get("TINA4_OVERRIDE_CLIENT")
if cli != "true" and override != "true":
    print("GUARD_BLOCKED")
    sys.exit(1)
print("GUARD_PASSED")
sys.exit(0)
"""


def _run_guard(env_overrides: dict) -> subprocess.CompletedProcess:
    """Run the guard check script with the given env."""
    env = os.environ.copy()
    env.pop("TINA4_CLI", None)
    env.pop("TINA4_OVERRIDE_CLIENT", None)
    env.update(env_overrides)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_GUARD_SCRIPT)
        f.flush()
        try:
            return subprocess.run(
                [sys.executable, f.name],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
        finally:
            os.unlink(f.name)


def _run_app_with_env(env_overrides: dict, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a minimal Tina4 app in a subprocess with the given env."""
    env = os.environ.copy()
    env.pop("TINA4_CLI", None)
    env.pop("TINA4_OVERRIDE_CLIENT", None)
    env.update(env_overrides)

    code = (
        "import sys, os\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from tina4_python.core.server import run\n"
        "run()\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        try:
            return subprocess.run(
                [sys.executable, f.name],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        finally:
            os.unlink(f.name)


class TestCliGuard:
    """Verify that run() enforces tina4 CLI requirement."""

    def test_run_without_cli_exits_with_code_1(self):
        """Running without TINA4_CLI=true should exit with code 1."""
        result = _run_app_with_env({})
        assert result.returncode == 1

    def test_run_without_cli_shows_tina4_serve(self):
        """The error message should tell users to use tina4 serve."""
        result = _run_app_with_env({})
        assert "tina4 serve" in result.stdout

    def test_run_without_cli_shows_override_hint(self):
        """The error message should mention TINA4_OVERRIDE_CLIENT."""
        result = _run_app_with_env({})
        assert "TINA4_OVERRIDE_CLIENT" in result.stdout

    def test_run_without_cli_shows_install_hint(self):
        """The error message should mention cargo install tina4."""
        result = _run_app_with_env({})
        assert "cargo install tina4" in result.stdout

    def test_run_without_cli_shows_docs_link(self):
        """The error message should mention https://tina4.com."""
        result = _run_app_with_env({})
        assert "https://tina4.com" in result.stdout

    def test_guard_blocks_without_env(self):
        """Guard blocks when neither TINA4_CLI nor TINA4_OVERRIDE_CLIENT is set."""
        result = _run_guard({})
        assert result.returncode == 1
        assert "GUARD_BLOCKED" in result.stdout

    def test_guard_passes_with_cli(self):
        """Guard passes when TINA4_CLI=true is set."""
        result = _run_guard({"TINA4_CLI": "true"})
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout

    def test_guard_passes_with_override(self):
        """Guard passes when TINA4_OVERRIDE_CLIENT=true is set."""
        result = _run_guard({"TINA4_OVERRIDE_CLIENT": "true"})
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout

    def test_guard_blocks_with_false_override(self):
        """TINA4_OVERRIDE_CLIENT=false should still block."""
        result = _run_guard({"TINA4_OVERRIDE_CLIENT": "false"})
        assert result.returncode == 1
        assert "GUARD_BLOCKED" in result.stdout

    def test_guard_blocks_with_false_cli(self):
        """TINA4_CLI=false should still block."""
        result = _run_guard({"TINA4_CLI": "false"})
        assert result.returncode == 1
        assert "GUARD_BLOCKED" in result.stdout

    def test_both_set_passes(self):
        """Both TINA4_CLI and TINA4_OVERRIDE_CLIENT set should pass."""
        result = _run_guard({"TINA4_CLI": "true", "TINA4_OVERRIDE_CLIENT": "true"})
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout
