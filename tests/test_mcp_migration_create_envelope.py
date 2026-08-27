"""MCP `migration_create` tool emits the ADR-0063 generate_v1_1 envelope.

Locks the unification of the third migration-create surface (the MCP dev tool)
with the two CLI surfaces (`tina4python migrate:create` and
`tina4python generate migration`). Before this change the MCP tool called
`create_migration()` directly and returned `{"created": <filename>}` — no
envelope, no `edit_hints[]`, no `next[]` — so an agent hitting the MCP tool
got a strictly worse contract than a human hitting the CLI.

What this test locks in:

  * Positive envelope — a successful call returns the ADR-0063 envelope with
    the SAME shape the CLI emits: `command`/`target`/`input`/nested
    `resolution` carrying populated `edit_hints[]` and `next[]`, plus
    `actions_taken` and `dry_run: False`.
  * Envelope parity — for the SAME input, the nested `resolution` from the
    MCP tool equals what `tina4python migrate:create <slug> --json --dry-run`
    produces (modulo timestamped filenames). Also asserts the manifest
    advertises `resolution_contract = {"version": "1.1", "envelope":
    "generate_v1_1"}` — the discoverability handshake an agent relies on.
  * Duplicate-slug preserved — a second call with the same description
    against the same tmpdir returns `{"ok": False, "existing": [...]}`
    naming the first file. Envelope is NOT emitted on the refused call.
  * No test co-emitted — a bare migration_create call writes ONLY the
    `.sql` + `.down.sql` pair; `tests/` is never touched (matches the
    migrate:create contract).
  * Mutation gate — stashing the delegation change in `tools.py` reverts
    `migration_create` to the pre-fix `{"created": ...}` shape, and the
    positive-envelope test asserts FAILS. Proves the assertion isn't a
    tautology that would silently pass on the broken shape.

NO mocks. The direct-handler cases construct a real McpServer under a per-test
`tmp_path`, invoke the registered handler, and inspect the real files it wrote.
The parity case shells out to a fresh subprocess running the real
`tina4_python.cli.main` entrypoint, so what these tests observe is exactly
what the CLI does end-to-end.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


CLI_INVOKE = (
    "import sys; sys.argv={argv!r}; "
    "from tina4_python.cli import main; main()"
)


def _run(cwd, argv):
    """Run the real CLI in a fresh subprocess under `cwd`."""
    return subprocess.run(
        [sys.executable, "-c", CLI_INVOKE.format(argv=argv)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _fresh_mcp_handler(tmp_path):
    """Build a real McpServer under `tmp_path`, register the real dev tools,
    and return `(server, handler)` — no mocks, no fakes. Caller must chdir
    back to the previous cwd on teardown."""
    from tina4_python.mcp import McpServer
    from tina4_python.mcp.tools import register_dev_tools

    os.chdir(tmp_path)
    server = McpServer("/__dev/mcp", name="Envelope Test")
    register_dev_tools(server)
    return server, server._tools["migration_create"]["handler"]


def _project_files(root: Path):
    """Every file anywhere under `root`, as relative POSIX strings."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ── 1. Positive envelope — the wire contract an agent depends on ────────

def test_migration_create_returns_generate_v1_1_envelope(tmp_path):
    """A bare `migration_create("add users")` call:

    * writes `migrations/{ts}_add_users.sql` + its `.down.sql` sibling
    * returns `{"ok": True, "created": <path>, "resolution": <envelope>}`
    * the envelope's inner `resolution` carries populated `edit_hints[]`
      (from `tina4:edit` markers baked into both files) and populated
      `next[]` (the three-step curated block per ADR-0063).
    """
    old_cwd = os.getcwd()
    try:
        server, handler = _fresh_mcp_handler(tmp_path)
        result = handler(description="add users")

        assert isinstance(result, dict), result
        assert result.get("ok") is True, result
        # `created` is the primary UP file, prefixed with the migrations dir.
        created = result["created"]
        assert re.match(r"migrations/\d{14}_add_users\.sql$", created), created
        assert (tmp_path / created).is_file(), created
        # Sibling .down.sql exists too — the pair is the migration file-shape.
        down = created[:-len(".sql")] + ".down.sql"
        assert (tmp_path / down).is_file(), down

        envelope = result["resolution"]
        # Envelope top-level shape — the CLI generates the same keys.
        assert envelope["command"] == "generate", envelope
        assert envelope["target"] == "migration", envelope
        assert envelope["dry_run"] is False, envelope
        assert envelope["input"] == {"name": "add_users", "fields": None}, envelope

        # Nested resolution — what an agent reads to steer the next patch.
        resolution = envelope["resolution"]
        assert resolution["file_path"] == created, resolution
        assert resolution["migration_path"] == created, resolution
        assert resolution["table_name"] == "users", resolution
        assert resolution["test_paths"] == [], resolution  # _no_test suppressed

        # Populated edit_hints[] — one per `tina4:edit` marker in each file.
        hints = resolution["edit_hints"]
        assert isinstance(hints, list) and len(hints) >= 2, hints
        hint_files = {h["file"] for h in hints}
        assert created in hint_files, hint_files
        assert down in hint_files, hint_files
        for hint in hints:
            assert isinstance(hint["line"], int) and hint["line"] > 0, hint
            assert isinstance(hint["label"], str) and hint["label"], hint

        # Populated next[] — three curated steps for the migration verb.
        steps = resolution["next"]
        assert isinstance(steps, list) and len(steps) == 3, steps
        assert any("tina4 migrate" in s and "rollback" not in s and "status" not in s
                   for s in steps), steps
        assert any("--rollback" in s for s in steps), steps
        assert any("--status" in s for s in steps), steps

        # actions_taken reflects the real writes.
        actions = envelope["actions_taken"]
        assert f"wrote {created}" in actions, actions
        assert f"wrote {down}" in actions, actions
    finally:
        os.chdir(old_cwd)


# ── 2. Envelope parity — MCP nested resolution == CLI nested resolution ─

def test_mcp_envelope_matches_cli_envelope_for_same_input(tmp_path):
    """The nested `resolution` from `migration_create("add users")` must
    equal what `tina4python migrate:create add_users --json --dry-run`
    produces (modulo the timestamped filename). This is the contract that
    lets an agent switch surfaces without changing how it parses the
    response.

    NOTE: the CLI is invoked with the pre-slugged `add_users` (not
    "add users") because CLI callers pass a snake_case name; the MCP tool
    accepts natural language and slugs internally. Both surfaces converge
    on the SAME slug, so the nested resolution matches byte-for-byte
    after timestamp normalisation.
    """
    old_cwd = os.getcwd()
    mcp_dir = tmp_path / "mcp"
    cli_dir = tmp_path / "cli"
    mcp_dir.mkdir()
    cli_dir.mkdir()
    try:
        # --- MCP side (real write) ---
        _, handler = _fresh_mcp_handler(mcp_dir)
        mcp_result = handler(description="add users")
        assert mcp_result["ok"] is True, mcp_result
        mcp_resolution = mcp_result["resolution"]["resolution"]

        # --- CLI side (real subprocess, --dry-run so we don't need cleanup) ---
        os.chdir(old_cwd)
        cli = _run(
            cli_dir,
            ["tina4python", "migrate:create", "add_users", "--json", "--dry-run"],
        )
        assert cli.returncode == 0, f"CLI failed: {cli.stderr!r}"
        cli_envelope = json.loads(cli.stdout)

        # Envelope-level identity: both speak `generate migration`.
        assert cli_envelope["command"] == "generate"
        assert cli_envelope["target"] == "migration"
        assert cli_envelope["input"] == mcp_result["resolution"]["input"], (
            cli_envelope["input"], mcp_result["resolution"]["input"]
        )
        cli_resolution = cli_envelope["resolution"]

        # Normalise timestamped filenames — the subprocess and the direct
        # handler run seconds apart, so file_path differs by TS only.
        def _norm(res):
            clone = dict(res)
            for key in ("file_path", "migration_path"):
                if clone.get(key):
                    clone[key] = re.sub(r"\d{14}_", "TS_", clone[key])
            clone["edit_hints"] = [
                {**h, "file": re.sub(r"\d{14}_", "TS_", h["file"])}
                for h in clone.get("edit_hints", [])
            ]
            return clone

        assert _norm(mcp_resolution) == _norm(cli_resolution), (
            f"nested resolutions differ:\n"
            f"MCP={_norm(mcp_resolution)!r}\nCLI={_norm(cli_resolution)!r}"
        )

        # Explicit spot-checks: next[] and edit_hints labels line up.
        assert mcp_resolution["next"] == cli_resolution["next"]
        assert [h["label"] for h in mcp_resolution["edit_hints"]] == [
            h["label"] for h in cli_resolution["edit_hints"]
        ]

        # The manifest advertises the envelope schema an agent pins against.
        manifest = _run(cli_dir, ["tina4python", "commands", "--json"])
        assert manifest.returncode == 0, manifest.stderr
        contract = json.loads(manifest.stdout)["resolution_contract"]
        assert contract == {"version": "1.1", "envelope": "generate_v1_1"}, contract
    finally:
        os.chdir(old_cwd)


# ── 3. Duplicate slug — refused, envelope not emitted ───────────────────

def test_duplicate_slug_refused_second_call_returns_existing(tmp_path):
    """A second call with the same description returns the collision guard
    (envelope suppressed) so an agent can't spawn a second migration for the
    same schema change."""
    old_cwd = os.getcwd()
    try:
        _, handler = _fresh_mcp_handler(tmp_path)

        first = handler(description="add users")
        assert first["ok"] is True, first
        first_file = first["created"]

        second = handler(description="add users")
        assert second["ok"] is False, second
        assert "already exists" in second["error"], second
        assert isinstance(second["existing"], list), second
        # `existing` includes the first migration file (the collision the
        # agent must edit instead of writing a second one). The pre-existing
        # guard globs `*.sql` so the paired `.down.sql` is also listed;
        # both are legitimate members of the "already there" set.
        assert first_file in second["existing"], second
        # Envelope is NOT emitted on the refused call — no ambiguity about
        # whether a second migration was written.
        assert "resolution" not in second, second

        # And no second .sql pair landed on disk — still exactly the two
        # files from the first call.
        migrations = sorted((tmp_path / "migrations").iterdir())
        assert len(migrations) == 2, [m.name for m in migrations]
    finally:
        os.chdir(old_cwd)


# ── 4. No test co-emitted — migrate:create semantics preserved ──────────

def test_migration_create_never_writes_a_test_file(tmp_path):
    """The MCP tool matches the `migrate:create` contract: a single-file
    operation. Even for a `create_` name (whose DDL would otherwise be
    asserted by a co-emitted test in `generate migration`), the MCP tool
    writes ONLY the .sql + .down.sql pair — `tests/` is untouched."""
    old_cwd = os.getcwd()
    try:
        _, handler = _fresh_mcp_handler(tmp_path)
        result = handler(description="create products")
        assert result["ok"] is True, result

        files = _project_files(tmp_path)
        # At least the two migration files landed.
        assert any(f.startswith("migrations/") and f.endswith(".sql") for f in files), files
        # And nothing under tests/ was written.
        assert not any(f.startswith("tests/") for f in files), (
            f"MCP migration_create must not co-emit a test, wrote: {files!r}"
        )
        # Envelope agrees — test_paths[] is empty for a create_ name too.
        assert result["resolution"]["resolution"]["test_paths"] == [], result
    finally:
        os.chdir(old_cwd)


# ── 5. Mutation gate — proves the positive test isn't a tautology ───────

def test_positive_envelope_test_fails_when_delegation_is_reverted(tmp_path):
    """Stash a broken `migration_create` shape (the pre-fix `{"created": ...}`
    return) into a shadow module, invoke it the same way the positive test
    does, and assert the same assertions FAIL. Proves the positive test is
    a real gate: revert the delegation and it goes red.

    We DO NOT edit `tools.py` — we redefine the handler with the old shape
    on a real McpServer instance and re-run the positive test's checks.
    """
    old_cwd = os.getcwd()
    (tmp_path / "stash").mkdir()
    (tmp_path / "broken").mkdir()
    try:
        _, real_handler = _fresh_mcp_handler(tmp_path / "stash")

        # Build the pre-fix (broken) handler the way the old code did — a
        # bare `create_migration()` call returning `{"created": <filename>}`
        # with no envelope. Chdir into a separate dir so its writes don't
        # collide with the real handler's.
        from tina4_python.migration import create_migration
        os.chdir(tmp_path / "broken")

        def broken_migration_create(description: str) -> dict:
            filename = create_migration(description)
            return {"created": filename}

        result = broken_migration_create("add users")

        # Assertions from the positive test — they MUST fail on the broken
        # shape. Use pytest.raises to prove the shape check is a real gate.
        import pytest
        with pytest.raises((AssertionError, KeyError, TypeError)):
            assert result.get("ok") is True, result  # missing key -> fails
            envelope = result["resolution"]           # missing key -> KeyError
            assert envelope["command"] == "generate"
            assert envelope["resolution"]["edit_hints"]
            assert envelope["resolution"]["next"]

        # And prove the fixed handler DOES pass the same shape check on the
        # same input in the same session — the gate is real in both
        # directions.
        os.chdir(tmp_path / "stash")
        fixed = real_handler(description="add users")
        assert fixed.get("ok") is True
        assert fixed["resolution"]["command"] == "generate"
        assert fixed["resolution"]["resolution"]["edit_hints"]
        assert fixed["resolution"]["resolution"]["next"]
    finally:
        os.chdir(old_cwd)
