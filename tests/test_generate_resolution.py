"""Real-subprocess tests for `tina4 generate` resolution transparency.

ADR-0062, agent-experience contract: every `generate model/route/migration/
middleware` call exposes the mapping the framework decided to build. `--json`
emits a stable envelope on stdout; `--dry-run` computes the envelope without
writing anything; bare calls print the human resolution block to stderr AFTER
the normal writes complete. The envelope's schema version is discoverable via
the `commands --json` manifest so an agent can pin against it.

NO mocks. Each case shells out to a fresh Python subprocess running the real
`tina4_python.cli.main` entrypoint, in a pytest tmp_path project scaffold, so
what these tests observe is exactly what the CLI does end-to-end.
"""
from __future__ import annotations

import json
import subprocess
import sys


CLI_INVOKE = (
    "import sys; sys.argv={argv!r}; "
    "from tina4_python.cli import main; main()"
)


def _run(tmp_path, argv, extra_env=None):
    """Run the real CLI in a fresh subprocess under `tmp_path`."""
    env = None
    if extra_env is not None:
        import os
        env = {**os.environ, **extra_env}
    return subprocess.run(
        [sys.executable, "-c", CLI_INVOKE.format(argv=argv)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _project_files(tmp_path):
    """All files anywhere under tmp_path — used to prove --dry-run wrote none."""
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
                  if p.is_file())


def test_generate_model_json_dry_run_returns_envelope(tmp_path):
    """--json + --dry-run for a non-reserved name emits the full envelope with
    dry_run=true, actions_taken=[], transformations=[], and touches NO files.

    Proves: (1) the envelope shape matches the ADR-0062 contract exactly;
    (2) the resolution computes even though no writes happen; (3) --dry-run
    is honoured — a passing test with files on disk is a broken dry-run.
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Foo",
                             "--json", "--dry-run"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    envelope = json.loads(result.stdout)
    assert envelope["command"] == "generate"
    assert envelope["target"] == "model"
    assert envelope["input"] == {"name": "Foo", "fields": None}
    assert envelope["dry_run"] is True
    assert envelope["actions_taken"] == []

    resolution = envelope["resolution"]
    assert resolution["class_name"] == "Foo"
    assert resolution["table_name"] == "foo"
    assert resolution["file_path"] == "src/orm/Foo.py"
    assert resolution["migration_path"].startswith("migrations/")
    assert resolution["migration_path"].endswith("_create_foo.sql")
    assert resolution["transformations"] == []
    assert resolution["routes"] == []
    assert resolution["test_paths"] == ["tests/test_foo_model.py"]

    # NO files created — this is the load-bearing dry-run assertion.
    assert _project_files(tmp_path) == [], (
        f"dry-run wrote files: {_project_files(tmp_path)!r}"
    )


def test_generate_model_reserved_word_names_transformation(tmp_path):
    """--json + --dry-run for a SQL-reserved name (Order) surfaces the
    `reserved_word_pluralize` transformation with the raw and target names,
    a human reason, and the override that would opt out.

    An agent should be able to spot the pluralization from the envelope
    alone — no reverse-engineering from a scanned migration file.
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Order",
                             "--json", "--dry-run"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    envelope = json.loads(result.stdout)
    transformations = envelope["resolution"]["transformations"]
    assert len(transformations) == 1, transformations

    t = transformations[0]
    assert t["kind"] == "reserved_word_pluralize"
    assert t["from"] == "order"
    assert t["to"] == "orders"
    assert "SQL reserved word" in t["reason"]
    assert "--table" in t["override"] and "--quote" in t["override"]

    assert envelope["resolution"]["table_name"] == "orders"
    assert envelope["dry_run"] is True
    assert _project_files(tmp_path) == [], (
        f"dry-run wrote files: {_project_files(tmp_path)!r}"
    )


def test_generate_model_bare_writes_files_and_prints_resolution_to_stderr(tmp_path):
    """Bare `generate model Foo` writes the real files AND prints the human
    resolution block to STDERR — the block never contends with a caller
    parsing stdout, and every path the block names actually exists.
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Foo"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    # Real files exist on disk.
    assert (tmp_path / "src" / "orm" / "Foo.py").is_file()
    assert (tmp_path / "tests" / "test_foo_model.py").is_file()
    migration_files = list((tmp_path / "migrations").glob("*_create_foo.sql"))
    assert migration_files, "expected a *_create_foo.sql migration"

    # Human resolution block on stderr with the expected shape.
    stderr = result.stderr
    assert "Generated model Foo" in stderr, stderr
    assert "class" in stderr, stderr
    assert "src/orm/Foo.py" in stderr, stderr
    assert "table" in stderr, stderr
    # And a non-reserved name has NO pluralize note.
    assert "auto-pluralized" not in stderr, stderr


def test_generate_model_reserved_name_prints_pluralize_note_to_stderr(tmp_path):
    """Bare `generate model Order` prints the pluralize note to stderr —
    both the mechanism ("auto-pluralized") AND the reason ("SQL reserved
    word") — so a developer sees why "orders" appeared instead of "order".
    """
    result = _run(tmp_path, ["tina4python", "generate", "model", "Order"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    stderr = result.stderr
    assert "auto-pluralized" in stderr, stderr
    assert "SQL reserved word" in stderr, stderr
    assert "'order'" in stderr, stderr

    # The real table on disk agrees with the block.
    migrations = list((tmp_path / "migrations").glob("*_create_orders.sql"))
    assert migrations, "expected a *_create_orders.sql migration"


def test_commands_manifest_advertises_resolution_contract(tmp_path):
    """The `commands --json` manifest advertises the resolution contract's
    schema version so an agent can pin against it and know whether the
    envelope shape it depends on is still current.
    """
    result = _run(tmp_path, ["tina4python", "commands", "--json"])
    assert result.returncode == 0, (
        f"exit {result.returncode}; stderr={result.stderr!r}"
    )

    manifest = json.loads(result.stdout[result.stdout.find("{"):])
    contract = manifest.get("resolution_contract")
    assert contract is not None, (
        f"manifest missing resolution_contract: {list(manifest)!r}"
    )
    assert contract["version"] == "1", contract
    assert contract["envelope"] == "generate_v1", contract
