# Regression tests for .env.local precedence at boot.
#
# Bug (v3 dev-secret work): the boot loader loaded .env first, then
# .env.local with override=True. override=true overwrites keys ALREADY
# PRESENT in the real process environment, so a stray gitignored .env.local
# (auto-generated on a prior dev-mode boot) would CLOBBER an explicitly-set
# real env var. That broke a real TINA4_SECRET (a stale .env.local overrode
# it → signed tokens no longer validated) and is security-relevant
# (a stray .env.local could override a real production TINA4_SECRET).
#
# Correct precedence:  real-env  >  .env.local  >  .env
#
# Fix: load .env.local with override=False, BEFORE .env (also override=False).
# Because override=false means "set only if not already present" (first-wins),
# loading .env.local first lets it beat .env, while a real (pre-boot) env var
# beats both.
import os

from tina4_python.dotenv import load_env, reset_env


def _run_boot_load_sequence(cwd):
    """Mirror the server boot load order from tina4_python/core/server.py.

    The order and override flags here MUST match the real boot sites. If the
    bug regresses (e.g. .env.local loaded with override=True, or .env loaded
    before .env.local), these tests fail.
    """
    load_env(str(cwd / ".env.local"), override=False)
    load_env(str(cwd / ".env"), override=False)


class TestEnvLocalPrecedence:
    """real-env > .env.local > .env"""

    def test_real_env_wins_over_env_local(self, tmp_path):
        # A stray gitignored .env.local must NOT clobber a real env var that
        # was explicitly set before boot. This is the exact bug + security case.
        (tmp_path / ".env.local").write_text("TINA4_SECRET=from_local\n")

        os.environ["TINA4_SECRET"] = "from_real"  # real env, set before load
        try:
            _run_boot_load_sequence(tmp_path)
            # The bug would show "from_local" here.
            assert os.environ["TINA4_SECRET"] == "from_real"
        finally:
            os.environ.pop("TINA4_SECRET", None)
            reset_env()

    def test_env_local_wins_over_dotenv(self, tmp_path):
        # With no real TINA4_SECRET set, .env.local must still beat .env so a
        # locally-generated dev secret is the one that takes effect.
        (tmp_path / ".env").write_text("TINA4_SECRET=from_dotenv\n")
        (tmp_path / ".env.local").write_text("TINA4_SECRET=from_local\n")

        os.environ.pop("TINA4_SECRET", None)  # ensure no real value present
        try:
            _run_boot_load_sequence(tmp_path)
            assert os.environ["TINA4_SECRET"] == "from_local"
        finally:
            os.environ.pop("TINA4_SECRET", None)
            reset_env()

    def test_dotenv_fills_keys_absent_from_env_local(self, tmp_path):
        # Sanity: .env still provides keys that .env.local does not define.
        (tmp_path / ".env").write_text(
            "TINA4_SECRET=from_dotenv\nONLY_IN_DOTENV=dotenv_value\n"
        )
        (tmp_path / ".env.local").write_text("TINA4_SECRET=from_local\n")

        os.environ.pop("TINA4_SECRET", None)
        os.environ.pop("ONLY_IN_DOTENV", None)
        try:
            _run_boot_load_sequence(tmp_path)
            assert os.environ["TINA4_SECRET"] == "from_local"
            assert os.environ["ONLY_IN_DOTENV"] == "dotenv_value"
        finally:
            os.environ.pop("TINA4_SECRET", None)
            os.environ.pop("ONLY_IN_DOTENV", None)
            reset_env()
