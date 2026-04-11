# Tests for the tina4 CLI guard — ensures `run()` refuses to start
# without `--managed` flag unless `TINA4_OVERRIDE_CLIENT=true` is set.
import os
import subprocess
import sys
import tempfile

import pytest

# Helper script that tests just the guard logic (same as in server.py run())
_GUARD_SCRIPT = """\
import sys, os
sys.path.insert(0, os.getcwd())
is_managed = "--managed" in sys.argv
override = os.environ.get("TINA4_OVERRIDE_CLIENT")
if not is_managed and override != "true":
    print("GUARD_BLOCKED")
    sys.exit(1)
print("GUARD_PASSED")
sys.exit(0)
"""


def _run_guard(extra_args: list = None, env_overrides: dict = None) -> subprocess.CompletedProcess:
    """Run the guard check script with the given args and env."""
    env = os.environ.copy()
    env.pop("TINA4_OVERRIDE_CLIENT", None)
    if env_overrides:
        env.update(env_overrides)

    args = [sys.executable]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_GUARD_SCRIPT)
        f.flush()
        args.append(f.name)
        if extra_args:
            args.extend(extra_args)
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
        finally:
            os.unlink(f.name)


def _run_app_with_args(extra_args: list = None, env_overrides: dict = None, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a minimal Tina4 app in a subprocess with the given args and env."""
    env = os.environ.copy()
    env.pop("TINA4_OVERRIDE_CLIENT", None)
    if env_overrides:
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
        args = [sys.executable, f.name]
        if extra_args:
            args.extend(extra_args)
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        finally:
            os.unlink(f.name)


class TestCliGuard:
    """Verify that run() enforces tina4 CLI requirement via --managed flag."""

    def test_run_without_managed_exits_with_code_1(self):
        """Running without --managed should exit with code 1."""
        result = _run_app_with_args()
        assert result.returncode == 1

    def test_run_without_managed_shows_tina4_serve(self):
        """The error message should tell users to use tina4 serve."""
        result = _run_app_with_args()
        assert "tina4 serve" in result.stdout

    def test_run_without_managed_shows_override_hint(self):
        """The error message should mention TINA4_OVERRIDE_CLIENT."""
        result = _run_app_with_args()
        assert "TINA4_OVERRIDE_CLIENT" in result.stdout

    def test_run_without_managed_shows_install_hint(self):
        """The error message should mention cargo install tina4."""
        result = _run_app_with_args()
        assert "cargo install tina4" in result.stdout

    def test_run_without_managed_shows_docs_link(self):
        """The error message should mention https://tina4.com."""
        result = _run_app_with_args()
        assert "https://tina4.com" in result.stdout

    def test_guard_blocks_without_managed(self):
        """Guard blocks when neither --managed nor TINA4_OVERRIDE_CLIENT is set."""
        result = _run_guard()
        assert result.returncode == 1
        assert "GUARD_BLOCKED" in result.stdout

    def test_guard_passes_with_managed(self):
        """Guard passes when --managed flag is passed."""
        result = _run_guard(extra_args=["--managed"])
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout

    def test_guard_passes_with_override(self):
        """Guard passes when TINA4_OVERRIDE_CLIENT=true is set."""
        result = _run_guard(env_overrides={"TINA4_OVERRIDE_CLIENT": "true"})
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout

    def test_guard_blocks_with_false_override(self):
        """TINA4_OVERRIDE_CLIENT=false should still block."""
        result = _run_guard(env_overrides={"TINA4_OVERRIDE_CLIENT": "false"})
        assert result.returncode == 1
        assert "GUARD_BLOCKED" in result.stdout

    def test_both_managed_and_override_passes(self):
        """Both --managed and TINA4_OVERRIDE_CLIENT set should pass."""
        result = _run_guard(extra_args=["--managed"], env_overrides={"TINA4_OVERRIDE_CLIENT": "true"})
        assert result.returncode == 0
        assert "GUARD_PASSED" in result.stdout
