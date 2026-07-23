"""Real tests for the self-describing `commands` CLI subcommand.

No mocks. These exercise the ACTUAL CLI code path two ways:

  * in-process — the real `_commands` handler and `_commands_manifest` builder,
    asserting the manifest's shape and that it is DERIVED from the single-source
    COMMANDS / GENERATORS registries (so it can never drift from dispatch);
  * as a real subprocess running the `tina4python` entrypoint (`main`) in a
    clean temp dir with NO database configured — proving `commands --json` is
    cheap and side-effect-free (no bootstrap, no DB, no migrations). This is the
    contract the tina4 Rust client relies on when it calls the command on every
    `tina4 --help`, in any directory.
"""
import json
import os
import re
import subprocess
import sys

from tina4_python import __version__
from tina4_python.cli import _commands, _commands_manifest, COMMANDS, DELEGATED, GENERATORS

# The command set the tina4 client must be able to discover truthfully.
KNOWN_COMMANDS = {"migrate", "migrate:create", "seed", "test", "routes", "generate", "commands",
                  "queue", "build"}


def _manifest_from_handler(capsys) -> dict:
    """Run the REAL `commands --json` handler and parse the JSON it prints."""
    _commands(["--json"])
    return json.loads(capsys.readouterr().out)


class TestCommandsManifestContent:
    """The manifest emitted by `commands --json`, asserted in-process."""

    def test_handler_json_matches_builder(self, capsys):
        """The --json handler prints exactly the manifest the builder returns."""
        assert _manifest_from_handler(capsys) == _commands_manifest()

    def test_framework_is_python(self, capsys):
        assert _manifest_from_handler(capsys)["framework"] == "python"

    def test_version_is_nonempty_and_versionish(self, capsys):
        version = _manifest_from_handler(capsys)["version"]
        assert isinstance(version, str) and version.strip()
        assert re.match(r"^\d+\.\d+", version), f"not version-looking: {version!r}"
        assert version == __version__

    def test_commands_is_nonempty_and_well_formed(self, capsys):
        commands = _manifest_from_handler(capsys)["commands"]
        assert isinstance(commands, list) and commands
        for entry in commands:
            assert entry.get("name"), f"entry missing name: {entry}"
            assert entry.get("summary"), f"entry missing summary: {entry}"

    def test_known_commands_all_present(self, capsys):
        names = {c["name"] for c in _manifest_from_handler(capsys)["commands"]}
        missing = KNOWN_COMMANDS - names
        assert not missing, f"manifest missing commands: {missing}"

    def test_manifest_lists_exactly_the_dispatchable_commands(self, capsys):
        """Anti-drift lock-in: the manifest is DERIVED from the dispatch
        registries, so it lists exactly what `main()` can dispatch — the native
        COMMANDS plus the DELEGATED commands handed to the tina4 client — with no
        separate hand-kept list."""
        names = [c["name"] for c in _manifest_from_handler(capsys)["commands"]]
        assert names == list(COMMANDS) + list(DELEGATED)

    def test_only_delegated_commands_carry_the_delegated_flag(self, capsys):
        """The flag says WHO implements a command; a native one must never claim
        to be delegated, and a delegated one must never be silently native."""
        entries = {c["name"]: c for c in _manifest_from_handler(capsys)["commands"]}
        for name in DELEGATED:
            assert entries[name].get("delegated") is True, f"{name} not flagged"
        for name in COMMANDS:
            assert "delegated" not in entries[name], f"{name} wrongly flagged"

    def test_generate_has_subcommands_with_model_and_crud(self, capsys):
        generate = next(
            c for c in _manifest_from_handler(capsys)["commands"] if c["name"] == "generate"
        )
        subcommands = generate.get("subcommands")
        assert isinstance(subcommands, list) and subcommands
        assert {"model", "crud"} <= set(subcommands)
        # Derived from the GENERATORS registry — never a hand-kept fourth list.
        assert subcommands == list(GENERATORS)

    def test_migrate_create_declares_its_positional_arg(self, capsys):
        entry = next(
            c for c in _manifest_from_handler(capsys)["commands"] if c["name"] == "migrate:create"
        )
        assert entry.get("args") == ["description"]

    def test_queue_is_a_top_level_command_and_a_generator(self, capsys):
        """Phase 3: `queue` is now BOTH a top-level command (run workers / manage
        jobs) with work/stats/retry/clear subcommands, AND a `generate`
        subcommand (scaffold a consumer). The two are distinct surfaces."""
        commands = _manifest_from_handler(capsys)["commands"]
        names = {c["name"] for c in commands}
        assert "queue" in names, "top-level queue command missing from manifest"
        queue = next(c for c in commands if c["name"] == "queue")
        assert queue.get("subcommands") == ["work", "stats", "retry", "clear"]
        # Still a scaffolding generator too (unchanged).
        assert "queue" in list(GENERATORS)

    def test_build_declares_deploy_oriented_summary(self, capsys):
        """`build` produces the deployable Docker image, not a library package."""
        entry = next(
            c for c in _manifest_from_handler(capsys)["commands"] if c["name"] == "build"
        )
        assert "Docker" in entry["summary"]


class TestCommandsHumanOutput:
    """The default (non-JSON) `commands` output is a readable list."""

    def test_lists_every_command_name(self, capsys):
        _commands([])
        out = capsys.readouterr().out
        for name in COMMANDS:
            assert name in out, f"human output omits {name!r}"


# The real entrypoint, driven exactly as the tina4 client would drive it.
_ENTRYPOINT_CODE = (
    "import sys\n"
    "sys.argv = ['tina4python', 'commands', '--json']\n"
    "from tina4_python.cli import main\n"
    "main()\n"
)


class TestCommandsIsAppAndDbFree:
    """Real subprocess: `commands --json` must run with NO database configured,
    in an empty project dir (no migrations/), exit 0 fast with valid JSON, and
    open no database — proving it never bootstraps the framework."""

    def _run(self, cwd):
        env = os.environ.copy()
        env.pop("TINA4_DATABASE_URL", None)  # no DB configured at all
        # A genuinely fresh process — import-time must not bootstrap / migrate /
        # open a DB. A 60s ceiling is generous for a cold import; a bootstrap
        # attempt would either error (non-zero) or hang past it.
        return subprocess.run(
            [sys.executable, "-c", _ENTRYPOINT_CODE],
            cwd=str(cwd), env=env,
            capture_output=True, text=True, timeout=60,
        )

    def test_exits_zero_with_valid_json_and_no_db(self, tmp_path):
        assert not (tmp_path / "migrations").exists()
        assert not (tmp_path / "app.py").exists()

        result = self._run(tmp_path)

        assert result.returncode == 0, f"non-zero exit; stderr:\n{result.stderr}"
        manifest = json.loads(result.stdout)  # raises if not valid JSON
        assert manifest["framework"] == "python"
        assert manifest["version"].strip()
        assert any(c["name"] == "commands" for c in manifest["commands"])
        assert any(c["name"] == "generate" for c in manifest["commands"])

        # No SQLite file anywhere under the project dir — nothing opened a DB.
        created_dbs = list(tmp_path.rglob("*.db"))
        assert created_dbs == [], f"commands opened/created a database: {created_dbs}"
