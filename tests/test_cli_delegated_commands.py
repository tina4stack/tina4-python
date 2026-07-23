"""Real tests for the client-owned commands the CLI reaches by DELEGATION.

`doctor`, `setup` and `deploy` are owned by the Rust `tina4` client. This CLI
recognises them (the closed `DELEGATED` registry) and runs the client with the
same argv, propagating its exit code — so `tina4python doctor` behaves exactly
like `tina4 doctor` without cloning the client into four languages.

NO MOCKS. Every test here launches the REAL `tina4python` entrypoint as a real
subprocess. The positive test puts a REAL executable named `tina4` on a real
temp PATH and asserts the CLI actually exec'd it with the exact argv and
propagated its exit code — real process, real PATH resolution, real exit status.
The negative tests use a real PATH with no `tina4` on it at all.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from tina4_python.cli import (
    CLIENT_BINARY,
    COMMANDS,
    DELEGATED,
    DELEGATION_GUARD_ENV,
    EXIT_CLIENT_UNAVAILABLE,
    EXIT_UNKNOWN_COMMAND,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The real entrypoint, driven exactly as a user (or the client) would drive it.
_ENTRYPOINT = "import sys; from tina4_python.cli import main; main()"


def _run_cli(argv, *, path, cwd, extra_env=None, timeout=60):
    """Run the REAL tina4python entrypoint as a subprocess with a controlled PATH."""
    env = os.environ.copy()
    env["PATH"] = path
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.pop(DELEGATION_GUARD_ENV, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", _ENTRYPOINT, *argv],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout,
    )


def _client_dir_without_tina4(tmp_path) -> str:
    """A real PATH directory that genuinely has NO `tina4` executable on it."""
    bindir = tmp_path / "nobin"
    bindir.mkdir(exist_ok=True)
    assert not (bindir / CLIENT_BINARY).exists()
    return str(bindir)


def _install_real_client_on_path(tmp_path, exit_code=0) -> str:
    """Install a REAL executable named `tina4` on a fresh temp PATH.

    It is a genuine program (not a test double standing in for one): a small
    shell script that records the argv and guard variable it was invoked with,
    then exits with `exit_code`. That is exactly the collaborator the delegation
    code has — "whatever executable named tina4 is first on PATH" — so the test
    exercises the real PATH lookup, real spawn, real stdio inheritance and real
    exit-status propagation, with no in-process substitution anywhere.
    """
    bindir = tmp_path / "clientbin"
    bindir.mkdir(exist_ok=True)
    client = bindir / CLIENT_BINARY
    client.write_text(
        "#!/bin/sh\n"
        f'for arg in "$@"; do printf "%s\\n" "$arg" >> "{tmp_path / "argv.txt"}"; done\n'
        f'printf "%s\\n" "${DELEGATION_GUARD_ENV}" > "{tmp_path / "guard.txt"}"\n'
        'echo "REAL-CLIENT-RAN $*"\n'
        f"exit {exit_code}\n"
    )
    client.chmod(client.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(bindir)


def _recorded_argv(tmp_path) -> list:
    return (tmp_path / "argv.txt").read_text().splitlines()


def _recorded_guard(tmp_path) -> str:
    return (tmp_path / "guard.txt").read_text().strip()


def _client_was_invoked(tmp_path) -> bool:
    return (tmp_path / "guard.txt").exists()


class TestDelegatedRegistry:
    """The registry itself — pure data, no dependency, no double."""

    def test_the_three_client_commands_are_declared(self):
        assert set(DELEGATED) == {"doctor", "setup", "deploy"}

    def test_delegated_never_shadows_a_native_command(self):
        """A name in both registries would make dispatch ambiguous."""
        assert not (set(DELEGATED) & set(COMMANDS))

    def test_every_delegated_entry_has_a_summary(self):
        for name, spec in DELEGATED.items():
            assert spec.get("summary"), f"{name} has no summary"


class TestDelegationReachesTheClient:
    """Positive: a delegated command really runs the `tina4` executable."""

    def test_doctor_execs_the_client_with_the_same_argv(self, tmp_path):
        path = _install_real_client_on_path(tmp_path, exit_code=0)

        result = _run_cli(["doctor"], path=path, cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert "REAL-CLIENT-RAN doctor" in result.stdout, result.stdout
        assert _recorded_argv(tmp_path) == ["doctor"]

    def test_deploy_passes_its_arguments_and_flags_through(self, tmp_path):
        path = _install_real_client_on_path(tmp_path, exit_code=0)

        result = _run_cli(["deploy", "docker", "--force"], path=path, cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        assert _recorded_argv(tmp_path) == ["deploy", "docker", "--force"]

    def test_client_exit_code_is_propagated_not_swallowed(self, tmp_path):
        """A failing client must fail the framework CLI too (CI depends on it)."""
        path = _install_real_client_on_path(tmp_path, exit_code=3)

        result = _run_cli(["doctor"], path=path, cwd=tmp_path)

        assert result.returncode == 3, f"expected the client's 3, got {result.returncode}"

    def test_loop_guard_is_set_on_the_child(self, tmp_path):
        """The child is marked so a client that resolves back here is caught."""
        path = _install_real_client_on_path(tmp_path, exit_code=0)

        _run_cli(["setup"], path=path, cwd=tmp_path)

        assert _recorded_guard(tmp_path) == "setup"


class TestDelegationFailsActionably:
    """Negative: every failure path is loud, actionable and non-zero."""

    def test_missing_client_names_the_command_and_how_to_install(self, tmp_path):
        path = _client_dir_without_tina4(tmp_path)

        result = _run_cli(["doctor"], path=path, cwd=tmp_path)

        assert result.returncode == EXIT_CLIENT_UNAVAILABLE
        message = result.stdout + result.stderr
        assert "doctor" in message
        assert "tina4 client" in message
        assert "install.sh" in message, "no actionable install hint"
        assert "Traceback" not in message, "leaked a stack trace instead of an error"

    def test_loop_guard_refuses_to_respawn(self, tmp_path):
        """With the guard already set for this command, delegation must refuse
        rather than spawn — otherwise a `tina4` that resolves back to a framework
        CLI would fork-bomb."""
        path = _install_real_client_on_path(tmp_path, exit_code=0)

        result = _run_cli(["doctor"], path=path, cwd=tmp_path,
                          extra_env={DELEGATION_GUARD_ENV: "doctor"})

        assert result.returncode == EXIT_CLIENT_UNAVAILABLE
        assert "Refusing to delegate" in result.stdout + result.stderr
        assert not _client_was_invoked(tmp_path), "it spawned the client anyway"

    def test_unknown_command_exits_non_zero(self, tmp_path):
        """Regression lock-in: this used to print the error and exit 0, so a typo
        in a script or CI step reported success."""
        path = _client_dir_without_tina4(tmp_path)

        result = _run_cli(["definitely-not-a-command"], path=path, cwd=tmp_path)

        assert result.returncode == EXIT_UNKNOWN_COMMAND
        assert "Unknown command: definitely-not-a-command" in result.stdout + result.stderr

    def test_unknown_command_is_not_delegated(self, tmp_path):
        """Delegation is allow-listed: an unknown command must never be handed to
        the client (that is how a forward loop starts)."""
        path = _install_real_client_on_path(tmp_path, exit_code=0)

        result = _run_cli(["not-a-real-command"], path=path, cwd=tmp_path)

        assert result.returncode == EXIT_UNKNOWN_COMMAND
        assert not _client_was_invoked(tmp_path), "forwarded an unknown command"


class TestHelpAndManifestTellTheTruth:
    """`--help` and `commands --json` must advertise the delegated commands."""

    def test_help_lists_the_delegated_commands_in_their_own_section(self, tmp_path):
        path = _client_dir_without_tina4(tmp_path)

        result = _run_cli(["help"], path=path, cwd=tmp_path)

        assert result.returncode == 0
        assert f"Delegated to the {CLIENT_BINARY} client" in result.stdout
        for name in DELEGATED:
            assert name in result.stdout, f"help omits {name}"

    def test_manifest_lists_delegated_commands_flagged(self, tmp_path):
        path = _client_dir_without_tina4(tmp_path)

        result = _run_cli(["commands", "--json"], path=path, cwd=tmp_path)

        assert result.returncode == 0, result.stderr
        manifest = json.loads(result.stdout)
        by_name = {c["name"]: c for c in manifest["commands"]}
        for name in DELEGATED:
            assert name in by_name, f"manifest omits {name}"
            assert by_name[name].get("delegated") is True, f"{name} not flagged delegated"
        for name in COMMANDS:
            assert "delegated" not in by_name[name], f"{name} wrongly flagged delegated"
